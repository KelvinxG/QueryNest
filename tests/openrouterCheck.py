from __future__ import annotations

import json
import re
from pathlib import Path

import requests
from dotenv import dotenv_values


def _normalize_openrouter_key(raw_key: str | None) -> str:
    if not raw_key:
        raise RuntimeError("OPENAI_API_KEY is missing from .env.")

    match = re.search(r"sk-or-v1-[A-Za-z0-9_-]+", raw_key)
    if match:
        return match.group(0)

    if raw_key.startswith("sk-"):
        return raw_key.strip()

    raise RuntimeError("Could not find a valid OpenRouter API key in OPENAI_API_KEY.")


project_root = Path(__file__).resolve().parent.parent
settings = dotenv_values(project_root / ".env")
api_key = _normalize_openrouter_key(settings.get("OPENAI_API_KEY"))
model_name = settings.get("OPENAI_SMALL_MODEL") or "openai/gpt-4o-mini"

response = requests.post(
    url="https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "knowledgeGraph-openrouterCheck",
    },
    data=json.dumps(
        {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": "Hello! What can you help me with today?",
                }
            ],
        }
    ),
    timeout=60,
)

response.raise_for_status()
data = response.json()
print(data["choices"][0]["message"]["content"])
print("Model used:", data["model"])