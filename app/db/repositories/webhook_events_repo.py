from typing import Any

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json


def create_if_new(
    conn: PgConnection,
    *,
    provider: str,
    event_type: str,
    provider_object_id: str | None,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO webhook_events (
                provider,
                event_type,
                provider_object_id,
                payload
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (provider, event_type, provider_object_id)
            WHERE provider_object_id IS NOT NULL
            DO NOTHING
            RETURNING *
            """,
            (provider, event_type, provider_object_id, Json(payload)),
        )
        row = cur.fetchone()
    return (dict(row), True) if row else (None, False)


def mark_processed(conn: PgConnection, *, event_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE webhook_events
            SET processed_at = NOW()
            WHERE id = %s
            """,
            (event_id,),
        )
