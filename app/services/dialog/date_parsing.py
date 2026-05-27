from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

from app.services.dialog.formatting import format_date_ru


WEEKDAY_ALIASES = {
    "понедельник": 0,
    "понедельника": 0,
    "вторник": 1,
    "вторника": 1,
    "среду": 2,
    "среда": 2,
    "четверг": 3,
    "четверга": 3,
    "пятницу": 4,
    "пятница": 4,
    "субботу": 5,
    "суббота": 5,
    "воскресенье": 6,
    "воскресенья": 6,
}

MONTH_NUMBERS_RU = {
    "января": 1,
    "январь": 1,
    "февраля": 2,
    "февраль": 2,
    "марта": 3,
    "март": 3,
    "апреля": 4,
    "апрель": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июля": 7,
    "июль": 7,
    "августа": 8,
    "август": 8,
    "сентября": 9,
    "сентябрь": 9,
    "октября": 10,
    "октябрь": 10,
    "ноября": 11,
    "ноябрь": 11,
    "декабря": 12,
    "декабрь": 12,
}

MONTH_PATTERN = (
    r"января|январь|февраля|февраль|марта|март|апреля|апрель|мая|май|"
    r"июня|июнь|июля|июль|августа|август|сентября|сентябрь|"
    r"октября|октябрь|ноября|ноябрь|декабря|декабрь"
)


def bare_weekday_candidate(text: str, now: datetime) -> tuple[str, date] | None:
    normalized = text.lower().replace("ё", "е")
    if any(marker in normalized for marker in ("завтра", "послезавтра", "сегодня", "следующ", "ближайш", "эту ", "этот ")):
        return None
    for word, weekday in WEEKDAY_ALIASES.items():
        if re.search(rf"\b{word}\b", normalized):
            delta = (weekday - now.date().weekday()) % 7
            if delta == 0:
                delta = 7
            candidate = now.date() + timedelta(days=delta)
            return word, candidate
    return None


def bare_weekday_confirmation(text: str, now: datetime) -> str | None:
    candidate = bare_weekday_candidate(text, now)
    if not candidate:
        return None
    word, date_value = candidate
    return (
        f"Уточню дату: вы имеете в виду ближайшую {word}, "
        f"{format_date_ru(date_value.isoformat())}, или другую дату?"
    )


def relative_date_patch(text: str, now: datetime) -> dict[str, str]:
    normalized = text.lower()
    today = now.date()

    if re.search(r"\bсегодня\b", normalized):
        return {"date": today.isoformat()}
    if re.search(r"\bзавтра\b", normalized):
        return {"date": (today + timedelta(days=1)).isoformat()}
    if re.search(r"\bпослезавтра\b", normalized):
        return {"date": (today + timedelta(days=2)).isoformat()}

    for word, weekday in WEEKDAY_ALIASES.items():
        if re.search(rf"\b{word}\b", normalized):
            if not any(marker in normalized for marker in ("следующ", "ближайш", "эту ", "этот ")):
                return {}
            delta = (weekday - today.weekday()) % 7
            if "следующ" in normalized and delta == 0:
                delta = 7
            return {"date": (today + timedelta(days=delta)).isoformat()}

    explicit_date = re.search(rf"\b(\d{{1,2}})\s+({MONTH_PATTERN})\b", normalized)
    if explicit_date:
        day = int(explicit_date.group(1))
        month = MONTH_NUMBERS_RU[explicit_date.group(2)]
        year = today.year
        try:
            candidate = today.replace(year=year, month=month, day=day)
        except ValueError:
            return {}
        if candidate < today:
            candidate = candidate.replace(year=year + 1)
        return {"date": candidate.isoformat()}

    day_only = re.search(r"\b(\d{1,2})\s*(?:числа|число)\b", normalized)
    if day_only:
        day = int(day_only.group(1))
        return _next_day_number_patch(day, today)
    return {}


def bare_day_patch(text: str, now: datetime, expected_key: str | None) -> dict[str, str]:
    if expected_key != "date":
        return {}
    normalized = text.lower().strip()
    match = re.fullmatch(r"\d{1,2}", normalized)
    if not match:
        return {}
    day = int(match.group(0))
    if day <= 0:
        return {}
    return _next_day_number_patch(day, now.date())


def date_patch_after_marker(
    text: str,
    now: datetime,
    marker: str,
    *,
    base_date: date | None = None,
) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    index = normalized.find(marker)
    if index < 0:
        return {}
    fragment = normalized[index + len(marker) :]
    patch = relative_date_patch(fragment, now)
    if patch:
        return patch
    bare_day = re.search(r"\b(\d{1,2})\b", fragment)
    if not bare_day:
        return {}
    day = int(bare_day.group(1))
    if base_date:
        try:
            candidate = base_date.replace(day=day)
        except ValueError:
            return {}
        if candidate < now.date():
            candidate = candidate.replace(year=candidate.year + 1)
        return {"date": candidate.isoformat()}
    return _next_day_number_patch(day, now.date())


def has_date_signal(text: str) -> bool:
    normalized = text.lower()
    if any(word in normalized for word in ("сегодня", "завтра", "послезавтра")):
        return True
    if any(re.search(rf"\b{word}\b", normalized) for word in WEEKDAY_ALIASES):
        return True
    return bool(
        re.search(
            r"\b\d{1,2}\s*(мая|июня|июля|августа|сентября|октября|ноября|декабря|января|февраля|марта|апреля)?\b",
            normalized,
        )
    )


def date_patch_in_segment(text: str, now: datetime, *, base_date: date | None = None) -> dict[str, str]:
    if base_date and not contains_month_name(text):
        base_day = day_number_in_text_patch(text, now, base_date=base_date)
        if base_day:
            return base_day
    return (
        relative_date_patch(text, now)
        or last_explicit_date_patch(text, now)
        or day_number_in_text_patch(text, now, base_date=base_date)
        or bare_day_patch(text.strip(), now, "date")
    )


def contains_month_name(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(month in normalized for month in MONTH_NUMBERS_RU)


def day_number_in_text_patch(text: str, now: datetime, *, base_date: date | None = None) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    match = re.search(r"\b(?:на|к|ко)\s+(\d{1,2})(?:\s*(?:числа|число))?\b", normalized)
    if not match:
        match = re.search(r"\b(\d{1,2})\s*(?:числа|число)\b", normalized)
    if not match:
        return {}
    day = int(match.group(1))
    if day <= 0:
        return {}
    today = now.date()
    if base_date:
        try:
            candidate = base_date.replace(day=day)
        except ValueError:
            return {}
        if candidate < today:
            try:
                candidate = candidate.replace(year=candidate.year + 1)
            except ValueError:
                return {}
        return {"date": candidate.isoformat()}
    return _next_day_number_patch(day, today)


def reschedule_source_target_day_patch(text: str, now: datetime, base_date: date | None) -> dict[str, str]:
    if not base_date:
        return {}
    normalized = text.lower().replace("ё", "е")
    patterns = (
        rf"\bс\s+\d{{1,2}}(?:\s+(?:{MONTH_PATTERN}))?\s+на\s+(\d{{1,2}})(?:\s+({MONTH_PATTERN}))?\b",
        rf"\b\d{{1,2}}(?:\s+(?:{MONTH_PATTERN}))?\s+на\s+(\d{{1,2}})(?:\s+({MONTH_PATTERN}))?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        day = int(match.group(1))
        month = MONTH_NUMBERS_RU.get(match.group(2) or "") if match.group(2) else base_date.month
        try:
            candidate = base_date.replace(month=month, day=day)
        except ValueError:
            continue
        if candidate < now.date():
            candidate = candidate.replace(year=candidate.year + 1)
        if candidate != base_date:
            return {"date": candidate.isoformat()}
    return {}


def last_explicit_date_patch(text: str, now: datetime, *, exclude_date: date | None = None) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    matches = list(re.finditer(rf"\b(\d{{1,2}})\s+({MONTH_PATTERN})\b", normalized))
    for match in reversed(matches):
        day = int(match.group(1))
        month = MONTH_NUMBERS_RU[match.group(2)]
        year = now.date().year
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate < now.date():
            candidate = date(year + 1, month, day)
        if exclude_date and candidate == exclude_date:
            continue
        return {"date": candidate.isoformat()}
    return {}


def _next_day_number_patch(day: int, today: date) -> dict[str, str]:
    month = today.month
    year = today.year
    for _ in range(13):
        if day <= calendar.monthrange(year, month)[1]:
            candidate = date(year, month, day)
            if candidate >= today:
                return {"date": candidate.isoformat()}
        month += 1
        if month > 12:
            month = 1
            year += 1
    return {}
