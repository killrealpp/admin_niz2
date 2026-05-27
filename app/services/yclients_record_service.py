from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2.extensions import connection as PgConnection

from app.core.config import get_settings
from app.db.repositories import bookings_repo, yclients_records_repo
from app.integrations.yclients_client import YClientsError
from app.integrations.yclients_client import YClientsClient
from app.services.availability_service import clear_availability_cache, load_services_map


def create_yclients_record_for_booking(
    conn: PgConnection,
    *,
    booking: dict[str, Any],
) -> dict[str, Any]:
    payload = build_book_record_payload(booking)
    response = YClientsClient().create_book_record(payload)
    record_id = _extract_record_id(response)
    if not record_id:
        raise RuntimeError(f"YCLIENTS did not return record id: {response}")
    updated_booking = bookings_repo.mark_yclients_created(
        conn,
        booking_id=booking["id"],
        yclients_record_id=record_id,
    )
    local_booking = {**booking, **(updated_booking or {}), "yclients_record_id": record_id}
    upsert_local_yclients_record_for_booking(conn, booking=local_booking)
    upsert_local_busy_interval_for_booking(
        conn,
        booking=local_booking,
        source="bot_booking",
    )
    clear_availability_cache()
    return response


def create_missing_yclients_records(conn: PgConnection, *, limit: int = 20) -> dict[str, int]:
    result = {"checked": 0, "created": 0, "failed": 0}
    for booking in bookings_repo.list_paid_without_yclients_record(conn, limit=limit):
        result["checked"] += 1
        try:
            create_yclients_record_for_booking(conn, booking=booking)
        except Exception as exc:
            result["failed"] += 1
            bookings_repo.mark_yclients_create_error(
                conn,
                booking_id=booking["id"],
                error=str(exc),
            )
        else:
            result["created"] += 1
    return result


def delete_yclients_record_for_booking(
    conn: PgConnection,
    *,
    booking: dict[str, Any],
) -> bool:
    record_id = str(booking.get("yclients_record_id") or "")
    if not record_id:
        yclients_records_repo.delete_busy_interval(
            conn,
            source="bot_booking",
            source_record_id=str(booking.get("id")),
        )
        clear_availability_cache()
        return True
    try:
        YClientsClient().delete_record(record_id)
    except YClientsError as exc:
        error_text = str(exc).lower()
        if "404" not in error_text and "не найден" not in error_text:
            return False
    except Exception:
        return False
    yclients_records_repo.delete_busy_interval(
        conn,
        source="bot_booking",
        source_record_id=str(booking.get("id")),
    )
    yclients_records_repo.delete_busy_interval(
        conn,
        source="yclients",
        source_record_id=record_id,
    )
    yclients_records_repo.delete_record_by_id(conn, record_id=record_id)
    clear_availability_cache()
    return True


def build_book_record_payload(booking: dict[str, Any]) -> dict[str, Any]:
    service_id, staff_id = _resolve_yclients_ids(booking)
    if not service_id or not staff_id:
        raise RuntimeError(
            f"YCLIENTS ids are not configured for booking #{booking.get('id')}"
        )

    dt = _booking_datetime(booking)
    comment = _booking_comment(booking)
    return {
        "phone": _digits_phone(str(booking.get("phone") or "")),
        "fullname": str(booking.get("client_name") or "Клиент"),
        "email": str(booking.get("email") or ""),
        "comment": comment,
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


def upsert_local_busy_interval_for_booking(
    conn: PgConnection,
    *,
    booking: dict[str, Any],
    source: str = "bot_booking",
) -> None:
    service_id, staff_id = _resolve_yclients_ids(booking)
    if not staff_id:
        return
    start_at = _booking_datetime(booking)
    duration = int(booking.get("duration_minutes") or 60)
    end_at = start_at + timedelta(minutes=duration)
    title = (load_services_map().get(booking.get("service_type")) or {}).get("title") or booking.get("service_type")
    yclients_records_repo.upsert_busy_interval(
        conn,
        {
            "source": source,
            "source_record_id": str(booking.get("id") or booking.get("yclients_record_id") or ""),
            "service_type": str(booking.get("service_type") or "unknown"),
            "yclients_service_id": service_id,
            "yclients_staff_id": staff_id,
            "title": title,
            "start_at": start_at,
            "end_at": end_at,
            "status": "active",
            "raw_payload": {
                "booking_id": booking.get("id"),
                "yclients_record_id": booking.get("yclients_record_id"),
                "source": source,
            },
            "updated_at": datetime.now(start_at.tzinfo),
        },
    )
    clear_availability_cache()


def upsert_local_yclients_record_for_booking(
    conn: PgConnection,
    *,
    booking: dict[str, Any],
) -> None:
    record_id = str(booking.get("yclients_record_id") or "").strip()
    if not record_id:
        return
    service_id, staff_id = _resolve_yclients_ids(booking)
    if not service_id or not staff_id:
        return
    start_at = _booking_datetime(booking)
    duration = int(booking.get("duration_minutes") or 60)
    end_at = start_at + timedelta(minutes=duration)
    settings = get_settings()
    service_title = _service_title_for_booking(booking, service_id)
    yclients_records_repo.upsert_record(
        conn,
        {
            "yclients_record_id": record_id,
            "company_id": str(settings.yclients_company_id or ""),
            "service_type": str(booking.get("service_type") or "unknown"),
            "yclients_service_id": service_id,
            "yclients_staff_id": staff_id,
            "service_title": service_title,
            "staff_title": service_title,
            "client_name": str(booking.get("client_name") or ""),
            "client_phone": _digits_phone(str(booking.get("phone") or "")),
            "status": "active",
            "attendance": None,
            "start_at": start_at,
            "end_at": end_at,
            "duration_minutes": duration,
            "raw_payload": {
                "source": "bot_booking",
                "booking_id": booking.get("id"),
                "yclients_record_id": record_id,
            },
            "synced_at": datetime.now(start_at.tzinfo),
            "updated_at": datetime.now(start_at.tzinfo),
        },
    )
    clear_availability_cache()


def _resolve_yclients_ids(booking: dict[str, Any]) -> tuple[str, str]:
    service_type = booking.get("service_type")
    config = load_services_map().get(service_type) or {}
    variants = config.get("variants") or []
    duration = booking.get("duration_minutes")
    booking_date = booking.get("booking_date")
    weekday = booking_date.weekday() if hasattr(booking_date, "weekday") else None

    candidates = []
    hold_service_id = str(booking.get("hold_yclients_service_id") or "")
    for variant in variants:
        if hold_service_id and str(variant.get("yclients_service_id") or "") != hold_service_id:
            continue
        weekdays = variant.get("weekdays")
        if weekdays and weekday is not None and weekday not in weekdays:
            continue
        if duration and variant.get("duration_minutes") and int(variant["duration_minutes"]) != int(duration):
            continue
        candidates.append(variant)
    if not candidates:
        candidates = variants or [config]

    if booking.get("service_type") == "gazebo":
        # A gazebo booking is already tied to a selected variant via availability/hold.
        # Prefer the first matching capacity/title candidate, otherwise the configured default.
        candidates = candidates or variants or [config]

    selected = candidates[0] if candidates else config
    return (
        str(selected.get("yclients_service_id") or config.get("yclients_service_id") or ""),
        str(selected.get("yclients_staff_id") or config.get("yclients_staff_id") or ""),
    )


def _service_title_for_booking(booking: dict[str, Any], service_id: str) -> str:
    service_type = booking.get("service_type")
    config = load_services_map().get(service_type) or {}
    for variant in config.get("variants") or []:
        if str(variant.get("yclients_service_id") or "") == str(service_id):
            return str(variant.get("title") or config.get("title") or service_type or "")
    return str(config.get("title") or service_type or "")


def _booking_datetime(booking: dict[str, Any]) -> datetime:
    settings = get_settings()
    date_value = booking["booking_date"]
    time_value = booking["booking_time"]
    text = f"{date_value.isoformat()} {str(time_value)[:8]}"
    dt = datetime.fromisoformat(text)
    return dt.replace(tzinfo=ZoneInfo(settings.app_timezone))


def _booking_comment(booking: dict[str, Any]) -> str:
    extras = ", ".join(booking.get("upsell_items") or []) or "не указаны"
    duration = booking.get("duration_minutes")
    duration_text = f"{duration} мин" if duration else "не указана"
    return (
        "Заявка из Telegram-бота. "
        f"Гостей: {booking.get('guests_count') or 'не указано'}. "
        f"Формат: {booking.get('event_format') or 'не указано'}. "
        f"Допы: {extras}. "
        f"Длительность: {duration_text}."
    )


def _digits_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("8") and len(digits) == 11:
        return "7" + digits[1:]
    return digits


def _extract_record_id(response: dict[str, Any]) -> str:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        for key in ("record_id", "visit_id", "id"):
            if data.get(key):
                return str(data[key])
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            for key in ("record_id", "visit_id", "id"):
                if first.get(key):
                    return str(first[key])
    if isinstance(response, dict):
        for key in ("record_id", "visit_id", "id"):
            if response.get(key):
                return str(response[key])
    return ""
