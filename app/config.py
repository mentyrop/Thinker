"""Конфигурация приложения.

Используем python-dotenv для загрузки .env и pydantic для валидации значений.
Это не привязывает нас к конкретному провайдеру LLM: достаточно указать
OpenAI-совместимый base_url (OpenAI, OpenRouter, прокси Claude и т.п.).
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()


class Settings(BaseModel):
    bot_token: str = Field(..., description="Токен Telegram-бота")
    database_url: str = Field(..., description="Async DSN PostgreSQL (asyncpg)")
    llm_api_key: str = Field("", description="Ключ OpenAI-совместимого API")
    llm_base_url: str = Field("https://api.openai.com/v1")
    llm_model: str = Field("gpt-4o-mini")

    @field_validator("bot_token")
    @classmethod
    def _check_token(cls, v: str) -> str:
        if not v:
            raise ValueError("BOT_TOKEN не задан в .env")
        return v


def get_settings() -> Settings:
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/thinker_bot",
        ),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
    )


settings = get_settings()
