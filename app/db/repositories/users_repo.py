from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection


def find_by_external_id(
    conn: PgConnection, channel: str, external_id: str
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM users
            WHERE channel = %s AND external_id = %s
            LIMIT 1
            """,
            (channel, external_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def create(
    conn: PgConnection,
    channel: str,
    external_id: str,
    name: str | None,
    seen_at: datetime,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (channel, external_id, name, last_seen_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (channel, external_id, name, seen_at, seen_at),
        )
        row = cur.fetchone()
    return dict(row)


def get_by_id(conn: PgConnection, user_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM users
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def touch(
    conn: PgConnection,
    user_id: int,
    name: str | None,
    seen_at: datetime,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET name = COALESCE(%s, name),
                last_seen_at = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (name, seen_at, seen_at, user_id),
        )


def update_phone(conn: PgConnection, user_id: int, phone: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users SET phone = %s, updated_at = NOW() WHERE id = %s
            """,
            (phone, user_id),
        )


def set_handoff(
    conn: PgConnection,
    *,
    user_id: int,
    until: datetime,
    reason: str,
    summary: str,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET handoff_until = %s,
                handoff_reason = %s,
                handoff_summary = %s,
                handoff_notified_at = NULL,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (until, reason[:500], summary[:2000], user_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def clear_handoff(conn: PgConnection, *, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET handoff_until = NULL,
                handoff_reason = NULL,
                handoff_summary = NULL,
                handoff_notified_at = NULL,
                updated_at = NOW()
            WHERE id = %s
            """,
            (user_id,),
        )


def mark_handoff_notified(conn: PgConnection, *, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET handoff_notified_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            """,
            (user_id,),
        )


def list_handoffs_to_notify(
    conn: PgConnection,
    *,
    now: datetime,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM users
            WHERE handoff_until IS NOT NULL
              AND handoff_until > %s
              AND handoff_notified_at IS NULL
            ORDER BY updated_at ASC, id ASC
            LIMIT %s
            """,
            (now, limit),
        )
        return [dict(row) for row in cur.fetchall()]
