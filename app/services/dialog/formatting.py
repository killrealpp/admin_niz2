from __future__ import annotations

import re
from datetime import datetime
from typing import Any


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
