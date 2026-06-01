from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import lru_cache
import re
import time as time_module
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from psycopg2.extensions import connection as PgConnection

from app.core.config import get_settings
from app.core.config import PROJECT_ROOT
from app.db.repositories import slot_holds_repo, yclients_records_repo
from app.integrations.yclients_client import YClientsClient, YClientsError

SERVICES_MAP_PATH = PROJECT_ROOT / "config" / "services_map.yaml"
AVAILABILITY_CACHE_TTL_SECONDS = 15
DEFAULT_DAY_START = time(9, 0)
DEFAULT_DAY_END = time(5, 0)
DEFAULT_SLOT_STEP_MINUTES = 30
BATHHOUSE_MAX_GUESTS = 15


@dataclass
class AvailabilityResult:
    ok: bool
    message: str
    slots: list[str]


_availability_cache: dict[tuple[Any, ...], tuple[float, AvailabilityResult]] = {}


def clear_availability_cache() -> None:
    _availability_cache.clear()


@lru_cache
def load_services_map() -> dict[str, dict[str, Any]]:
    if not SERVICES_MAP_PATH.exists():
        return {}
    return yaml.safe_load(SERVICES_MAP_PATH.read_text(encoding="utf-8")) or {}


def check_availability(
    conn: PgConnection,
    *,
    form_data: dict[str, Any],
    now: datetime,
) -> AvailabilityResult:
    service_type = form_data.get("service_type")
    date_value = form_data.get("date")
    if not service_type or not date_value:
        return AvailabilityResult(False, "Не хватает объекта или даты для проверки.", [])

    cache_key = (
        service_type,
        date_value,
        form_data.get("service_variant"),
        form_data.get("guests_count"),
        form_data.get("time"),
        form_data.get("duration"),
        tuple(sorted(str(item) for item in (form_data.get("ignore_source_record_ids") or []) if item)),
    )
    cached = _availability_cache.get(cache_key)
    if cached and time_module.monotonic() - cached[0] < AVAILABILITY_CACHE_TTL_SECONDS:
        return cached[1]

    service_config = load_services_map().get(service_type) or {}
    title = service_config.get("title") or service_type
    capacity_issue = _service_capacity_issue(service_type, form_data, title)
    if capacity_issue:
        result = AvailabilityResult(True, capacity_issue, [])
        _availability_cache[cache_key] = (time_module.monotonic(), result)
        return result
    duration_issue = _fixed_duration_issue(service_config, form_data, date_value, title)
    if duration_issue:
        result = AvailabilityResult(True, duration_issue, [])
        _availability_cache[cache_key] = (time_module.monotonic(), result)
        return result
    variants = _select_variants(service_config, form_data, date_value)

    if not variants or not any(str(variant.get("yclients_service_id") or "").strip() for variant in variants):
        return AvailabilityResult(
            False,
            f"Автоматическая проверка расписания для «{title}» пока не подключена.",
            [],
        )

    online_result = _fixed_service_online_time_result(service_type, title, variants, form_data, date_value)
    if online_result is not None:
        _availability_cache[cache_key] = (time_module.monotonic(), online_result)
        return online_result

    local_result = _check_local_availability(conn, service_type, title, variants, form_data, now)
    if local_result is not None:
        _availability_cache[cache_key] = (time_module.monotonic(), local_result)
        return local_result

    result = AvailabilityResult(
        False,
        (
            "Локальная таблица записей ещё не синхронизирована, поэтому сейчас не могу надёжно проверить "
            f"свободность для «{title}». Попробуйте чуть позже."
        ),
        [],
    )
    _availability_cache[cache_key] = (time_module.monotonic(), result)
    return result


def _check_local_availability(
    conn: PgConnection,
    service_type: str,
    title: str,
    variants: list[dict[str, Any]],
    form_data: dict[str, Any],
    now: datetime,
) -> AvailabilityResult | None:
    if not _has_successful_sync(conn):
        return None

    settings = get_settings()
    tz = ZoneInfo(settings.app_timezone)
    slot_date = datetime.fromisoformat(form_data["date"]).date()
    day_start, day_end = _availability_window(slot_date, tz)
    service_config = load_services_map().get(service_type) or {}
    requested_minutes = _duration_minutes(form_data.get("duration"))
    requested_time = _requested_time(form_data.get("time"))
    variant_filter = _variant_filter(form_data)
    ignored_source_record_ids = {
        str(item)
        for item in (form_data.get("ignore_source_record_ids") or [])
        if item
    }
    active_holds = slot_holds_repo.list_active_for_slot(
        conn,
        service_type=service_type,
        slot_date=slot_date,
        now=now,
        yclients_service_id=variant_filter.get("yclients_service_id") if variant_filter else None,
        yclients_staff_id=variant_filter.get("yclients_staff_id") if variant_filter else None,
    )
    if active_holds and not (service_type == "gazebo" and not variant_filter):
        return AvailabilityResult(
            True,
            f"На эту дату для «{title}» уже есть предварительная заявка, поэтому день пока закрыт.",
            [],
        )
    if service_config.get("block_full_day_on_any_booking"):
        overnight_records = _filter_intervals_by_variant(
            _filter_ignored_intervals(
                yclients_records_repo.list_busy_intervals_crossing_service_time(
                    conn,
                    service_type=service_type,
                    moment=day_start,
                ),
                ignored_source_record_ids,
            ),
            variant_filter,
        )
        if overnight_records and not (service_type == "gazebo" and not variant_filter):
            return AvailabilityResult(
                True,
                f"На эту дату для «{title}» уже есть бронь, которая занимает утро, поэтому день закрыт для новых броней.",
                [],
            )
        day_records = _filter_intervals_by_variant(
            _filter_ignored_intervals(
                yclients_records_repo.list_busy_intervals_starting_on_service_date(
                    conn,
                    service_type=service_type,
                    start_at=day_start,
                    end_at=day_end,
                ),
                ignored_source_record_ids,
            ),
            variant_filter,
        )
        if day_records and not (service_type == "gazebo" and not variant_filter):
            return AvailabilityResult(
                True,
                f"На эту дату для «{title}» уже есть бронь, поэтому день закрыт для новых броней.",
                [],
            )
        if service_type == "gazebo" and not variant_filter:
            busy_staff_ids = {
                str(item.get("yclients_staff_id") or "")
                for item in (overnight_records + day_records)
            }
            held_service_ids = {
                str(item.get("yclients_service_id") or "")
                for item in active_holds
            }
            held_staff_ids = {
                str(item.get("yclients_staff_id") or "")
                for item in active_holds
            }
            free_variants = [
                variant for variant in variants
                if str(variant.get("yclients_staff_id") or "") not in busy_staff_ids
                and str(variant.get("yclients_staff_id") or "") not in held_staff_ids
                and str(variant.get("yclients_service_id") or "") not in held_service_ids
            ]
            if free_variants:
                if requested_time and requested_minutes:
                    start_at = datetime.combine(slot_date, requested_time, tzinfo=tz)
                    if start_at < day_start:
                        start_at += timedelta(days=1)
                    end_at = start_at + timedelta(minutes=requested_minutes)
                    slots = [
                        f"{variant.get('title') or title}: {_format_period(start_at, end_at)}"
                        for variant in free_variants[:8]
                    ]
                else:
                    slots = [
                        f"{variant.get('title') or title}: дата свободна"
                        for variant in free_variants[:8]
                    ]
                return AvailabilityResult(
                    True,
                    f"Нашёл свободные варианты для «{title}».",
                    slots,
                )
            return AvailabilityResult(
                True,
                f"Свободных вариантов для «{title}» на эту дату не нашёл.",
                [],
            )
        if requested_time and requested_minutes:
            start_at = datetime.combine(slot_date, requested_time, tzinfo=tz)
            if start_at < day_start:
                start_at += timedelta(days=1)
            end_at = start_at + timedelta(minutes=requested_minutes)
            return AvailabilityResult(
                True,
                f"Дата для «{title}» свободна по локальному календарю.",
                [f"{title}: {_format_period(start_at, end_at)}"],
            )
        return AvailabilityResult(
            True,
            f"Дата для «{title}» свободна по локальному календарю.",
            [f"{title}: дата свободна"],
        )

    slots: list[str] = []
    seen_resources: set[str] = set()
    for variant in variants:
        staff_id = str(variant.get("yclients_staff_id") or "").strip()
        if variant_filter and staff_id != variant_filter.get("yclients_staff_id"):
            continue
        if not staff_id or staff_id in seen_resources:
            continue
        seen_resources.add(staff_id)
        intervals = yclients_records_repo.list_busy_intervals(
            conn,
            service_type=service_type,
            staff_id=staff_id,
            start_at=day_start,
            end_at=day_end,
        )
        intervals = _filter_ignored_intervals(intervals, ignored_source_record_ids)
        busy = [(item["start_at"], item["end_at"]) for item in intervals]
        windows = _free_windows(day_start, day_end, busy)
        if requested_time and requested_minutes:
            start_at = datetime.combine(slot_date, requested_time, tzinfo=tz)
            if start_at < day_start:
                start_at += timedelta(days=1)
            end_at = start_at + timedelta(minutes=requested_minutes)
            if any(start_at >= free_start and end_at <= free_end for free_start, free_end in windows):
                slots.append(f"{variant.get('title') or title}: {_format_period(start_at, end_at)}")
            continue
        if requested_minutes:
            possible = _possible_starts(windows, requested_minutes)
            if possible:
                slots.append(f"{variant.get('title') or title}: {_format_slots(possible)}")
            continue
        shown_windows = [
            _format_period(start, end)
            for start, end in windows
            if (end - start).total_seconds() >= 30 * 60
        ]
        if shown_windows:
            slots.append(f"{title}: {', '.join(shown_windows[:4])}")

    if slots:
        return AvailabilityResult(True, f"Нашёл свободные варианты для «{title}» по локальному календарю.", slots[:8])
    return AvailabilityResult(True, f"Свободных вариантов для «{title}» на эту дату не нашёл по локальному календарю.", [])


def _fixed_service_online_time_result(
    service_type: str,
    title: str,
    variants: list[dict[str, Any]],
    form_data: dict[str, Any],
    date_value: str,
) -> AvailabilityResult | None:
    if service_type not in {"bathhouse", "house"}:
        return None
    requested_time = _requested_time(form_data.get("time"))
    requested_minutes = _duration_minutes(form_data.get("duration"))
    if not requested_time or not requested_minutes:
        return None
    fixed_variants = [variant for variant in variants if variant.get("duration_minutes")]
    if not fixed_variants:
        return None
    requested_time_text = requested_time.strftime("%H:%M")
    available_starts: list[str] = []
    checked_any = False
    for variant in fixed_variants:
        service_id = str(variant.get("yclients_service_id") or "").strip()
        staff_id = str(variant.get("yclients_staff_id") or "").strip()
        if not service_id or not staff_id:
            continue
        checked_any = True
        starts = _load_yclients_book_times(
            staff_id=staff_id,
            service_id=service_id,
            date_value=date_value,
        )
        if starts is None:
            return AvailabilityResult(
                False,
                (
                    f"Сейчас не могу надёжно проверить точное время для «{title}» в YCLIENTS. "
                    "Лучше попробовать чуть позже или передать заявку администратору."
                ),
                [],
            )
        available_starts.extend(starts)
    if not checked_any:
        return None
    available_starts = sorted(set(available_starts))
    if requested_time_text in available_starts:
        return None
    if available_starts:
        shown = _format_slots(available_starts[:12])
        return AvailabilityResult(
            True,
            (
                f"Для «{title}» выбранный старт {requested_time_text} сейчас недоступен в YCLIENTS. "
                f"На эту дату доступны старты: {shown}. Напишите удобное время из списка."
            ),
            [],
        )
    return AvailabilityResult(
        True,
        f"Для «{title}» на выбранную дату свободных стартов в YCLIENTS не нашла.",
        [],
    )


def _load_yclients_book_times(*, staff_id: str, service_id: str, date_value: str) -> list[str] | None:
    try:
        raw_times = YClientsClient().get_book_times(
            staff_id=staff_id,
            service_id=service_id,
            date=date_value,
        )
    except (YClientsError, Exception):
        return None
    starts: list[str] = []
    for item in raw_times:
        time_text = _book_time_to_hhmm(item)
        if time_text:
            starts.append(time_text)
    return sorted(set(starts))


def _book_time_to_hhmm(item: Any) -> str | None:
    if isinstance(item, str):
        text = item
    elif isinstance(item, dict):
        text = str(
            item.get("time")
            or item.get("datetime")
            or item.get("start")
            or item.get("start_time")
            or item.get("seance_time")
            or ""
        )
    else:
        return None
    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _has_successful_sync(conn: PgConnection) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT last_started_at, last_success_at, last_error, updated_at
            FROM yclients_sync_state
            WHERE sync_name = 'yclients_records'
            """
        )
        row = cur.fetchone()
    if not row or not row.get("last_success_at"):
        return False
    settings = get_settings()
    tz = ZoneInfo(settings.app_timezone)
    last_success = row["last_success_at"]
    updated_at = row.get("updated_at")
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=tz)
    if updated_at and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=tz)
    if row.get("last_error") and updated_at and updated_at > last_success:
        return False
    max_age = max(settings.yclients_sync_interval_seconds * 12, 600)
    if datetime.now(tz) - last_success > timedelta(seconds=max_age):
        return False
    return True


def _variant_filter(form_data: dict[str, Any]) -> dict[str, str] | None:
    service_type = form_data.get("service_type")
    variant_name = str(form_data.get("service_variant") or "").lower().replace("ё", "е")
    if service_type != "gazebo" or not variant_name:
        return None
    config = load_services_map().get(service_type) or {}
    variants = list(config.get("variants") or [])
    for variant in variants:
        title = str(variant.get("title") or "").lower().replace("ё", "е")
        if title and title in variant_name:
            return {
                "yclients_staff_id": str(variant.get("yclients_staff_id") or ""),
                "yclients_service_id": str(variant.get("yclients_service_id") or ""),
            }
    if "крыт" in variant_name:
        for variant in variants:
            if "крыт" in str(variant.get("title") or "").lower().replace("ё", "е"):
                return {
                    "yclients_staff_id": str(variant.get("yclients_staff_id") or ""),
                    "yclients_service_id": str(variant.get("yclients_service_id") or ""),
                }
    return None


def _filter_ignored_intervals(intervals: list[dict[str, Any]], ignored_source_record_ids: set[str]) -> list[dict[str, Any]]:
    if not ignored_source_record_ids:
        return intervals
    return [
        item
        for item in intervals
        if str(item.get("source_record_id") or "") not in ignored_source_record_ids
    ]


def _filter_intervals_by_variant(
    intervals: list[dict[str, Any]],
    variant_filter: dict[str, str] | None,
) -> list[dict[str, Any]]:
    if not variant_filter:
        return intervals
    staff_id = variant_filter.get("yclients_staff_id")
    return [item for item in intervals if str(item.get("yclients_staff_id") or "") == staff_id]


def _availability_window(slot_date: Any, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start_at = datetime.combine(slot_date, DEFAULT_DAY_START, tzinfo=tz)
    end_at = datetime.combine(slot_date, DEFAULT_DAY_END, tzinfo=tz)
    if end_at <= start_at:
        end_at += timedelta(days=1)
    return start_at, end_at


def _requested_time(value: Any) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(str(value)[:5])
    except ValueError:
        return None


def _free_windows(
    day_start: datetime,
    day_end: datetime,
    busy: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    cursor = day_start
    for busy_start, busy_end in sorted(busy):
        busy_start = max(busy_start, day_start)
        busy_end = min(busy_end, day_end)
        if busy_end <= cursor:
            continue
        if busy_start > cursor:
            windows.append((cursor, busy_start))
        cursor = max(cursor, busy_end)
    if cursor < day_end:
        windows.append((cursor, day_end))
    return windows


def _possible_starts(windows: list[tuple[datetime, datetime]], duration_minutes: int) -> list[str]:
    starts: list[str] = []
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=DEFAULT_SLOT_STEP_MINUTES)
    for free_start, free_end in windows:
        current = free_start
        while current + duration <= free_end:
            starts.append(_format_time(current))
            current += step
            if len(starts) >= 12:
                return starts
    return starts


def _format_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def _format_period(start: datetime, end: datetime) -> str:
    suffix = " следующего дня" if end.date() > start.date() else ""
    return f"{_format_time(start)}-{_format_time(end)}{suffix}"


def _format_slots(slots: list[str]) -> str:
    if len(slots) <= 8:
        return ", ".join(slots)
    return ", ".join(slots[:6]) + f" и ещё {len(slots) - 6}"


def _select_variants(
    service_config: dict[str, Any],
    form_data: dict[str, Any],
    date_value: str,
) -> list[dict[str, Any]]:
    variants = list(service_config.get("variants") or [])
    if not variants:
        variants = [service_config]

    slot_date = datetime.fromisoformat(date_value).date()
    weekday = slot_date.weekday()
    guests_count = form_data.get("guests_count")
    duration = _duration_minutes(form_data.get("duration"))

    filtered: list[dict[str, Any]] = []
    for variant in variants:
        weekdays = variant.get("weekdays")
        if weekdays and weekday not in weekdays:
            continue
        capacity_max = variant.get("capacity_max")
        if guests_count and capacity_max and int(guests_count) > int(capacity_max):
            continue
        duration_minutes = variant.get("duration_minutes")
        if duration and duration_minutes and int(duration) != int(duration_minutes):
            continue
        filtered.append(variant)
    candidates = filtered or variants
    if service_config.get("title") == "Беседка" and guests_count and int(guests_count) >= 20:
        candidates.sort(
            key=lambda item: (
                0 if "№1" in str(item.get("title") or "") else 1,
                int(item.get("duration_minutes") or 9999),
                int(item.get("price") or 999999),
                int(item.get("capacity_max") or 9999),
            )
        )
    else:
        candidates.sort(
            key=lambda item: (
                int(item.get("duration_minutes") or 9999),
                int(item.get("capacity_max") or 9999),
                int(item.get("price") or 999999),
            )
        )
    return candidates[:12] if duration is None else candidates[:8]


def _fixed_duration_issue(
    service_config: dict[str, Any],
    form_data: dict[str, Any],
    date_value: str,
    title: str,
) -> str | None:
    variants = [variant for variant in (service_config.get("variants") or []) if variant.get("duration_minutes")]
    if not variants:
        return None
    duration = _duration_minutes(form_data.get("duration"))
    if duration is None:
        return None
    slot_date = datetime.fromisoformat(date_value).date()
    weekday = slot_date.weekday()
    allowed = sorted(
        {
            int(variant["duration_minutes"])
            for variant in variants
            if not variant.get("weekdays") or weekday in variant.get("weekdays")
        }
    )
    if not allowed:
        allowed = sorted({int(variant["duration_minutes"]) for variant in variants})
    if int(duration) in allowed:
        return None
    return (
        f"Для «{title}» нельзя оформить произвольный период на {_format_duration_for_reply(duration)}: "
        f"по базе доступны только фиксированные пакеты {_format_allowed_durations(allowed)}. "
        "Напишите нужный пакет из этих вариантов."
    )


def _service_capacity_issue(service_type: str, form_data: dict[str, Any], title: str) -> str | None:
    guests_count = form_data.get("guests_count")
    if not guests_count:
        return None
    try:
        guests = int(guests_count)
    except (TypeError, ValueError):
        return None
    if service_type == "bathhouse" and guests > BATHHOUSE_MAX_GUESTS:
        return (
            f"Для «{title}» {guests} гостей — слишком большая компания: баню не оформляю больше чем на "
            f"{BATHHOUSE_MAX_GUESTS} человек без ручного уточнения.\n\n"
            "Для такой компании лучше подобрать просторную беседку, например Беседку №1, если она свободна на нужную дату."
        )
    return None


def _format_allowed_durations(minutes_values: list[int]) -> str:
    hours = [minutes // 60 for minutes in minutes_values if minutes % 60 == 0]
    if len(hours) == len(minutes_values) and hours:
        parts = [str(value) for value in hours]
        if len(parts) == 1:
            return f"{parts[0]} часов"
        return f"{', '.join(parts[:-1])} или {parts[-1]} часов"
    return ", ".join(f"{minutes} минут" for minutes in minutes_values)


def _format_duration_for_reply(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        if hours % 10 == 1 and hours % 100 != 11:
            suffix = "час"
        elif hours % 10 in {2, 3, 4} and hours % 100 not in {12, 13, 14}:
            suffix = "часа"
        else:
            suffix = "часов"
        return f"{hours} {suffix}"
    return f"{minutes} минут"


def _duration_minutes(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value * 60 if value <= 24 else value
    text = str(value).lower()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    number = int(digits)
    if "мин" in text:
        return number
    return number * 60
