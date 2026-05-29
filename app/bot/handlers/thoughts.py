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

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    after_kb,
    calendar_result_kb,
    delegation_kb,
    first_step_kb,
    project_goal_kb,
    project_goal_saved_kb,
    project_kb,
    project_steps_kb,
    research_kb,
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
    generate_project_goal,
    generate_project_steps,
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
    await ThoughtRepository.set_category_status(
        session, thought, category="delegate", status="delegation_ready"
    )
    text = thought_processor.build_delegation_text(thought)
    share_url = thought_processor.build_telegram_share_url(text)
    await message.answer(
        "Готовый текст для делегирования:\n\n" f"<code>{html.escape(text)}</code>",
        reply_markup=delegation_kb(share_url),
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
        session, thought, category="calendar", status="calendar_pending"
    )
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


async def _start_deep_dive(message: Message, state: FSMContext) -> None:
    """Запускает классическую цепочку вопросов с Вопроса 1."""
    await state.set_state(None)
    await message.answer(Q1, reply_markup=yes_no_kb("q1"))


# ---------------------------------------------------------------------------
# Точка входа: анализ + выбор маршрута
# ---------------------------------------------------------------------------
async def _route_thought(
    message: Message, session: AsyncSession, thought: Thought, state: FSMContext
) -> None:
    """Показывает резюме и направляет в ОДИН контекстный сценарий."""
    await state.set_state(None)
    await state.update_data(thought_id=thought.id)
    await message.answer(thought_processor.analysis_intro(thought))

    route = thought.recommended_route or "ask_actionable"

    if route == "empty_thought":
        await message.answer(Q1, reply_markup=yes_no_kb("q1"))
    elif route == "delegate":
        await message.answer(
            "Похоже, это можно делегировать. Хотите подготовить сообщение исполнителю?",
            reply_markup=yes_no_kb("rt_delegate", "Да, подготовить", "Нет, разобрать дальше"),
        )
    elif route == "calendar":
        await message.answer(
            "Похоже, это можно запланировать. Добавим в календарь?",
            reply_markup=yes_no_kb("rt_calendar", "Да, добавить", "Нет, разобрать дальше"),
        )
    elif route == "project":
        # Помечаем как проект сразу — пользователь уже внутри проектного сценария.
        await ThoughtRepository.set_category_status(
            session, thought, category="project", status="in_progress"
        )
        await message.answer("Это похоже на мини-проект.", reply_markup=project_kb())
    elif route == "research":
        # Фиксируем как исследование до выбора конкретного способа сбора фактов.
        await ThoughtRepository.set_category_status(
            session, thought, category="research", status="research_needed"
        )
        await message.answer(
            "Похоже, для этой мысли нужно собрать больше фактов.",
            reply_markup=research_kb(),
        )
    elif route == "think_later":
        await message.answer(
            "Пока неясно, что с этим делать. Сохранить в «Мысли додумать»?",
            reply_markup=yes_no_kb("rt_later", "Да", "Нет, разобрать подробнее"),
        )
    else:  # ask_actionable — LLM не уверена, спрашиваем сами
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
@router.callback_query(F.data == "rt_delegate:yes")
async def rt_delegate_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _do_delegation(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "rt_delegate:no")
async def rt_delegate_no(callback: CallbackQuery, state: FSMContext) -> None:
    await _start_deep_dive(callback.message, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Маршрут: calendar
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "rt_calendar:yes")
async def rt_calendar_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _ask_calendar_datetime(callback.message, session, thought, state)
    await callback.answer()


@router.callback_query(F.data == "rt_calendar:no")
async def rt_calendar_no(callback: CallbackQuery, state: FSMContext) -> None:
    await _start_deep_dive(callback.message, state)
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
    await _start_deep_dive(callback.message, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Маршрут: project — бот САМ предлагает результат и шаги через LLM.
# Ручной ввод используется только как правка («Изменить»/«Редактировать»)
# или fallback, если LLM недоступна / вернула невалидный JSON.
# ---------------------------------------------------------------------------
async def _propose_goal(
    message: Message, session: AsyncSession, thought: Thought, state: FSMContext
) -> None:
    """LLM предлагает результат для текущей мысли. Обновляет ту же запись."""
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
        # Fallback: просим пользователя сформулировать самому.
        await state.set_state(ThoughtStates.waiting_for_project_outcome)
        await message.answer(
            "Опиши одним сообщением, какой результат ты хочешь получить."
        )
        return

    await state.update_data(
        proposed_goal=result.project_goal,
        proposed_criteria=result.success_criteria,
        proposed_title=result.short_title,
    )
    await message.answer(
        thought_processor.format_project_goal(
            result.project_goal, result.success_criteria, result.short_title
        ),
        reply_markup=project_goal_kb(),
    )


async def _propose_steps(
    message: Message, session: AsyncSession, thought: Thought, state: FSMContext
) -> None:
    """LLM раскладывает текущую мысль на шаги. Обновляет ту же запись."""
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
        await state.set_state(ThoughtStates.waiting_for_project_steps)
        await message.answer(
            "Напиши первый конкретный шаг или несколько шагов одним сообщением."
        )
        return

    # Сразу фиксируем шаги и параметры календаря, чтобы кнопка
    # «Добавить первый шаг в календарь» работала без отдельного сохранения.
    thought.suggested_calendar_title = result.calendar_title
    thought.suggested_duration_minutes = result.duration_minutes
    await ThoughtRepository.set_project_steps(
        session,
        thought,
        steps=result.steps,
        first_step=result.first_step,
        project_goal=result.project_goal,
    )
    await state.update_data(proposed_steps=result.steps)
    await message.answer(
        thought_processor.format_project_steps(result.steps, result.project_goal),
        reply_markup=project_steps_kb(),
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
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    data = await state.get_data()
    goal = data.get("proposed_goal")
    if not goal:
        await callback.answer("Нет предложенного результата.", show_alert=True)
        return
    await ThoughtRepository.set_project_goal(
        session,
        thought,
        project_goal=goal,
        success_criteria=data.get("proposed_criteria"),
        project_title=data.get("proposed_title"),
    )
    await callback.message.answer(
        "Отлично. Результат сохранён.", reply_markup=project_goal_saved_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "goal:edit")
async def goal_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ThoughtStates.waiting_for_project_outcome)
    await callback.message.answer("Напиши результат своими словами одним сообщением.")
    await callback.answer()


@router.message(ThoughtStates.waiting_for_project_outcome, F.text)
async def on_project_outcome(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await message.answer(NOT_FOUND, reply_markup=after_kb())
        await state.set_state(None)
        return
    await ThoughtRepository.set_project_goal(
        session, thought, project_goal=message.text
    )
    await state.set_state(None)
    await message.answer(
        f"Отлично. Результат сохранён:\n<b>{html.escape(message.text)}</b>",
        reply_markup=project_goal_saved_kb(),
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
    await ThoughtRepository.set_category_status(
        session, thought, category="project", status="project_saved"
    )
    await callback.message.answer("Мини-проект сохранён.", reply_markup=after_kb())
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
    steps = [s.strip() for s in message.text.splitlines() if s.strip()]
    if not steps:
        steps = [message.text.strip()]
    first_step = steps[0]
    await ThoughtRepository.set_project_steps(
        session, thought, steps=steps, first_step=first_step
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
    # Обновляем СУЩЕСТВУЮЩУЮ мысль, дубль не создаём.
    await ThoughtRepository.set_category_status(
        session, thought, category="calendar", status="calendar_created"
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
    if thought:
        await ThoughtRepository.set_category_status(
            session, thought, category="research", status="research_needed"
        )
    await callback.message.answer("Как лучше собрать факты?", reply_markup=research_kb())
    await callback.answer()


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
        session, thought, category="calendar", status="calendar_pending"
    )
    await state.set_state(ThoughtStates.waiting_for_calendar_datetime)
    await callback.message.answer("Когда запланировать исследование?\n\n" + DATETIME_HINT)
    await callback.answer()


@router.callback_query(F.data == "research:delegate")
async def research_delegate(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await ThoughtRepository.set_category_status(
        session, thought, category="delegate", status="delegation_ready"
    )
    text = f"Нужно собрать факты по вопросу: {thought.summary or thought.raw_text}"
    share_url = thought_processor.build_telegram_share_url(text)
    await callback.message.answer(
        "Текст для делегирования поиска фактов:\n\n" f"<code>{html.escape(text)}</code>",
        reply_markup=delegation_kb(share_url),
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
    if thought:
        await ThoughtRepository.set_category_status(
            session, thought, category="research", status="research_needed"
        )
    await callback.message.answer(
        f"Зафиксировал первый способ сбора фактов: <b>{label}</b>.\n"
        "Мысль сохранена в раздел «Исследование».",
        reply_markup=after_kb(),
    )
    await state.set_state(None)
    await callback.answer()


# ---------------------------------------------------------------------------
# Карточка мысли из журнала. Все действия работают с СУЩЕСТВУЮЩЕЙ мыслью
# по thought_id и обновляют её — новые Thought тут не создаются.
# ---------------------------------------------------------------------------
async def _show_card(message: Message, thought: Thought, edit: bool = False) -> None:
    text = thought_processor.format_thought_card(thought)
    kb = thought_card_kb(thought.id)
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
    await _show_card(callback.message, thought, edit=True)
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
    await state.update_data(thought_id=thought.id)
    await ThoughtRepository.set_category_status(
        session, thought, category="research", status="research_needed"
    )
    await callback.message.answer(
        "Как лучше собрать факты?", reply_markup=research_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("thought_delegate:"))
async def thought_delegate(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _owned_from_cb(callback, session)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await state.update_data(thought_id=thought.id)
    await ThoughtRepository.set_category_status(
        session, thought, category="delegate", status="delegation_ready"
    )
    text = thought_processor.build_delegation_text(thought)
    share_url = thought_processor.build_telegram_share_url(text)
    await callback.message.answer(
        "Готовый текст для делегирования:\n\n" f"<code>{html.escape(text)}</code>",
        reply_markup=delegation_kb(share_url, thought_id=thought.id),
    )
    await callback.answer()


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
    await _show_card(callback.message, thought, edit=True)
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
    try:
        thought_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный идентификатор.", show_alert=True)
        return
    thought = await ThoughtRepository.get(session, thought_id)
    if not thought:
        await callback.answer("Мысль не найдена.", show_alert=True)
        return
    await state.clear()
    await _route_thought(callback.message, session, thought, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Fallback: любой текст без состояния трактуем как новую мысль
# ---------------------------------------------------------------------------
_RESERVED = {
    "📝 Новая мысль",
    "📓 Журнал мыслей",
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
