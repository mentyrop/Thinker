"""LLM-сервис.

Отправляет мысль в OpenAI-совместимый API и получает СТРОГО JSON.
Результат валидируется через pydantic. При любой ошибке (сеть, невалидный
JSON, нестыковка схемы) используется детерминированный fallback — логика бота
никогда не зависит от доступности LLM.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import settings

logger = logging.getLogger(__name__)

ThoughtType = Literal[
    "task", "worry", "idea", "reflection", "project", "fact_search", "other"
]
NoteCategory = Literal[
    "journal", "thoughts_to_finish", "calendar", "delegate", "research"
]


SYSTEM_PROMPT = """Ты ассистент для Telegram-бота "Мыслитель". Твоя задача — анализировать мысли пользователя и возвращать только валидный JSON без markdown.

Методология:
- Любая мысль сначала фиксируется в журнале.
- Если человек не может повлиять на мысль, она считается пустой/не требующей действия.
- Если мысль можно превратить в задачу, нужно понять: можно ли делегировать, можно ли поставить в календарь, есть ли первый шаг.
- Если мысль важная, но непонятно что делать, её можно сохранить в "Мысли додумать".
- Если не хватает фактов, предложи исследование, звонок, чтение, встречу или сбор информации.

Верни JSON по схеме:

{
  "summary": "короткая ясная формулировка мысли",
  "type": "task | worry | idea | reflection | project | fact_search | other",
  "actionable": true/false,
  "can_delegate": true/false,
  "calendar_candidate": true/false,
  "needs_first_step": true/false,
  "needs_research": true/false,
  "suggested_first_step": "конкретный первый шаг или null",
  "suggested_calendar_title": "название события для календаря или null",
  "suggested_duration_minutes": 30,
  "suggested_note_category": "journal | thoughts_to_finish | calendar | delegate | research",
  "user_question_next": "какой вопрос лучше задать пользователю дальше"
}

Правила:
- Не ставь диагнозы.
- Не давай медицинские или психологические заключения.
- Если мысль тревожная или эмоциональная, всё равно мягко помоги понять, есть ли действие.
- Если мысль опасная, связана с самоповреждением или угрозой жизни, выставь type = "worry", actionable = false и user_question_next = "Похоже, это тяжёлая мысль. Если есть риск навредить себе или кому-то, пожалуйста, обратись за срочной помощью к близким или экстренным службам."
- Возвращай только JSON."""


class ThoughtAnalysis(BaseModel):
    summary: str
    type: ThoughtType = "other"
    actionable: bool = True
    can_delegate: bool = False
    calendar_candidate: bool = False
    needs_first_step: bool = True
    needs_research: bool = False
    suggested_first_step: str | None = None
    suggested_calendar_title: str | None = None
    suggested_duration_minutes: int = Field(default=30, ge=1, le=24 * 60)
    suggested_note_category: NoteCategory = "journal"
    user_question_next: str = "Можем ли мы повлиять на эту мысль?"


def _fallback(raw_text: str) -> ThoughtAnalysis:
    return ThoughtAnalysis(
        summary=raw_text.strip()[:500] or "Мысль",
        type="other",
        actionable=True,
        can_delegate=False,
        calendar_candidate=False,
        needs_first_step=True,
        needs_research=False,
        suggested_first_step=None,
        suggested_calendar_title=None,
        suggested_duration_minutes=30,
        suggested_note_category="journal",
        user_question_next="Можем ли мы повлиять на эту мысль?",
    )


def _strip_code_fences(content: str) -> str:
    """Некоторые модели всё равно оборачивают JSON в ```json ... ```."""
    content = content.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", content, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return content


def _parse(content: str, raw_text: str) -> ThoughtAnalysis:
    try:
        payload = json.loads(_strip_code_fences(content))
        return ThoughtAnalysis.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("LLM вернула невалидный JSON, использую fallback: %s", exc)
        return _fallback(raw_text)


async def analyze_thought(raw_text: str) -> ThoughtAnalysis:
    """Анализирует мысль. Никогда не бросает исключение наружу."""
    if not settings.llm_api_key:
        logger.warning("LLM_API_KEY не задан — использую fallback-анализ.")
        return _fallback(raw_text)

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Ошибка обращения к LLM, использую fallback: %s", exc)
        return _fallback(raw_text)

    return _parse(content, raw_text)
