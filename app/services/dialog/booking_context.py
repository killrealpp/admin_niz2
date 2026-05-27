from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.db.repositories import (
    bookings_repo,
    conversation_summaries_repo,
    yclients_records_repo,
)
from app.services.dialog.booking_texts import format_booking_summary


def active_user_bookings(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    bookings = bookings_repo.list_future_active_for_user(
        conn,
        user_id=int(conversation["user_id"]),
        now=now,
    )
    bookings = filter_actual_journal_bookings(conn, bookings, now)
    if bookings:
        return bookings
    fallback_bookings = bookings_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation["id"],
    )
    return filter_actual_journal_bookings(conn, fallback_bookings, now)


def conversation_bookings_for_active_flow(conn, conversation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        booking
        for booking in bookings_repo.list_active_for_conversation(
            conn,
            conversation_id=conversation["id"],
        )
        if booking.get("status") != "cancelled"
    ]


def filter_actual_journal_bookings(
    conn,
    bookings: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    actual: list[dict[str, Any]] = []
    missing_ids: list[int] = []
    present_ids: list[int] = []
    for booking in bookings:
        record_id = str(booking.get("yclients_record_id") or "").strip()
        if record_id and not booking.get("synced_yclients_record_id"):
            if booking_sync_grace_active(booking, now) and yclients_records_repo.has_active_busy_interval_for_booking(
                conn,
                booking_id=int(booking["id"]),
                yclients_record_id=record_id,
            ):
                actual.append(
                    {
                        **booking,
                        "status": (
                            "created_in_yclients"
                            if booking.get("status") == "journal_missing"
                            else booking.get("status")
                        ),
                        "synced_yclients_record_id": record_id,
                    }
                )
                present_ids.append(int(booking["id"]))
                continue
            missing_ids.append(int(booking["id"]))
            continue
        if str(booking.get("synced_yclients_status") or "").lower() in {
            "cancelled",
            "canceled",
            "deleted",
            "removed",
            "not_come",
        }:
            missing_ids.append(int(booking["id"]))
            continue
        actual.append(booking)
        if booking.get("status") == "journal_missing":
            present_ids.append(int(booking["id"]))
    if present_ids:
        bookings_repo.mark_journal_present_by_ids(conn, booking_ids=present_ids, now=now)
    if missing_ids:
        bookings_repo.mark_journal_missing_by_ids(conn, booking_ids=missing_ids, now=now)
        for booking_id in missing_ids:
            yclients_records_repo.delete_busy_interval(
                conn,
                source="bot_booking",
                source_record_id=str(booking_id),
            )
    return actual


def booking_sync_grace_active(booking: dict[str, Any], now: datetime) -> bool:
    created_at = booking.get("yclients_created_at") or booking.get("updated_at") or booking.get("created_at")
    if not isinstance(created_at, datetime):
        return False
    if created_at.tzinfo is None and now.tzinfo is not None:
        created_at = created_at.replace(tzinfo=now.tzinfo)
    if now.tzinfo is not None and created_at.tzinfo is not None:
        created_at = created_at.astimezone(now.tzinfo)
    return now - created_at <= timedelta(minutes=15)


def has_user_bookings(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> bool:
    return bool(active_user_bookings(conn, conversation, form_data, now))


def as_post_booking_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    return {
        **conversation,
        "status": "payment_paid",
        "current_step": "reserved",
        "next_step": "payment_status",
    }


def context_summaries(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    summaries = conversation_summaries_repo.list_for_user(
        conn,
        user_id=int(conversation["user_id"]),
        limit=5,
    )
    bookings = active_user_bookings(conn, conversation, form_data, now)
    if bookings:
        summaries.append(
            {
                "messages_from": "active_bookings",
                "messages_to": "active_bookings",
                "summary": (
                    "Активные будущие брони этого клиента, даже если они были оформлены "
                    "в старом диалоге:\n"
                    f"{format_booking_summary(bookings)}"
                ),
            }
        )
    return summaries
