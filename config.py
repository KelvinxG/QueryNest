import os
from functools import lru_cache
from pathlib import Path
from typing import Any
import re

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SMALL_MODEL = "gpt-4o-mini"
DEFAULT_LARGE_MODEL = "gpt-4o"


class Settings(BaseSettings):
    OPENAI_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_SMALL_MODEL: str = DEFAULT_SMALL_MODEL
    OPENAI_LARGE_MODEL: str = DEFAULT_LARGE_MODEL
    NEO4J_URI: str | None = None
    NEO4J_USER: str | None = None
    NEO4J_PASSWORD: str | None = None
    SLACK_BOT_TOKEN: str | None = None
    SLACK_SIGNING_SECRET: str | None = None
    GOOGLE_CREDENTIALS_FILE_PATH: str | None = None
    INGESTION_API_TOKEN: str | None = None

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


def _resolve_env_file_for_mode(app_env: str) -> str:
    project_root = Path(__file__).resolve().parent
    env_files = {
        "dev": project_root / ".env.dev",
        "prod": project_root / ".env.prod",
        "default": project_root / ".env",
    }

    preferred = env_files.get(app_env, env_files["default"])
    if preferred.exists():
        return str(preferred)

    fallback = env_files["default"]
    return str(fallback)


@lru_cache(maxsize=4)
def _load_settings_for_env(app_env: str) -> Settings:
    env_file = _resolve_env_file_for_mode(app_env)
    return Settings(_env_file=env_file)


def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "default").strip().lower()
    return _load_settings_for_env(app_env)


def require_settings(*names: str) -> dict[str, str]:
    settings = get_settings()
    values: dict[str, str] = {}
    missing: list[str] = []

    for name in names:
        raw_value = getattr(settings, name, None)
        value = raw_value.strip() if isinstance(raw_value, str) else raw_value
        if not value:
            missing.append(name)
            continue
        values[name] = str(value)

    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(f"Missing required settings: {missing_list}")

    return values


def _normalize_openai_api_key(raw_key: str | None, fallback_key: str | None = None) -> str:
    candidate_sources = [raw_key or "", fallback_key or ""]

    for candidate in candidate_sources:
        if not candidate:
            continue

        # OpenRouter keys normally start with sk-or-v1-. If the env value got
        # accidentally concatenated with another secret, recover the actual key.
        match = re.search(r"sk-or-v1-[A-Za-z0-9_-]+", candidate)
        if match:
            return match.group(0)

        if candidate.startswith("sk-"):
            return candidate.strip()

    return (raw_key or fallback_key or "").strip()


def get_llm_kwargs(*, model: str) -> dict[str, Any]:
    settings = get_settings()
    api_key = _normalize_openai_api_key(settings.OPENAI_API_KEY, settings.OPENROUTER_API_KEY)
    if not api_key:
        raise RuntimeError("Missing required settings: OPENAI_API_KEY")

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
    }

    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL

    return kwargs