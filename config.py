from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SMALL_MODEL = "gpt-4o-mini"
DEFAULT_LARGE_MODEL = "gpt-4o"


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    OPENAI_BASE_URL: str | None = None
    OPENAI_SMALL_MODEL: str = DEFAULT_SMALL_MODEL
    OPENAI_LARGE_MODEL: str = DEFAULT_LARGE_MODEL
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    SLACK_BOT_TOKEN: str
    SLACK_SIGNING_SECRET: str
    GOOGLE_CREDENTIALS_FILE_PATH: str
    INGESTION_API_TOKEN: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_llm_kwargs(*, model: str) -> dict[str, Any]:
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": settings.OPENAI_API_KEY,
    }

    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL

    return kwargs