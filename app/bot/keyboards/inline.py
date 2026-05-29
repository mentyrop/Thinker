"""Inline-клавиатуры. callback_data сделаны понятными и плоскими."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import Thought
from app.services.thought_processor import journal_button_label


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Новая мысль", callback_data="menu:new")
    kb.button(text="📓 Журнал мыслей", callback_data="menu:journal")
    kb.button(text="💭 Мысли додумать", callback_data="menu:to_finish")
    kb.button(text="🧩 Мини-проекты", callback_data="menu:projects")
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


def delegation_kb(share_url: str, thought_id: int | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📤 Отправить в Telegram", url=share_url)
    kb.button(text="📋 Скопировать текст вручную", callback_data="delegate:copy")
    if thought_id is not None:
        kb.button(text="⬅️ Назад к мысли", callback_data=f"thought_open:{thought_id}")
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


# --------------------------------------------------------------------------- #
# Интерактивный журнал мыслей                                                 #
# --------------------------------------------------------------------------- #
def journal_list_kb(
    thoughts: list[Thought], page: int, total: int, page_size: int = 10
) -> InlineKeyboardMarkup:
    """Список мыслей кнопками + пагинация.

    page — текущая страница (с 0). callback мыслей: thought_open:<id>,
    страниц: journal_page:<page>.
    """
    kb = InlineKeyboardBuilder()
    for i, t in enumerate(thoughts, start=page * page_size + 1):
        kb.button(
            text=journal_button_label(t, i),
            callback_data=f"thought_open:{t.id}",
        )
    kb.adjust(1)  # каждая мысль — на своей строке

    # Пагинация
    has_prev = page > 0
    has_next = (page + 1) * page_size < total
    nav = InlineKeyboardBuilder()
    if has_prev:
        nav.button(text="◀️ Предыдущие", callback_data=f"journal_page:{page - 1}")
    if has_next:
        nav.button(text="▶️ Следующие", callback_data=f"journal_page:{page + 1}")
    if has_prev or has_next:
        nav.adjust(2)
        kb.attach(nav)

    tail = InlineKeyboardBuilder()
    tail.button(text="🏠 В меню", callback_data="menu:home")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def thought_card_kb(
    thought: Thought, has_calendar: bool = False
) -> InlineKeyboardMarkup:
    """Динамические действия над конкретной мыслью.

    Набор кнопок зависит от текущего состояния мысли: есть ли результат/шаги,
    календарное событие, выбран ли способ исследования или делегирования,
    закрыта ли мысль. Все callback несут thought_id.
    """
    tid = thought.id
    is_project = thought.category == "project"
    kb = InlineKeyboardBuilder()

    # Результат
    if thought.project_goal:
        kb.button(text="✏️ Изменить результат", callback_data=f"thought_goal_edit:{tid}")
    else:
        kb.button(text="🎯 Сформулировать результат", callback_data=f"thought_goal:{tid}")

    # Шаги
    if thought.project_steps:
        kb.button(text="✏️ Редактировать шаги", callback_data=f"thought_steps_edit:{tid}")
    else:
        kb.button(text="🪜 Разбить на шаги", callback_data=f"thought_steps:{tid}")

    # Календарь
    if has_calendar:
        kb.button(
            text="📅 Открыть календарное действие",
            callback_data=f"thought_calendar_open:{tid}",
        )
    else:
        kb.button(
            text="📅 Добавить первый шаг в календарь",
            callback_data=f"thought_calendar:{tid}",
        )

    # Исследование (способ сбора фактов выбран, если категория research)
    if thought.category == "research":
        kb.button(
            text="🔁 Изменить способ сбора фактов",
            callback_data=f"thought_research:{tid}",
        )
    else:
        kb.button(
            text="🔎 Исследовать / собрать факты",
            callback_data=f"thought_research:{tid}",
        )

    # Делегирование (текст готов, если категория delegate)
    if thought.category == "delegate":
        kb.button(
            text="📤 Открыть текст делегирования",
            callback_data=f"thought_delegate:{tid}",
        )
    else:
        kb.button(text="🤝 Делегировать", callback_data=f"thought_delegate:{tid}")

    # Сохранить как мини-проект — только если ещё не проект
    if not is_project:
        kb.button(
            text="✅ Сохранить как мини-проект",
            callback_data=f"thought_save_project:{tid}",
        )

    kb.button(
        text="💭 Перенести в «Мысли додумать»",
        callback_data=f"thought_think_later:{tid}",
    )

    # Закрыть / вернуть в работу
    if thought.status == "closed":
        kb.button(text="🔄 Вернуть в работу", callback_data=f"thought_reopen:{tid}")
    else:
        kb.button(text="✅ Закрыть мысль", callback_data=f"thought_close:{tid}")

    kb.button(text="🗑 Удалить", callback_data=f"thought_delete:{tid}")
    kb.button(text="⬅️ Назад к журналу", callback_data="journal_page:0")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


# --------------------------------------------------------------------------- #
# Мини-проекты                                                                #
# --------------------------------------------------------------------------- #
def projects_list_kb(thoughts: list[Thought]) -> InlineKeyboardMarkup:
    """Список мини-проектов кнопками. callback: thought_open:<id>."""
    kb = InlineKeyboardBuilder()
    for i, t in enumerate(thoughts, start=1):
        kb.button(
            text=journal_button_label(t, i),
            callback_data=f"thought_open:{t.id}",
        )
    kb.adjust(1)
    tail = InlineKeyboardBuilder()
    tail.button(text="📓 Журнал мыслей", callback_data="menu:journal")
    tail.button(text="🏠 В меню", callback_data="menu:home")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def project_saved_kb(thought_id: int) -> InlineKeyboardMarkup:
    """Кнопки после сохранения мысли как мини-проекта."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📌 Открыть мини-проект", callback_data=f"thought_open:{thought_id}")
    kb.button(
        text="📅 Добавить первый шаг в календарь",
        callback_data=f"thought_calendar:{thought_id}",
    )
    kb.button(text="✏️ Редактировать шаги", callback_data=f"thought_steps_edit:{thought_id}")
    kb.button(text="🎯 Изменить результат", callback_data=f"thought_goal_edit:{thought_id}")
    kb.button(text="🧩 Все мини-проекты", callback_data="menu:projects")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def goal_edited_kb(thought_id: int) -> InlineKeyboardMarkup:
    """Кнопки после редактирования результата."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📌 Открыть мысль", callback_data=f"thought_open:{thought_id}")
    kb.button(text="🪜 Разбить на шаги", callback_data=f"thought_steps:{thought_id}")
    kb.button(
        text="📅 Добавить первый шаг в календарь",
        callback_data=f"thought_calendar:{thought_id}",
    )
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def steps_edited_kb(thought_id: int) -> InlineKeyboardMarkup:
    """Кнопки после редактирования шагов."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📌 Открыть мини-проект", callback_data=f"thought_open:{thought_id}")
    kb.button(
        text="📅 Добавить первый шаг в календарь",
        callback_data=f"thought_calendar:{thought_id}",
    )
    kb.button(text="🎯 Изменить результат", callback_data=f"thought_goal_edit:{thought_id}")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def thought_delete_confirm_kb(thought_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить", callback_data=f"thought_delete_confirm:{thought_id}")
    kb.button(text="Отмена", callback_data=f"thought_delete_cancel:{thought_id}")
    kb.adjust(2)
    return kb.as_markup()
