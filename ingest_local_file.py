from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

DEFAULT_BASE_URL = "http://127.0.0.1:8001"


def _candidate_env_files(project_root: Path) -> list[Path]:
    app_env = os.getenv("APP_ENV", "").strip().lower()

    candidates: list[Path] = []
    if app_env == "prod":
        candidates.extend([project_root / ".env.prod", project_root / ".env"])
    elif app_env == "dev":
        candidates.extend([project_root / ".env.dev", project_root / ".env"])
    else:
        candidates.extend([project_root / ".env", project_root / ".env.prod", project_root / ".env.dev"])

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
        env_values = dotenv_values(env_path)
        value = env_values.get(key) or _read_env_value(key, env_path)
        if value:
            return str(value).strip()

    return None


def _build_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parent
    default_base_url = _resolve_config_value("PUBLIC_API_BASE_URL", project_root) or DEFAULT_BASE_URL

    parser = argparse.ArgumentParser(description="Ingest a local text file using /ingest/text.")
    parser.add_argument("--file", required=True, help="Path to local text file.")
    parser.add_argument("--title", required=False, help="Document title. Defaults to file stem.")
    parser.add_argument("--document-id", required=False, help="Document id. Auto-generated if omitted.")
    parser.add_argument("--base-url", default=default_base_url, help="API base URL.")
    parser.add_argument(
        "--api-key",
        required=False,
        help="Ingestion API key. If omitted, reads INGESTION_API_TOKEN from .env.",
    )
    parser.add_argument("--timeout", type=int, default=120, help="HTTP timeout in seconds.")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    file_path = Path(args.file)
    if not file_path.exists() or not file_path.is_file():
        raise RuntimeError(f"File not found: {file_path}")

    project_root = Path(__file__).resolve().parent
    api_key = args.api_key or _resolve_config_value("INGESTION_API_TOKEN", project_root)
    if not api_key:
        raise RuntimeError("Missing ingestion API key. Provide --api-key or set INGESTION_API_TOKEN in .env.")

    document_id = args.document_id or f"local-file-{int(time.time())}"
    title = args.title or file_path.stem
    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("Local file is empty.")

    endpoint = f"{args.base_url.rstrip('/')}/ingest/text"
    payload = {
        "document_id": document_id,
        "title": title,
        "text": text,
    }

    response = requests.post(
        endpoint,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": str(api_key),
        },
        json=payload,
        timeout=args.timeout,
    )

    print("POST", endpoint)
    print("document_id:", document_id)
    print("status:", response.status_code)

    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)

    if response.status_code != 202:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
