from datetime import date, datetime, time
from typing import Any

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json


def create_or_touch(
    conn: PgConnection,
    *,
    conversation_id: int,
    user_id: int,
    service_type: str,
    desired_date: date,
    service_variant: str | None = None,
    desired_time: time | None = None,
    duration_minutes: int | None = None,
    guests_count: int | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO waitlist_requests (
                conversation_id,
                user_id,
                service_type,
                service_variant,
                desired_date,
                desired_time,
                duration_minutes,
                guests_count,
                raw_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, service_type, desired_date, COALESCE(desired_time, TIME '00:00'))
            WHERE status = 'active'
            DO UPDATE SET
                conversation_id = EXCLUDED.conversation_id,
                service_variant = COALESCE(EXCLUDED.service_variant, waitlist_requests.service_variant),
                duration_minutes = COALESCE(EXCLUDED.duration_minutes, waitlist_requests.duration_minutes),
                guests_count = COALESCE(EXCLUDED.guests_count, waitlist_requests.guests_count),
                raw_payload = EXCLUDED.raw_payload,
                updated_at = NOW()
            RETURNING *
            """,
            (
                conversation_id,
                user_id,
                service_type,
                service_variant,
                desired_date,
                desired_time,
                duration_minutes,
                guests_count,
                Json(raw_payload or {}),
            ),
        )
        return dict(cur.fetchone())


def list_active_due(
    conn: PgConnection,
    *,
    now: datetime,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT wr.*, u.external_id AS user_external_id
            FROM waitlist_requests wr
            JOIN users u ON u.id = wr.user_id
            WHERE wr.status = 'active'
              AND wr.desired_date >= %s
              AND (wr.last_checked_at IS NULL OR wr.last_checked_at < %s - INTERVAL '5 minutes')
            ORDER BY wr.created_at ASC, wr.id ASC
            LIMIT %s
            """,
            (now.date(), now, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def mark_checked(conn: PgConnection, *, waitlist_id: int, now: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE waitlist_requests
            SET last_checked_at = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (now, waitlist_id),
        )


def mark_notified(conn: PgConnection, *, waitlist_id: int, now: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE waitlist_requests
            SET status = 'notified',
                notified_at = %s,
                last_checked_at = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (now, now, waitlist_id),
        )


def close_matching(
    conn: PgConnection,
    *,
    service_type: str,
    desired_date: date,
    desired_time: time | None = None,
) -> int:
    with conn.cursor() as cur:
        sql = """
            UPDATE waitlist_requests
            SET status = 'closed',
                updated_at = NOW()
            WHERE status = 'active'
              AND service_type = %s
              AND desired_date = %s
        """
        params: list[Any] = [service_type, desired_date]
        if desired_time is not None:
            sql += " AND desired_time = %s"
            params.append(desired_time)
        cur.execute(sql, params)
        return cur.rowcount


def close_for_user(conn: PgConnection, *, user_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE waitlist_requests
            SET status = 'closed',
                updated_at = NOW()
            WHERE user_id = %s
              AND status IN ('active', 'notified')
            """,
            (user_id,),
        )
        return cur.rowcount
