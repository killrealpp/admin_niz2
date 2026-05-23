from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    variants = _select_variants(service_config, form_data, date_value)

    if not variants or not any(str(variant.get("yclients_service_id") or "").strip() for variant in variants):
        return AvailabilityResult(
            False,
            f"Автоматическая проверка расписания для «{title}» пока не подключена.",
            [],
        )

    local_result = _check_local_availability(conn, service_type, title, variants, form_data, now)
    if local_result is not None:
        _availability_cache[cache_key] = (time_module.monotonic(), local_result)
        return local_result

    client = YClientsClient()
    slot_holds_repo.expire_old(conn, now)
    slot_date = datetime.fromisoformat(date_value).date()
    slots: list[str] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=min(4, len(variants))) as executor:
        future_map = {
            executor.submit(_fetch_variant_times, client, variant, title, date_value): variant
            for variant in variants
        }
        for future in as_completed(future_map):
            variant_title, raw_times, error = future.result()
            if error:
                errors.append(error)
                continue
            variant_slots: list[str] = []
            for item in raw_times:
                slot = _extract_time(item)
                if not slot:
                    continue
                slot_time = time.fromisoformat(slot)
                if slot_holds_repo.is_slot_held(
                    conn,
                    service_type=service_type,
                    slot_date=slot_date,
                    slot_time=slot_time,
                    now=now,
                    yclients_service_id=str(variant.get("yclients_service_id") or ""),
                ):
                    continue
                variant_slots.append(slot)
            if variant_slots:
                shown = _format_slots(sorted(set(variant_slots)))
                slots.append(f"{variant_title}: {shown}")

    unique_slots = slots[:8]
    if not unique_slots:
        suffix = f" ({'; '.join(errors[:2])})" if errors else ""
        result = AvailabilityResult(True, f"Свободных вариантов для «{title}» на эту дату не нашёл.{suffix}", [])
        _availability_cache[cache_key] = (time_module.monotonic(), result)
        return result
    result = AvailabilityResult(True, f"Нашёл свободные варианты для «{title}».", unique_slots)
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
            free_variants = [
                variant for variant in variants
                if str(variant.get("yclients_staff_id") or "") not in busy_staff_ids
                and str(variant.get("yclients_service_id") or "") not in held_service_ids
            ]
            if free_variants:
                if requested_time and requested_minutes:
                    start_at = datetime.combine(slot_date, requested_time, tzinfo=tz)
                    if start_at < day_start:
                        start_at += timedelta(days=1)
                    end_at = start_at + timedelta(minutes=requested_minutes)
                    slots = [
                        f"{variant.get('title') or title}: {_format_time(start_at)}-{_format_time(end_at)}"
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
                [f"{title}: {_format_time(start_at)}-{_format_time(end_at)}"],
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
                slots.append(f"{variant.get('title') or title}: {_format_time(start_at)}-{_format_time(end_at)}")
            continue
        if requested_minutes:
            possible = _possible_starts(windows, requested_minutes)
            if possible:
                slots.append(f"{variant.get('title') or title}: {_format_slots(possible)}")
            continue
        shown_windows = [
            f"{_format_time(start)}-{_format_time(end)}"
            for start, end in windows
            if (end - start).total_seconds() >= 30 * 60
        ]
        if shown_windows:
            slots.append(f"{title}: {', '.join(shown_windows[:4])}")

    if slots:
        return AvailabilityResult(True, f"Нашёл свободные варианты для «{title}» по локальному календарю.", slots[:8])
    return AvailabilityResult(True, f"Свободных вариантов для «{title}» на эту дату не нашёл по локальному календарю.", [])


def _has_successful_sync(conn: PgConnection) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT last_success_at
            FROM yclients_sync_state
            WHERE sync_name = 'yclients_records'
            """
        )
        row = cur.fetchone()
    return bool(row and row.get("last_success_at"))


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
    candidates.sort(
        key=lambda item: (
            int(item.get("duration_minutes") or 9999),
            int(item.get("capacity_max") or 9999),
            int(item.get("price") or 999999),
        )
    )
    return candidates[:12] if duration is None else candidates[:8]


def _duration_minutes(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value * 60 if value < 24 else value
    text = str(value).lower()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    number = int(digits)
    if "мин" in text:
        return number
    return number * 60


def _first_id(items: list[dict[str, Any]]) -> str:
    for item in items:
        value = item.get("id")
        if value is not None:
            return str(value)
    return ""


def _fetch_variant_times(
    client: YClientsClient,
    variant: dict[str, Any],
    default_title: str,
    date_value: str,
) -> tuple[str, list[Any], str | None]:
    service_id = str(variant.get("yclients_service_id") or "").strip()
    staff_id = str(variant.get("yclients_staff_id") or "").strip()
    variant_title = variant.get("title") or default_title
    if not service_id:
        return variant_title, [], f"{variant_title}: не указан service_id"
    try:
        if not staff_id:
            staff_id = _first_id(client.get_book_staff(service_id))
        if not staff_id:
            return variant_title, [], f"{variant_title}: не найден ресурс"
        raw_times = client.get_book_times(
            staff_id=staff_id,
            date=date_value,
            service_id=service_id,
        )
        return variant_title, raw_times, None
    except YClientsError as exc:
        return variant_title, [], f"{variant_title}: {exc}"


def _extract_time(item: Any) -> str | None:
    if isinstance(item, str):
        return item[:5] if ":" in item else None
    if not isinstance(item, dict):
        return None
    for key in ("time", "datetime", "date", "seance_time"):
        value = item.get(key)
        if not value:
            continue
        text = str(value)
        if "T" in text:
            text = text.split("T", 1)[1]
        if " " in text:
            text = text.rsplit(" ", 1)[-1]
        if ":" in text:
            return text[:5]
    return None
