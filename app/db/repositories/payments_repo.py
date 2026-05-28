from datetime import datetime
from decimal import Decimal
from typing import Any

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json


def create_pending(
    conn: PgConnection,
    *,
    conversation_id: int,
    user_id: int,
    booking_ids: list[int],
    provider: str,
    amount: Decimal,
    currency: str,
    description: str,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO payments (
                conversation_id,
                user_id,
                booking_ids,
                provider,
                amount,
                currency,
                description,
                raw_payload,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            RETURNING *
            """,
            (
                conversation_id,
                user_id,
                Json(booking_ids),
                provider,
                amount,
                currency,
                description,
                Json(raw_payload) if raw_payload is not None else None,
            ),
        )
        return dict(cur.fetchone())


def find_active_for_hold_ids(
    conn: PgConnection,
    *,
    conversation_id: int,
    provider: str,
    hold_ids: list[int],
) -> dict[str, Any] | None:
    wanted = sorted(int(item) for item in hold_ids)
    if not wanted:
        return None
    for payment in list_for_conversation(conn, conversation_id=conversation_id):
        if payment.get("provider") != provider:
            continue
        if payment.get("status") not in {"pending", "waiting_for_capture"}:
            continue
        raw_payload = payment.get("raw_payload") or {}
        if not isinstance(raw_payload, dict):
            continue
        payment_hold_ids = sorted(
            int(item)
            for item in raw_payload.get("hold_ids") or []
            if str(item).isdigit()
        )
        if payment_hold_ids == wanted:
            return payment
    return None


def attach_provider_response(
    conn: PgConnection,
    *,
    payment_id: int,
    provider_payment_id: str | None,
    payment_url: str | None,
    status: str,
    raw_payload: dict[str, Any],
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE payments
            SET provider_payment_id = %s,
                payment_url = %s,
                status = %s,
                raw_payload = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                provider_payment_id,
                payment_url,
                status,
                Json(raw_payload),
                payment_id,
            ),
        )
        return dict(cur.fetchone())


def mark_failed(
    conn: PgConnection,
    *,
    payment_id: int,
    raw_payload: dict[str, Any],
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE payments
            SET status = 'failed',
                raw_payload = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (Json(raw_payload), payment_id),
        )
        return dict(cur.fetchone())


def list_for_conversation(
    conn: PgConnection,
    *,
    conversation_id: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM payments
            WHERE conversation_id = %s
            ORDER BY id DESC
            """,
            (conversation_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def find_by_provider_payment_id(
    conn: PgConnection,
    *,
    provider: str,
    provider_payment_id: str,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM payments
            WHERE provider = %s
              AND provider_payment_id = %s
            LIMIT 1
            """,
            (provider, provider_payment_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def list_sync_candidates(
    conn: PgConnection,
    *,
    provider: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM payments
            WHERE provider = %s
              AND provider_payment_id IS NOT NULL
              AND status IN ('pending', 'waiting_for_capture')
            ORDER BY created_at ASC, id ASC
            LIMIT %s
            """,
            (provider, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def update_provider_status(
    conn: PgConnection,
    *,
    payment_id: int,
    status: str,
    raw_payload: dict[str, Any],
    paid_at: datetime | None = None,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE payments
            SET status = %s,
                raw_payload = %s,
                paid_at = COALESCE(%s, paid_at),
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (status, Json(raw_payload), paid_at, payment_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_paid_unnotified(
    conn: PgConnection,
    *,
    provider: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                p.*,
                u.external_id AS user_external_id,
                u.name AS user_name
            FROM payments p
            JOIN users u ON u.id = p.user_id
            WHERE p.provider = %s
              AND p.status = 'paid'
              AND p.payment_notified_at IS NULL
            ORDER BY p.paid_at ASC NULLS LAST, p.updated_at ASC, p.id ASC
            LIMIT %s
            """,
            (provider, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def update_booking_ids(
    conn: PgConnection,
    *,
    payment_id: int,
    booking_ids: list[int],
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE payments
            SET booking_ids = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (Json(booking_ids), payment_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def mark_payment_notified(
    conn: PgConnection,
    *,
    payment_id: int,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE payments
            SET payment_notified_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payment_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def mark_paid(
    conn: PgConnection,
    *,
    provider: str,
    provider_payment_id: str,
    paid_at: datetime,
    raw_payload: dict[str, Any],
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE payments
            SET status = 'paid',
                raw_payload = %s,
                paid_at = %s,
                updated_at = NOW()
            WHERE provider = %s
              AND provider_payment_id = %s
            RETURNING *
            """,
            (Json(raw_payload), paid_at, provider, provider_payment_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
