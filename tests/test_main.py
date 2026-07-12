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
    def test_slack_events_accepts_url_verification_without_loading_full_settings(self) -> None:
        client = TestClient(main.app)

        with patch("main.get_settings", side_effect=RuntimeError("settings should not load for challenge")):
            response = client.post(
                "/slack/events",
                json={"type": "url_verification", "challenge": "abc123"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"challenge": "abc123"})


if __name__ == "__main__":
    unittest.main()
