"""Inline-клавиатуры. callback_data сделаны понятными и плоскими."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Новая мысль", callback_data="menu:new")
    kb.button(text="📓 Журнал мыслей", callback_data="menu:journal")
    kb.button(text="💭 Мысли додумать", callback_data="menu:to_finish")
    kb.button(text="📅 Календарь / Запланированные", callback_data="menu:calendar")
    kb.button(text="ℹ️ Помощь", callback_data="menu:help")
    kb.adjust(1)
    return kb.as_markup()


def start_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Новая мысль", callback_data="menu:new")
    kb.button(text="📓 Журнал мыслей", callback_data="menu:journal")
    kb.button(text="💭 Мысли додумать", callback_data="menu:to_finish")
    kb.button(text="ℹ️ Помощь", callback_data="menu:help")
    kb.adjust(1)
    return kb.as_markup()


def after_kb() -> InlineKeyboardMarkup:
    """Кнопки завершения: новая мысль / в меню."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Новая мысль", callback_data="menu:new")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(2)
    return kb.as_markup()


def yes_no_kb(step: str, yes_text: str = "Да", no_text: str = "Нет") -> InlineKeyboardMarkup:
    """Универсальная клавиатура Да/Нет для шага дерева вопросов.

    step — идентификатор вопроса: q1..q5. callback_data вида "q1:yes".
    """
    kb = InlineKeyboardBuilder()
    kb.button(text=yes_text, callback_data=f"{step}:yes")
    kb.button(text=no_text, callback_data=f"{step}:no")
    kb.adjust(2)
    return kb.as_markup()


def delegation_kb(share_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📤 Отправить в Telegram", url=share_url)
    kb.button(text="📋 Скопировать текст вручную", callback_data="delegate:copy")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def calendar_result_kb(gcal_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Открыть Google Calendar", url=gcal_url)
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def first_step_kb() -> InlineKeyboardMarkup:
    """После того как первый шаг определён — предложить календарь."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Добавить в календарь", callback_data="step:calendar")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def research_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Погуглить / почитать", callback_data="research:read")
    kb.button(text="📞 Позвонить человеку", callback_data="research:call")
    kb.button(text="🤝 Назначить встречу", callback_data="research:meeting")
    kb.button(text="👥 Делегировать поиск фактов", callback_data="research:delegate")
    kb.button(text="📅 Добавить исследование в календарь", callback_data="research:calendar")
    kb.button(text="💭 Подумать позже", callback_data="research:later")
    kb.adjust(1)
    return kb.as_markup()


def project_kb() -> InlineKeyboardMarkup:
    """Опции для мысли-проекта."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 Сформулировать результат", callback_data="proj:outcome")
    kb.button(text="🪜 Разбить на шаги", callback_data="proj:steps")
    kb.button(text="📅 Добавить первый шаг в календарь", callback_data="proj:calendar")
    kb.button(text="💭 Подумать позже", callback_data="proj:later")
    kb.adjust(1)
    return kb.as_markup()


def project_goal_kb() -> InlineKeyboardMarkup:
    """После того как LLM предложила формулировку результата."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подходит", callback_data="goal:ok")
    kb.button(text="✏️ Изменить", callback_data="goal:edit")
    kb.button(text="🪜 Разбить на шаги", callback_data="proj:steps")
    kb.button(text="📅 Добавить первый шаг в календарь", callback_data="proj:calendar")
    kb.button(text="💭 Подумать позже", callback_data="proj:later")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(2, 1, 1, 1, 1)
    return kb.as_markup()


def project_goal_saved_kb() -> InlineKeyboardMarkup:
    """После сохранения результата — что делать дальше."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🪜 Разбить на шаги", callback_data="proj:steps")
    kb.button(text="📅 Добавить первый шаг в календарь", callback_data="proj:calendar")
    kb.button(text="💭 Подумать позже", callback_data="proj:later")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def project_steps_kb() -> InlineKeyboardMarkup:
    """После того как LLM предложила шаги проекта."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Добавить первый шаг в календарь", callback_data="proj:calendar")
    kb.button(text="✅ Сохранить как мини-проект", callback_data="steps:save")
    kb.button(text="✏️ Редактировать шаги", callback_data="steps:edit")
    kb.button(text="🎯 Сформулировать результат", callback_data="proj:outcome")
    kb.button(text="💭 Подумать позже", callback_data="proj:later")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def reanalyze_kb(thought_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Разобрать снова", callback_data=f"reanalyze:{thought_id}")
    return kb.as_markup()


def to_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В меню", callback_data="menu:home")
    return kb.as_markup()
