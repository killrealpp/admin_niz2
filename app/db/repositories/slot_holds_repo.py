from datetime import date, datetime, time
from typing import Any

from psycopg2.extensions import connection as PgConnection


def list_active_for_slot(
    conn: PgConnection,
    *,
    service_type: str,
    slot_date: date,
    now: datetime,
    yclients_service_id: str | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        sql = """
            SELECT *
            FROM slot_holds
            WHERE service_type = %s
              AND slot_date = %s
              AND status = 'active'
              AND expires_at > %s
        """
        params: list[Any] = [service_type, slot_date, now]
        if yclients_service_id:
            sql += " AND yclients_service_id = %s"
            params.append(yclients_service_id)
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def is_slot_held(
    conn: PgConnection,
    *,
    service_type: str,
    slot_date: date,
    slot_time: time,
    now: datetime,
    yclients_service_id: str | None = None,
) -> bool:
    with conn.cursor() as cur:
        sql = """
            SELECT 1
            FROM slot_holds
            WHERE service_type = %s
              AND slot_date = %s
              AND slot_time = %s
              AND status = 'active'
              AND expires_at > %s
        """
        params: list[Any] = [service_type, slot_date, slot_time, now]
        if yclients_service_id:
            sql += " AND yclients_service_id = %s"
            params.append(yclients_service_id)
        sql += """
            LIMIT 1
        """
        cur.execute(sql, params)
        return cur.fetchone() is not None


def list_active_for_conversation(
    conn: PgConnection,
    *,
    conversation_id: int,
    now: datetime,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM slot_holds
            WHERE conversation_id = %s
              AND status = 'active'
              AND expires_at > %s
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id, now),
        )
        return [dict(row) for row in cur.fetchall()]


def create(
    conn: PgConnection,
    *,
    conversation_id: int,
    user_id: int,
    service_type: str,
    yclients_service_id: str | None,
    slot_date: date,
    slot_time: time,
    duration_minutes: int | None,
    expires_at: datetime,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO slot_holds (
                conversation_id,
                user_id,
                service_type,
                yclients_service_id,
                slot_date,
                slot_time,
                duration_minutes,
                status,
                expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s)
            RETURNING *
            """,
            (
                conversation_id,
                user_id,
                service_type,
                yclients_service_id,
                slot_date,
                slot_time,
                duration_minutes,
                expires_at,
            ),
        )
        return dict(cur.fetchone())


def cancel_matching(
    conn: PgConnection,
    *,
    conversation_id: int,
    now: datetime,
    service_type: str | None = None,
    slot_date: date | None = None,
) -> int:
    with conn.cursor() as cur:
        sql = """
            UPDATE slot_holds
            SET status = 'cancelled', updated_at = %s
            WHERE conversation_id = %s
              AND status = 'active'
              AND expires_at > %s
        """
        params: list[Any] = [now, conversation_id, now]
        if service_type:
            sql += " AND service_type = %s"
            params.append(service_type)
        if slot_date:
            sql += " AND slot_date = %s"
            params.append(slot_date)
        cur.execute(sql, params)
        return cur.rowcount


def cancel_ids(
    conn: PgConnection,
    *,
    hold_ids: list[int],
    now: datetime,
) -> int:
    if not hold_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE slot_holds
            SET status = 'cancelled', updated_at = %s
            WHERE id = ANY(%s)
              AND status = 'active'
            """,
            (now, hold_ids),
        )
        return cur.rowcount


def get_by_id(conn: PgConnection, hold_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM slot_holds
            WHERE id = %s
            LIMIT 1
            """,
            (hold_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def update_slot(
    conn: PgConnection,
    *,
    hold_id: int,
    yclients_service_id: str | None,
    slot_date: date,
    slot_time: time,
    duration_minutes: int | None,
    now: datetime,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE slot_holds
            SET yclients_service_id = %s,
                slot_date = %s,
                slot_time = %s,
                duration_minutes = %s,
                updated_at = %s
            WHERE id = %s
            RETURNING *
            """,
            (
                yclients_service_id,
                slot_date,
                slot_time,
                duration_minutes,
                now,
                hold_id,
            ),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def mark_converted(conn: PgConnection, *, hold_id: int, now: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE slot_holds
            SET status = 'converted', updated_at = %s
            WHERE id = %s
            """,
            (now, hold_id),
        )


def expire_old(conn: PgConnection, now: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE slot_holds
            SET status = 'expired', updated_at = %s
            WHERE status = 'active' AND expires_at <= %s
            """,
            (now, now),
        )
        return cur.rowcount
