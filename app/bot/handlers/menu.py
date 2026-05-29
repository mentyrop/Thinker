"""Меню и разделы: журнал, мысли додумать, календарь, помощь."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.start import HELP_TEXT
from app.bot.keyboards.inline import (
    journal_list_kb,
    main_menu_kb,
    projects_list_kb,
    think_later_list_kb,
    to_menu_kb,
)
from app.database.repositories import (
    CalendarEventRepository,
    ThoughtRepository,
    UserRepository,
)

router = Router(name="menu")

JOURNAL_PAGE_SIZE = 10
JOURNAL_HEADER = "📓 <b>Журнал мыслей</b>\n\nВыберите мысль, чтобы открыть:"
PROJECTS_HEADER = "🧩 <b>Мини-проекты</b>\n\nВыберите проект, чтобы открыть:"
TO_FINISH_HEADER = "💭 <b>Мысли додумать</b>\n\nВыберите мысль, чтобы открыть:"


async def _user_id(session: AsyncSession, tg_user) -> int:
    user = await UserRepository.get_or_create(
        session,
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )
    return user.id


async def _send_menu(message: Message) -> None:
    await message.answer("Главное меню:", reply_markup=main_menu_kb())


async def _send_journal(
    message: Message,
    session: AsyncSession,
    tg_user,
    page: int = 0,
    edit: bool = False,
) -> None:
    uid = await _user_id(session, tg_user)
    total = await ThoughtRepository.count_for_user(session, uid)
    if total == 0:
        await message.answer("Журнал пуст. Напиши первую мысль!", reply_markup=to_menu_kb())
        return
    # Защита от выхода за границы (например, после удаления последней мысли).
    max_page = max(0, (total - 1) // JOURNAL_PAGE_SIZE)
    page = max(0, min(page, max_page))
    thoughts = await ThoughtRepository.get_user_thoughts(
        session, uid, limit=JOURNAL_PAGE_SIZE, offset=page * JOURNAL_PAGE_SIZE
    )
    kb = journal_list_kb(thoughts, page, total, JOURNAL_PAGE_SIZE)
    if edit:
        try:
            await message.edit_text(JOURNAL_HEADER, reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(JOURNAL_HEADER, reply_markup=kb)


async def _send_to_finish(message: Message, session: AsyncSession, tg_user) -> None:
    uid = await _user_id(session, tg_user)
    thoughts = await ThoughtRepository.last_to_finish(session, uid, limit=10)
    if not thoughts:
        await message.answer(
            "В разделе «Мысли додумать» пока пусто.", reply_markup=to_menu_kb()
        )
        return
    await message.answer(TO_FINISH_HEADER, reply_markup=think_later_list_kb(thoughts))


async def _send_projects(message: Message, session: AsyncSession, tg_user) -> None:
    uid = await _user_id(session, tg_user)
    thoughts = await ThoughtRepository.projects_for_user(session, uid, limit=10)
    if not thoughts:
        await message.answer(
            "Мини-проектов пока нет.\n"
            "Открой мысль в журнале и нажми «Сохранить как мини-проект».",
            reply_markup=to_menu_kb(),
        )
        return
    await message.answer(PROJECTS_HEADER, reply_markup=projects_list_kb(thoughts))


async def _send_calendar(message: Message, session: AsyncSession, tg_user) -> None:
    uid = await _user_id(session, tg_user)
    events = await CalendarEventRepository.upcoming_for_user(session, uid, limit=10)
    if not events:
        await message.answer(
            "Запланированных действий пока нет.", reply_markup=to_menu_kb()
        )
        return
    lines = ["<b>📅 Мои запланированные действия:</b>\n"]
    for e in events:
        lines.append(
            f"• {e.start_datetime.strftime('%d.%m.%Y %H:%M')} — "
            f"{html.escape(e.title[:120])}"
        )
    await message.answer("\n".join(lines), reply_markup=to_menu_kb())


# --- callbacks ---
@router.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _send_menu(callback.message)
    await callback.answer()


@router.callback_query(F.data == "menu:journal")
async def cb_journal(callback: CallbackQuery, session: AsyncSession) -> None:
    await _send_journal(callback.message, session, callback.from_user, page=0)
    await callback.answer()


@router.callback_query(F.data.startswith("journal_page:"))
async def cb_journal_page(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        page = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        page = 0
    await _send_journal(
        callback.message, session, callback.from_user, page=page, edit=True
    )
    await callback.answer()


@router.callback_query(F.data == "menu:to_finish")
async def cb_to_finish(callback: CallbackQuery, session: AsyncSession) -> None:
    await _send_to_finish(callback.message, session, callback.from_user)
    await callback.answer()


@router.callback_query(F.data == "menu:projects")
async def cb_projects(callback: CallbackQuery, session: AsyncSession) -> None:
    await _send_projects(callback.message, session, callback.from_user)
    await callback.answer()


@router.callback_query(F.data == "menu:calendar")
async def cb_calendar(callback: CallbackQuery, session: AsyncSession) -> None:
    await _send_calendar(callback.message, session, callback.from_user)
    await callback.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(callback: CallbackQuery) -> None:
    await callback.message.answer(HELP_TEXT, reply_markup=to_menu_kb())
    await callback.answer()


# --- reply-кнопки ---
@router.message(F.text == "📓 Журнал мыслей")
async def reply_journal(message: Message, session: AsyncSession) -> None:
    await _send_journal(message, session, message.from_user)


@router.message(F.text == "💭 Мысли додумать")
async def reply_to_finish(message: Message, session: AsyncSession) -> None:
    await _send_to_finish(message, session, message.from_user)


@router.message(F.text == "ℹ️ Помощь")
async def reply_help(message: Message) -> None:
    await message.answer(HELP_TEXT)
