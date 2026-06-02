from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable

from app.ai.errors import AIProviderUnavailable
from app.core.constants import SENDER_ASSISTANT, SENDER_USER
from app.db.repositories import payments_repo, slot_holds_repo
from app.services.dialog.booking_context import active_user_bookings
from app.services.dialog.booking_texts import format_booking_summary, format_hold_summary


def post_booking_summary(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> str:
    bookings = active_user_bookings(conn, conversation, form_data, now)
    active_holds = slot_holds_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation["id"],
        now=now,
    )
    if bookings and not active_holds:
        return format_booking_summary(bookings)
    if bookings and active_holds:
        return (
            f"{format_booking_summary(bookings)}\n\n"
            f"Сейчас дополнительно в резерве:\n{format_hold_summary(active_holds, form_data)}"
        )
    if active_holds:
        summary = format_hold_summary(active_holds, form_data)
        if conversation.get("status") == "payment_paid":
            summary = summary.replace(
                " для финального подтверждения и предоплаты",
                " для финального подтверждения",
            )
        return summary
    return (
        "Пока не вижу активных броней по вашему номеру.\n\n"
        "Если хотите оформить бронь, напишите услугу и дату — проверю свободные варианты."
    )


def payment_status_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    *,
    now: datetime,
    sync_payment_statuses: Callable[[Any], Any],
    create_missing_yclients_records: Callable[[Any], Any],
    log_exception: Callable[[str, Any], None],
) -> tuple[str, str]:
    try:
        sync_payment_statuses(conn)
        create_missing_yclients_records(conn)
    except Exception:
        log_exception("Payment status sync failed conversation_id=%s", conversation["id"])

    payments = payments_repo.list_for_conversation(
        conn,
        conversation_id=conversation["id"],
    )
    if not payments:
        return (
            "Я пока не вижу созданной ссылки на оплату по этой заявке. "
            "Если заявка уже подтверждена, напишите «да» ещё раз — пришлю ссылку на предоплату.",
            "reserved",
        )

    paid_payment = next((payment for payment in payments if payment.get("status") == "paid"), None)
    if paid_payment:
        bookings = active_user_bookings(conn, conversation, form_data, now)
        if not bookings:
            return (
                "Оплата получена ✅\n\n"
                "Но резерв по этой ссылке уже истёк, поэтому бронь не закрепилась автоматически. "
                "Напишите, если слот всё ещё актуален — я заново проверю свободность.",
                "waiting_user",
            )
        journal_ready = bool(bookings) and all(booking.get("yclients_record_id") for booking in bookings)
        if journal_ready and not paid_payment.get("payment_notified_at"):
            payments_repo.mark_payment_notified(conn, payment_id=paid_payment["id"])
        summary = format_booking_summary(bookings) if bookings else "Заявка зафиксирована."
        return (
            f"Да, оплата получена. Спасибо!\n\n{summary}\n\n"
            "Повторно подтверждать заявку уже не нужно.",
            "payment_paid",
        )

    latest_payment = payments[0]
    if latest_payment.get("payment_url"):
        return (
            "Пока оплата ещё не отразилась в ЮKassa. Обычно это занимает немного времени.\n\n"
            f"Если нужно, вот ссылка ещё раз:\n{latest_payment['payment_url']}",
            "reserved",
        )
    return (
        "Пока оплата ещё не отразилась в ЮKassa. Проверю её автоматически ещё раз чуть позже.",
        "reserved",
    )


def classify_post_booking_safely(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    now: datetime,
    classify_post_booking_message: Callable[..., Any],
    load_knowledge: Callable[[], str],
    log_exception: Callable[[str], None],
) -> Any:
    try:
        return classify_post_booking_message(
            text=text,
            form_data=form_data,
            history=history,
            current_datetime=now,
            knowledge=load_knowledge(),
        )
    except AIProviderUnavailable:
        raise
    except Exception:
        log_exception("Post-booking classification failed")
        return None


def plain_ack_after_closed_booking(
    text: str,
    confirmation_yes: Callable[[str], bool],
) -> bool:
    normalized = re.sub(r"[^\w+]+", " ", text.lower().replace("ё", "е")).strip()
    if confirmation_yes(text):
        return True
    return normalized in {
        "ок",
        "окей",
        "спасибо",
        "спс",
        "понял",
        "поняла",
        "ладно",
        "ясно",
        "ок спасибо",
        "хорошо спасибо",
    }


def continues_booking_summary_question(text: str, history: list[dict[str, Any]]) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    if normalized not in {
        "и это все",
        "это все",
        "только одна",
        "только одну",
    }:
        return False
    for item in reversed(history[:-1]):
        if item.get("sender") == SENDER_USER:
            continue
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        previous = str(item.get("text") or "").lower().replace("ё", "е")
        return "брон" in previous
    return False


def is_waitlist_decline(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    return any(
        marker in normalized
        for marker in (
            "не актуально",
            "уже не актуально",
            "больше не актуально",
            "не нужно уведомлять",
            "не надо уведомлять",
            "снял запрос",
            "снять запрос",
        )
    )
