from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.data.services import load_services, service_title, service_variants, variant_by_title
from app.dialog.availability_cache import get_cached_times
from app.dialog.state import BookingDraft
from app.storage import sqlite


@dataclass
class Availability:
    ok: bool
    message: str
    variants: list[str]


def suitable_variants(draft: BookingDraft) -> list[dict[str, Any]]:
    variants = service_variants(draft.service_type)
    if not variants:
        config = load_services().get(draft.service_type or "") or {}
        variants = [config] if config else []
    weekday = datetime.fromisoformat(draft.date).date().weekday() if draft.date else None
    result: list[dict[str, Any]] = []
    for variant in variants:
        if variant.get("weekdays") and weekday is not None and weekday not in variant["weekdays"]:
            continue
        if draft.guests_count and variant.get("capacity_max") and draft.guests_count > int(variant["capacity_max"]):
            continue
        if draft.duration and variant.get("duration_minutes"):
            requested_minutes = int(float(draft.duration) * 60)
            # Баня может бронироваться больше 7 часов: для проверки доступности и выбора
            # YClients-услуги используем базовый вариант на 7 часов, а итоговая цена
            # считается отдельно в pricing.py. Сам payload записи не меняем.
            if draft.service_type == "bathhouse" and requested_minutes > 7 * 60:
                requested_minutes = 7 * 60
            if requested_minutes != int(variant["duration_minutes"]):
                continue
        result.append(variant)
    result.sort(key=lambda item: (int(item.get("capacity_max") or 9999), int(item.get("price") or 999999)))
    return result[:10]

def _has_any_booking_for_date(service_type: str, date_str: str, staff_id: str) -> bool:
    from app.integrations.yclients import YClientsClient
    try:
        client = YClientsClient()
        records = client.get_records(start_date=date_str, end_date=date_str, page=1)
        for r in records:
            if str(r.get('staff_id', '')) == staff_id:
                return True
        return False
    except Exception:
        return False

def check_availability(draft: BookingDraft, *, chat_id: str | None = None) -> Availability:
    if not draft.service_type or not draft.date:
        return Availability(False, "", [])
    variants = suitable_variants(draft)
    if draft.service_type == "gazebo" and not draft.service_variant:
        titles: list[str] = []
        for item in variants:
            title = str(item.get("title") or "")
            service_id = str(item.get("yclients_service_id") or "")
            staff_id = str(item.get("yclients_staff_id") or "")
            if not title:
                continue
            if not service_id or not staff_id:
                continue
            known, cached_times = get_cached_times(staff_id=staff_id, service_id=service_id, date=draft.date)
            
            if _has_any_booking_for_date(draft.service_type, draft.date, staff_id):
                continue
            
            if known and cached_times:
                titles.append(title)
        if titles:
            return Availability(True, "", titles)
        return Availability(False, "", [])

    selected = _selected_variant(draft, variants)
    if not selected:
        return Availability(False, "", [])
    service_id = str(selected.get("yclients_service_id") or "")
    staff_id = str(selected.get("yclients_staff_id") or "")
    if not service_id or not staff_id:
        return Availability(False, "", [])
    
    known, cached_times = get_cached_times(staff_id=staff_id, service_id=service_id, date=draft.date)
    if not known:
        return Availability(True, "", [str(selected.get("title") or "")])
    
    if _has_any_booking_for_date(draft.service_type, draft.date, staff_id):
                return Availability(False, "", [])
            
    normalized_times = sorted(set(cached_times))
    if not draft.time:
        return Availability(True, "", [str(selected.get("title") or "")])
    
    if draft.time in normalized_times:
        return Availability(True, "", [str(selected.get("title") or "")])
    
    return Availability(False, "", [])


def list_available_dates(
    draft: BookingDraft,
    *,
    days: int = 14,
    limit: int = 5,
    chat_id: str | None = None,
) -> list[dict[str, Any]]:
    if not draft.service_type:
        return []
    start_date = datetime.fromisoformat(draft.date).date() if draft.date else datetime.now().date()
    variants = suitable_variants(draft)
    results: list[dict[str, Any]] = []
    for offset in range(days):
        date = (start_date + timedelta(days=offset)).isoformat()
        for variant in variants:
            probe = BookingDraft.from_dict(draft.to_dict())
            probe.date = date
            probe.service_variant = str(variant.get("title") or probe.service_variant or "")
            service_id = str(variant.get("yclients_service_id") or "")
            staff_id = str(variant.get("yclients_staff_id") or "")
            if not service_id or not staff_id:
                continue
            known, cached_times = get_cached_times(staff_id=staff_id, service_id=service_id, date=date)
            if not known:
                continue
            normalized_times = sorted(cached_times)
            if not normalized_times:
                continue
            if draft.time and draft.time not in normalized_times:
                shown_times = normalized_times[:3]
            else:
                shown_times = [draft.time] if draft.time else normalized_times[:3]
            if _active_hold_exists_safe(probe, chat_id=chat_id):
                continue
            results.append({"date": date, "title": probe.service_variant, "times": shown_times})
            if len(results) >= limit:
                return results
    return results


def build_yclients_payload(draft: BookingDraft) -> dict[str, Any]:
    variants = suitable_variants(draft)
    selected = _selected_variant(draft, variants)
    if not selected:
        raise RuntimeError("Cannot resolve YCLIENTS service/staff ids")
    service_id = str(selected.get("yclients_service_id") or "")
    staff_id = str(selected.get("yclients_staff_id") or "")
    if not service_id or not staff_id:
        raise RuntimeError("YCLIENTS ids are not configured")
    dt = datetime.fromisoformat(f"{draft.date} {draft.time}:00").replace(tzinfo=ZoneInfo(get_settings().app_timezone))
    return {
        "phone": _digits_phone(draft.phone or ""),
        "fullname": draft.client_name or "Клиент",
        "email": "",
        "comment": _comment(draft),
        "notify_by_sms": 0,
        "notify_by_email": 0,
        "appointments": [
            {
                "id": 1,
                "services": [int(service_id)],
                "staff_id": int(staff_id),
                "datetime": dt.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        ],
    }


def booking_period(draft: BookingDraft) -> str:
    if not draft.time or not draft.duration:
        return "время не указано"
    start = datetime.fromisoformat(f"2000-01-01 {draft.time}:00")
    end = start + timedelta(hours=float(draft.duration))
    suffix = " следующего дня" if end.day != start.day else ""
    return f"с {start:%H:%M} до {end:%H:%M}{suffix}"


def _selected_variant(draft: BookingDraft, variants: list[dict[str, Any]]) -> dict[str, Any] | None:
    if draft.service_variant:
        return variant_by_title(draft.service_type, draft.service_variant) or (variants[0] if variants else None)
    return variants[0] if variants else None


def _extract_time(value: Any) -> str | None:
    if isinstance(value, str):
        return _normalize_time(value)
    if isinstance(value, dict):
        if value.get("time"):
            return _normalize_time(str(value["time"]))
        for key in ("datetime", "seance_date"):
            if value.get(key):
                raw = str(value[key])
                if "T" in raw:
                    try:
                        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%H:%M")
                    except ValueError:
                        return _normalize_time(raw[11:16])
                return _normalize_time(raw)
    return None


def _normalize_time(value: str) -> str | None:
    try:
        parts = value.strip()[:5].split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    except Exception:
        return None
    return None


def _active_hold_exists_safe(draft: BookingDraft, *, chat_id: str | None = None) -> bool:
    try:
        return sqlite.active_hold_exists(draft.to_dict(), ignore_chat_id=chat_id)
    except Exception:
        return False


def _digits_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("8") and len(digits) == 11:
        return "7" + digits[1:]
    if digits.startswith("9") and len(digits) == 10:
        return "7" + digits
    return digits


def _comment(draft: BookingDraft) -> str:
    upsells = ", ".join(draft.upsell_items) or "не указаны"
    return (
        f"Заявка из Telegram-бота. Гостей: {draft.guests_count or 'не указано'}. "
        f"Формат: {draft.event_format or 'не указано'}. Допы: {upsells}. "
        f"Длительность: {draft.duration or 'не указана'} ч."
    )