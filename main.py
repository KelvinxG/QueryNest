from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from config import get_settings, require_settings
from engine import generate_usage_guidance, query_graph_rag
from graph_db import build_neo4j_manager
from ingestion import ingest_google_document, ingest_text_document
from slack_handler import receive_slack_webhook, send_slack_bot_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)
app = FastAPI(title="GraphRAG Slack Backend")

SLACK_SIGNATURE_VERSION = "v0"
SLACK_TIMESTAMP_TOLERANCE_SECONDS = 300
HELP_KEYWORDS = {"help", "usage", "how to use", "example", "examples", "suggest", "suggestions"}


class GoogleIngestionRequest(BaseModel):
    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_type: Literal["sheet", "slides", "doc"]


class AcceptedResponse(BaseModel):
    status: str
    detail: str


class TextIngestionRequest(BaseModel):
    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)


class QueryResponse(BaseModel):
    status: str
    answer: str


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
    settings = require_settings("SLACK_BOT_TOKEN")
    try:
        send_slack_bot_message(
            bot_token=settings["SLACK_BOT_TOKEN"],
            channel=channel,
            text=text,
        )
    except Exception as exc:
        logger.exception("Failed to post Slack message to channel %s.", channel)
        raise RuntimeError("Failed to post Slack message.") from exc


def _verify_slack_signature(
    raw_body: bytes,
    timestamp: str | None,
    slack_signature: str | None,
) -> None:
    settings = require_settings("SLACK_SIGNING_SECRET")

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
        settings["SLACK_SIGNING_SECRET"].encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected_signature = f"{SLACK_SIGNATURE_VERSION}={digest}"

    if not hmac.compare_digest(expected_signature, slack_signature):
        logger.warning("Slack signature verification failed.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack signature.")


def _verify_ingestion_api_key(api_key: str | None) -> None:
    settings = require_settings("INGESTION_API_TOKEN")
    if not api_key or not hmac.compare_digest(api_key, settings["INGESTION_API_TOKEN"]):
        logger.warning("Rejected ingestion request with an invalid API key.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ingestion API key.")


def _normalize_slack_text(text: str) -> str:
    return re.sub(r"<@[^>]+>", "", text).strip()


def _is_guidance_request(text: str) -> bool:
    normalized = _normalize_slack_text(text).lower()
    if not normalized:
        return True

    return normalized in HELP_KEYWORDS


def process_app_mention(channel: str, user_text: str) -> None:
    try:
        if _is_guidance_request(user_text):
            answer = generate_usage_guidance()
        else:
            answer = query_graph_rag(_normalize_slack_text(user_text))
        post_slack_message(channel, answer)
    except Exception:
        logger.exception("Failed to process Slack app mention for channel %s.", channel)


def process_google_ingestion(document_id: str, title: str, source_type: str) -> None:
    try:
        ingest_google_document(document_id=document_id, title=title, source_type=source_type)
        logger.info("Completed ingestion for document %s from source %s.", document_id, source_type)
    except Exception:
        logger.exception("Failed background ingestion for document %s.", document_id)


def process_text_ingestion(document_id: str, title: str, text: str) -> None:
    try:
        ingest_text_document(document_id=document_id, title=title, document_text=text)
        logger.info("Completed direct text ingestion for document %s.", document_id)
    except Exception:
        logger.exception("Failed background direct text ingestion for document %s.", document_id)


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


@app.post("/ingest/text", response_model=AcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_text_source(
    payload: TextIngestionRequest,
    background_tasks: BackgroundTasks,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AcceptedResponse:
    _verify_ingestion_api_key(x_api_key)
    background_tasks.add_task(
        process_text_ingestion,
        payload.document_id.strip(),
        payload.title.strip(),
        payload.text.strip(),
    )
    return AcceptedResponse(status="accepted", detail="Direct text ingestion has been queued.")


@app.post("/query", response_model=QueryResponse)
async def query_graph(payload: QueryRequest) -> QueryResponse:
    try:
        answer = query_graph_rag(payload.question.strip())
        return QueryResponse(status="ok", answer=answer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to answer GraphRAG query.")
        raise HTTPException(status_code=500, detail="Failed to generate answer.") from exc


@app.post("/slack/events")
async def slack_events(
    request: Request,
    background_tasks: BackgroundTasks,
    x_slack_request_timestamp: str | None = Header(default=None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str | None = Header(default=None, alias="X-Slack-Signature"),
) -> dict[str, Any]:
    try:
        raw_body = await request.body()
        parsed = receive_slack_webhook(
            raw_body=raw_body,
            timestamp=None,
            slack_signature=None,
            signing_secret="",
        )
    except Exception as exc:
        try:
            settings = require_settings("SLACK_SIGNING_SECRET")
            parsed = receive_slack_webhook(
                raw_body=raw_body,
                timestamp=x_slack_request_timestamp,
                slack_signature=x_slack_signature,
                signing_secret=settings["SLACK_SIGNING_SECRET"],
            )
        except Exception as inner_exc:
            logger.exception("Failed to parse or verify the Slack request.")
            raise HTTPException(status_code=400, detail="Invalid Slack request.") from inner_exc

    if parsed.get("kind") == "challenge":
        return {"challenge": parsed.get("challenge")}

    data = parsed.get("payload", {})

    try:
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

    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)