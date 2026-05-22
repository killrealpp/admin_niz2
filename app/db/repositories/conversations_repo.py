import json
from datetime import datetime, timedelta
from typing import Any

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json

from app.core.constants import ACTIVE_CONVERSATION_STATUSES, EMPTY_FORM_DATA


def get_by_id(conn: PgConnection, conversation_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM conversations
            WHERE id = %s
            LIMIT 1
            """,
            (conversation_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    data = dict(row)
    if isinstance(data.get("form_data"), str):
        data["form_data"] = json.loads(data["form_data"])
    return data


def find_active_for_user(
    conn: PgConnection,
    user_id: int,
    ttl_hours: int,
    now: datetime,
) -> dict[str, Any] | None:
    cutoff = now - timedelta(hours=ttl_hours)
    statuses = list(ACTIVE_CONVERSATION_STATUSES)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM conversations
            WHERE user_id = %s
              AND status = ANY(%s)
              AND last_message_time >= %s
            ORDER BY last_message_time DESC
            LIMIT 1
            """,
            (user_id, statuses, cutoff),
        )
        row = cur.fetchone()
    if not row:
        return None
    data = dict(row)
    if isinstance(data.get("form_data"), str):
        data["form_data"] = json.loads(data["form_data"])
    return data


def create(
    conn: PgConnection,
    user_id: int,
    channel: str,
    now: datetime,
    form_data: dict | None = None,
) -> dict[str, Any]:
    payload = form_data or EMPTY_FORM_DATA.copy()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conversations (
                user_id, channel, status, form_data,
                last_message_time, created_at, updated_at
            )
            VALUES (%s, %s, 'active', %s, %s, %s, %s)
            RETURNING *
            """,
            (user_id, channel, Json(payload), now, now, now),
        )
        row = cur.fetchone()
    data = dict(row)
    if isinstance(data.get("form_data"), str):
        data["form_data"] = json.loads(data["form_data"])
    return data


def update_after_message(
    conn: PgConnection,
    conversation_id: int,
    now: datetime,
    *,
    status: str | None = None,
    intent: str | None = None,
    current_step: str | None = None,
    next_step: str | None = None,
    form_data: dict | None = None,
) -> None:
    fields: list[str] = ["last_message_time = %s", "updated_at = %s"]
    values: list[Any] = [now, now]

    if status is not None:
        fields.append("status = %s")
        values.append(status)
    if intent is not None:
        fields.append("intent = %s")
        values.append(intent)
    if current_step is not None:
        fields.append("current_step = %s")
        values.append(current_step)
    if next_step is not None:
        fields.append("next_step = %s")
        values.append(next_step)
    if form_data is not None:
        fields.append("form_data = %s")
        values.append(Json(form_data))

    values.append(conversation_id)
    sql = f"UPDATE conversations SET {', '.join(fields)} WHERE id = %s"
    with conn.cursor() as cur:
        cur.execute(sql, values)


def expire_stale(
    conn: PgConnection,
    user_id: int,
    ttl_hours: int,
    now: datetime,
) -> int:
    cutoff = now - timedelta(hours=ttl_hours)
    statuses = list(ACTIVE_CONVERSATION_STATUSES)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE conversations
            SET status = 'expired', updated_at = %s
            WHERE user_id = %s
              AND status = ANY(%s)
              AND last_message_time < %s
            """,
            (now, user_id, statuses, cutoff),
        )
        return cur.rowcount
