"""Google Calendar (template link, без OAuth) + простой парсер даты/времени.

Архитектура оставляет место для будущего полноценного Google Calendar API:
сейчас мы лишь генерируем ссылку-шаблон render?action=TEMPLATE.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import quote_plus, urlencode

_GCAL_FMT = "%Y%m%dT%H%M%S"

# Эвристики для детерминированного распознавания «календарной» мысли:
# нужны И время (HH:MM), И дата-подобный маркер (число.месяц.год, относительный
# день или день недели). Это позволяет боту не спрашивать «можно ли повлиять»,
# когда в мысли явно указаны дата и время.
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_DATE_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")
_REL_DAY_RE = re.compile(r"\b(сегодня|завтра|послезавтра)\b")
_WEEKDAY_RE = re.compile(
    r"\b(понедельник|вторник|сред[уае]|четверг|пятниц[уае]|"
    r"суббот[уае]|воскресень[ея])\b"
)


def has_explicit_datetime(text: str) -> bool:
    """True, если в тексте есть И время, И дата/день — явный кандидат в календарь."""
    low = text.lower()
    has_time = bool(_TIME_RE.search(low))
    has_date = bool(
        _DATE_RE.search(low)
        or _REL_DAY_RE.search(low)
        or _WEEKDAY_RE.search(low)
    )
    return has_time and has_date


def parse_datetime(text: str) -> datetime | None:
    """Парсит дату/время из свободной формы.

    Поддерживаются:
      - DD.MM.YYYY HH:MM   (30.05.2026 15:30)
      - "завтра HH:MM"     (завтра 12:00)
      - "сегодня HH:MM"    (сегодня 18:45)
    Возвращает None, если распарсить не удалось.
    """
    raw = text.strip().lower()
    now = datetime.now()

    m = re.match(r"^(завтра|сегодня)\s+(\d{1,2}):(\d{2})$", raw)
    if m:
        word, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        base = now + timedelta(days=1) if word == "завтра" else now
        return base.replace(hour=hh, minute=mm, second=0, microsecond=0)

    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H.%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue

    return None


def build_google_calendar_url(
    title: str,
    details: str,
    start: datetime,
    duration_minutes: int = 30,
) -> str:
    """Формирует ссылку-шаблон Google Calendar."""
    end = start + timedelta(minutes=max(1, duration_minutes))
    dates = f"{start.strftime(_GCAL_FMT)}/{end.strftime(_GCAL_FMT)}"
    params = {
        "action": "TEMPLATE",
        "text": title or "Действие",
        "dates": dates,
        "details": details or "",
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(
        params, quote_via=quote_plus
    )


def event_end(start: datetime, duration_minutes: int = 30) -> datetime:
    return start + timedelta(minutes=max(1, duration_minutes))
