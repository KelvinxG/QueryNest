from __future__ import annotations

import hashlib
import hmac
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import main


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
        with patch("main.get_settings", return_value=SimpleNamespace(SLACK_SIGNING_SECRET=self.secret)):
            with patch("main.time.time", return_value=int(self.timestamp)):
                main._verify_slack_signature(self.body, self.timestamp, self._signature())

    def test_verify_slack_signature_rejects_invalid_signature(self) -> None:
        with patch("main.get_settings", return_value=SimpleNamespace(SLACK_SIGNING_SECRET=self.secret)):
            with patch("main.time.time", return_value=int(self.timestamp)):
                with self.assertRaises(HTTPException) as context:
                    main._verify_slack_signature(self.body, self.timestamp, "v0=invalid")

        self.assertEqual(context.exception.status_code, 401)

    def test_verify_slack_signature_rejects_expired_timestamp(self) -> None:
        with patch("main.get_settings", return_value=SimpleNamespace(SLACK_SIGNING_SECRET=self.secret)):
            with patch(
                "main.time.time",
                return_value=int(self.timestamp) + main.SLACK_TIMESTAMP_TOLERANCE_SECONDS + 1,
            ):
                with self.assertRaises(HTTPException) as context:
                    main._verify_slack_signature(self.body, self.timestamp, self._signature())

        self.assertEqual(context.exception.status_code, 401)


class IngestionApiKeyTests(unittest.TestCase):
    def test_verify_ingestion_api_key_accepts_match(self) -> None:
        with patch("main.get_settings", return_value=SimpleNamespace(INGESTION_API_TOKEN="abc123")):
            main._verify_ingestion_api_key("abc123")

    def test_verify_ingestion_api_key_rejects_mismatch(self) -> None:
        with patch("main.get_settings", return_value=SimpleNamespace(INGESTION_API_TOKEN="abc123")):
            with self.assertRaises(HTTPException) as context:
                main._verify_ingestion_api_key("wrong")

        self.assertEqual(context.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()