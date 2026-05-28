"""Чистая бизнес-логика обработки мысли (без aiogram и без БД).

Здесь живут формулировки текстов и сборка ссылок. Дерево вопросов реализовано
в коде хендлеров — LLM лишь подсказывает классификацию и первый шаг.
"""
from __future__ import annotations

from urllib.parse import quote

from app.database.models import Thought


def build_delegation_text(thought: Thought) -> str:
    """Готовый текст для передачи задачи другому человеку."""
    summary = thought.summary or thought.raw_text
    first_step = thought.suggested_first_step or "—"
    return f"Задача: {summary}\nПервый шаг: {first_step}"


def build_telegram_share_url(text: str) -> str:
    """Ссылка для шаринга текста в Telegram."""
    return f"https://t.me/share/url?text={quote(text)}"


def calendar_title_for(thought: Thought) -> str:
    return thought.suggested_calendar_title or thought.summary or thought.raw_text


def calendar_details_for(thought: Thought) -> str:
    parts = [thought.raw_text]
    if thought.suggested_first_step:
        parts.append(f"Первый шаг: {thought.suggested_first_step}")
    return "\n\n".join(parts)


def analysis_intro(thought: Thought) -> str:
    """Краткое резюме, которое показывается перед деревом вопросов."""
    summary = thought.summary or thought.raw_text
    first_step = thought.suggested_first_step or "пока не определён"
    return (
        "Я понял мысль так:\n\n"
        f"<b>{summary}</b>\n\n"
        "Предложенный первый шаг:\n"
        f"{first_step}"
    )
