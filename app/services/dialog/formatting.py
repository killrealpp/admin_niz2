from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.dialog.time_parsing import normalize_duration_value


MONTH_NAMES_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def duration_minutes_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(float(value) * 60) if float(value) <= 24 else int(value)
    text = str(value).lower().replace(",", ".")
    normalized_hours = normalize_duration_value(text)
    if normalized_hours is not None:
        return int(float(normalized_hours) * 60)
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    number = float(match.group(1))
    return int(number) if "мин" in text else int(number * 60)


def format_duration(value: Any) -> str:
    minutes = duration_minutes_value(value)
    if minutes is None:
        return str(value or "")
    if minutes % 60 == 0:
        hours = minutes // 60
        if hours % 10 == 1 and hours % 100 != 11:
            suffix = "час"
        elif hours % 10 in (2, 3, 4) and hours % 100 not in (12, 13, 14):
            suffix = "часа"
        else:
            suffix = "часов"
        return f"{hours} {suffix}"
    return f"{minutes} минут"


def format_time_duration_range(start_time: Any, duration: Any) -> str:
    start_text = str(start_time or "").strip()[:5]
    minutes = duration_minutes_value(duration)
    if not start_text or minutes is None:
        duration_text = format_duration(duration) if duration not in (None, "") else ""
        return f"с {start_text} на {duration_text}".strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", start_text)
    if not match:
        return f"с {start_text} на {format_duration(duration)}"
    start_hour = int(match.group(1))
    start_minute = int(match.group(2))
    if start_hour > 23 or start_minute > 59:
        return f"с {start_text} на {format_duration(duration)}"
    start_total = start_hour * 60 + start_minute
    end_total = start_total + minutes
    end_hour = (end_total // 60) % 24
    end_minute = end_total % 60
    next_day = " следующего дня" if end_total >= 24 * 60 else ""
    return (
        f"с {start_hour:02d}:{start_minute:02d} "
        f"до {end_hour:02d}:{end_minute:02d}{next_day} "
        f"({format_duration(duration)})"
    )


def format_date_ru(value: Any) -> str:
    if not value:
        return "выбранную дату"
    try:
        parsed = datetime.fromisoformat(str(value)).date()
    except ValueError:
        return str(value)
    return f"{parsed.day} {MONTH_NAMES_RU[parsed.month]}"


def format_rub(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,}".replace(",", " ")


def hours_from_minutes(minutes: Any) -> int | None:
    if not minutes:
        return None
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return None
    return value // 60 if value % 60 == 0 else value
