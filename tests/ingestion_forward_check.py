from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://3554qlgx-8001.asse.devtunnels.ms/"
DEFAULT_TIMEOUT_SECONDS = 90


def _read_env_value(key: str, env_path: Path) -> str | None:
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Forward a simple ingestion request to a remote API to verify OpenRouter/LLM path."
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Remote base URL where main.py is running.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Ingestion API key. If omitted, reads INGESTION_API_TOKEN from ../.env.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--text",
        default=(
            "This is a smoke test document for OpenRouter path verification. "
            "Category should be inferred and summary generated."
        ),
        help="Text to ingest.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"

    api_key = args.api_key or _read_env_value("INGESTION_API_TOKEN", env_path)
    if not api_key:
        raise RuntimeError(
            "Missing ingestion API key. Provide --api-key or set INGESTION_API_TOKEN in .env."
        )

    base_url = args.base_url.rstrip("/")
    endpoint = f"{base_url}/ingest/text"

    payload = {
        "document_id": f"forward-smoke-{int(time.time())}",
        "title": "Forward Smoke Test",
        "text": args.text,
    }

    response = requests.post(
        endpoint,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        json=payload,
        timeout=args.timeout,
    )

    print("POST", endpoint)
    print("Status:", response.status_code)

    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}

    print(json.dumps(body, indent=2))

    if response.status_code != 202:
        raise SystemExit(1)

    print("Ingestion request accepted. If remote service is configured correctly, it should process LLM mapping in background.")


if __name__ == "__main__":
    main()
