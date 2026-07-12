from __future__ import annotations

import hashlib
import hmac
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


def _required_settings(**values: str):
    def _resolver(*names: str) -> dict[str, str]:
        missing = [name for name in names if name not in values]
        if missing:
            raise RuntimeError(f"Missing required settings: {', '.join(missing)}")
        return {name: values[name] for name in names}

    return _resolver


class SlackVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.body = b'{"type":"url_verification"}'
        self.timestamp = "1700000000"
        self.secret = "test-secret"

    def _signature(self) -> str:
        base_string = f"v0:{self.timestamp}:{self.body.decode('utf-8')}"
        digest = hmac.new(
            self.secret.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"v0={digest}"

    def test_verify_slack_signature_accepts_valid_signature(self) -> None:
        with patch("main.require_settings", side_effect=_required_settings(SLACK_SIGNING_SECRET=self.secret)):
            with patch("main.time.time", return_value=int(self.timestamp)):
                main._verify_slack_signature(self.body, self.timestamp, self._signature())

    def test_verify_slack_signature_rejects_invalid_signature(self) -> None:
        with patch("main.require_settings", side_effect=_required_settings(SLACK_SIGNING_SECRET=self.secret)):
            with patch("main.time.time", return_value=int(self.timestamp)):
                with self.assertRaises(HTTPException) as context:
                    main._verify_slack_signature(self.body, self.timestamp, "v0=invalid")

        self.assertEqual(context.exception.status_code, 401)

    def test_verify_slack_signature_rejects_expired_timestamp(self) -> None:
        with patch("main.require_settings", side_effect=_required_settings(SLACK_SIGNING_SECRET=self.secret)):
            with patch(
                "main.time.time",
                return_value=int(self.timestamp) + main.SLACK_TIMESTAMP_TOLERANCE_SECONDS + 1,
            ):
                with self.assertRaises(HTTPException) as context:
                    main._verify_slack_signature(self.body, self.timestamp, self._signature())

        self.assertEqual(context.exception.status_code, 401)


class IngestionApiKeyTests(unittest.TestCase):
    def test_verify_ingestion_api_key_accepts_match(self) -> None:
        with patch("main.require_settings", side_effect=_required_settings(INGESTION_API_TOKEN="abc123")):
            main._verify_ingestion_api_key("abc123")

    def test_verify_ingestion_api_key_rejects_mismatch(self) -> None:
        with patch("main.require_settings", side_effect=_required_settings(INGESTION_API_TOKEN="abc123")):
            with self.assertRaises(HTTPException) as context:
                main._verify_ingestion_api_key("wrong")

        self.assertEqual(context.exception.status_code, 401)


class SlackGuidanceRoutingTests(unittest.TestCase):
    def test_is_guidance_request_accepts_bare_mention(self) -> None:
        self.assertTrue(main._is_guidance_request("<@U12345>"))

    def test_is_guidance_request_accepts_help_keyword(self) -> None:
        self.assertTrue(main._is_guidance_request("<@U12345> help"))

    def test_is_guidance_request_rejects_normal_question(self) -> None:
        self.assertFalse(main._is_guidance_request("<@U12345> summarize roadmap"))

    def test_process_app_mention_uses_usage_guidance_for_help_requests(self) -> None:
        with patch("main.generate_usage_guidance", return_value="usage text") as guidance:
            with patch("main.post_slack_message") as post_message:
                main.process_app_mention("C123", "<@U12345> help")

        guidance.assert_called_once_with()
        post_message.assert_called_once_with("C123", "usage text")

    def test_process_app_mention_uses_graph_query_for_normal_questions(self) -> None:
        with patch("main.query_graph_rag", return_value="answer") as query:
            with patch("main.post_slack_message") as post_message:
                main.process_app_mention("C123", "<@U12345> summarize roadmap")

        query.assert_called_once_with("summarize roadmap")
        post_message.assert_called_once_with("C123", "answer")


class DirectTextIngestionTests(unittest.TestCase):
    def test_process_text_ingestion_calls_ingestion_layer(self) -> None:
        with patch("main.ingest_text_document") as ingest_text:
            main.process_text_ingestion("doc-1", "Manual Input", "Some direct text")

        ingest_text.assert_called_once_with(
            document_id="doc-1",
            title="Manual Input",
            document_text="Some direct text",
        )


class QueryEndpointTests(unittest.TestCase):
    def test_query_graph_returns_query_response(self) -> None:
        with patch("main.query_graph_rag", return_value="answer"):
            result = asyncio.run(main.query_graph(main.QueryRequest(question="hello")))

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.answer, "answer")


class SlackEndpointChallengeTests(unittest.TestCase):
    def test_slack_events_accepts_signed_url_verification(self) -> None:
        client = TestClient(main.app)
        raw_body = b'{"type":"url_verification","challenge":"abc123"}'
        timestamp = "1700000000"
        signing_secret = "test-secret"
        base_string = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
        digest = hmac.new(
            signing_secret.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signature = f"v0={digest}"

        with patch("main.require_settings", side_effect=_required_settings(SLACK_SIGNING_SECRET=signing_secret)):
            with patch("main.time.time", return_value=int(timestamp)):
                response = client.post(
                    "/slack/events",
                    content=raw_body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Slack-Request-Timestamp": timestamp,
                        "X-Slack-Signature": signature,
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"challenge": "abc123"})

    def test_slack_events_rejects_unsigned_url_verification(self) -> None:
        client = TestClient(main.app)

        with patch("main.require_settings", side_effect=_required_settings(SLACK_SIGNING_SECRET="test-secret")):
            response = client.post(
                "/slack/events",
                json={"type": "url_verification", "challenge": "abc123"},
            )

        self.assertEqual(response.status_code, 400)


class WebSocketEndpointTests(unittest.TestCase):
    def test_websocket_chat_rejects_invalid_token(self) -> None:
        client = TestClient(main.app)

        with patch("main.require_settings", side_effect=_required_settings(INGESTION_API_TOKEN="ws-token")):
            with self.assertRaises(Exception):
                with client.websocket_connect("/ws/chat?token=invalid"):
                    pass

    def test_websocket_chat_returns_answer_for_question_payload(self) -> None:
        client = TestClient(main.app)

        with patch("main.require_settings", side_effect=_required_settings(INGESTION_API_TOKEN="ws-token")):
            with patch("main.query_graph_rag", return_value="socket answer") as query_graph_rag:
                with client.websocket_connect("/ws/chat?token=ws-token") as websocket:
                    connected_payload = websocket.receive_json()
                    self.assertEqual(connected_payload["type"], "connected")

                    websocket.send_json({"question": "What is in the graph?"})
                    response = websocket.receive_json()

        self.assertEqual(response["type"], "answer")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["answer"], "socket answer")
        query_graph_rag.assert_called_once_with("What is in the graph?")

    def test_websocket_chat_returns_error_for_empty_payload(self) -> None:
        client = TestClient(main.app)

        with patch("main.require_settings", side_effect=_required_settings(INGESTION_API_TOKEN="ws-token")):
            with client.websocket_connect("/ws/chat?token=ws-token") as websocket:
                websocket.receive_json()
                websocket.send_json({"question": "   "})
                response = websocket.receive_json()

        self.assertEqual(response["type"], "error")
        self.assertEqual(response["status"], "bad_request")

    def test_websocket_chat_routes_help_requests_to_guidance(self) -> None:
        client = TestClient(main.app)

        with patch("main.require_settings", side_effect=_required_settings(INGESTION_API_TOKEN="ws-token")):
            with patch("main.generate_usage_guidance", return_value="usage guidance") as guidance:
                with client.websocket_connect("/ws/chat?token=ws-token") as websocket:
                    websocket.receive_json()
                    websocket.send_json({"question": "help"})
                    response = websocket.receive_json()

        self.assertEqual(response["type"], "answer")
        self.assertEqual(response["answer"], "usage guidance")
        guidance.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
