from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    @staticmethod
    def _build_slack_signature(body: bytes, timestamp: str, signing_secret: str) -> str:
        base_string = f"v0:{timestamp}:{body.decode('utf-8')}"
        digest = hmac.new(
            signing_secret.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"v0={digest}"

    class _FakeSlackResponse:
        def __init__(self, payload: dict[str, object] | None = None) -> None:
            self.status_code = 200
            self._payload = payload or {"ok": True, "channel": "C123"}
            self.text = "ok"

        def raise_for_status(self) -> None:
            return

        def json(self) -> dict[str, object]:
            return self._payload

    def test_slack_event_flow_routes_to_rag_and_posts_reply(self) -> None:
        signing_secret = "integration-secret"
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U123",
                "text": "<@U999> summarize roadmap",
                "channel": "C123",
            },
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = self._build_slack_signature(raw_body, timestamp, signing_secret)

        with patch(
            "main.get_settings",
            return_value=SimpleNamespace(
                SLACK_SIGNING_SECRET=signing_secret,
                SLACK_BOT_TOKEN="xoxb-test-token",
                INGESTION_API_TOKEN="ingest-token",
            ),
        ):
            with patch("main.query_graph_rag", return_value="Graph answer") as query_graph_rag:
                with patch(
                    "slack_handler.requests.post",
                    return_value=self._FakeSlackResponse(),
                ) as requests_post:
                    response = self.client.post(
                        "/slack/events",
                        content=raw_body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Slack-Request-Timestamp": timestamp,
                            "X-Slack-Signature": signature,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        query_graph_rag.assert_called_once_with("summarize roadmap")
        requests_post.assert_called_once()
        call_args = requests_post.call_args
        self.assertEqual(call_args.args[0], "https://slack.com/api/chat.postMessage")
        self.assertEqual(call_args.kwargs["json"], {"channel": "C123", "text": "Graph answer"})
        self.assertIn("Authorization", call_args.kwargs["headers"])
        self.assertTrue(call_args.kwargs["headers"]["Authorization"].startswith("Bearer xoxb-test-token"))

    def test_slack_url_verification_returns_challenge(self) -> None:
        payload = {"type": "url_verification", "challenge": "challenge-token"}

        with patch(
            "main.get_settings",
            return_value=SimpleNamespace(
                SLACK_SIGNING_SECRET="integration-secret",
                SLACK_BOT_TOKEN="xoxb-test-token",
                INGESTION_API_TOKEN="ingest-token",
            ),
        ):
            response = self.client.post(
                "/slack/events",
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"challenge": "challenge-token"})

    def test_text_ingestion_endpoint_triggers_background_ingestion(self) -> None:
        payload = {
            "document_id": "doc-001",
            "title": "Manual Context",
            "text": "This is direct text for ingestion.",
        }

        with patch(
            "main.get_settings",
            return_value=SimpleNamespace(
                SLACK_SIGNING_SECRET="integration-secret",
                SLACK_BOT_TOKEN="xoxb-test-token",
                INGESTION_API_TOKEN="ingest-token",
            ),
        ):
            with patch("main.ingest_text_document") as ingest_text_document:
                response = self.client.post(
                    "/ingest/text",
                    json=payload,
                    headers={"X-API-Key": "ingest-token"},
                )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.json(),
            {
                "status": "accepted",
                "detail": "Direct text ingestion has been queued.",
            },
        )
        ingest_text_document.assert_called_once_with(
            document_id="doc-001",
            title="Manual Context",
            document_text="This is direct text for ingestion.",
        )

    def test_query_endpoint_returns_answer_text(self) -> None:
        with patch("main.query_graph_rag", return_value="This is a GraphRAG answer.") as query_graph_rag:
            response = self.client.post(
                "/query",
                json={"question": "What is in the graph?"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "answer": "This is a GraphRAG answer.",
            },
        )
        query_graph_rag.assert_called_once_with("What is in the graph?")

    def test_query_endpoint_rejects_empty_question(self) -> None:
        response = self.client.post(
            "/query",
            json={"question": "   "},
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
