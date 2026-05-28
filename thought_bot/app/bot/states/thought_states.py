"""FSM-состояния диалога обработки мысли."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ThoughtStates(StatesGroup):
    # Ждём текст новой мысли
    waiting_for_thought = State()
    # Ждём дату/время для календаря
    waiting_for_calendar_datetime = State()
    # Ждём, пока пользователь сам напишет первый шаг
    waiting_for_first_step = State()
