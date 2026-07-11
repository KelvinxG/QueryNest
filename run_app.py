from __future__ import annotations

import argparse
import os

import uvicorn


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run GraphRAG API with explicit dev/prod environment mode.")
    parser.add_argument("--env", choices=["dev", "prod"], required=True, help="Environment mode.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=None, help="Port to bind. Defaults to PORT env or 8001.")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development.")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    os.environ["APP_ENV"] = args.env

    env_port = os.getenv("PORT", "").strip()
    if args.port is not None:
        port = args.port
    elif env_port.isdigit():
        port = int(env_port)
    else:
        port = 8001

    uvicorn.run(
        "app.api.asgi:app",
        host=args.host,
        port=port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
