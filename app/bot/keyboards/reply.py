"""Reply-клавиатура с постоянным быстрым доступом к разделам.

В MVP основная навигация — inline, но reply-меню удобно держать под рукой.
"""
from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def main_reply_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="📝 Новая мысль")
    kb.button(text="📓 Журнал мыслей")
    kb.button(text="🧩 Мини-проекты")
    kb.button(text="🔎 Исследования")
    kb.button(text="🤝 Делегирование")
    kb.button(text="📅 Календарь / Запланированные")
    kb.button(text="💭 Мысли додумать")
    kb.button(text="ℹ️ Помощь")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True, input_field_placeholder="Напиши мысль…")
