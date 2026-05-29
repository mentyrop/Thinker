"""Создание новой мысли и smart-routing обработки.

Любая мысль сначала сохраняется в журнал, затем LLM возвращает JSON с полем
`recommended_route`. Бот НЕ задаёт все вопросы подряд: он выбирает один
контекстный сценарий и сразу предлагает уместное действие. Полная цепочка
вопросов («разобрать подробнее») запускается только для маршрута
`ask_actionable` или когда пользователь явно просит разобрать дальше.

Вся логика ветвления — в коде. LLM лишь классифицирует мысль, переформулирует
её и подсказывает первый шаг.
"""
from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    after_kb,
    calendar_result_kb,
    calendar_route_kb,
    clarify_kb,
    delegate_confirm_kb,
    delegation_kb,
    direction_kb,
    first_step_kb,
    goal_edited_kb,
    project_goal_kb,
    project_saved_kb,
    project_steps_kb,
    research_kb,
    research_plan_kb,
    research_saved_kb,
    steps_edited_kb,
    thought_card_kb,
    thought_delete_confirm_kb,
    yes_no_kb,
)
from app.bot.states.thought_states import ThoughtStates
from app.database.models import Thought
from app.database.repositories import (
    CalendarEventRepository,
    ThoughtRepository,
    UserRepository,
)
from app.services import calendar_service, thought_processor
from app.services.llm_service import (
    analyze_thought,
    generate_delegation_message,
    generate_project_goal,
    generate_project_steps,
    generate_research_plan,
)

router = Router(name="thoughts")

# Тексты вопросов классической цепочки (deep-dive)
Q1 = "Можем ли мы повлиять на эту мысль?"
Q2 = "Можно ли делегировать эту задачу другому человеку?"
Q3 = "Можно ли записать это как действие на конкретный день и время?"
Q4 = "Понятен ли первый шаг?"
Q5 = "Нужно ли больше фактов, чтобы решить этот вопрос?"

DATETIME_HINT = (
    "Напиши дату и время в свободной форме:\n"
    "• <code>завтра 12:00</code>\n"
    "• <code>30.05.2026 15:30</code>"
)
DATETIME_RETRY = (
    "Не получилось распознать дату. Введи в формате "
    "<code>DD.MM.YYYY HH:MM</code>, например <code>30.05.2026 15:30</code>."
)
NOT_FOUND = "Мысль не найдена, начни заново."

# Снимаем нумерацию/маркеры в начале строки: «1. », «2) », «- », «• ».
_STEP_PREFIX_RE = re.compile(r"^\s*(?:\d+[.)]\s*|[-*•]\s*)")


def _parse_steps(text: str) -> list[str]:
    """Разбивает текст на шаги: каждая непустая строка — отдельный шаг.
    Если строк нет (одна строка) — это один шаг. Нумерация удаляется."""
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    if not lines:
        lines = [text.strip()]
    return [_STEP_PREFIX_RE.sub("", line).strip() for line in lines]


async def _has_calendar(session: AsyncSession, thought_id: int) -> bool:
    event = await CalendarEventRepository.latest_for_thought(session, thought_id)
    return event is not None


# Категории, которые при добавлении в календарь становятся "calendar".
# Проект/исследование/делегирование сохраняют свою идентичность — добавление
# календарного события не должно стирать их категорию.
_CALENDAR_REPLACEABLE = {None, "journal", "thoughts_to_finish", "calendar"}


def _calendar_category(thought: Thought) -> str | None:
    """Возвращает 'calendar', если категорию можно переопределить, иначе None
    (None означает «не менять категорию» в set_category_status)."""
    return "calendar" if thought.category in _CALENDAR_REPLACEABLE else None


async def _get_thought(session: AsyncSession, state: FSMContext) -> Thought | None:
    data = await state.get_data()
    thought_id = data.get("thought_id")
    if thought_id is None:
        return None
    return await ThoughtRepository.get(session, thought_id)


async def _owned_from_cb(
    callback: CallbackQuery, session: AsyncSession
) -> Thought | None:
    """Достаёт мысль по id из callback_data, проверяя владельца.

    Возвращает None, если id некорректен или мысль чужая/удалена —
    нельзя открыть чужую мысль по id.
    """
    try:
        thought_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return None
    user = await UserRepository.get_or_create(
        session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )
    return await ThoughtRepository.get_owned(session, thought_id, user.id)


# ---------------------------------------------------------------------------
# Переиспользуемые конечные действия веток
# ---------------------------------------------------------------------------
async def _do_delegation(
    message: Message, session: AsyncSession, thought: Thought, state: FSMContext
) -> None:
    """Готовит готовое человеческое сообщение адресату и сохраняет мысль
    как делегирование. LLM пишет текст; при сбое — детерминированный fallback.
    Обновляет ту же запись (без дублей)."""
    await state.update_data(thought_id=thought.id)
    thinking = await message.answer("Готовлю сообщение…")
    result = await generate_delegation_message(thought.raw_text)
    try:
        await thinking.delete()
    except Exception:
        pass

    if result is not None and result.message.strip():
        text = result.message.strip()
    else:
        text = thought_processor.build_delegation_text(thought)

    await ThoughtRepository.set_delegation(session, thought, text)
    await message.answer(
        "🤝 <b>Делегирование</b>\n\n"
        "Готовое сообщение — можно отправить как есть:\n\n"
        f"<code>{html.escape(text)}</code>",
        reply_markup=delegation_kb(thought_id=thought.id),
    )
    await state.set_state(None)


async def _ask_calendar_datetime(
    message: Message,
    session: AsyncSession,
    thought: Thought,
    state: FSMContext,
    prompt: str = DATETIME_HINT,
) -> None:
    await ThoughtRepository.set_category_status(
        session,
        thought,
        category=_calendar_category(thought),
        status="calendar_pending",
    )
    await state.update_data(thought_id=thought.id)
    await state.set_state(ThoughtStates.waiting_for_calendar_datetime)
    await message.answer(prompt)


async def _save_think_later(
    message: Message, session: AsyncSession, thought: Thought, state: FSMContext
) -> None:
    await ThoughtRepository.set_category_status(
        session, thought, category="thoughts_to_finish", status="think_later"
    )
    await message.answer(
        "Сохранил мысль в раздел «Мысли додумать». Вернёмся к ней позже.",
        reply_markup=after_kb(),
    )
    await state.set_state(None)


VAGUE_CLARIFY_TEXT = (
    "Эта мысль пока слишком общая. Чтобы я смог разложить её на действие, "
    "нужно чуть уточнить.\n\n"
    "Попробуй ответить на один из вопросов:\n\n"
    "1. Что именно тебя не устраивает?\n"
    "2. Какой результат ты хочешь получить?\n"
    "3. Что должно измениться в идеале?\n"
    "4. Какой самый маленький шаг можно сделать, чтобы разобраться?\n\n"
    "Напиши уточнение одним сообщением."
)


async def _start_clarification(
    message: Message, session: AsyncSession, thought: Thought, state: FSMContext
) -> None:
    """Запускает сценарий уточнения слишком общей мысли. Ответ пользователя
    дописывается к той же мысли и переанализируется (без создания дубля)."""
    await ThoughtRepository.set_category_status(
        session, thought, category="thoughts_to_finish", status="clarification_needed"
    )
    await state.update_data(thought_id=thought.id)
    await state.set_state(ThoughtStates.waiting_for_clarification)
    await message.answer(VAGUE_CLARIFY_TEXT, reply_markup=clarify_kb())


async def _show_direction_menu(message: Message, state: FSMContext) -> None:
    """Меню «разобрать иначе» вместо старой линейной анкеты.

    Старая цепочка вопросов q1→q5 теперь запускается только для маршрута
    ask_actionable (когда LLM не уверена), а пользовательское «разобрать
    иначе» ведёт в это контекстное меню действий.
    """
    await state.set_state(None)
    await message.answer(
        "Окей, разберём мысль другим способом. Что сделать?",
        reply_markup=direction_kb(),
    )


# ---------------------------------------------------------------------------
# Точка входа: анализ + выбор маршрута
# ---------------------------------------------------------------------------
async def _route_thought(
    message: Message,
    session: AsyncSession,
    thought: Thought,
    state: FSMContext,
    allow_clarify: bool = True,
) -> None:
    """Показывает резюме и направляет в ОДИН контекстный сценарий.

    allow_clarify=False отключает сценарий уточнения — используется после
    того, как пользователь уже уточнил мысль, чтобы не зациклиться.
    """
    await state.set_state(None)
    await state.update_data(thought_id=thought.id)

    route = thought.recommended_route or "ask_actionable"

    # Слишком общая мысль (или маршрут «подумать позже») → не навязываем
    # мини-проект, а просим уточнить. Календарь — исключение: дата уже явна.
    if allow_clarify and route != "calendar" and (
        route == "think_later" or thought_processor.is_vague_thought(thought.raw_text)
    ):
        await _start_clarification(message, session, thought, state)
        return

    if route == "project":
        # Строгий сценарий мини-проекта: сразу предлагаем результат (LLM).
        await _propose_goal(message, session, thought, state)
        return

    await message.answer(thought_processor.analysis_intro(thought))

    if route == "empty_thought":
        # Спрашиваем о подконтрольности отдельным префиксом (ea), чтобы НЕ
        # запускать линейную анкету q1→q5.
        await message.answer(Q1, reply_markup=yes_no_kb("ea"))
    elif route == "delegate":
        await message.answer(
            "Похоже, это можно делегировать. Подготовить сообщение?",
            reply_markup=delegate_confirm_kb(),
        )
    elif route == "calendar":
        await message.answer(
            "Похоже, это можно запланировать. Добавим в календарь?",
            reply_markup=calendar_route_kb(),
        )
    elif route == "research":
        # Бот сам предлагает план исследования (LLM); fallback — выбор способа.
        await _propose_research(message, session, thought, state)
    else:  # ask_actionable — LLM не уверена, запускаем классическую анкету
        await message.answer(Q1, reply_markup=yes_no_kb("q1"))


async def process_new_thought(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Сохраняет сырую мысль, анализирует через LLM, выбирает маршрут."""
    user = await UserRepository.get_or_create(
        session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    thought = await ThoughtRepository.create(session, user.id, message.text)

    thinking = await message.answer("Думаю над мыслью…")
    analysis = await analyze_thought(thought.raw_text)
    # Детерминированный override: если в тексте явно есть дата И время —
    # это календарная задача, что бы ни сказала LLM. Так бот не спрашивает
    # «можно ли повлиять» на очевидное запланированное действие.
    if calendar_service.has_explicit_datetime(thought.raw_text):
        analysis.recommended_route = "calendar"
        analysis.calendar_candidate = True
        analysis.actionable = True
    thought = await ThoughtRepository.apply_analysis(session, thought, analysis)
    try:
        await thinking.delete()
    except Exception:
        pass

    await _route_thought(message, session, thought, state)


# ---------------------------------------------------------------------------
# Точки входа в создание мысли
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:new")
async def cb_new_thought(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ThoughtStates.waiting_for_thought)
    await callback.message.answer("Напиши мысль одним сообщением.")
    await callback.answer()


@router.message(F.text == "📝 Новая мысль")
async def reply_new_thought(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ThoughtStates.waiting_for_thought)
    await message.answer("Напиши мысль одним сообщением.")


@router.message(ThoughtStates.waiting_for_thought, F.text)
async def on_thought_text(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    await process_new_thought(message, session, state)


# ---------------------------------------------------------------------------
# Маршрут: delegate
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "delegate:prepare")
async def delegate_prepare(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _do_delegation(callback.message, session, thought, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Маршрут: calendar (явная дата/время в мысли)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "cal_route:yes")
async def cal_route_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _ask_calendar_datetime(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "cal_route:other")
async def cal_route_other(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_direction_menu(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "cal_route:later")
async def cal_route_later(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _save_think_later(callback.message, session, thought, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Маршрут: think_later
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "rt_later:yes")
async def rt_later_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _save_think_later(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "rt_later:no")
async def rt_later_no(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_direction_menu(callback.message, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# empty_thought: можно ли повлиять? (без линейной анкеты)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "ea:no")
async def ea_no(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if thought:
        await ThoughtRepository.set_category_status(
            session, thought, category="journal", status="empty_closed"
        )
    await callback.message.answer(
        "Окей. Мысль сохранена в журнале как та, на которую сейчас не нужно "
        "тратить энергию.",
        reply_markup=after_kb(),
    )
    await state.set_state(None)
    await callback.answer()


@router.callback_query(F.data == "ea:yes")
async def ea_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_direction_menu(callback.message, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Меню «разобрать иначе»: контекстные направления
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "dir:goal")
async def dir_goal(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    await _propose_goal(callback.message, session, thought, state)


@router.callback_query(F.data == "dir:research")
async def dir_research(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    await _propose_research(callback.message, session, thought, state)


@router.callback_query(F.data == "dir:calendar")
async def dir_calendar(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _ask_calendar_datetime(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "dir:delegate")
async def dir_delegate(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _do_delegation(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "dir:later")
async def dir_later(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _save_think_later(callback.message, session, thought, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Маршрут: project — бот САМ предлагает результат и шаги через LLM.
# Ручной ввод используется только как правка («Изменить»/«Редактировать»)
# или fallback, если LLM недоступна / вернула невалидный JSON.
# ---------------------------------------------------------------------------
async def _propose_goal(
    message: Message,
    session: AsyncSession,
    thought: Thought,
    state: FSMContext,
    regenerated: bool = False,
) -> None:
    """LLM предлагает результат для текущей мысли. Обновляет ту же запись.

    Ручного ввода результата в MVP нет: если LLM недоступна, формулируем
    результат автоматически из summary/raw_text и сразу показываем кнопки.
    """
    await state.update_data(thought_id=thought.id)
    await ThoughtRepository.set_category_status(
        session, thought, category="project", status="in_progress"
    )

    thinking = await message.answer("Формулирую результат…")
    result = await generate_project_goal(thought.raw_text)
    try:
        await thinking.delete()
    except Exception:
        pass

    if result is None:
        # Fallback без ручного ввода: берём краткую формулировку мысли.
        goal = (thought.summary or thought.raw_text or "").strip()
    else:
        goal = result.project_goal

    await state.update_data(proposed_goal=goal)
    await message.answer(
        thought_processor.format_project_goal(goal, regenerated=regenerated),
        reply_markup=project_goal_kb(),
    )


async def _propose_steps(
    message: Message,
    session: AsyncSession,
    thought: Thought,
    state: FSMContext,
    intro: str | None = None,
) -> None:
    """LLM раскладывает текущую мысль на шаги. Обновляет ту же запись.

    Ручного ввода шагов в MVP нет: если LLM недоступна, формируем один шаг
    автоматически (первый шаг / summary) и сразу показываем кнопки.
    """
    await state.update_data(thought_id=thought.id)
    await ThoughtRepository.set_category_status(
        session, thought, category="project", status="in_progress"
    )

    thinking = await message.answer("Раскладываю на шаги…")
    result = await generate_project_steps(thought.raw_text, thought.project_goal)
    try:
        await thinking.delete()
    except Exception:
        pass

    if result is None:
        # Fallback без ручного ввода: один автоматический шаг.
        steps = [
            (thought.suggested_first_step or thought.summary or thought.raw_text or "").strip()
        ]
        first_step = steps[0]
        project_goal = thought.project_goal
    else:
        steps = result.steps
        first_step = result.first_step
        project_goal = result.project_goal
        # Параметры календаря фиксируем сразу, чтобы кнопка
        # «Добавить первый шаг в календарь» работала без доп. сохранения.
        thought.suggested_calendar_title = result.calendar_title
        thought.suggested_duration_minutes = result.duration_minutes

    await ThoughtRepository.set_project_steps(
        session,
        thought,
        steps=steps,
        first_step=first_step,
        project_goal=project_goal,
    )
    await ThoughtRepository.set_category_status(
        session, thought, category="project", status="steps_generated"
    )
    await state.update_data(proposed_steps=steps)
    await message.answer(
        thought_processor.format_project_steps(steps, project_goal, intro=intro),
        reply_markup=project_steps_kb(),
    )


async def _propose_research(
    message: Message, session: AsyncSession, thought: Thought, state: FSMContext
) -> None:
    """LLM предлагает план исследования (цель, шаги, первый шаг). Обновляет ту
    же запись. Если LLM недоступна — fallback на выбор способа сбора фактов."""
    await state.update_data(thought_id=thought.id)

    thinking = await message.answer("Собираю план исследования…")
    result = await generate_research_plan(thought.raw_text)
    try:
        await thinking.delete()
    except Exception:
        pass

    if result is None:
        # Fallback: помечаем как исследование и предлагаем выбрать способ.
        await ThoughtRepository.set_category_status(
            session, thought, category="research", status="research_needed"
        )
        await message.answer(
            "Похоже, для этой мысли нужно собрать больше фактов. "
            "Как лучше собрать факты?",
            reply_markup=research_kb(),
        )
        return

    # Сохраняем план сразу в черновик статуса (но окончательно — по кнопке).
    await state.update_data(
        proposed_research_goal=result.research_goal,
        proposed_research_steps=result.steps,
        proposed_research_first=result.first_step,
    )
    await ThoughtRepository.set_category_status(
        session, thought, category="research", status="research_plan_generated"
    )
    await message.answer(
        thought_processor.format_research_plan(
            result.research_goal, result.steps, result.first_step
        ),
        reply_markup=research_plan_kb(),
    )


@router.callback_query(F.data == "proj:outcome")
async def proj_outcome(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    await _propose_goal(callback.message, session, thought, state)


@router.callback_query(F.data == "goal:ok")
async def goal_ok(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """Результат подтверждён → сохраняем и СРАЗУ раскладываем на шаги.
    Промежуточного экрана «Разбить на шаги» больше нет."""
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    data = await state.get_data()
    goal = data.get("proposed_goal")
    if not goal:
        await callback.answer("Нет предложенного результата.", show_alert=True)
        return
    await ThoughtRepository.set_project_goal(session, thought, project_goal=goal)
    await callback.answer()
    await _propose_steps(
        callback.message,
        session,
        thought,
        state,
        intro="Отлично. Результат зафиксирован.",
    )


@router.callback_query(F.data == "goal:regen")
async def goal_regen(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """«Сформулировать иначе»: только перегенерируем результат для той же
    мысли — без повторного анализа, смены маршрута и создания дублей."""
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    await _propose_goal(callback.message, session, thought, state, regenerated=True)


@router.message(ThoughtStates.waiting_for_project_outcome, F.text)
async def on_project_outcome(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Совместимость: ручной ввод результата в MVP UI не вызывается, но если
    состояние всё же активно — сохраняем результат и сразу раскладываем шаги."""
    thought = await _get_thought(session, state)
    if not thought:
        await message.answer(NOT_FOUND, reply_markup=after_kb())
        await state.set_state(None)
        return
    await ThoughtRepository.set_project_goal(
        session, thought, project_goal=message.text.strip()
    )
    await state.set_state(None)
    await _propose_steps(
        message, session, thought, state, intro="Отлично. Результат зафиксирован."
    )


@router.callback_query(F.data == "proj:steps")
async def proj_steps(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    await _propose_steps(callback.message, session, thought, state)


@router.callback_query(F.data == "steps:save")
async def steps_save(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    # Гарантируем заголовок для календаря (название первого шага).
    if not thought.suggested_calendar_title:
        steps = list(thought.project_steps or [])
        title = (
            thought.suggested_first_step
            or (steps[0] if steps else None)
            or thought.project_title
            or thought.summary
        )
        if title:
            thought.suggested_calendar_title = title
    await ThoughtRepository.set_category_status(
        session, thought, category="project", status="project_saved"
    )
    await callback.message.answer(
        "✅ Мини-проект сохранён.\n\n"
        "Теперь он доступен в разделе «Мини-проекты» и в журнале мыслей.",
        reply_markup=project_saved_kb(thought.id),
    )
    await state.set_state(None)
    await callback.answer()


@router.callback_query(F.data == "steps:edit")
async def steps_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ThoughtStates.waiting_for_project_steps)
    await callback.message.answer(
        "Напиши шаги одним сообщением. Каждый шаг можно писать с новой строки."
    )
    await callback.answer()


@router.message(ThoughtStates.waiting_for_project_steps, F.text)
async def on_project_steps(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await message.answer(NOT_FOUND, reply_markup=after_kb())
        await state.set_state(None)
        return
    steps = _parse_steps(message.text)
    first_step = steps[0]
    await ThoughtRepository.set_project_steps(
        session, thought, steps=steps, first_step=first_step
    )
    await ThoughtRepository.set_category_status(
        session, thought, category="project", status="steps_generated"
    )
    await state.set_state(None)
    await message.answer(
        thought_processor.format_project_steps(steps, thought.project_goal),
        reply_markup=project_steps_kb(),
    )


@router.callback_query(F.data == "proj:calendar")
async def proj_calendar(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _ask_calendar_datetime(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "proj:later")
async def proj_later(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _save_think_later(callback.message, session, thought, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Классическая цепочка (deep-dive): Вопрос 1 — можно ли повлиять
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "q1:no")
async def q1_no(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if thought:
        await ThoughtRepository.set_category_status(
            session, thought, category="journal", status="empty_closed"
        )
    await callback.message.answer(
        "Окей. Мысль сохранена в журнале как та, на которую сейчас не нужно "
        "тратить энергию.",
        reply_markup=after_kb(),
    )
    await state.set_state(None)
    await callback.answer()


@router.callback_query(F.data == "q1:yes")
async def q1_yes(callback: CallbackQuery) -> None:
    await callback.message.answer(Q2, reply_markup=yes_no_kb("q2", "Да, делегировать", "Нет"))
    await callback.answer()


# Вопрос 2 — делегирование
@router.callback_query(F.data == "q2:yes")
async def q2_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _do_delegation(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "q2:no")
async def q2_no(callback: CallbackQuery) -> None:
    await callback.message.answer(
        Q3, reply_markup=yes_no_kb("q3", "Да, добавить в календарь", "Нет")
    )
    await callback.answer()


@router.callback_query(F.data == "delegate:copy")
async def delegate_copy(callback: CallbackQuery) -> None:
    await callback.answer("Скопируй текст из сообщения выше вручную.", show_alert=True)


# Вопрос 3 — календарь
@router.callback_query(F.data == "q3:yes")
async def q3_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _ask_calendar_datetime(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "q3:no")
async def q3_no(callback: CallbackQuery) -> None:
    await callback.message.answer(Q4, reply_markup=yes_no_kb("q4"))
    await callback.answer()


@router.callback_query(F.data == "step:calendar")
async def step_calendar(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _ask_calendar_datetime(callback.message, session, thought, state)
    await callback.answer()


@router.message(ThoughtStates.waiting_for_calendar_datetime, F.text)
async def on_calendar_datetime(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    start = calendar_service.parse_datetime(message.text)
    if start is None:
        await message.answer(DATETIME_RETRY)
        return

    thought = await _get_thought(session, state)
    if not thought:
        await message.answer(NOT_FOUND, reply_markup=after_kb())
        await state.set_state(None)
        return

    title = thought_processor.calendar_title_for(thought)
    details = thought_processor.calendar_details_for(thought)
    duration = thought.suggested_duration_minutes or 30
    end = calendar_service.event_end(start, duration)
    gcal_url = calendar_service.build_google_calendar_url(title, details, start, duration)

    await CalendarEventRepository.create(
        session,
        thought_id=thought.id,
        title=title,
        description=details,
        start_datetime=start,
        end_datetime=end,
        google_calendar_url=gcal_url,
    )
    # Обновляем СУЩЕСТВУЮЩУЮ мысль, дубль не создаём. Категорию проекта/
    # исследования/делегирования сохраняем — добавление события не меняет суть.
    await ThoughtRepository.set_category_status(
        session, thought, category=_calendar_category(thought), status="calendar_created"
    )

    await message.answer(
        f"Событие запланировано на {start.strftime('%d.%m.%Y %H:%M')} "
        f"({duration} мин).",
        reply_markup=calendar_result_kb(gcal_url),
    )
    await state.set_state(None)


# Вопрос 4 — первый шаг
@router.callback_query(F.data == "q4:yes")
async def q4_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    if thought.suggested_first_step:
        await callback.message.answer(
            f"Первый шаг:\n<b>{html.escape(thought.suggested_first_step)}</b>",
            reply_markup=first_step_kb(),
        )
    else:
        await state.set_state(ThoughtStates.waiting_for_first_step)
        await callback.message.answer("Напиши, какой первый шаг ты видишь.")
    await callback.answer()


@router.callback_query(F.data == "q4:no")
async def q4_no(callback: CallbackQuery) -> None:
    await callback.message.answer(
        Q5, reply_markup=yes_no_kb("q5", "Да, провести исследование", "Нет, подумать позже")
    )
    await callback.answer()


@router.message(ThoughtStates.waiting_for_first_step, F.text)
async def on_first_step(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await message.answer(NOT_FOUND, reply_markup=after_kb())
        await state.set_state(None)
        return
    await ThoughtRepository.set_first_step(session, thought, message.text)
    await state.set_state(None)
    await message.answer(
        f"Записал первый шаг:\n<b>{html.escape(message.text)}</b>",
        reply_markup=first_step_kb(),
    )


# Вопрос 5 — нужны ли факты
@router.callback_query(F.data == "q5:yes")
async def q5_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    await _propose_research(callback.message, session, thought, state)


@router.callback_query(F.data == "q5:no")
async def q5_no(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if thought:
        await _save_think_later(callback.message, session, thought, state)
    else:
        await state.set_state(None)
    await callback.answer()


# ---------------------------------------------------------------------------
# Варианты исследования (маршрут research)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "research:calendar")
async def research_calendar(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await ThoughtRepository.set_category_status(
        session, thought, category=_calendar_category(thought), status="calendar_pending"
    )
    await state.update_data(thought_id=thought.id)
    await state.set_state(ThoughtStates.waiting_for_calendar_datetime)
    await callback.message.answer("Когда запланировать исследование?\n\n" + DATETIME_HINT)
    await callback.answer()


@router.callback_query(F.data == "research:delegate")
async def research_delegate(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    topic = thought.summary or thought.raw_text
    text = (
        "Привет! Можешь, пожалуйста, помочь собрать факты по вопросу: "
        f"{topic} Если получится — дай знать, пожалуйста."
    )
    await ThoughtRepository.set_delegation(session, thought, text)
    await callback.message.answer(
        "🤝 <b>Делегирование</b>\n\n"
        "Готовое сообщение — можно отправить как есть:\n\n"
        f"<code>{html.escape(text)}</code>",
        reply_markup=delegation_kb(thought_id=thought.id),
    )
    await state.set_state(None)
    await callback.answer()


@router.callback_query(F.data == "research:later")
async def research_later(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _save_think_later(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data.in_({"research:read", "research:call", "research:meeting"}))
async def research_simple(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    labels = {
        "research:read": "Погуглить / почитать",
        "research:call": "Позвонить человеку",
        "research:meeting": "Назначить встречу",
    }
    label = labels.get(callback.data, "Исследование")
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await ThoughtRepository.set_research(session, thought, label)
    await callback.message.answer(
        f"Зафиксировал первый способ сбора фактов: <b>{html.escape(label)}</b>.\n\n"
        "Мысль обновлена в журнале и помечена как «Исследование · нужны факты».",
        reply_markup=research_saved_kb(thought.id),
    )
    await state.set_state(None)
    await callback.answer()


# ---------------------------------------------------------------------------
# AI-план исследования (research_plan_kb): сохранить / пересобрать / календарь
# ---------------------------------------------------------------------------
async def _persist_research_plan(
    session: AsyncSession, thought: Thought, data: dict
) -> bool:
    """Сохраняет предложенный план из FSM-данных в мысль. False, если плана нет."""
    goal = data.get("proposed_research_goal")
    steps = data.get("proposed_research_steps") or []
    first = data.get("proposed_research_first")
    if not goal:
        return False
    await ThoughtRepository.set_research_plan(
        session, thought, research_goal=goal, steps=steps, first_step=first
    )
    return True


@router.callback_query(F.data == "research_plan:save")
async def research_plan_save(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    data = await state.get_data()
    if not await _persist_research_plan(session, thought, data):
        await callback.answer("План не найден, пересоберём.", show_alert=True)
        await _propose_research(callback.message, session, thought, state)
        return
    await callback.message.answer(
        "✅ Исследование сохранено.\n\n"
        "Теперь оно доступно в разделе «Исследования» и в журнале мыслей.",
        reply_markup=research_saved_kb(thought.id),
    )
    await state.set_state(None)
    await callback.answer()


@router.callback_query(F.data == "research_plan:replan")
async def research_plan_replan(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    await _propose_research(callback.message, session, thought, state)


@router.callback_query(F.data == "research_plan:calendar")
async def research_plan_calendar(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    data = await state.get_data()
    # Сначала фиксируем план (чтобы исследование жило в своём разделе),
    # затем заголовком календаря делаем первый шаг исследования.
    await _persist_research_plan(session, thought, data)
    first = data.get("proposed_research_first") or thought.first_research_step
    if first:
        thought.suggested_calendar_title = first
    await _ask_calendar_datetime(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "research_plan:later")
async def research_plan_later(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _save_think_later(callback.message, session, thought, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Карточка мысли из журнала. Все действия работают с СУЩЕСТВУЮЩЕЙ мыслью
# по thought_id и обновляют её — новые Thought тут не создаются.
# ---------------------------------------------------------------------------
async def _show_card(
    message: Message,
    session: AsyncSession,
    thought: Thought,
    edit: bool = False,
) -> None:
    text = thought_processor.format_thought_card(thought)
    has_calendar = await _has_calendar(session, thought.id)
    kb = thought_card_kb(thought, has_calendar=has_calendar)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("thought_open:"))
async def thought_open(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await state.set_state(None)
    await state.update_data(thought_id=thought.id)
    await _show_card(callback.message, session, thought, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("thought_goal:"))
async def thought_goal(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await callback.answer()
    await _propose_goal(callback.message, session, thought, state)


@router.callback_query(F.data.startswith("thought_steps:"))
async def thought_steps(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await callback.answer()
    await _propose_steps(callback.message, session, thought, state)


# --- Редактирование результата мини-проекта (FSM) ---
@router.callback_query(F.data.startswith("thought_goal_edit:"))
async def thought_goal_edit(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await state.update_data(thought_id=thought.id)
    await state.set_state(ThoughtStates.editing_goal)
    await callback.message.answer("Напиши новый результат одним сообщением.")
    await callback.answer()


@router.message(ThoughtStates.editing_goal, F.text)
async def on_editing_goal(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await message.answer(NOT_FOUND, reply_markup=after_kb())
        await state.set_state(None)
        return
    await ThoughtRepository.set_project_goal(
        session, thought, project_goal=message.text.strip()
    )
    await ThoughtRepository.set_category_status(
        session, thought, category="project", status="project_saved"
    )
    await state.set_state(None)
    await message.answer("✅ Результат обновлён.", reply_markup=goal_edited_kb(thought.id))


# --- Редактирование шагов мини-проекта (FSM) ---
@router.callback_query(F.data.startswith("thought_steps_edit:"))
async def thought_steps_edit(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await state.update_data(thought_id=thought.id)
    await state.set_state(ThoughtStates.editing_steps)
    await callback.message.answer(
        "Напиши шаги одним сообщением.\n"
        "Каждый шаг можно написать с новой строки."
    )
    await callback.answer()


@router.message(ThoughtStates.editing_steps, F.text)
async def on_editing_steps(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await message.answer(NOT_FOUND, reply_markup=after_kb())
        await state.set_state(None)
        return
    steps = _parse_steps(message.text)
    # Первый шаг ставим только если он ещё не задан.
    first_step = steps[0] if not thought.suggested_first_step else None
    await ThoughtRepository.set_project_steps(
        session, thought, steps=steps, first_step=first_step
    )
    await ThoughtRepository.set_category_status(
        session, thought, category="project", status="project_saved"
    )
    await state.set_state(None)
    await message.answer("✅ Шаги обновлены.", reply_markup=steps_edited_kb(thought.id))


# --- Сохранить мысль как мини-проект из карточки ---
@router.callback_query(F.data.startswith("thought_save_project:"))
async def thought_save_project(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await ThoughtRepository.set_category_status(
        session, thought, category="project", status="project_saved"
    )
    await state.update_data(thought_id=thought.id)
    await callback.message.answer(
        "✅ Мини-проект сохранён.\n\n"
        "Теперь он доступен в разделе «Мини-проекты» и в журнале мыслей.",
        reply_markup=project_saved_kb(thought.id),
    )
    await callback.answer()


# --- Открыть уже созданное календарное действие ---
@router.callback_query(F.data.startswith("thought_calendar_open:"))
async def thought_calendar_open(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    event = await CalendarEventRepository.latest_for_thought(session, thought.id)
    if event is None:
        # Календарного события нет — предлагаем создать.
        await state.update_data(thought_id=thought.id)
        await _ask_calendar_datetime(callback.message, session, thought, state)
        await callback.answer()
        return
    await callback.message.answer(
        f"Запланировано на {event.start_datetime.strftime('%d.%m.%Y %H:%M')}:\n"
        f"<b>{html.escape(event.title)}</b>",
        reply_markup=calendar_result_kb(event.google_calendar_url),
    )
    await callback.answer()


# --- Вернуть закрытую мысль в работу ---
@router.callback_query(F.data.startswith("thought_reopen:"))
async def thought_reopen(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await ThoughtRepository.set_category_status(
        session, thought, status="in_progress"
    )
    await state.set_state(None)
    await state.update_data(thought_id=thought.id)
    await _show_card(callback.message, session, thought, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("thought_calendar:"))
async def thought_calendar(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await state.update_data(thought_id=thought.id)
    await _ask_calendar_datetime(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data.startswith("thought_research:"))
async def thought_research(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await callback.answer()
    await _propose_research(callback.message, session, thought, state)


@router.callback_query(F.data.startswith("thought_delegate:"))
async def thought_delegate(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await state.update_data(thought_id=thought.id)
    if thought.delegation_text:
        # Уже подготовлено — просто показываем сохранённое сообщение.
        text = thought.delegation_text
        await callback.message.answer(
            "🤝 <b>Делегирование</b>\n\n"
            "Готовое сообщение — можно отправить как есть:\n\n"
            f"<code>{html.escape(text)}</code>",
            reply_markup=delegation_kb(thought_id=thought.id),
        )
        await callback.answer()
        return
    # Ещё не делегировали — генерируем сообщение через LLM.
    await callback.answer()
    await _do_delegation(callback.message, session, thought, state)


@router.callback_query(F.data.startswith("thought_clarify:"))
async def thought_clarify(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    """«Уточнить мысль»: НЕ повторный анализ того же текста, а наводящие
    вопросы. Ответ дописывается к той же мысли и переанализируется."""
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await callback.answer()
    await _start_clarification(callback.message, session, thought, state)


@router.callback_query(F.data == "clarify:later")
async def clarify_later(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _save_think_later(callback.message, session, thought, state)
    await callback.answer()


@router.message(ThoughtStates.waiting_for_clarification, F.text)
async def on_clarification(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await message.answer(NOT_FOUND, reply_markup=after_kb())
        await state.set_state(None)
        return
    # Дописываем уточнение к той же мысли (без создания новой записи).
    thought = await ThoughtRepository.append_clarification(
        session, thought, message.text
    )
    thinking = await message.answer("Переосмысливаю мысль…")
    analysis = await analyze_thought(thought.raw_text)
    if calendar_service.has_explicit_datetime(thought.raw_text):
        analysis.recommended_route = "calendar"
        analysis.calendar_candidate = True
        analysis.actionable = True
    thought = await ThoughtRepository.apply_analysis(session, thought, analysis)
    try:
        await thinking.delete()
    except Exception:
        pass
    await state.set_state(None)
    # allow_clarify=False — пользователь уже уточнил, не зацикливаемся.
    await _route_thought(message, session, thought, state, allow_clarify=False)


@router.callback_query(F.data.startswith("thought_think_later:"))
async def thought_think_later(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await state.update_data(thought_id=thought.id)
    await _save_think_later(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data.startswith("thought_close:"))
async def thought_close(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await ThoughtRepository.set_category_status(session, thought, status="closed")
    await callback.message.answer("Мысль закрыта.", reply_markup=after_kb())
    await state.set_state(None)
    await callback.answer()


@router.callback_query(F.data.startswith("thought_delete_confirm:"))
async def thought_delete_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await ThoughtRepository.soft_delete(session, thought)
    await state.set_state(None)
    try:
        await callback.message.edit_text("Мысль удалена.", reply_markup=after_kb())
    except Exception:
        await callback.message.answer("Мысль удалена.", reply_markup=after_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("thought_delete_cancel:"))
async def thought_delete_cancel(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await _show_card(callback.message, session, thought, edit=True)
    await callback.answer()


# Важно: общий префикс — этот хендлер регистрируем ПОСЛЕ confirm/cancel,
# чтобы "thought_delete:" не перехватывал "thought_delete_confirm:".
@router.callback_query(F.data.startswith("thought_delete:"))
async def thought_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await callback.message.answer(
        "Удалить эту мысль из журнала?",
        reply_markup=thought_delete_confirm_kb(thought.id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Разобрать мысль снова (из раздела «Мысли додумать»)
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("reanalyze:"))
async def reanalyze(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    # Берём СУЩЕСТВУЮЩУЮ мысль (с проверкой владельца), повторно прогоняем
    # raw_text через LLM, обновляем summary/type/route — дубль не создаём.
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await callback.answer()
    thinking = await callback.message.answer("Думаю над мыслью заново…")
    analysis = await analyze_thought(thought.raw_text)
    if calendar_service.has_explicit_datetime(thought.raw_text):
        analysis.recommended_route = "calendar"
        analysis.calendar_candidate = True
        analysis.actionable = True
    thought = await ThoughtRepository.apply_analysis(session, thought, analysis)
    try:
        await thinking.delete()
    except Exception:
        pass
    await state.clear()
    await _route_thought(callback.message, session, thought, state)


# ---------------------------------------------------------------------------
# Fallback: любой текст без состояния трактуем как новую мысль
# ---------------------------------------------------------------------------
_RESERVED = {
    "📝 Новая мысль",
    "📓 Журнал мыслей",
    "🧩 Мини-проекты",
    "🔎 Исследования",
    "🤝 Делегирование",
    "📅 Календарь / Запланированные",
    "💭 Мысли додумать",
    "ℹ️ Помощь",
}


@router.message(F.text & ~F.text.startswith("/"))
async def fallback_thought(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    if (await state.get_state()) is not None:
        return
    if message.text in _RESERVED:
        return
    await process_new_thought(message, session, state)
