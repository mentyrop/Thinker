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
- "calendar" — это конкретное действие, которое стоит привязать к дате и времени. ВАЖНО: если в мысли уже названы дата, день недели или время (например «завтра в 12:00», «в пятницу в 15:00», «30.05.2026 18:30»), почти всегда выбирай "calendar", ставь calendar_candidate = true, actionable = true и НЕ выбирай "empty_thought".
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
}

Пример. Мысль: "Нужно завтра в 12:00 позвонить в архив и уточнить часы работы."
Ответ:
{
  "summary": "Завтра в 12:00 позвонить в архив и уточнить часы работы",
  "type": "task",
  "recommended_route": "calendar",
  "confidence": 0.95,
  "actionable": true,
  "can_delegate": false,
  "calendar_candidate": true,
  "needs_research": false,
  "suggested_first_step": "Позвонить в архив в 12:00 и уточнить часы работы",
  "suggested_calendar_title": "Звонок в архив",
  "suggested_duration_minutes": 15,
  "user_question_next": "Добавить это действие в календарь?"
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


def _extract_json(content: str) -> str:
    """Аккуратно достаёт JSON, даже если модель добавила текст вокруг.

    Сначала снимаем code-fence, затем берём подстроку от первой `{`
    до последней `}`. Если ничего не нашли — возвращаем исходную строку,
    пусть json.loads сам бросит ошибку, которую перехватит вызывающий код.
    """
    cleaned = _strip_code_fences(content)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _parse(content: str, raw_text: str) -> ThoughtAnalysis:
    try:
        payload = json.loads(_strip_code_fences(content))
        return ThoughtAnalysis.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("LLM вернула невалидный JSON, использую fallback: %s", exc)
        return _fallback(raw_text)


async def _chat_json(system_prompt: str, user_text: str) -> str | None:
    """Один запрос к OpenAI-совместимому /chat/completions.

    Возвращает строку-контент ответа модели или None при любой ошибке
    (нет ключа, сеть, неожиданный формат ответа). Сам JSON не парсит —
    это делает вызывающий код.
    """
    if not settings.llm_api_key:
        logger.warning("LLM_API_KEY не задан — LLM недоступна.")
        return None

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
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("Ошибка обращения к LLM: %s", exc)
        return None


async def analyze_thought(raw_text: str) -> ThoughtAnalysis:
    """Анализирует мысль. Никогда не бросает исключение наружу."""
    content = await _chat_json(SYSTEM_PROMPT, raw_text)
    if content is None:
        return _fallback(raw_text)
    return _parse(content, raw_text)


# --------------------------------------------------------------------------- #
# Мини-проекты: LLM сама предлагает формулировку результата и шаги.            #
# Обе функции возвращают Optional — None означает «не получилось, попроси      #
# пользователя ввести вручную». Логика бота при None показывает fallback.      #
# --------------------------------------------------------------------------- #


class ProjectGoalResult(BaseModel):
    project_goal: str
    success_criteria: list[str] = Field(default_factory=list)
    short_title: str


class ProjectStepsResult(BaseModel):
    project_goal: str | None = None
    steps: list[str] = Field(default_factory=list)
    first_step: str
    calendar_title: str
    duration_minutes: int = Field(default=60, ge=1, le=24 * 60)


GOAL_PROMPT = """Ты ассистент Telegram-бота "Мыслитель". Помогаешь превратить расплывчатую мысль в чёткий желаемый результат мини-проекта. Возвращай только валидный JSON без markdown.

По тексту мысли пользователя сформулируй:
- project_goal — одно ясное предложение о том, какого результата человек хочет достичь (результат, а не процесс).
- success_criteria — список из 2-4 коротких критериев, по которым будет понятно, что результат достигнут.
- short_title — короткое название проекта (2-5 слов) для календаря и списков.

Правила:
- Формулируй за пользователя, не задавай ему вопросов.
- Пиши конкретно и по делу, без воды.
- ВАЖНО: не теряй важные элементы исходной мысли. Если пользователь перечислил несколько действий или целей, project_goal должен включать ВСЕ важные элементы, а success_criteria — соответствовать им.
- Возвращай только JSON по схеме:
{
  "project_goal": "...",
  "success_criteria": ["...", "..."],
  "short_title": "..."
}

Пример. Мысль: "Хочу восстановить семейное древо, найти архивные документы, поговорить с родственниками и собрать всё в одну понятную схему."
Ответ:
{
  "project_goal": "Восстановить семейное древо, собрать архивные документы, уточнить информацию у родственников и оформить всё в понятную схему",
  "success_criteria": ["Составлен список родственников с ФИО, датами и связями", "Найдены или запрошены архивные документы", "Получены уточнения от родственников", "Информация оформлена в единую схему семейного древа"],
  "short_title": "Семейное древо"
}"""


STEPS_PROMPT = """Ты ассистент Telegram-бота "Мыслитель". Помогаешь разложить мысль или проект на конкретные выполнимые шаги. Возвращай только валидный JSON без markdown.

По тексту мысли (и желаемому результату, если он дан) предложи:
- project_goal — желаемый результат одним предложением (повтори или уточни данный, либо сформулируй сам).
- steps — список из 3-6 конкретных последовательных шагов. Каждый шаг — короткое действие, начинающееся с глагола.
- first_step — самый первый конкретный шаг (обычно это steps[0]).
- calendar_title — короткое название для календарного события под первый шаг.
- duration_minutes — разумная длительность первого шага в минутах (число).

Правила:
- Делай шаги за пользователя, не задавай ему вопросов.
- Шаги должны быть выполнимыми и конкретными, без воды.
- Возвращай только JSON по схеме:
{
  "project_goal": "...",
  "steps": ["...", "...", "..."],
  "first_step": "...",
  "calendar_title": "...",
  "duration_minutes": 60
}

Пример. Мысль: "Хочу собрать семейное древо по линии бабушки." Результат: "Составить документированное семейное древо по линии бабушки минимум на три поколения".
Ответ:
{
  "project_goal": "Составить документированное семейное древо по линии бабушки минимум на три поколения",
  "steps": ["Записать всё, что уже известно: ФИО, даты, места", "Расспросить старших родственников и записать их рассказы", "Запросить документы в архивах ЗАГС по местам рождения", "Внести данные в сервис для построения древа", "Сверить и дополнить недостающие звенья"],
  "first_step": "Записать всё, что уже известно: ФИО, даты и места рождения родственников",
  "calendar_title": "Собрать известные данные о родственниках",
  "duration_minutes": 60
}"""


async def generate_project_goal(thought_text: str) -> ProjectGoalResult | None:
    """LLM предлагает формулировку результата проекта. None при неудаче."""
    content = await _chat_json(GOAL_PROMPT, thought_text)
    if content is None:
        return None
    try:
        payload = json.loads(_extract_json(content))
        return ProjectGoalResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("generate_project_goal: невалидный JSON: %s", exc)
        return None


async def generate_project_steps(
    thought_text: str, project_goal: str | None = None
) -> ProjectStepsResult | None:
    """LLM раскладывает мысль на шаги. None при неудаче."""
    user_text = thought_text
    if project_goal:
        user_text = f"Мысль: {thought_text}\nЖелаемый результат: {project_goal}"
    content = await _chat_json(STEPS_PROMPT, user_text)
    if content is None:
        return None
    try:
        payload = json.loads(_extract_json(content))
        return ProjectStepsResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("generate_project_steps: невалидный JSON: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Исследования: LLM сама предлагает план сбора фактов.                         #
# --------------------------------------------------------------------------- #


class ResearchPlanResult(BaseModel):
    research_goal: str
    steps: list[str] = Field(default_factory=list)
    first_step: str


RESEARCH_PROMPT = """Ты ассистент Telegram-бота "Мыслитель". Помогаешь, когда для решения мысли сначала нужно собрать факты или информацию. Возвращай только валидный JSON без markdown.

По тексту мысли пользователя предложи план исследования:
- research_goal — одно ясное предложение о том, что именно нужно выяснить или понять (цель сбора фактов).
- steps — список из 3-5 конкретных шагов исследования: что выяснить, где искать, кому позвонить, что прочитать, какие документы запросить. Каждый шаг — короткое действие, начинающееся с глагола.
- first_step — самый первый конкретный шаг (обычно steps[0]).

Правила:
- Делай план за пользователя, не задавай ему вопросов.
- Шаги должны быть выполнимыми и конкретными, без воды.
- Возвращай только JSON по схеме:
{
  "research_goal": "...",
  "steps": ["...", "...", "..."],
  "first_step": "..."
}

Пример. Мысль: "Хочу разобраться, с чего начать поиск родственников по линии бабушки, но пока не знаю, какие документы нужны."
Ответ:
{
  "research_goal": "Понять, какие документы и источники нужны, чтобы начать поиск родственников по линии бабушки",
  "steps": ["Записать всё, что уже известно: ФИО, даты и места рождения бабушки и её родни", "Узнать, в каких архивах ЗАГС и областных архивах хранятся нужные записи", "Прочитать гайд по генеалогическому поиску для начинающих", "Составить список запросов в архивы по местам рождения", "Спросить старших родственников о сохранившихся документах и фото"],
  "first_step": "Записать всё, что уже известно: ФИО, даты и места рождения бабушки и её родни"
}"""


DELEGATION_PROMPT = """Ты ассистент Telegram-бота "Мыслитель". Помогаешь превратить задачу в готовое вежливое сообщение, которое пользователь сразу отправит другому человеку. Возвращай только валидный JSON без markdown.

По тексту мысли составь готовое к отправке сообщение адресату:
- message — короткое, живое и вежливое сообщение от первого лица, как будто пишет сам пользователь.

Правила:
- Если в мысли указан адресат (мама, папа, Саша, брат, сестра, коллега, преподаватель, друг и т.д.), обратись к нему по имени/роли в начале: "Мам, привет!", "Саша, привет!".
- Если адресат не указан, начни нейтрально: "Привет! Можешь, пожалуйста, ...".
- НЕ используй формат "Задача:", "Первый шаг:", "Исполнитель:". Это должно быть человеческое сообщение, а не карточка задачи.
- Сообщение короткое (1-3 предложения), вежливое, с конкретной просьбой и, если уместно, просьбой прислать результат.
- Возвращай только JSON по схеме:
{
  "message": "..."
}

Пример. Мысль: "Нужно попросить маму найти дома старые фотографии, свидетельства и любые документы по бабушке, чтобы потом добавить их в семейное древо."
Ответ:
{
  "message": "Мам, привет! Можешь, пожалуйста, посмотреть дома старые фотографии, свидетельства или любые документы по бабушке? Я хочу добавить их в семейное древо. Если найдёшь что-то, сфотографируй и скинь мне, пожалуйста."
}"""


class DelegationResult(BaseModel):
    message: str


async def generate_research_plan(thought_text: str) -> ResearchPlanResult | None:
    """LLM предлагает план исследования. None при неудаче."""
    content = await _chat_json(RESEARCH_PROMPT, thought_text)
    if content is None:
        return None
    try:
        payload = json.loads(_extract_json(content))
        return ResearchPlanResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("generate_research_plan: невалидный JSON: %s", exc)
        return None


async def generate_delegation_message(thought_text: str) -> DelegationResult | None:
    """LLM составляет готовое сообщение адресату. None при неудаче."""
    content = await _chat_json(DELEGATION_PROMPT, thought_text)
    if content is None:
        return None
    try:
        payload = json.loads(_extract_json(content))
        return DelegationResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("generate_delegation_message: невалидный JSON: %s", exc)
        return None
