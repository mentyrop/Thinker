"""Команды /start и /help."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import help_kb, start_kb
from app.bot.keyboards.reply import main_reply_kb
from app.database.repositories import UserRepository

router = Router(name="start")

START_TEXT = (
    "Привет! Я помогу навести порядок в мыслях. "
    "Напиши любую мысль, задачу, тревогу или идею — "
    "я сохраню её и помогу понять, что с ней делать."
)

HELP_TEXT = (
    "<b>Как работает метод «Мыслитель»</b>\n\n"
    "Сначала мы фиксируем мысль. Потом определяем, можно ли на неё повлиять. "
    "Если нельзя — оставляем в журнале. Если можно — превращаем её в "
    "делегирование, календарное действие, исследование или мысль для "
    "дальнейшей проработки.\n\n"
    "<b>Разделы продукта</b>\n"
    "📓 <b>Журнал мыслей</b> — все сохранённые мысли.\n"
    "🧩 <b>Мини-проекты</b> — мысли с целью и шагами.\n"
    "🔎 <b>Исследования</b> — мысли, где нужно собрать факты; "
    "бот предлагает план исследования.\n"
    "🤝 <b>Делегирование</b> — задачи, для которых готовится сообщение "
    "другому человеку.\n"
    "📅 <b>Календарь / Запланированные</b> — действия с датой и временем.\n"
    "💭 <b>Мысли додумать</b> — то, к чему стоит вернуться позже.\n\n"
    "<b>Дерево вопросов</b>\n"
    "1. Можно ли повлиять на эту мысль?\n"
    "2. Можно ли делегировать задачу?\n"
    "3. Можно ли поставить в календарь?\n"
    "4. Понятен ли первый шаг?\n"
    "5. Нужно ли больше фактов?\n"
    "6. Сохранить в «Мысли додумать»?"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await UserRepository.get_or_create(
        session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await message.answer(START_TEXT, reply_markup=main_reply_kb())
    await message.answer("С чего начнём?", reply_markup=start_kb())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=help_kb())
