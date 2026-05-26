from datetime import date, datetime, time
from typing import Any

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json


def create_from_hold(
    conn: PgConnection,
    *,
    conversation_id: int,
    user_id: int,
    slot_hold_id: int,
    service_type: str,
    booking_date: date,
    booking_time: time,
    duration_minutes: int | None,
    client_name: str,
    phone: str,
    guests_count: int | None,
    event_format: str | None,
    preferences: str | None,
    upsell_items: list[str] | None,
    status: str = "pending_admin_confirmation",
    payment_status: str = "not_required_yet",
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bookings (
                conversation_id,
                user_id,
                slot_hold_id,
                service_type,
                booking_date,
                booking_time,
                duration_minutes,
                client_name,
                phone,
                guests_count,
                event_format,
                preferences,
                upsell_items,
                status,
                payment_status
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                conversation_id,
                user_id,
                slot_hold_id,
                service_type,
                booking_date,
                booking_time,
                duration_minutes,
                client_name,
                phone,
                guests_count,
                event_format,
                preferences,
                Json(upsell_items or []),
                status,
                payment_status,
            ),
        )
        return dict(cur.fetchone())


def find_by_hold_id(
    conn: PgConnection,
    *,
    slot_hold_id: int,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM bookings
            WHERE slot_hold_id = %s
              AND status NOT IN ('cancelled')
            ORDER BY id DESC
            LIMIT 1
            """,
            (slot_hold_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def list_for_conversation(
    conn: PgConnection,
    *,
    conversation_id: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.*, sh.yclients_service_id AS hold_yclients_service_id
            FROM bookings b
            LEFT JOIN slot_holds sh ON sh.id = b.slot_hold_id
            WHERE b.conversation_id = %s
            ORDER BY b.created_at ASC, b.id ASC
            """,
            (conversation_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def list_active_for_conversation(
    conn: PgConnection,
    *,
    conversation_id: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.*,
                   sh.yclients_service_id AS hold_yclients_service_id,
                   yr.yclients_record_id AS synced_yclients_record_id,
                   yr.status AS synced_yclients_status
            FROM bookings b
            LEFT JOIN slot_holds sh ON sh.id = b.slot_hold_id
            LEFT JOIN yclients_records yr ON yr.yclients_record_id = b.yclients_record_id
            WHERE b.conversation_id = %s
              AND b.status NOT IN ('cancelled')
            ORDER BY b.id ASC
            """,
            (conversation_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def list_active_for_user(
    conn: PgConnection,
    *,
    user_id: int,
    phone: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: list[Any] = [user_id]
    phone_filter = ""
    if phone:
        phone_filter = " OR regexp_replace(b.phone, '\\D', '', 'g') = regexp_replace(%s, '\\D', '', 'g')"
        params.append(phone)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT b.*,
                   sh.yclients_service_id AS hold_yclients_service_id,
                   yr.yclients_record_id AS synced_yclients_record_id,
                   yr.status AS synced_yclients_status
            FROM bookings b
            LEFT JOIN slot_holds sh ON sh.id = b.slot_hold_id
            LEFT JOIN yclients_records yr ON yr.yclients_record_id = b.yclients_record_id
            WHERE (b.user_id = %s{phone_filter})
              AND b.status NOT IN ('cancelled')
            ORDER BY b.booking_date ASC, b.booking_time ASC, b.id ASC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def list_future_active_for_user(
    conn: PgConnection,
    *,
    user_id: int,
    now: datetime,
    phone: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: list[Any] = [user_id]
    phone_filter = ""
    if phone:
        phone_filter = " OR regexp_replace(b.phone, '\\D', '', 'g') = regexp_replace(%s, '\\D', '', 'g')"
        params.append(phone)
    params.append(now.date())
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT b.*,
                   sh.yclients_service_id AS hold_yclients_service_id,
                   yr.yclients_record_id AS synced_yclients_record_id,
                   yr.status AS synced_yclients_status
            FROM bookings b
            LEFT JOIN slot_holds sh ON sh.id = b.slot_hold_id
            LEFT JOIN yclients_records yr ON yr.yclients_record_id = b.yclients_record_id
            WHERE (b.user_id = %s{phone_filter})
              AND b.status NOT IN ('cancelled')
              AND b.booking_date >= %s
            ORDER BY b.booking_date ASC, b.booking_time ASC, b.id ASC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def cancel_by_hold(
    conn: PgConnection,
    *,
    conversation_id: int,
    slot_hold_id: int,
    now: datetime,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET status = 'cancelled', updated_at = %s
            WHERE conversation_id = %s
              AND slot_hold_id = %s
              AND status NOT IN ('cancelled', 'created_in_yclients')
            """,
            (now, conversation_id, slot_hold_id),
        )
        return cur.rowcount


def cancel_matching(
    conn: PgConnection,
    *,
    conversation_id: int,
    now: datetime,
    service_type: str | None = None,
    booking_date: date | None = None,
) -> int:
    with conn.cursor() as cur:
        sql = """
            UPDATE bookings
            SET status = 'cancelled', updated_at = %s
            WHERE conversation_id = %s
              AND status NOT IN ('cancelled', 'created_in_yclients')
        """
        params: list[Any] = [now, conversation_id]
        if service_type:
            sql += " AND service_type = %s"
            params.append(service_type)
        if booking_date:
            sql += " AND booking_date = %s"
            params.append(booking_date)
        cur.execute(sql, params)
        return cur.rowcount


def cancel_by_id(
    conn: PgConnection,
    *,
    booking_id: int,
    now: datetime,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET status = 'cancelled',
                updated_at = %s
            WHERE id = %s
              AND status NOT IN ('cancelled', 'journal_missing')
            RETURNING *
            """,
            (now, booking_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def update_payment_status_by_ids(
    conn: PgConnection,
    *,
    booking_ids: list[int],
    payment_status: str,
) -> int:
    if not booking_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET payment_status = %s,
                updated_at = NOW()
            WHERE id = ANY(%s)
              AND status NOT IN ('cancelled', 'journal_missing')
            """,
            (payment_status, booking_ids),
        )
        return cur.rowcount


def mark_journal_missing_by_ids(
    conn: PgConnection,
    *,
    booking_ids: list[int],
    now: datetime,
) -> int:
    if not booking_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET status = 'journal_missing',
                updated_at = %s
            WHERE id = ANY(%s)
              AND status NOT IN ('cancelled', 'journal_missing')
            """,
            (now, booking_ids),
        )
        return cur.rowcount


def mark_journal_present_by_ids(
    conn: PgConnection,
    *,
    booking_ids: list[int],
    now: datetime,
) -> int:
    if not booking_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET status = CASE
                    WHEN status = 'journal_missing' THEN 'created_in_yclients'
                    ELSE status
                END,
                updated_at = %s
            WHERE id = ANY(%s)
              AND status NOT IN ('cancelled')
            """,
            (now, booking_ids),
        )
        return cur.rowcount


def list_admin_unnotified(
    conn: PgConnection,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM bookings
            WHERE admin_notified_at IS NULL
              AND status NOT IN ('cancelled', 'journal_missing')
            ORDER BY created_at ASC, id ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def mark_admin_notified(
    conn: PgConnection,
    *,
    booking_ids: list[int],
) -> int:
    if not booking_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET admin_notified_at = NOW(),
                updated_at = NOW()
            WHERE id = ANY(%s)
            """,
            (booking_ids,),
        )
        return cur.rowcount


def list_due_reminders(
    conn: PgConnection,
    *,
    reminder_date: date,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.*, u.external_id AS user_external_id, u.channel AS user_channel
            FROM bookings b
            JOIN users u ON u.id = b.user_id
            WHERE b.booking_date = %s
              AND b.payment_status = 'paid'
              AND b.reminder_sent_at IS NULL
              AND b.status NOT IN ('cancelled', 'journal_missing')
            ORDER BY b.booking_time ASC, b.id ASC
            LIMIT %s
            """,
            (reminder_date, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def mark_reminder_sent(
    conn: PgConnection,
    *,
    booking_id: int,
    now: datetime,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET reminder_sent_at = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (now, now, booking_id),
        )


def mark_reminder_response(
    conn: PgConnection,
    *,
    booking_ids: list[int],
    response: str,
    now: datetime,
) -> int:
    if not booking_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET reminder_response = %s,
                reminder_response_at = %s,
                updated_at = %s
            WHERE id = ANY(%s)
              AND status NOT IN ('cancelled', 'journal_missing')
            """,
            (response, now, now, booking_ids),
        )
        return cur.rowcount


def list_waiting_reminder_response_for_user(
    conn: PgConnection,
    *,
    user_id: int,
    now: datetime,
    phone: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    params: list[Any] = [user_id]
    phone_filter = ""
    if phone:
        phone_filter = " OR regexp_replace(b.phone, '\\D', '', 'g') = regexp_replace(%s, '\\D', '', 'g')"
        params.append(phone)
    params.extend([now.date(), limit])
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT b.*, sh.yclients_service_id AS hold_yclients_service_id
            FROM bookings b
            LEFT JOIN slot_holds sh ON sh.id = b.slot_hold_id
            WHERE (b.user_id = %s{phone_filter})
              AND b.reminder_sent_at IS NOT NULL
              AND b.reminder_response IS NULL
              AND b.booking_date >= %s
              AND b.status NOT IN ('cancelled', 'journal_missing')
            ORDER BY b.booking_date ASC, b.booking_time ASC, b.id ASC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def list_paid_without_yclients_record(
    conn: PgConnection,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.*, sh.yclients_service_id AS hold_yclients_service_id
            FROM bookings b
            LEFT JOIN slot_holds sh ON sh.id = b.slot_hold_id
            WHERE b.payment_status = 'paid'
              AND b.yclients_record_id IS NULL
              AND (
                  b.yclients_create_error IS NULL
                  OR b.updated_at < NOW() - INTERVAL '5 minutes'
              )
              AND b.status NOT IN ('cancelled', 'journal_missing')
            ORDER BY b.updated_at ASC, b.id ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def mark_yclients_created(
    conn: PgConnection,
    *,
    booking_id: int,
    yclients_record_id: str,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET yclients_record_id = %s,
                yclients_created_at = NOW(),
                yclients_create_error = NULL,
                status = 'created_in_yclients',
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (yclients_record_id, booking_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def mark_yclients_create_error(
    conn: PgConnection,
    *,
    booking_id: int,
    error: str,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET yclients_create_error = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (error[:1000], booking_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_by_id(conn: PgConnection, *, booking_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.*, sh.yclients_service_id AS hold_yclients_service_id
            FROM bookings b
            LEFT JOIN slot_holds sh ON sh.id = b.slot_hold_id
            WHERE b.id = %s
            LIMIT 1
            """,
            (booking_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def update_schedule(
    conn: PgConnection,
    *,
    booking_id: int,
    booking_date: date,
    booking_time: time,
    duration_minutes: int | None,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bookings
            SET booking_date = %s,
                booking_time = %s,
                duration_minutes = %s,
                yclients_record_id = NULL,
                yclients_created_at = NULL,
                yclients_create_error = NULL,
                status = 'confirmed',
                updated_at = NOW()
            WHERE id = %s
              AND status NOT IN ('cancelled')
            RETURNING *
            """,
            (booking_date, booking_time, duration_minutes, booking_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def update_details(
    conn: PgConnection,
    *,
    booking_id: int,
    guests_count: int | None = None,
    event_format: str | None = None,
    upsell_items: list[str] | None = None,
) -> dict[str, Any] | None:
    fields: list[str] = ["updated_at = NOW()"]
    values: list[Any] = []
    if guests_count is not None:
        fields.append("guests_count = %s")
        values.append(guests_count)
    if event_format is not None:
        fields.append("event_format = %s")
        values.append(event_format)
    if upsell_items is not None:
        fields.append("upsell_items = %s")
        values.append(Json(upsell_items))
    values.append(booking_id)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE bookings
            SET {', '.join(fields)}
            WHERE id = %s
              AND status NOT IN ('cancelled')
            RETURNING *
            """,
            values,
        )
        row = cur.fetchone()
    return dict(row) if row else None
