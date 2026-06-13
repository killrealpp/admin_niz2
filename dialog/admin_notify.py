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
        breakdown = _price_breakdown(draft)
        if breakdown:
            lines.append(f"Расчёт стоимости: {breakdown}")
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



def _price_breakdown(draft: BookingDraft) -> str | None:
    if draft.service_type != "bathhouse" or not draft.duration:
        return None
    try:
        duration = int(float(draft.duration))
    except (TypeError, ValueError):
        return None
    if duration <= 7:
        return None
    total = calculate_booking_price(draft)
    if not total:
        return None
    extra_hours = duration - 7
    extra_sum = extra_hours * 1500
    base = total - extra_sum
    return f"{base:,} ₽ за 7 часов + {extra_hours} × 1 500 ₽ = {total:,} ₽".replace(",", " ")


def notify_admin_cancel_refund_required(
    *,
    chat_id: str,
    booking_id: int,
    draft: BookingDraft,
    reason: str | None = None,
) -> None:
    extra_lines = [
        "Клиент попросил отменить бронь.",
        "Если предоплата уже была получена, нужно вернуть её в течение 7 дней.",
    ]
    if reason:
        extra_lines.append(f"Причина/комментарий: {reason}")
    sqlite.enqueue_admin_notification(
        _booking_message(
            title="Отмена брони: проверьте возврат предоплаты",
            chat_id=chat_id,
            booking_id=booking_id,
            draft=draft,
            payment_status="нужно проверить оплату/возврат",
            extra_lines=extra_lines,
        ),
        chat_id=chat_id,
    )


def notify_admin_booking_rescheduled(
    *,
    chat_id: str,
    booking_id: int,
    draft: BookingDraft,
    old_date: str | None,
    old_time: str | None,
) -> None:
    sqlite.enqueue_admin_notification(
        _booking_message(
            title="Бронь перенесена",
            chat_id=chat_id,
            booking_id=booking_id,
            draft=draft,
            payment_status="проверьте статус оплаты по брони",
            extra_lines=[f"Было: {old_date or 'не указано'} {old_time or ''}".strip()],
        ),
        chat_id=chat_id,
    )
