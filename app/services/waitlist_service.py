from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.core.config import get_settings
from app.core.constants import SENDER_USER
from app.db.connection import get_connection
from app.db.repositories import bookings_repo, messages_repo, waitlist_repo
from app.services.availability_service import check_availability, load_services_map

logger = logging.getLogger(__name__)


def remember_waitlist_request(
    conn,
    *,
    conversation_id: int,
    user_id: int,
    form_data: dict[str, Any],
) -> dict[str, Any] | None:
    if not form_data.get("service_type") or not form_data.get("date"):
        return None
    try:
        desired_date = datetime.fromisoformat(str(form_data["date"])).date()
    except ValueError:
        return None
    desired_time = None
    if form_data.get("time"):
        try:
            desired_time = datetime.strptime(str(form_data["time"])[:5], "%H:%M").time()
        except ValueError:
            desired_time = None
    duration = _duration_minutes(form_data.get("duration"))
    guests = int(form_data["guests_count"]) if form_data.get("guests_count") else None
    return waitlist_repo.create_or_touch(
        conn,
        conversation_id=conversation_id,
        user_id=user_id,
        service_type=str(form_data["service_type"]),
        service_variant=form_data.get("service_variant"),
        desired_date=desired_date,
        desired_time=desired_time,
        duration_minutes=duration,
        guests_count=guests,
        raw_payload={"form_data": form_data},
    )


async def notify_waitlist_matches(bot: Bot) -> int:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    sent = 0
    with get_connection() as conn:
        rows = waitlist_repo.list_active_due(conn, now=now)

    for row in rows:
        form_data = _form_data_from_waitlist(row)
        try:
            with get_connection() as conn:
                if _waitlist_request_is_obsolete(conn, row, now):
                    waitlist_repo.mark_closed(conn, waitlist_id=row["id"], now=now)
                    continue
                availability = check_availability(conn, form_data=form_data, now=now)
                waitlist_repo.mark_checked(conn, waitlist_id=row["id"], now=now)
        except Exception:
            logger.exception("Waitlist availability check failed id=%s", row.get("id"))
            continue
        if not availability.ok or not availability.slots:
            continue

        service_title = (load_services_map().get(row["service_type"]) or {}).get("title") or row["service_type"]
        text = (
            "Появилось свободное место ✅\n\n"
            f"По вашему запросу на {service_title.lower()} {_date_ru(row['desired_date'])} снова есть свободный вариант.\n\n"
            "Напишите, пожалуйста, если ещё актуально, и я проверю слот перед оформлением."
        )
        try:
            await bot.send_message(chat_id=str(row["user_external_id"]), text=text)
        except Exception:
            logger.exception("Waitlist notification failed id=%s", row.get("id"))
            continue
        with get_connection() as conn:
            waitlist_repo.mark_notified(conn, waitlist_id=row["id"], now=now)
        sent += 1
    return sent


def _waitlist_request_is_obsolete(conn, row: dict[str, Any], now: datetime) -> bool:
    if row.get("status") != "active":
        return True
    desired_date = row.get("desired_date")
    if desired_date and desired_date < now.date():
        return True
    if _user_declined_waitlist(conn, row):
        return True
    if _matching_active_booking_exists(conn, row, now):
        return True
    if _matching_active_hold_exists(conn, row, now):
        return True
    return False


def _user_declined_waitlist(conn, row: dict[str, Any]) -> bool:
    created_at = row.get("created_at")
    messages = messages_repo.list_recent(conn, int(row["conversation_id"]), limit=12)
    for item in messages:
        if item.get("sender") != SENDER_USER:
            continue
        if created_at and item.get("created_at") and item["created_at"] < created_at:
            continue
        compact = " ".join(str(item.get("text") or "").lower().replace("ё", "е").split())
        if any(
            marker in compact
            for marker in (
                "не надо уведом",
                "не нужно уведом",
                "не актуально",
                "уже не актуально",
                "передумал",
                "передумала",
                "отбой",
            )
        ):
            return True
    return False


def _matching_active_booking_exists(conn, row: dict[str, Any], now: datetime) -> bool:
    raw_payload = row.get("raw_payload") or {}
    form_data = raw_payload.get("form_data") if isinstance(raw_payload, dict) else {}
    phone = form_data.get("phone") if isinstance(form_data, dict) else None
    bookings = bookings_repo.list_future_active_for_user(conn, user_id=int(row["user_id"]), now=now, phone=phone)
    for booking in bookings:
        if booking.get("service_type") != row.get("service_type"):
            continue
        if str(booking.get("booking_date")) != str(row.get("desired_date")):
            continue
        if row.get("desired_time") and str(booking.get("booking_time"))[:5] != str(row.get("desired_time"))[:5]:
            continue
        if row.get("duration_minutes") and booking.get("duration_minutes"):
            if int(row["duration_minutes"]) != int(booking["duration_minutes"]):
                continue
        return True
    return False


def _matching_active_hold_exists(conn, row: dict[str, Any], now: datetime) -> bool:
    with conn.cursor() as cur:
        sql = """
            SELECT 1
            FROM slot_holds
            WHERE user_id = %s
              AND service_type = %s
              AND slot_date = %s
              AND status = 'active'
              AND expires_at > %s
        """
        params: list[Any] = [row["user_id"], row["service_type"], row["desired_date"], now]
        if row.get("desired_time"):
            sql += " AND slot_time = %s"
            params.append(row["desired_time"])
        if row.get("duration_minutes"):
            sql += " AND duration_minutes = %s"
            params.append(row["duration_minutes"])
        sql += " LIMIT 1"
        cur.execute(sql, params)
        return cur.fetchone() is not None


def _form_data_from_waitlist(row: dict[str, Any]) -> dict[str, Any]:
    time_text = row["desired_time"].strftime("%H:%M") if row.get("desired_time") else None
    duration_hours = None
    if row.get("duration_minutes"):
        duration_hours = int(row["duration_minutes"]) // 60
    return {
        "service_type": row["service_type"],
        "service_variant": row.get("service_variant"),
        "date": row["desired_date"].isoformat(),
        "time": time_text,
        "duration": duration_hours,
        "guests_count": row.get("guests_count"),
    }


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
    return number if "мин" in text else number * 60


def _date_ru(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y")
    return str(value)
