from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Literal

import requests
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from config import get_settings
from engine import query_graph_rag
from graph_db import build_neo4j_manager
from ingestion import ingest_google_document

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)
app = FastAPI(title="GraphRAG Slack Backend")

SLACK_SIGNATURE_VERSION = "v0"
SLACK_TIMESTAMP_TOLERANCE_SECONDS = 300


class GoogleIngestionRequest(BaseModel):
    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_type: Literal["sheet", "slides"]


class AcceptedResponse(BaseModel):
    status: str
    detail: str


@app.get("/health")
def health_check() -> dict[str, str]:
    manager = build_neo4j_manager()
    try:
        manager.check_health()
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("Health check failed.")
        raise HTTPException(status_code=503, detail="Service unavailable.") from exc
    finally:
        manager.close()


def post_slack_message(channel: str, text: str) -> None:
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"channel": channel, "text": text}

    try:
        response = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        response_payload = response.json()
        if not response_payload.get("ok"):
            raise RuntimeError(f"Slack API error: {response_payload}")
    except Exception as exc:
        logger.exception("Failed to post Slack message to channel %s.", channel)
        raise RuntimeError("Failed to post Slack message.") from exc


def _verify_slack_signature(
    raw_body: bytes,
    timestamp: str | None,
    slack_signature: str | None,
) -> None:
    settings = get_settings()

    if not timestamp or not slack_signature:
        logger.warning("Slack request missing signature headers.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Slack signature headers.")

    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        logger.warning("Slack request provided a non-numeric timestamp.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack timestamp.") from exc

    if abs(int(time.time()) - timestamp_value) > SLACK_TIMESTAMP_TOLERANCE_SECONDS:
        logger.warning("Slack request timestamp fell outside the allowed tolerance window.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expired Slack request.")

    basestring = f"{SLACK_SIGNATURE_VERSION}:{timestamp}:{raw_body.decode('utf-8')}"
    digest = hmac.new(
        settings.SLACK_SIGNING_SECRET.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected_signature = f"{SLACK_SIGNATURE_VERSION}={digest}"

    if not hmac.compare_digest(expected_signature, slack_signature):
        logger.warning("Slack signature verification failed.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack signature.")


def _verify_ingestion_api_key(api_key: str | None) -> None:
    settings = get_settings()
    if not api_key or not hmac.compare_digest(api_key, settings.INGESTION_API_TOKEN):
        logger.warning("Rejected ingestion request with an invalid API key.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ingestion API key.")


def process_app_mention(channel: str, user_text: str) -> None:
    try:
        answer = query_graph_rag(user_text)
        post_slack_message(channel, answer)
    except Exception:
        logger.exception("Failed to process Slack app mention for channel %s.", channel)


def process_google_ingestion(document_id: str, title: str, source_type: str) -> None:
    try:
        ingest_google_document(document_id=document_id, title=title, source_type=source_type)
        logger.info("Completed ingestion for document %s from source %s.", document_id, source_type)
    except Exception:
        logger.exception("Failed background ingestion for document %s.", document_id)


@app.post("/ingest/google", response_model=AcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_google_source(
    payload: GoogleIngestionRequest,
    background_tasks: BackgroundTasks,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AcceptedResponse:
    _verify_ingestion_api_key(x_api_key)
    background_tasks.add_task(
        process_google_ingestion,
        payload.document_id.strip(),
        payload.title.strip(),
        payload.source_type,
    )
    return AcceptedResponse(status="accepted", detail="Google document ingestion has been queued.")


@app.post("/slack/events")
async def slack_events(
    request: Request,
    background_tasks: BackgroundTasks,
    x_slack_request_timestamp: str | None = Header(default=None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str | None = Header(default=None, alias="X-Slack-Signature"),
) -> dict[str, Any]:
    try:
        raw_body = await request.body()
        _verify_slack_signature(raw_body, x_slack_request_timestamp, x_slack_signature)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to read or verify the Slack request.")
        raise HTTPException(status_code=400, detail="Invalid Slack request.") from exc

    try:
        data: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to parse Slack request body.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    try:
        if "challenge" in data:
            return {"challenge": data["challenge"]}

        event = data.get("event", {})
        event_type = event.get("type")
        subtype = event.get("subtype")

        if event_type != "app_mention" or subtype == "bot_message":
            return {"ok": True}

        text = str(event.get("text", "")).strip()
        channel = str(event.get("channel", "")).strip()

        if not text or not channel:
            logger.warning("Slack app mention was missing text or channel data.")
            return {"ok": True}

        background_tasks.add_task(process_app_mention, channel, text)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to handle Slack event.")
        raise HTTPException(status_code=500, detail="Slack event handling failed.") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)