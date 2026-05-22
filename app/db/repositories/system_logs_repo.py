from __future__ import annotations

from typing import Any

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json


def create(
    conn: PgConnection,
    *,
    level: str,
    event_type: str,
    message: str,
    conversation_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO system_logs (conversation_id, level, event_type, message, payload)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (conversation_id, level, event_type, message, Json(payload or {})),
        )
        return dict(cur.fetchone())


def list_admin_unnotified(
    conn: PgConnection,
    *,
    event_type: str = "ai_provider_unavailable",
    limit: int = 10,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM system_logs
            WHERE event_type = %s
              AND admin_notified_at IS NULL
            ORDER BY created_at ASC, id ASC
            LIMIT %s
            """,
            (event_type, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def mark_admin_notified(conn: PgConnection, *, log_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE system_logs
            SET admin_notified_at = NOW()
            WHERE id = %s
            """,
            (log_id,),
        )
