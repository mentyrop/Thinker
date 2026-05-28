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
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.config import settings

logger = logging.getLogger(__name__)

ThoughtType = Literal[
    "task", "worry", "idea", "reflection", "project", "fact_search", "other"
]
NoteCategory = Literal[
    "journal", "thoughts_to_finish", "calendar", "delegate", "research"
]
RecommendedRoute = Literal[
    "empty_thought",
    "delegate",
    "calendar",
    "project",
    "research",
    "think_later",
    "ask_actionable",
]


SYSTEM_PROMPT = """Ты ассистент для Telegram-бота "Мыслитель". Твоя задача — анализировать мысли пользователя и возвращать только валидный JSON без markdown.

Методология:
- Любая мысль сначала фиксируется в журнале.
- Дальше нужно определить ОДИН наиболее подходящий маршрут обработки (recommended_route), чтобы бот не задавал все вопросы подряд, а сразу предложил уместное действие.
- Если человек не может повлиять на мысль — это пустая мысль, не требующая действия.
- Если мысль можно превратить в задачу — оцени, лучше её делегировать, запланировать в календарь или это целый проект.
- Если мысль важная, но непонятно что делать — её можно сохранить в "Мысли додумать".
- Если не хватает фактов — нужно исследование (звонок, чтение, встреча, сбор информации).

Выбор recommended_route:
- "empty_thought" — мысль не требует действия / на неё нельзя повлиять (тревога о том, что вне контроля).
- "delegate" — это задача, которую логично передать другому человеку.
- "calendar" — это конкретное действие, которое стоит привязать к дате и времени.
- "project" — крупная многошаговая задача / мини-проект.
- "research" — для решения сначала нужно собрать факты или информацию.
- "think_later" — мысль расплывчатая, пока неясно, что с ней делать.
- "ask_actionable" — ты не уверена в маршруте; пусть бот сам спросит, можно ли повлиять.

confidence — твоя уверенность в выбранном маршруте, число от 0.0 до 1.0. Если confidence < 0.5, ставь recommended_route = "ask_actionable".

Верни JSON строго по схеме:

{
  "summary": "короткая ясная формулировка мысли",
  "type": "task | worry | idea | reflection | project | fact_search | other",
  "recommended_route": "empty_thought | delegate | calendar | project | research | think_later | ask_actionable",
  "confidence": 0.0,
  "actionable": true/false,
  "can_delegate": true/false,
  "calendar_candidate": true/false,
  "needs_research": true/false,
  "suggested_first_step": "конкретный первый шаг или null",
  "suggested_calendar_title": "название события для календаря или null",
  "suggested_duration_minutes": 30,
  "user_question_next": "какой вопрос лучше задать пользователю дальше"
}

Правила:
- Не ставь диагнозы.
- Не давай медицинские или психологические заключения.
- Если мысль тревожная или эмоциональная, всё равно мягко помоги понять, есть ли действие.
- Если мысль опасная, связана с самоповреждением или угрозой жизни, выставь type = "worry", recommended_route = "empty_thought", actionable = false и user_question_next = "Похоже, это тяжёлая мысль. Если есть риск навредить себе или кому-то, пожалуйста, обратись за срочной помощью к близким или экстренным службам."
- Возвращай только JSON.

Пример. Мысль: "Хочу разобраться, с чего начать поиск родственников по линии бабушки, но пока не знаю, какие документы нужны."
Ответ:
{
  "summary": "Понять, с каких документов начать поиск родственников по линии бабушки",
  "type": "fact_search",
  "recommended_route": "research",
  "confidence": 0.9,
  "actionable": true,
  "can_delegate": false,
  "calendar_candidate": true,
  "needs_research": true,
  "suggested_first_step": "Составить список известных ФИО, дат рождения и мест проживания родственников",
  "suggested_calendar_title": "Исследовать документы для поиска родственников",
  "suggested_duration_minutes": 60,
  "user_question_next": "Как лучше собрать факты по этой мысли?"
}"""


class ThoughtAnalysis(BaseModel):
    summary: str
    type: ThoughtType = "other"
    recommended_route: RecommendedRoute = "ask_actionable"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
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

    @model_validator(mode="after")
    def _low_confidence_to_ask(self) -> "ThoughtAnalysis":
        # При низкой уверенности не доверяем маршруту — пусть бот спросит сам.
        if self.confidence < 0.5 and self.recommended_route != "ask_actionable":
            object.__setattr__(self, "recommended_route", "ask_actionable")
        return self


def _fallback(raw_text: str) -> ThoughtAnalysis:
    return ThoughtAnalysis(
        summary=raw_text.strip()[:500] or "Мысль",
        type="other",
        recommended_route="ask_actionable",
        confidence=0.0,
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
