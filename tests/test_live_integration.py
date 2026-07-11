from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import unittest

from fastapi.testclient import TestClient
import requests

import main
from config import get_settings
from slack_handler import send_slack_bot_message


LIVE_FLAG = "RUN_LIVE_SLACK_TESTS"
LIVE_CHANNEL_ENV = "SLACK_TEST_CHANNEL_ID"


class LiveSlackIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.getenv(LIVE_FLAG, "0") != "1":
            raise unittest.SkipTest(
                f"Set {LIVE_FLAG}=1 to run live Slack integration tests."
            )

        cls.settings = get_settings()
        cls.test_channel = os.getenv(LIVE_CHANNEL_ENV, "").strip()
        if not cls.test_channel:
            raise unittest.SkipTest(
                f"Set {LIVE_CHANNEL_ENV} to a real Slack channel ID (for example C0123456789)."
            )

        cls.client = TestClient(main.app)

    @staticmethod
    def _build_signature(body: bytes, timestamp: str, signing_secret: str) -> str:
        base_string = f"v0:{timestamp}:{body.decode('utf-8')}"
        digest = hmac.new(
            signing_secret.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"v0={digest}"

    def _fetch_recent_messages(self, *, limit: int = 10) -> list[dict[str, object]]:
        response = requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {self.settings.SLACK_BOT_TOKEN}"},
            params={"channel": self.test_channel, "limit": limit},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self.assertTrue(data.get("ok"), msg=f"Failed to fetch Slack history: {data}")
        messages = data.get("messages", [])
        return [message for message in messages if isinstance(message, dict)]

    def test_live_send_slack_bot_message(self) -> None:
        marker = f"kg-live-send-{int(time.time())}"
        message = f"[live-test] send_slack_bot_message {marker}"

        result = send_slack_bot_message(
            bot_token=self.settings.SLACK_BOT_TOKEN,
            channel=self.test_channel,
            text=message,
        )

        self.assertTrue(result.get("ok"), msg=f"Slack API response: {result}")
        self.assertEqual(result.get("channel"), self.test_channel)

        messages = self._fetch_recent_messages(limit=15)
        self.assertTrue(
            any(marker in str(msg.get("text", "")) for msg in messages),
            msg="Live message marker was not found in channel history.",
        )

    def test_live_slack_events_endpoint_verifies_signature_and_routes(self) -> None:
        marker = f"kg-live-events-{int(time.time())}"
        payload = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": f"<@U_TEST> what is this? {marker}",
                "channel": self.test_channel,
            },
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = self._build_signature(raw_body, timestamp, self.settings.SLACK_SIGNING_SECRET)

        with unittest.mock.patch("main.query_graph_rag", return_value=f"live-rag-response {marker}"):
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

        # Background task posts asynchronously; poll briefly to verify delivery.
        found = False
        for _ in range(5):
            messages = self._fetch_recent_messages(limit=20)
            if any(f"live-rag-response {marker}" in str(msg.get("text", "")) for msg in messages):
                found = True
                break
            time.sleep(1)

        self.assertTrue(found, msg="Expected Slack response message was not found after event handling.")


if __name__ == "__main__":
    unittest.main()
