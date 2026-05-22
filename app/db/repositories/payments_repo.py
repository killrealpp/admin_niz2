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
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
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
            ),
        )
        return dict(cur.fetchone())


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
