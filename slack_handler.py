from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
from typing import Any

import requests


SLACK_SIGNATURE_VERSION = "v0"
SLACK_TIMESTAMP_TOLERANCE_SECONDS = 300


def verify_slack_signature(
    *,
    raw_body: bytes,
    timestamp: str,
    slack_signature: str,
    signing_secret: str,
    tolerance_seconds: int = SLACK_TIMESTAMP_TOLERANCE_SECONDS,
) -> bool:
    """Validate an incoming Slack request signature."""
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise ValueError("Slack timestamp must be numeric.") from exc

    if abs(int(time.time()) - timestamp_value) > tolerance_seconds:
        raise ValueError("Slack request timestamp is outside the allowed window.")

    basestring = f"{SLACK_SIGNATURE_VERSION}:{timestamp}:{raw_body.decode('utf-8')}"
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected_signature = f"{SLACK_SIGNATURE_VERSION}={digest}"

    return hmac.compare_digest(expected_signature, slack_signature)


def receive_slack_webhook(
    *,
    raw_body: bytes,
    timestamp: str | None,
    slack_signature: str | None,
    signing_secret: str,
) -> dict[str, Any]:
    """Parse and validate a Slack webhook payload.

    Returns a normalized result object:
    - URL verification: {"kind": "challenge", "challenge": "..."}
    - Event callback: {"kind": "event", "event": {...}, "payload": {...}}
    """
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON payload.") from exc

    if "challenge" in payload:
        return {"kind": "challenge", "challenge": payload["challenge"], "payload": payload}

    if not timestamp or not slack_signature:
        raise ValueError("Missing Slack signature headers.")

    is_valid = verify_slack_signature(
        raw_body=raw_body,
        timestamp=timestamp,
        slack_signature=slack_signature,
        signing_secret=signing_secret,
    )
    if not is_valid:
        raise ValueError("Invalid Slack signature.")

    return {"kind": "event", "event": payload.get("event", {}), "payload": payload}


def send_slack_webhook_message(
    *,
    webhook_url: str,
    text: str,
    username: str | None = None,
    icon_emoji: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Send a message through a Slack Incoming Webhook URL."""
    request_payload: dict[str, Any] = {"text": text}
    if username:
        request_payload["username"] = username
    if icon_emoji:
        request_payload["icon_emoji"] = icon_emoji

    response = requests.post(webhook_url, json=request_payload, timeout=timeout_seconds)
    response.raise_for_status()

    if not response.text.strip().lower().startswith("ok"):
        return {"ok": False, "status_code": response.status_code, "raw_response": response.text}

    return {"ok": True, "status_code": response.status_code, "raw_response": response.text}


def send_slack_bot_message(
    *,
    bot_token: str,
    channel: str,
    text: str,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Send a message with chat.postMessage using a bot token."""
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"channel": channel, "text": text}

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers,
        json=payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data}")

    return data


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Slack send/receive helper script.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_hook = subparsers.add_parser("send-webhook", help="Send message via incoming webhook URL.")
    send_hook.add_argument("--webhook-url", required=True)
    send_hook.add_argument("--text", required=True)
    send_hook.add_argument("--username", required=False)
    send_hook.add_argument("--icon-emoji", required=False)

    send_bot = subparsers.add_parser("send-bot", help="Send message via bot token and channel.")
    send_bot.add_argument("--bot-token", required=True)
    send_bot.add_argument("--channel", required=True)
    send_bot.add_argument("--text", required=True)

    verify = subparsers.add_parser("verify", help="Verify a Slack webhook request from stdin body.")
    verify.add_argument("--signing-secret", required=True)
    verify.add_argument("--timestamp", required=True)
    verify.add_argument("--signature", required=True)
    verify.add_argument(
        "--body",
        required=True,
        help="Raw JSON body string exactly as sent by Slack.",
    )

    return parser


def _main() -> None:
    parser = _build_cli()
    args = parser.parse_args()

    if args.command == "send-webhook":
        result = send_slack_webhook_message(
            webhook_url=args.webhook_url,
            text=args.text,
            username=args.username,
            icon_emoji=args.icon_emoji,
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "send-bot":
        result = send_slack_bot_message(
            bot_token=args.bot_token,
            channel=args.channel,
            text=args.text,
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "verify":
        parsed = receive_slack_webhook(
            raw_body=args.body.encode("utf-8"),
            timestamp=args.timestamp,
            slack_signature=args.signature,
            signing_secret=args.signing_secret,
        )
        print(json.dumps(parsed, indent=2))
        return


if __name__ == "__main__":
    _main()