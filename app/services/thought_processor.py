"""Чистая бизнес-логика обработки мысли (без aiogram и без БД).

Здесь живут формулировки текстов и сборка ссылок. Дерево вопросов реализовано
в коде хендлеров — LLM лишь подсказывает классификацию и первый шаг.
"""
from __future__ import annotations

import html
from urllib.parse import quote

from app.database.models import Thought

# Технические значения → человекочитаемые русские.
CATEGORY_LABELS = {
    "journal": "Журнал",
    "project": "Мини-проект",
    "calendar": "Календарь",
    "research": "Исследование",
    "thoughts_to_finish": "Мысли додумать",
    "delegate": "Делегирование",
}

STATUS_LABELS = {
    "new": "новая",
    "in_progress": "в работе",
    "goal_confirmed": "результат зафиксирован",
    "steps_generated": "шаги предложены",
    "project_saved": "сохранён",
    "calendar_pending": "ожидает выбора даты",
    "calendar_created": "добавлено в календарь",
    "research_needed": "нужны факты",
    "think_later": "отложено",
    "empty_closed": "закрыто как неподконтрольное",
    "delegation_ready": "готово к делегированию",
    "closed": "закрыто",
}

TYPE_LABELS = {
    "task": "Задача",
    "worry": "Тревога",
    "idea": "Идея",
    "reflection": "Размышление",
    "project": "Мини-проект",
    "fact_search": "Поиск фактов",
    "other": "Другое",
}

# Лимит Telegram-сообщения 4096 символов. Держим запас под разметку.
MAX_MESSAGE_LEN = 3500


def format_category(category: str | None) -> str:
    if not category:
        return "—"
    return CATEGORY_LABELS.get(category, category)


def format_status(status: str | None) -> str:
    if not status:
        return "—"
    return STATUS_LABELS.get(status, status)


def format_type(type_: str | None) -> str:
    if not type_:
        return "—"
    return TYPE_LABELS.get(type_, type_)


def journal_line(thought: Thought) -> str:
    """Короткая подпись для текстового представления (если нужно)."""
    text = thought.summary or thought.raw_text
    return (
        f"{thought.created_at.strftime('%d.%m %H:%M')} — {text[:80]}\n"
        f"{format_category(thought.category)} · {format_status(thought.status)}"
    )


def journal_button_label(thought: Thought, index: int) -> str:
    """Подпись кнопки в списке журнала (коротко, до ~60 символов)."""
    text = (thought.summary or thought.raw_text or "Мысль").strip()
    text = " ".join(text.split())
    if len(text) > 55:
        text = text[:54].rstrip() + "…"
    return f"{index}. {text}"


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {html.escape(s)}" for i, s in enumerate(items, 1))


def format_thought_card(thought: Thought) -> str:
    """Карточка мысли. Показывает только заполненные блоки.

    Длинные поля при необходимости укорачиваются, чтобы не превышать
    лимит Telegram-сообщения.
    """
    raw = (thought.raw_text or "").strip()
    if len(raw) > 1500:
        raw = raw[:1500].rstrip() + "…"

    header = "🧩 <b>Мини-проект</b>" if thought.category == "project" else "📌 <b>Мысль</b>"
    parts: list[str] = [header, ""]
    parts.append("<b>Исходный текст:</b>")
    parts.append(html.escape(raw))

    if thought.summary:
        parts += ["", "<b>Кратко:</b>", html.escape(thought.summary)]

    parts += ["", "<b>Тип:</b>", format_type(thought.type)]
    parts += ["", "<b>Статус:</b>", format_status(thought.status)]
    parts += ["", "<b>Категория:</b>", format_category(thought.category)]

    if thought.research_method:
        parts += [
            "",
            "<b>Способ сбора фактов:</b>",
            html.escape(thought.research_method),
        ]

    if thought.suggested_first_step:
        parts += [
            "",
            "<b>Предложенный первый шаг:</b>",
            html.escape(thought.suggested_first_step),
        ]

    if thought.project_goal:
        parts += ["", "<b>Цель:</b>", html.escape(thought.project_goal)]

    if thought.project_steps:
        parts += ["", "<b>Шаги:</b>", _numbered(list(thought.project_steps))]

    if thought.success_criteria:
        parts += [
            "",
            "<b>Критерии готовности:</b>",
            _numbered(list(thought.success_criteria)),
        ]

    text = "\n".join(parts)
    if len(text) > MAX_MESSAGE_LEN:
        text = text[:MAX_MESSAGE_LEN].rstrip() + "\n…"
    return text


def format_project_goal(
    project_goal: str,
    success_criteria: list[str] | None = None,
    title: str | None = None,
) -> str:
    """Сообщение с предложенной формулировкой результата проекта."""
    lines = [
        "Это похоже на мини-проект.",
        "",
        "Я сформулировал возможный результат:",
        "",
        f"🎯 <b>{html.escape(project_goal)}</b>",
    ]
    if success_criteria:
        lines.append("")
        lines.append("Критерии готовности:")
        for c in success_criteria:
            lines.append(f"• {html.escape(c)}")
    if title:
        lines.append("")
        lines.append(f"Короткое название: <i>{html.escape(title)}</i>")
    lines += ["", "Подходит?"]
    return "\n".join(lines)


def format_project_steps(
    steps: list[str], project_goal: str | None = None
) -> str:
    """Сообщение с предложенными шагами проекта."""
    lines = []
    if project_goal:
        lines.append(f"🎯 Результат: <b>{html.escape(project_goal)}</b>")
        lines.append("")
    lines.append("Я разложил проект на шаги:")
    lines.append("")
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {html.escape(step)}")
    if steps:
        lines += ["", f"Первый шаг:\n<b>{html.escape(steps[0])}</b>"]
    lines += ["", "Всё выглядит нормально?"]
    return "\n".join(lines)


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
