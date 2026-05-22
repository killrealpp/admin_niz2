import json
from typing import Any

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json


def create(
    conn: PgConnection,
    conversation_id: int,
    sender: str,
    text: str,
    raw_payload: dict | None = None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages (conversation_id, sender, text, raw_payload)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (conversation_id, sender, text, Json(raw_payload) if raw_payload else None),
        )
        row = cur.fetchone()
    data = dict(row)
    if isinstance(data.get("raw_payload"), str):
        data["raw_payload"] = json.loads(data["raw_payload"])
    return data


def list_recent(
    conn: PgConnection,
    conversation_id: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sender, text, created_at
            FROM messages
            WHERE conversation_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (conversation_id, limit),
        )
        rows = cur.fetchall()
    return [dict(r) for r in reversed(rows)]


def list_old_conversation_batches(
    conn: PgConnection,
    *,
    cutoff,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                conversation_id,
                min(created_at) AS messages_from,
                max(created_at) AS messages_to,
                count(1) AS messages_count
            FROM messages
            WHERE created_at < %s
            GROUP BY conversation_id
            ORDER BY messages_to ASC
            LIMIT %s
            """,
            (cutoff, limit),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def list_until(
    conn: PgConnection,
    *,
    conversation_id: int,
    cutoff,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, sender, text, created_at
            FROM messages
            WHERE conversation_id = %s
              AND created_at < %s
            ORDER BY created_at ASC
            """,
            (conversation_id, cutoff),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def delete_ids(conn: PgConnection, message_ids: list[int]) -> int:
    if not message_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM messages WHERE id = ANY(%s)",
            (message_ids,),
        )
        return cur.rowcount
