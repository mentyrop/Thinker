"""Точка входа: создаёт Bot/Dispatcher, регистрирует middleware и роутеры."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import menu, start, thoughts
from app.bot.middlewares import DbSessionMiddleware
from app.config import settings
from app.database.session import async_session_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # Инжект async-сессии БД в каждый апдейт.
    # Регистрируем на observer `update` корневого роутера: данные, добавленные
    # здесь, корректно прокидываются во вложенные роутеры (sub-routers).
    dp.update.middleware(DbSessionMiddleware(async_session_factory))

    # Порядок важен: start → menu → thoughts (в thoughts последний — fallback)
    dp.include_router(start.router)
    dp.include_router(menu.router)
    dp.include_router(thoughts.router)
    return dp


async def main() -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    logger.info("Бот «Мыслитель» запускается…")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановлено.")
