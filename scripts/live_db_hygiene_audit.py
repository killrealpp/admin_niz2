"""Read-only audit for live DB artifacts after regression runs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import get_connection  # noqa: E402


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _fetch(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def run_audit(limit: int) -> dict[str, list[dict[str, Any]]]:
    with get_connection() as conn:
        conn.set_session(readonly=True, autocommit=False)
        return {
            "active_bot_booking_interval_without_active_booking": _fetch(
                conn,
                """
                SELECT
                    r.id,
                    r.service_type,
                    r.yclients_staff_id,
                    r.source,
                    r.source_record_id,
                    r.start_at,
                    r.end_at,
                    r.status
                FROM resource_busy_intervals r
                LEFT JOIN bookings b
                  ON (
                      b.id::text = r.source_record_id
                      OR COALESCE(b.yclients_record_id, '') = r.source_record_id
                  )
                 AND b.status NOT IN ('cancelled', 'journal_missing')
                WHERE r.source = 'bot_booking'
                  AND r.status = 'active'
                  AND b.id IS NULL
                ORDER BY r.start_at ASC, r.id ASC
                LIMIT %s
                """,
                (limit,),
            ),
            "paid_cancelled_refundable_without_refund_required": _fetch(
                conn,
                """
                SELECT
                    b.id,
                    b.conversation_id,
                    b.service_type,
                    b.booking_date,
                    b.booking_time,
                    b.status,
                    b.payment_status,
                    b.client_name,
                    b.phone
                FROM bookings b
                WHERE b.status = 'cancelled'
                  AND b.payment_status = 'paid'
                  AND b.booking_date >= CURRENT_DATE + INTERVAL '7 days'
                  AND NOT (
                      b.yclients_record_id IS NULL
                      AND COALESCE(b.yclients_create_error, '') ILIKE %s
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM system_logs sl
                      WHERE sl.event_type = 'refund_required'
                        AND sl.payload->>'booking_id' = b.id::text
                  )
                ORDER BY b.booking_date ASC, b.id ASC
                LIMIT %s
                """,
                ("%Archived local test paid booking%", limit),
            ),
            "paid_payment_without_client_notification_marker": _fetch(
                conn,
                """
                SELECT
                    p.id,
                    p.conversation_id,
                    p.user_id,
                    p.provider,
                    p.amount,
                    p.status,
                    p.paid_at,
                    p.payment_notified_at,
                    p.booking_ids
                FROM payments p
                WHERE p.status = 'paid'
                  AND p.payment_notified_at IS NULL
                ORDER BY p.paid_at ASC NULLS LAST, p.updated_at ASC, p.id ASC
                LIMIT %s
                """,
                (limit,),
            ),
            "waitlist_rows_left_by_regression_users": _fetch(
                conn,
                """
                SELECT
                    wr.id,
                    wr.conversation_id,
                    wr.user_id,
                    u.external_id,
                    wr.service_type,
                    wr.desired_date,
                    wr.status,
                    wr.notified_at,
                    wr.updated_at
                FROM waitlist_requests wr
                JOIN users u ON u.id = wr.user_id
                WHERE u.external_id LIKE %s
                ORDER BY wr.updated_at DESC, wr.id DESC
                LIMIT %s
                """,
                ("local_regression_%", limit),
            ),
            "refund_required_without_admin_notified_at": _fetch(
                conn,
                """
                SELECT
                    id,
                    conversation_id,
                    level,
                    message,
                    payload,
                    created_at,
                    admin_notified_at
                FROM system_logs
                WHERE event_type = 'refund_required'
                  AND admin_notified_at IS NULL
                ORDER BY created_at ASC, id ASC
                LIMIT %s
                """,
                (limit,),
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only live DB hygiene audit.")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    report = run_audit(args.limit)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))

    problematic = {name: rows for name, rows in report.items() if rows}
    if problematic:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
