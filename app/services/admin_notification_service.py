from datetime import date, time
from typing import Any

from psycopg2.extensions import connection as PgConnection

from app.db.repositories import bookings_repo
from app.services.availability_service import load_services_map


def _format_date(value: date | Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _format_time(value: time | Any) -> str:
    return str(value)[:5]


def _format_duration(minutes: int | None) -> str:
    if not minutes:
        return "не указано"
    if minutes % 60 == 0:
        return f"{minutes // 60} ч"
    return f"{minutes} мин"


def _service_title(service_type: str) -> str:
    return (load_services_map().get(service_type) or {}).get("title") or service_type


def format_admin_bookings_message(
    conn: PgConnection,
    *,
    conversation_id: int,
) -> str:
    bookings = bookings_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation_id,
    )
    if not bookings:
        return "Активных заявок для администратора нет."

    first = bookings[0]
    lines = [
        "Новая заявка на бронирование",
        f"Клиент: {first.get('client_name') or 'не указано'}",
        f"Телефон: {first.get('phone') or 'не указан'}",
        f"Гостей: {first.get('guests_count') or 'не указано'}",
        f"Формат: {first.get('event_format') or 'не указано'}",
        "",
        "Позиции:",
    ]

    for index, booking in enumerate(bookings, start=1):
        extras = ", ".join(booking.get("upsell_items") or []) or "не указаны"
        lines.extend(
            [
                (
                    f"{index}. {_service_title(booking['service_type'])}: "
                    f"{_format_date(booking['booking_date'])}, "
                    f"{_format_time(booking['booking_time'])}, "
                    f"длительность {_format_duration(booking.get('duration_minutes'))}"
                ),
                f"   Допы: {extras}",
                f"   Статус: {booking.get('status')}, оплата: {booking.get('payment_status')}",
                f"   YCLIENTS: {booking.get('yclients_record_id') or booking.get('yclients_create_error') or 'ещё не создано'}",
            ]
        )

    lines.append("")
    lines.append("Дальше: связаться с клиентом, подтвердить условия и предоплату.")
    return "\n".join(lines)
