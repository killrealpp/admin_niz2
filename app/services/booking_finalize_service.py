"""Create bookings from paid holds (after YooKassa payment)."""

from __future__ import annotations

import json
from typing import Any

from psycopg2.extensions import connection as PgConnection

from app.db.repositories import bookings_repo, payments_repo, slot_holds_repo


def hold_ids_from_payment(payment: dict[str, Any]) -> list[int]:
    raw = payment.get("raw_payload") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return []

    hold_ids = raw.get("hold_ids")
    if isinstance(hold_ids, list):
        return [int(item) for item in hold_ids if str(item).isdigit()]

    metadata = raw.get("metadata") or {}
    if isinstance(metadata, dict):
        text = str(metadata.get("hold_ids") or "")
        return [int(item) for item in text.split(",") if item.strip().isdigit()]
    return []


def finalize_bookings_for_paid_payment(
    conn: PgConnection,
    payment: dict[str, Any],
    *,
    now: Any,
) -> list[int]:
    """Create booking rows for holds linked to a paid payment. Idempotent."""
    existing = _existing_booking_ids(payment)
    if existing:
        return existing

    created: list[int] = []
    for hold_id in hold_ids_from_payment(payment):
        hold = slot_holds_repo.get_by_id(conn, hold_id)
        if not hold:
            continue
        if hold.get("status") == "converted":
            existing_booking = bookings_repo.find_by_hold_id(conn, slot_hold_id=hold_id)
            if existing_booking:
                created.append(int(existing_booking["id"]))
            continue

        existing_booking = bookings_repo.find_by_hold_id(conn, slot_hold_id=hold_id)
        if existing_booking:
            created.append(int(existing_booking["id"]))
            slot_holds_repo.mark_converted(conn, hold_id=hold_id, now=now)
            continue

        booking = bookings_repo.create_from_hold(
            conn,
            conversation_id=hold["conversation_id"],
            user_id=hold["user_id"],
            slot_hold_id=hold["id"],
            service_type=hold["service_type"],
            booking_date=hold["slot_date"],
            booking_time=hold["slot_time"],
            duration_minutes=hold.get("duration_minutes"),
            client_name=_client_name_for_hold(conn, hold),
            phone=_phone_for_hold(conn, hold),
            guests_count=_guests_count_for_hold(conn, hold),
            event_format=_field_from_conversation(conn, hold, "event_format"),
            preferences=_field_from_conversation(conn, hold, "preferences"),
            upsell_items=_field_from_conversation(conn, hold, "upsell_items") or [],
            status="confirmed",
            payment_status="paid",
        )
        slot_holds_repo.mark_converted(conn, hold_id=hold_id, now=now)
        created.append(int(booking["id"]))

    if created:
        payments_repo.update_booking_ids(conn, payment_id=payment["id"], booking_ids=created)
    return created


def _existing_booking_ids(payment: dict[str, Any]) -> list[int]:
    raw = payment.get("booking_ids") or []
    if isinstance(raw, list):
        return [int(item) for item in raw if str(item).isdigit()]
    return []


def _conversation_form_data(conn: PgConnection, conversation_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT form_data FROM conversations WHERE id = %s LIMIT 1",
            (conversation_id,),
        )
        row = cur.fetchone()
    if not row:
        return {}
    form_data = row.get("form_data") or {}
    if isinstance(form_data, str):
        return json.loads(form_data)
    return dict(form_data)


def _field_from_conversation(
    conn: PgConnection,
    hold: dict[str, Any],
    key: str,
) -> Any:
    return _conversation_form_data(conn, hold["conversation_id"]).get(key)


def _client_name_for_hold(conn: PgConnection, hold: dict[str, Any]) -> str:
    form_data = _conversation_form_data(conn, hold["conversation_id"])
    if form_data.get("client_name"):
        return str(form_data["client_name"])
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM users WHERE id = %s LIMIT 1", (hold["user_id"],))
        row = cur.fetchone()
    return str((row or {}).get("name") or "Клиент")


def _phone_for_hold(conn: PgConnection, hold: dict[str, Any]) -> str:
    form_data = _conversation_form_data(conn, hold["conversation_id"])
    if form_data.get("phone"):
        return str(form_data["phone"])
    with conn.cursor() as cur:
        cur.execute("SELECT phone FROM users WHERE id = %s LIMIT 1", (hold["user_id"],))
        row = cur.fetchone()
    return str((row or {}).get("phone") or "")


def _guests_count_for_hold(conn: PgConnection, hold: dict[str, Any]) -> int | None:
    guests = _field_from_conversation(conn, hold, "guests_count")
    if guests in (None, ""):
        return None
    return int(guests)
