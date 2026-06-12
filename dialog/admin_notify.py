from __future__ import annotations

from app.data.services import service_title
from app.dialog.pricing import calculate_booking_price
from app.dialog.state import BookingDraft
from app.storage import sqlite


def notify_admin_booking_created(
    *,
    chat_id: str,
    booking_id: int,
    draft: BookingDraft,
) -> None:
    sqlite.enqueue_admin_notification(
        _booking_message(
            title="Новая бронь",
            chat_id=chat_id,
            booking_id=booking_id,
            draft=draft,
            payment_status="ожидает оплаты",
        ),
        chat_id=chat_id,
    )


def notify_admin_payment_received(
    *,
    chat_id: str,
    booking_id: int,
    draft: BookingDraft,
) -> None:
    sqlite.enqueue_admin_notification(
        _booking_message(
            title="Оплата получена по брони",
            chat_id=chat_id,
            booking_id=booking_id,
            draft=draft,
            payment_status="оплачено",
        ),
        chat_id=chat_id,
    )


def notify_admin_payment_canceled(
    *,
    chat_id: str,
    booking_id: int,
    draft: BookingDraft,
    status: str,
) -> None:
    sqlite.enqueue_admin_notification(
        _booking_message(
            title="Оплата по брони не прошла / отменена",
            chat_id=chat_id,
            booking_id=booking_id,
            draft=draft,
            payment_status=status or "не оплачено",
        ),
        chat_id=chat_id,
    )


def notify_admin_manual_review(
    *,
    chat_id: str,
    booking_id: int,
    draft: BookingDraft,
    reason: str,
) -> None:
    sqlite.enqueue_admin_notification(
        _booking_message(
            title="Оплаченная заявка требует ручной проверки",
            chat_id=chat_id,
            booking_id=booking_id,
            draft=draft,
            payment_status="оплачено, нужна ручная проверка",
            extra_lines=[f"Причина: {reason}"],
        ),
        chat_id=chat_id,
    )


def notify_admin_yclients_error(
    *,
    chat_id: str,
    booking_id: int,
    draft: BookingDraft,
    error: str | None = None,
) -> None:
    extra_lines = []
    if error:
        extra_lines.append(f"Ошибка: {error}")
    sqlite.enqueue_admin_notification(
        _booking_message(
            title="Оплата прошла, но автоматическая запись в YClients не создалась",
            chat_id=chat_id,
            booking_id=booking_id,
            draft=draft,
            payment_status="оплачено, запись не создана автоматически",
            extra_lines=extra_lines,
        ),
        chat_id=chat_id,
    )


def _booking_message(
    *,
    title: str,
    chat_id: str,
    booking_id: int,
    draft: BookingDraft,
    payment_status: str,
    extra_lines: list[str] | None = None,
) -> str:
    price = calculate_booking_price(draft)

    lines = [
        title,
        "",
        f"Booking ID: {booking_id}",
        f"chat_id: {chat_id}",
        f"Статус оплаты: {payment_status}",
        "",
        f"Объект: {_object_title(draft)}",
        f"Дата: {draft.date or 'не указана'}",
        f"Время: {draft.time or 'не указано'}",
        f"Длительность: {_format_duration(draft.duration)}",
        f"Гостей: {draft.guests_count or 'не указано'}",
        f"Формат: {draft.event_format or 'не указан'}",
        f"Допы: {', '.join(draft.upsell_items) if draft.upsell_items else 'без допов'}",
        f"Имя: {draft.client_name or 'не указано'}",
        f"Телефон: {draft.phone or 'не указан'}",
    ]

    if price:
        lines.append(f"Стоимость: {price:,} ₽".replace(",", " "))
    if draft.payment_id:
        lines.append(f"YooKassa payment_id: {draft.payment_id}")
    if draft.yclients_record_id:
        lines.append(f"YClients record_id: {draft.yclients_record_id}")
    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)

    return "\n".join(lines)


def _object_title(draft: BookingDraft) -> str:
    if draft.service_variant:
        return draft.service_variant
    if draft.service_type == "bathhouse":
        return "Баня с бассейном"
    if draft.service_type == "house":
        return "Гостевой дом"
    return service_title(draft.service_type)


def _format_duration(value: object) -> str:
    if value is None:
        return "не указана"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == 24:
        return "сутки"
    if number.is_integer():
        return f"{int(number)} ч"
    return f"{number:g} ч"
