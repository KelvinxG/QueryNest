from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_TIMEOUT_SECONDS = 90


def _candidate_env_files(project_root: Path) -> list[Path]:
    app_env = os.getenv("APP_ENV", "").strip().lower()

    candidates: list[Path] = []
    if app_env == "prod":
        candidates.extend([project_root / ".env.prod", project_root / ".env"])
    elif app_env == "dev":
        candidates.extend([project_root / ".env.dev", project_root / ".env"])
    else:
        candidates.extend([project_root / ".env.prod", project_root / ".env", project_root / ".env.dev"])

    seen: set[Path] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)

    return ordered


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


def _resolve_config_value(key: str, project_root: Path) -> str | None:
    env_value = os.getenv(key, "").strip()
    if env_value:
        return env_value

    for env_path in _candidate_env_files(project_root):
        value = _read_env_value(key, env_path)
        if value:
            return value

    return None


def _build_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parent.parent
    default_base_url = _resolve_config_value("PUBLIC_API_BASE_URL", project_root) or DEFAULT_BASE_URL

    parser = argparse.ArgumentParser(
        description="Forward a simple ingestion request to a remote API to verify OpenRouter/LLM path."
    )
    parser.add_argument(
        "--base-url",
        default=default_base_url,
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
    api_key = args.api_key or _resolve_config_value("INGESTION_API_TOKEN", project_root)
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
