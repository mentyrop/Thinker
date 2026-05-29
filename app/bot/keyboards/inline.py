"""Inline-клавиатуры. callback_data сделаны понятными и плоскими."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import CalendarEvent, Thought
from app.services.thought_processor import journal_button_label


def main_menu_kb() -> InlineKeyboardMarkup:
    """Единое главное меню. Используется в /start и во всех «🏠 В меню»."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Новая мысль", callback_data="menu:new")
    kb.button(text="📓 Журнал мыслей", callback_data="menu:journal")
    kb.button(text="🧩 Мини-проекты", callback_data="menu:projects")
    kb.button(text="🔎 Исследования", callback_data="menu:research")
    kb.button(text="🤝 Делегирование", callback_data="menu:delegate")
    kb.button(text="📅 Календарь / Запланированные", callback_data="menu:calendar")
    kb.button(text="💭 Мысли додумать", callback_data="menu:to_finish")
    kb.button(text="ℹ️ Помощь", callback_data="menu:help")
    kb.adjust(1)
    return kb.as_markup()


# Единый публичный псевдоним — используем его как «одну функцию меню».
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return main_menu_kb()


def start_kb() -> InlineKeyboardMarkup:
    """Алиас единого главного меню (для совместимости со /start)."""
    return main_menu_kb()


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


def delegate_confirm_kb() -> InlineKeyboardMarkup:
    """Подтверждение подготовки сообщения для делегирования."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, подготовить", callback_data="delegate:prepare")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def delegation_kb(thought_id: int | None = None) -> InlineKeyboardMarkup:
    """Карточка делегирования. В MVP без «Отправить в Telegram» —
    показываем только готовый текст и кнопку копирования."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Показать текст для копирования", callback_data="delegate:copy")
    if thought_id is not None:
        kb.button(text="✅ Закрыть мысль", callback_data=f"thought_close:{thought_id}")
        kb.button(text="🗑 Удалить", callback_data=f"thought_delete:{thought_id}")
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


def project_goal_kb() -> InlineKeyboardMarkup:
    """Шаг 1 мини-проекта: LLM предложила результат.

    Простой UX: подтвердить, переформулировать (тот же результат заново),
    отложить или в меню. Ручного ввода результата в MVP нет.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подходит", callback_data="goal:ok")
    kb.button(text="🔄 Сформулировать иначе", callback_data="goal:regen")
    kb.button(text="💭 Подумать позже", callback_data="proj:later")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def project_steps_kb() -> InlineKeyboardMarkup:
    """Шаг 2 мини-проекта: шаги сгенерированы автоматически. Сохранить
    или переформулировать результат заново. Без ручного редактирования."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, сохранить мини-проект", callback_data="steps:save")
    kb.button(text="🔄 Сформулировать результат иначе", callback_data="goal:regen")
    kb.button(text="💭 Подумать позже", callback_data="proj:later")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def clarify_kb() -> InlineKeyboardMarkup:
    """Кнопки под просьбой уточнить слишком общую мысль."""
    kb = InlineKeyboardBuilder()
    kb.button(text="💭 Оставить на потом", callback_data="clarify:later")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def calendar_route_kb() -> InlineKeyboardMarkup:
    """Маршрут calendar: явная дата/время в мысли — сразу предлагаем календарь.

    По требованию UX показываем только подтверждение и выход в меню,
    без «разобрать иначе» / «подумать позже».
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, добавить", callback_data="cal_route:yes")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def research_plan_kb() -> InlineKeyboardMarkup:
    """AI-план исследования: подтверждение сохранения / пересборка / календарь."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сохранить исследование", callback_data="research_plan:save")
    kb.button(text="🔄 Пересобрать план", callback_data="research_plan:replan")
    kb.button(
        text="📅 Добавить первый шаг в календарь",
        callback_data="research_plan:calendar",
    )
    kb.button(text="💭 Подумать позже", callback_data="research_plan:later")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def help_kb() -> InlineKeyboardMarkup:
    """Кнопки под разделом «Помощь»."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Новая мысль", callback_data="menu:new")
    kb.button(text="📓 Журнал мыслей", callback_data="menu:journal")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def direction_kb() -> InlineKeyboardMarkup:
    """Меню «разобрать иначе» вместо старой линейной анкеты."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 Сформулировать результат", callback_data="dir:goal")
    kb.button(text="🔎 Исследовать / собрать факты", callback_data="dir:research")
    kb.button(text="📅 Добавить в календарь", callback_data="dir:calendar")
    kb.button(text="🤝 Делегировать", callback_data="dir:delegate")
    kb.button(text="💭 Подумать позже", callback_data="dir:later")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def research_saved_kb(thought_id: int) -> InlineKeyboardMarkup:
    """После выбора способа сбора фактов."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📌 Открыть мысль", callback_data=f"thought_open:{thought_id}")
    kb.button(text="📓 Журнал мыслей", callback_data="menu:journal")
    kb.button(text="📝 Новая мысль", callback_data="menu:new")
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
    """Динамические действия над мыслью — набор зависит от статуса/категории.

    Лишние действия не показываются: например, у незавершённого мини-проекта
    нет кнопки календаря, а у исследования — проектных кнопок. Все callback
    несут thought_id.
    """
    tid = thought.id
    status = thought.status
    category = thought.category
    kb = InlineKeyboardBuilder()

    def cal_button() -> None:
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

    # --- Закрытая мысль ---
    if status == "closed":
        kb.button(text="🔄 Вернуть в работу", callback_data=f"thought_reopen:{tid}")
        kb.button(text="🗑 Удалить", callback_data=f"thought_delete:{tid}")
        kb.button(text="🏠 В меню", callback_data="menu:home")
        kb.adjust(1)
        return kb.as_markup()

    # --- Сохранённый мини-проект (или любой проект с результатом/шагами) ---
    # Никаких «Сформулировать иначе» / «Пересобрать шаги» / «Изменить
    # результат» / «Редактировать шаги» — карточка только показывает проект.
    if category == "project" or status in ("goal_confirmed", "steps_generated"):
        cal_button()
        kb.button(text="✅ Закрыть мысль", callback_data=f"thought_close:{tid}")
        kb.button(text="🗑 Удалить", callback_data=f"thought_delete:{tid}")
        kb.button(text="🏠 В меню", callback_data="menu:home")
        kb.adjust(1)
        return kb.as_markup()

    # --- Исследование ---
    if category == "research":
        kb.button(text="🔄 Пересобрать план", callback_data=f"thought_research:{tid}")
        cal_button()
        kb.button(text="💭 Перенести в «Мысли додумать»", callback_data=f"thought_think_later:{tid}")
        kb.button(text="✅ Закрыть мысль", callback_data=f"thought_close:{tid}")
        kb.button(text="🗑 Удалить", callback_data=f"thought_delete:{tid}")
        kb.button(text="🏠 В меню", callback_data="menu:home")
        kb.adjust(1)
        return kb.as_markup()

    # --- Делегирование ---
    if category == "delegate":
        kb.button(text="📤 Открыть текст для отправки", callback_data=f"thought_delegate:{tid}")
        kb.button(text="✅ Закрыть мысль", callback_data=f"thought_close:{tid}")
        kb.button(text="🗑 Удалить", callback_data=f"thought_delete:{tid}")
        kb.button(text="🏠 В меню", callback_data="menu:home")
        kb.adjust(1)
        return kb.as_markup()

    # --- Мысли додумать (интерактивная карточка) ---
    if category == "thoughts_to_finish" or status in ("think_later", "clarification_needed"):
        kb.button(text="🔄 Уточнить мысль", callback_data=f"thought_clarify:{tid}")
        kb.button(text="🎯 Помочь сформулировать результат", callback_data=f"thought_goal:{tid}")
        kb.button(text="🔎 Найти, каких фактов не хватает", callback_data=f"thought_research:{tid}")
        kb.button(text="📅 Выбрать первый шаг", callback_data=f"thought_calendar:{tid}")
        kb.button(text="✅ Закрыть мысль", callback_data=f"thought_close:{tid}")
        kb.button(text="🗑 Удалить", callback_data=f"thought_delete:{tid}")
        kb.button(text="🏠 В меню", callback_data="menu:home")
        kb.adjust(1)
        return kb.as_markup()

    # --- Обычная мысль (journal / calendar / new): полный набор направлений ---
    kb.button(text="🎯 Сформулировать результат", callback_data=f"thought_goal:{tid}")
    kb.button(text="🔎 Исследовать / собрать факты", callback_data=f"thought_research:{tid}")
    cal_button()
    kb.button(text="🤝 Делегировать", callback_data=f"thought_delegate:{tid}")
    kb.button(text="💭 Перенести в «Мысли додумать»", callback_data=f"thought_think_later:{tid}")
    kb.button(text="✅ Закрыть мысль", callback_data=f"thought_close:{tid}")
    kb.button(text="🗑 Удалить", callback_data=f"thought_delete:{tid}")
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
    kb.button(text="🧩 Все мини-проекты", callback_data="menu:projects")
    kb.button(text="🏠 В меню", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def think_later_list_kb(thoughts: list[Thought]) -> InlineKeyboardMarkup:
    """Интерактивный список «Мысли додумать». callback: thought_open:<id>."""
    return _section_list_kb(thoughts)


def research_list_kb(thoughts: list[Thought]) -> InlineKeyboardMarkup:
    """Интерактивный список «Исследования». callback: thought_open:<id>."""
    return _section_list_kb(thoughts)


def delegate_list_kb(thoughts: list[Thought]) -> InlineKeyboardMarkup:
    """Интерактивный список «Делегирование». callback: thought_open:<id>."""
    return _section_list_kb(thoughts)


def _section_list_kb(thoughts: list[Thought]) -> InlineKeyboardMarkup:
    """Общий построитель списка раздела: мысли кнопками + журнал/меню."""
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


def calendar_list_kb(events: list[CalendarEvent]) -> InlineKeyboardMarkup:
    """Список запланированных действий. Каждая кнопка открывает связанную мысль."""
    kb = InlineKeyboardBuilder()
    for i, e in enumerate(events, start=1):
        when = e.start_datetime.strftime("%d.%m %H:%M")
        title = " ".join((e.title or "Действие").split())
        if len(title) > 40:
            title = title[:39].rstrip() + "…"
        kb.button(
            text=f"{i}. {title} — {when}",
            callback_data=f"thought_open:{e.thought_id}",
        )
    kb.adjust(1)
    tail = InlineKeyboardBuilder()
    tail.button(text="🏠 В меню", callback_data="menu:home")
    tail.adjust(1)
    kb.attach(tail)
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
