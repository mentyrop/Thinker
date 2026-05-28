"""Меню и разделы: журнал, мысли додумать, календарь, помощь."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.start import HELP_TEXT
from app.bot.keyboards.inline import main_menu_kb, reanalyze_kb, to_menu_kb
from app.database.repositories import (
    CalendarEventRepository,
    ThoughtRepository,
    UserRepository,
)

router = Router(name="menu")

CATEGORY_LABELS = {
    "journal": "журнал",
    "delegate": "делегирование",
    "calendar": "календарь",
    "research": "исследование",
    "thoughts_to_finish": "додумать",
}


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


async def _send_journal(message: Message, session: AsyncSession, tg_user) -> None:
    uid = await _user_id(session, tg_user)
    thoughts = await ThoughtRepository.last_for_user(session, uid, limit=10)
    if not thoughts:
        await message.answer("Журнал пуст. Напиши первую мысль!", reply_markup=to_menu_kb())
        return
    lines = ["<b>📓 Последние мысли:</b>\n"]
    for t in thoughts:
        text = t.summary or t.raw_text
        cat = CATEGORY_LABELS.get(t.category, t.category)
        lines.append(
            f"• {t.created_at.strftime('%d.%m %H:%M')} — "
            f"{html.escape(text[:120])}\n"
            f"  <i>{cat} · {t.status}</i>"
        )
    await message.answer("\n".join(lines), reply_markup=to_menu_kb())


async def _send_to_finish(message: Message, session: AsyncSession, tg_user) -> None:
    uid = await _user_id(session, tg_user)
    thoughts = await ThoughtRepository.last_to_finish(session, uid, limit=10)
    if not thoughts:
        await message.answer(
            "В разделе «Мысли додумать» пока пусто.", reply_markup=to_menu_kb()
        )
        return
    await message.answer("<b>💭 Мысли додумать:</b>")
    for t in thoughts:
        text = t.summary or t.raw_text
        await message.answer(
            f"• {t.created_at.strftime('%d.%m %H:%M')} — {html.escape(text[:200])}",
            reply_markup=reanalyze_kb(t.id),
        )


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
    await _send_journal(callback.message, session, callback.from_user)
    await callback.answer()


@router.callback_query(F.data == "menu:to_finish")
async def cb_to_finish(callback: CallbackQuery, session: AsyncSession) -> None:
    await _send_to_finish(callback.message, session, callback.from_user)
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
