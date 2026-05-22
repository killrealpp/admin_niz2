from datetime import datetime

from psycopg2.extensions import connection as PgConnection


def create(
    conn: PgConnection,
    *,
    conversation_id: int,
    summary: str,
    messages_from: datetime,
    messages_to: datetime,
    messages_count: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conversation_summaries (
                conversation_id,
                summary,
                messages_from,
                messages_to,
                messages_count
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                conversation_id,
                summary,
                messages_from,
                messages_to,
                messages_count,
            ),
        )


def list_for_conversation(
    conn: PgConnection,
    conversation_id: int,
    limit: int = 3,
) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT summary, messages_from, messages_to, messages_count, created_at
            FROM conversation_summaries
            WHERE conversation_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (conversation_id, limit),
        )
        rows = cur.fetchall()
    return [dict(row) for row in reversed(rows)]
