"""Создание новой мысли и дерево вопросов.

Логика дерева целиком в коде. LLM используется только для классификации,
переформулировки и подсказки первого шага.
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
    research_kb,
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
from app.services.llm_service import analyze_thought

router = Router(name="thoughts")

# Тексты вопросов
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


async def _get_thought(
    session: AsyncSession, state: FSMContext
) -> Thought | None:
    data = await state.get_data()
    thought_id = data.get("thought_id")
    if thought_id is None:
        return None
    return await ThoughtRepository.get(session, thought_id)


async def _present_analysis(message: Message, thought: Thought, state: FSMContext) -> None:
    """Показывает резюме и запускает дерево вопросов с Вопроса 1."""
    await state.set_state(None)
    await state.update_data(thought_id=thought.id)
    await message.answer(thought_processor.analysis_intro(thought))
    await message.answer(Q1, reply_markup=yes_no_kb("q1"))


async def process_new_thought(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """Сохраняет сырую мысль, анализирует через LLM, запускает дерево."""
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

    await _present_analysis(message, thought, state)


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
# Вопрос 1 — можно ли повлиять
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


# ---------------------------------------------------------------------------
# Вопрос 2 — делегирование
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "q2:yes")
async def q2_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer("Мысль не найдена, начни заново.", show_alert=True)
        return
    await ThoughtRepository.set_category_status(
        session, thought, category="delegate", status="delegation_ready"
    )
    text = thought_processor.build_delegation_text(thought)
    share_url = thought_processor.build_telegram_share_url(text)
    await callback.message.answer(
        "Готовый текст для делегирования:\n\n"
        f"<code>{html.escape(text)}</code>",
        reply_markup=delegation_kb(share_url),
    )
    await state.set_state(None)
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


# ---------------------------------------------------------------------------
# Вопрос 3 — календарь
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "q3:yes")
async def q3_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer("Мысль не найдена, начни заново.", show_alert=True)
        return
    await ThoughtRepository.set_category_status(
        session, thought, category="calendar", status="calendar_pending"
    )
    await state.set_state(ThoughtStates.waiting_for_calendar_datetime)
    await callback.message.answer(DATETIME_HINT)
    await callback.answer()


@router.callback_query(F.data == "q3:no")
async def q3_no(callback: CallbackQuery) -> None:
    await callback.message.answer(Q4, reply_markup=yes_no_kb("q4"))
    await callback.answer()


@router.callback_query(F.data == "step:calendar")
async def step_calendar(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer("Мысль не найдена, начни заново.", show_alert=True)
        return
    await ThoughtRepository.set_category_status(
        session, thought, category="calendar", status="calendar_pending"
    )
    await state.set_state(ThoughtStates.waiting_for_calendar_datetime)
    await callback.message.answer(DATETIME_HINT)
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
        await message.answer("Мысль не найдена, начни заново.", reply_markup=after_kb())
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

    await message.answer(
        f"Событие запланировано на {start.strftime('%d.%m.%Y %H:%M')} "
        f"({duration} мин).",
        reply_markup=calendar_result_kb(gcal_url),
    )
    await state.set_state(None)


# ---------------------------------------------------------------------------
# Вопрос 4 — первый шаг
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "q4:yes")
async def q4_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer("Мысль не найдена, начни заново.", show_alert=True)
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
        await message.answer("Мысль не найдена, начни заново.", reply_markup=after_kb())
        await state.set_state(None)
        return
    await ThoughtRepository.set_first_step(session, thought, message.text)
    await state.set_state(None)
    await message.answer(
        f"Записал первый шаг:\n<b>{html.escape(message.text)}</b>",
        reply_markup=first_step_kb(),
    )


# ---------------------------------------------------------------------------
# Вопрос 5 — нужны ли факты
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "q5:yes")
async def q5_yes(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if thought:
        await ThoughtRepository.set_category_status(
            session, thought, category="research", status="research_needed"
        )
    await callback.message.answer(
        "Как лучше собрать факты?", reply_markup=research_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "q5:no")
async def q5_no(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if thought:
        await ThoughtRepository.set_category_status(
            session, thought, category="thoughts_to_finish", status="think_later"
        )
    await callback.message.answer(
        "Сохранил мысль в раздел «Мысли додумать». Вернёмся к ней позже.",
        reply_markup=after_kb(),
    )
    await state.set_state(None)
    await callback.answer()


# ---------------------------------------------------------------------------
# Варианты исследования
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "research:calendar")
async def research_calendar(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer("Мысль не найдена, начни заново.", show_alert=True)
        return
    await state.set_state(ThoughtStates.waiting_for_calendar_datetime)
    await callback.message.answer(
        "Когда запланировать исследование?\n\n" + DATETIME_HINT
    )
    await callback.answer()


@router.callback_query(F.data == "research:delegate")
async def research_delegate(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    thought = await _get_thought(session, state)
    if not thought:
        await callback.answer("Мысль не найдена, начни заново.", show_alert=True)
        return
    text = (
        f"Нужно собрать факты по вопросу: "
        f"{thought.summary or thought.raw_text}"
    )
    share_url = thought_processor.build_telegram_share_url(text)
    await callback.message.answer(
        "Текст для делегирования поиска фактов:\n\n"
        f"<code>{html.escape(text)}</code>",
        reply_markup=delegation_kb(share_url),
    )
    await state.set_state(None)
    await callback.answer()


@router.callback_query(F.data.in_({"research:read", "research:call", "research:meeting"}))
async def research_simple(callback: CallbackQuery, state: FSMContext) -> None:
    labels = {
        "research:read": "Погуглить / почитать",
        "research:call": "Позвонить человеку",
        "research:meeting": "Назначить встречу",
    }
    label = labels.get(callback.data, "Исследование")
    await callback.message.answer(
        f"Отметил план: <b>{label}</b>. Мысль сохранена в раздел «Исследование».",
        reply_markup=after_kb(),
    )
    await state.set_state(None)
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
    await _present_analysis(callback.message, thought, state)
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
