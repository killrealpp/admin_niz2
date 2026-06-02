from __future__ import annotations

import re
from datetime import time
from typing import Any


def normalize_duration_value(value: Any) -> int | float | None:
    """Normalize duration to hours for form_data and availability checks."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        hours = float(value)
    else:
        text = str(value).lower().replace(",", ".").replace("ё", "е").strip()
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:час|часа|часов|ч\b|минут|мин)?", text)
        if not match:
            return None
        number = float(match.group(1))
        hours = number / 60 if "мин" in text else number
    if hours <= 0 or hours > 24:
        return None
    return int(hours) if hours.is_integer() else hours


def time_period_patch(text: str) -> dict[str, Any]:
    original_text = text.lower().replace("ё", "е").replace(",", ".")
    choice = _time_choice_patch(original_text)
    if choice:
        return choice
    normalized = original_text
    normalized = normalized.replace("утра", "").replace("дня", "").replace("вечера", "").replace("вечер", "")
    normalized = re.sub(r"\s*(?:час(?:а|ов)?|ч|чиса|чисов)\b", "", normalized)
    normalized = re.sub(r"\b(?:полночь|полночи|полноч)\b", "00", normalized)
    match = re.search(
        r"(?:с|к|в)?\s*(\d{1,2})(?:[:.\-]\s*(\d{2}))?\s*(?:и\s*)?(?:до|\-)\s*(\d{1,2})(?:[:.]\s*(\d{2}))?",
        normalized,
    )
    if not match:
        return {}
    if _period_match_is_people_count(original_text, match):
        return {}
    if _period_match_starts_with_duration_answer(original_text, match):
        return {}
    start_hour = int(match.group(1))
    start_minute = int(match.group(2) or 0)
    end_hour = int(match.group(3))
    end_minute = int(match.group(4) or 0)
    original = original_text
    start_context = original[max(0, original.find(match.group(1)) - 3) : original.find(match.group(1)) + 16]
    if start_hour < 12 and any(marker in start_context for marker in ("вечера", "вечер", "дня")):
        start_hour += 12
    end_pos = original.find(match.group(3), original.find(match.group(1)) + len(match.group(1)))
    end_context = original[max(0, end_pos - 3) : end_pos + 18] if end_pos >= 0 else ""
    if end_hour < 12 and any(marker in end_context for marker in ("вечера", "вечер", "дня")):
        end_hour += 12
    elif 8 <= end_hour < 12 and "ночи" in end_context:
        end_hour += 12
    elif end_hour == 12 and "ночи" in end_context:
        end_hour = 0
    if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
        return {}
    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute
    if end_total <= start_total:
        end_total += 24 * 60
    duration_hours = round((end_total - start_total) / 60, 2)
    duration_value: int | float = int(duration_hours) if duration_hours.is_integer() else duration_hours
    return {
        "time": f"{start_hour:02d}:{start_minute:02d}",
        "duration": duration_value,
    }


def _time_choice_patch(normalized: str) -> dict[str, Any]:
    match = re.search(
        r"(?:с|к|в|на)?\s*(\d{1,2})(?:[:.]\s*(\d{2}))?\s*(?:или|-|–)\s*(\d{1,2})(?:[:.]\s*(\d{2}))?\s*(утра|дня|вечера|вечер|ночи)?\b",
        normalized,
    )
    if not match:
        return {}
    if _period_match_is_people_count(normalized, match):
        return {}
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(5) or ""
    if hour > 23 or minute > 59:
        return {}
    if hour < 12 and meridiem in {"вечера", "вечер"}:
        hour += 12
    elif 1 <= hour < 12 and meridiem == "дня":
        hour += 12
    elif hour == 12 and meridiem == "ночи":
        hour = 0
    return {"time": f"{hour:02d}:{minute:02d}"}


def has_explicit_time_period(text: str) -> bool:
    return bool(time_period_patch(text))


def single_time_patch(text: str, expected_key: str | None = None) -> dict[str, Any]:
    normalized = text.lower().replace("ё", "е").replace(",", ".")
    if not (
        expected_key in {"time", "duration"}
        or any(marker in normalized for marker in ("вечера", "вечер", "утра", "дня", "ночи", "примерно", "приед", "заед"))
    ):
        return {}
    if re.search(r"\d{1,2}\s*(?:мая|июня|июля|августа|сентября|октября|ноября|декабря|января|февраля|марта|апреля)", normalized):
        return {}
    choice = _time_choice_patch(normalized)
    if choice:
        return choice
    match = re.search(
        r"(?:примерно\s*)?(?:с|к|в|на|после)?\s*(\d{1,2})(?:[:.]\s*(\d{2}))?"
        r"(?:\s*(?:час(?:а|ов)?|ч|чиса|чисов))?\s*(утра|дня|вечера|вечер|ночи)?\b",
        normalized,
    )
    if not match:
        return {}
    if _single_time_match_is_people_count(normalized, match):
        return {}
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3) or ""
    if hour > 23 or minute > 59:
        return {}
    if hour < 12 and meridiem in {"вечера", "вечер"}:
        hour += 12
    elif 1 <= hour < 12 and meridiem == "дня":
        hour += 12
    elif hour < 12 and meridiem == "ночи" and hour == 12:
        hour = 0
    return {"time": f"{hour:02d}:{minute:02d}"}


def until_time_duration_patch(text: str, start_time: Any) -> dict[str, Any]:
    if not start_time:
        return {}
    normalized = text.lower().replace("ё", "е").replace(",", ".")
    match = re.search(r"\bдо\s*(\d{1,2})(?:[:.]\s*(\d{2}))?\s*(утра|дня|вечера|вечер|ночи)?\b", normalized)
    if not match:
        return {}
    try:
        start = time.fromisoformat(str(start_time)[:5])
    except ValueError:
        return {}
    end_hour = int(match.group(1))
    end_minute = int(match.group(2) or 0)
    meridiem = match.group(3) or ""
    if end_hour > 23 or end_minute > 59:
        return {}
    if end_hour < 12 and meridiem in {"вечера", "вечер"}:
        end_hour += 12
    elif 1 <= end_hour < 12 and meridiem == "дня":
        end_hour += 12
    elif 8 <= end_hour < 12 and meridiem == "ночи":
        end_hour += 12
    elif end_hour == 12 and meridiem == "ночи":
        end_hour = 0
    elif end_hour <= start.hour and not meridiem:
        end_hour += 12
    if end_hour > 23:
        return {}
    start_total = start.hour * 60 + start.minute
    end_total = end_hour * 60 + end_minute
    if end_total <= start_total:
        end_total += 24 * 60
    duration_hours = round((end_total - start_total) / 60, 2)
    duration_value: int | float = int(duration_hours) if duration_hours.is_integer() else duration_hours
    if duration_value <= 0 or duration_value > 24:
        return {}
    return {"duration": duration_value}


def _period_match_starts_with_duration_answer(text: str, match: re.Match[str]) -> bool:
    start_index = match.start(1)
    before = text[max(0, start_index - 8):start_index]
    after = text[start_index:start_index + 14]
    return bool(re.search(r"\bРЅР°\s*$", before) and re.search(r"\d{1,2}\s*(?:С‡Р°СЃ|С‡)\b", after))


def _period_match_is_people_count(text: str, match: re.Match[str]) -> bool:
    start, end = match.span()
    before = text[max(0, start - 12):start]
    after = text[end:end + 24]
    around = f"{before} {match.group(0)} {after}"
    people_markers = ("человек", "челов", "чел", "гостей", "гостя", "гость", "взросл", "дети", "детей", "ребен")
    if not any(marker in around for marker in people_markers):
        return False
    if re.search(r"\b(?:с|от)\s*\d{1,2}\s*(?:до|-)\s*\d{1,2}\s*(?:час|ч|утра|дня|вечера|ночи)\b", around):
        return False
    return True


def _single_time_match_is_people_count(text: str, match: re.Match[str]) -> bool:
    start, end = match.span()
    before = text[max(0, start - 10):start]
    after = text[end:end + 20]
    around = f"{before} {match.group(0)} {after}"
    if not any(marker in around for marker in ("человек", "челов", "чел", "гостей", "гостя", "гость", "взросл", "дети", "детей", "ребен")):
        return False
    if match.group(3) in {"утра", "дня", "вечера", "вечер", "ночи"}:
        return False
    return True


def open_ended_until_morning_requested(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "как пойдет",
            "как пойдёт",
            "как получится",
            "сколько получится",
            "до утра",
            "до 8",
            "до 08",
            "до восьми",
            "до следующего утра",
            "на сутки",
            "сутки",
            "после 23",
            "после 11",
            "после одиннадцати",
        )
    )


def gazebo_open_ended_duration_requested(text: str) -> bool:
    return open_ended_until_morning_requested(text)


def default_duration_until_morning_from_time(value: Any) -> int | float | None:
    if not value:
        return None
    try:
        start = time.fromisoformat(str(value)[:5])
    except ValueError:
        return None
    end_minutes = 8 * 60
    start_minutes = start.hour * 60 + start.minute
    if start_minutes < end_minutes:
        return round((end_minutes - start_minutes) / 60, 2)
    return round(((24 * 60 - start_minutes) + end_minutes) / 60, 2)


def gazebo_default_duration_from_time(value: Any) -> int | float | None:
    return default_duration_until_morning_from_time(value)


def apply_open_ended_default_duration(form_data: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    if form_data.get("service_type") not in {"gazebo", "bathhouse", "house"}:
        return form_data
    if (form_data.get("duration") and not force) or not form_data.get("time"):
        return form_data
    duration = default_duration_until_morning_from_time(form_data.get("time"))
    if not duration:
        return form_data
    normalized_duration: int | float = int(duration) if float(duration).is_integer() else duration
    return {**form_data, "duration": normalized_duration}


def apply_gazebo_default_duration(form_data: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    return apply_open_ended_default_duration(form_data, force=force)


def duration_from_text(text: str) -> int | float | None:
    normalized = text.lower().replace(",", ".")
    match = re.search(r"(?:на\s*)?(\d+(?:\.\d+)?)\s*(?:час|часа|часов|ч\b)", normalized)
    if not match:
        return None
    return normalize_duration_value(match.group(0))


def bare_duration_from_text(text: str) -> int | float | None:
    normalized = text.lower().replace(",", ".").replace("ё", "е").strip()
    match = re.fullmatch(r"(?:на\s*)?(\d{1,2}(?:\.\d+)?)\s*", normalized)
    if not match:
        return None
    value = float(match.group(1))
    if value <= 0 or value > 24:
        return None
    return normalize_duration_value(value)


def period_conflict(text: str, patch: dict[str, Any]) -> bool:
    explicit_duration = duration_from_text(text)
    period_duration = patch.get("duration")
    if explicit_duration is None or period_duration is None:
        return False
    return abs(float(explicit_duration) - float(period_duration)) >= 0.25
