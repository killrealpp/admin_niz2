from __future__ import annotations

from typing import Any

from app.services.availability_service import load_services_map
from app.services.dialog.formatting import format_date_ru, format_time_duration_range, hours_from_minutes


def handoff_reply() -> str:
    return (
        "Простите, пожалуйста 🙏\n\n"
        "Передала ситуацию команде. Ваш номер сохранён, с вами свяжутся в ближайшее время."
    )


def confirmation_reply_text(form_data: dict[str, Any]) -> str:
    title = (load_services_map().get(form_data.get("service_type")) or {}).get("title") or "объект"
    variant = form_data.get("service_variant")
    object_text = f"{variant} ({title})" if variant else title
    extras = ", ".join(form_data.get("upsell_items") or []) or "не нужны"
    guests = form_data.get("guests_count") or "не указано"
    event_format = form_data.get("event_format") or "не указан"
    return (
        "Проверила заявку ✅\n\n"
        f"📍 Объект: {object_text}\n"
        f"📅 Дата: {format_date_ru(form_data.get('date'))}\n"
        f"🕒 Время: {format_time_duration_range(form_data.get('time'), form_data.get('duration'))}\n"
        f"👥 Гостей: {guests}\n"
        f"🎉 Формат: {event_format}\n"
        f"➕ Допы: {extras}\n"
        f"👤 Имя: {form_data.get('client_name')}\n"
        f"📞 Телефон: {form_data.get('phone')}\n\n"
        "Всё верно? Подтверждаете бронь?"
    )


def format_hold_summary(holds: list[dict[str, Any]], form_data: dict[str, Any]) -> str:
    lines = ["Зафиксировал заявку. Вот что сейчас в бронировании:"]
    for index, hold in enumerate(holds, start=1):
        title = (load_services_map().get(hold.get("service_type")) or {}).get("title") or hold.get("service_type")
        slot_time = str(hold.get("slot_time") or "")[:5]
        period = format_time_duration_range(slot_time, hold.get("duration_minutes"))
        lines.append(f"{index}. {title}: {format_date_ru(hold.get('slot_date'))}, {period}.")
    phone = form_data.get("phone")
    if phone:
        lines.append(f"Номер {phone} сохранил для связи по брони.")
    else:
        lines.append("Контакт для связи по брони сохранил.")
    return "\n".join(lines)


def booking_object_title(booking: dict[str, Any]) -> str:
    service_type = booking.get("service_type")
    config = load_services_map().get(service_type) or {}
    title = config.get("title") or str(service_type or "Бронь")
    if service_type != "gazebo":
        return title

    hold_service_id = str(booking.get("hold_yclients_service_id") or "").strip()
    for variant in config.get("variants") or []:
        if hold_service_id and str(variant.get("yclients_service_id") or "").strip() == hold_service_id:
            return str(variant.get("title") or title)
    return title


def booking_status_text(booking: dict[str, Any]) -> str:
    payment_status = str(booking.get("payment_status") or "")
    status = str(booking.get("status") or "")
    if payment_status == "paid" and booking.get("synced_yclients_record_id"):
        return "оплата прошла, бронь подтверждена"
    if payment_status == "paid" and booking.get("yclients_record_id"):
        return "оплата прошла, запись в журнале сейчас не найдена"
    if payment_status == "paid":
        return "оплата прошла, бронь подтверждается в журнале"
    if payment_status == "awaiting_payment":
        return "ожидает оплаты"
    if status == "confirmed":
        return "подтверждается"
    return "зафиксирована"


def booking_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "бронь"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "брони"
    return "броней"


def format_booking_summary(bookings: list[dict[str, Any]]) -> str:
    active = [
        booking
        for booking in bookings
        if booking.get("status") not in {"cancelled", "journal_missing"}
    ]
    if not active:
        return "Пока не вижу активных броней."

    count = len(active)
    lines = [f"У вас {count} {booking_word(count)}:"]
    for index, booking in enumerate(active, start=1):
        time_text = str(booking.get("booking_time") or "")[:5]
        period = format_time_duration_range(time_text, booking.get("duration_minutes"))
        guests = booking.get("guests_count")
        guests_text = f", гостей: {guests}" if guests else ""
        lines.append(
            f"{index}. {booking_object_title(booking)}: "
            f"{format_date_ru(booking.get('booking_date'))}, {period}"
            f"{guests_text}. {booking_status_text(booking)}."
        )
    return "\n".join(lines)


def payment_reply_text(payment: dict[str, Any] | None) -> str:
    if not payment or not payment.get("payment_url"):
        return (
            "Ссылку на предоплату сейчас автоматически создать не получилось. "
            "Ваш номер сохранён, с вами свяжутся в ближайшее время и отправят ссылку вручную."
        )
    return (
        f"Для закрепления заявки нужна предоплата {payment.get('amount')} ₽.\n"
        f"Оплатить можно по ссылке:\n{payment['payment_url']}\n\n"
        "Резерв держится 10 минут. После оплаты дождитесь подтверждения: "
        "мы пришлём сообщение, когда платёж пройдёт ✅"
    )


def booking_line_short(booking: dict[str, Any]) -> str:
    title = booking_object_title(booking)
    period = format_time_duration_range(str(booking.get("booking_time"))[:5], hours_from_minutes(booking.get("duration_minutes")))
    return (
        f"{title}: {format_date_ru(str(booking.get('booking_date')))}, "
        f"{period}"
    )
