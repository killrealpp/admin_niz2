"""Read-only live health report for release and production smoke checks."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.connection import get_connection  # noqa: E402


RUNTIME_TABLES = (
    "users",
    "conversations",
    "messages",
    "conversation_summaries",
    "slot_holds",
    "bookings",
    "payments",
    "waitlist_requests",
    "system_logs",
    "yclients_sync_state",
    "yclients_records",
    "resource_busy_intervals",
    "webhook_events",
)

REQUIRED_TABLES = (
    "users",
    "conversations",
    "messages",
    "slot_holds",
    "bookings",
    "payments",
    "system_logs",
    "yclients_sync_state",
    "yclients_records",
    "resource_busy_intervals",
)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _fetch_all(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def _fetch_one(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return dict(row) if row else None


def _existing_tables(conn: Any) -> set[str]:
    rows = _fetch_all(
        conn,
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        """,
    )
    return {str(row["table_name"]) for row in rows}


def _table_counts(conn: Any, existing_tables: set[str]) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for table in RUNTIME_TABLES:
        if table not in existing_tables:
            counts[table] = None
            continue
        row = _fetch_one(conn, f"SELECT count(1) AS total FROM {table}")
        counts[table] = int(row["total"]) if row else 0
    return counts


def _yclients_sync(conn: Any, existing_tables: set[str]) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    max_age_seconds = max(int(settings.yclients_sync_interval_seconds) * 12, 600)
    if "yclients_sync_state" not in existing_tables:
        return {
            "fresh": False,
            "reason": "missing_table",
            "max_age_seconds": max_age_seconds,
        }

    row = _fetch_one(
        conn,
        """
        SELECT sync_name,
               last_started_at,
               last_finished_at,
               last_success_at,
               last_error,
               records_seen,
               records_upserted,
               updated_at
        FROM yclients_sync_state
        WHERE sync_name = 'yclients_records'
        """,
    )
    if not row:
        return {
            "sync_name": "yclients_records",
            "fresh": False,
            "reason": "missing_sync_state",
            "max_age_seconds": max_age_seconds,
        }

    last_success_at = row.get("last_success_at")
    age_seconds = None
    if isinstance(last_success_at, datetime):
        if last_success_at.tzinfo is None:
            last_success_at = last_success_at.replace(tzinfo=now.tzinfo)
        age_seconds = max(0, int((now - last_success_at.astimezone(now.tzinfo)).total_seconds()))

    fresh = age_seconds is not None and age_seconds <= max_age_seconds and not row.get("last_error")
    return {
        "sync_name": row.get("sync_name"),
        "fresh": fresh,
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "last_success_at": row.get("last_success_at"),
        "last_started_at": row.get("last_started_at"),
        "last_finished_at": row.get("last_finished_at"),
        "records_seen": row.get("records_seen"),
        "records_upserted": row.get("records_upserted"),
        "last_error": row.get("last_error"),
    }


def _active_holds(conn: Any, existing_tables: set[str], limit: int) -> dict[str, Any]:
    if "slot_holds" not in existing_tables:
        return {"total": None, "items": []}
    count = _fetch_one(
        conn,
        """
        SELECT count(1) AS total
        FROM slot_holds
        WHERE status = 'active'
          AND expires_at > NOW()
        """,
    )
    items = _fetch_all(
        conn,
        """
        SELECT id,
               conversation_id,
               user_id,
               service_type,
               yclients_service_id,
               yclients_staff_id,
               slot_date,
               slot_time,
               duration_minutes,
               expires_at,
               created_at
        FROM slot_holds
        WHERE status = 'active'
          AND expires_at > NOW()
        ORDER BY expires_at ASC, id ASC
        LIMIT %s
        """,
        (limit,),
    )
    return {"total": int(count["total"]) if count else 0, "items": items}


def _pending_payments(conn: Any, existing_tables: set[str], limit: int) -> dict[str, Any]:
    if "payments" not in existing_tables:
        return {"total": None, "items": []}
    count = _fetch_one(
        conn,
        """
        SELECT count(1) AS total
        FROM payments
        WHERE status IN ('pending', 'waiting_for_capture')
        """,
    )
    items = _fetch_all(
        conn,
        """
        SELECT id,
               conversation_id,
               user_id,
               provider,
               provider_payment_id,
               amount,
               currency,
               status,
               created_at,
               updated_at
        FROM payments
        WHERE status IN ('pending', 'waiting_for_capture')
        ORDER BY created_at ASC, id ASC
        LIMIT %s
        """,
        (limit,),
    )
    return {"total": int(count["total"]) if count else 0, "items": items}


def _paid_payments_without_notification(conn: Any, existing_tables: set[str], limit: int) -> dict[str, Any]:
    if "payments" not in existing_tables:
        return {"total": None, "items": []}
    count = _fetch_one(
        conn,
        """
        SELECT count(1) AS total
        FROM payments
        WHERE status = 'paid'
          AND payment_notified_at IS NULL
        """,
    )
    items = _fetch_all(
        conn,
        """
        SELECT id,
               conversation_id,
               user_id,
               provider,
               provider_payment_id,
               amount,
               currency,
               paid_at,
               updated_at,
               booking_ids
        FROM payments
        WHERE status = 'paid'
          AND payment_notified_at IS NULL
        ORDER BY paid_at ASC NULLS LAST, updated_at ASC, id ASC
        LIMIT %s
        """,
        (limit,),
    )
    return {"total": int(count["total"]) if count else 0, "items": items}


def _paid_bookings_without_admin_notification(conn: Any, existing_tables: set[str], limit: int) -> dict[str, Any]:
    if "bookings" not in existing_tables:
        return {"total": None, "items": []}
    count = _fetch_one(
        conn,
        """
        SELECT count(1) AS total
        FROM bookings
        WHERE payment_status = 'paid'
          AND admin_notified_at IS NULL
          AND status NOT IN ('cancelled', 'journal_missing')
        """,
    )
    items = _fetch_all(
        conn,
        """
        SELECT id,
               conversation_id,
               user_id,
               service_type,
               booking_date,
               booking_time,
               duration_minutes,
               status,
               payment_status,
               yclients_record_id,
               created_at,
               updated_at
        FROM bookings
        WHERE payment_status = 'paid'
          AND admin_notified_at IS NULL
          AND status NOT IN ('cancelled', 'journal_missing')
        ORDER BY booking_date ASC, booking_time ASC, id ASC
        LIMIT %s
        """,
        (limit,),
    )
    return {"total": int(count["total"]) if count else 0, "items": items}


def _journal_or_yclients_errors(conn: Any, existing_tables: set[str], limit: int) -> dict[str, Any]:
    if "bookings" not in existing_tables:
        return {"total": None, "items": []}
    count = _fetch_one(
        conn,
        """
        SELECT count(1) AS total
        FROM bookings
        WHERE status = 'journal_missing'
           OR yclients_create_error IS NOT NULL
        """,
    )
    items = _fetch_all(
        conn,
        """
        SELECT id,
               conversation_id,
               user_id,
               service_type,
               booking_date,
               booking_time,
               duration_minutes,
               status,
               payment_status,
               yclients_record_id,
               yclients_create_error,
               updated_at
        FROM bookings
        WHERE status = 'journal_missing'
           OR yclients_create_error IS NOT NULL
        ORDER BY updated_at ASC, id ASC
        LIMIT %s
        """,
        (limit,),
    )
    return {"total": int(count["total"]) if count else 0, "items": items}


def _pending_refunds(conn: Any, existing_tables: set[str], limit: int) -> dict[str, Any]:
    if "system_logs" not in existing_tables:
        return {"total": None, "items": []}
    count = _fetch_one(
        conn,
        """
        SELECT count(1) AS total
        FROM system_logs
        WHERE event_type = 'refund_required'
          AND admin_notified_at IS NULL
        """,
    )
    items = _fetch_all(
        conn,
        """
        SELECT id,
               conversation_id,
               level,
               event_type,
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
    )
    return {"total": int(count["total"]) if count else 0, "items": items}


def _active_handoffs(conn: Any, existing_tables: set[str], limit: int) -> dict[str, Any]:
    if "users" not in existing_tables:
        return {"total": None, "items": []}
    count = _fetch_one(
        conn,
        """
        SELECT count(1) AS total
        FROM users
        WHERE handoff_until IS NOT NULL
          AND handoff_until > NOW()
        """,
    )
    items = _fetch_all(
        conn,
        """
        SELECT id,
               channel,
               external_id,
               name,
               phone,
               handoff_until,
               handoff_reason,
               handoff_notified_at,
               updated_at
        FROM users
        WHERE handoff_until IS NOT NULL
          AND handoff_until > NOW()
        ORDER BY updated_at DESC, id DESC
        LIMIT %s
        """,
        (limit,),
    )
    return {"total": int(count["total"]) if count else 0, "items": items}


def _recent_system_activity(conn: Any, existing_tables: set[str], limit: int) -> dict[str, Any]:
    if "system_logs" not in existing_tables:
        return {"recent_errors": [], "recent_logs": []}
    recent_errors = _fetch_all(
        conn,
        """
        SELECT id,
               conversation_id,
               level,
               event_type,
               message,
               payload,
               created_at,
               admin_notified_at
        FROM system_logs
        WHERE lower(level) IN ('error', 'critical')
           OR lower(event_type) LIKE '%%error%%'
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (limit,),
    )
    recent_logs = _fetch_all(
        conn,
        """
        SELECT id,
               conversation_id,
               level,
               event_type,
               message,
               created_at,
               admin_notified_at
        FROM system_logs
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (limit,),
    )
    return {"recent_errors": recent_errors, "recent_logs": recent_logs}


def build_report(limit: int) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    blockers: list[str] = []
    warnings: list[str] = []

    with get_connection() as conn:
        conn.set_session(readonly=True, autocommit=False)
        db_identity = _fetch_one(
            conn,
            """
            SELECT current_database() AS db,
                   current_user AS usr,
                   current_schema() AS schema
            """,
        )
        existing_tables = _existing_tables(conn)
        missing_required = [table for table in REQUIRED_TABLES if table not in existing_tables]
        blockers.extend(f"missing_table:{table}" for table in missing_required)

        yclients_sync = _yclients_sync(conn, existing_tables)
        if not yclients_sync.get("fresh"):
            blockers.append("yclients_sync_not_fresh")

        active_holds = _active_holds(conn, existing_tables, limit)
        if active_holds["total"]:
            warnings.append("active_holds_present")

        pending_payments = _pending_payments(conn, existing_tables, limit)
        if pending_payments["total"]:
            warnings.append("pending_payments_present")

        paid_payments_unnotified = _paid_payments_without_notification(conn, existing_tables, limit)
        if paid_payments_unnotified["total"]:
            blockers.append("paid_payments_without_client_notification")

        paid_bookings_admin_unnotified = _paid_bookings_without_admin_notification(conn, existing_tables, limit)
        if paid_bookings_admin_unnotified["total"]:
            blockers.append("paid_bookings_without_admin_notification")

        journal_or_yclients_errors = _journal_or_yclients_errors(conn, existing_tables, limit)
        if journal_or_yclients_errors["total"]:
            blockers.append("booking_journal_or_yclients_errors")

        pending_refunds = _pending_refunds(conn, existing_tables, limit)
        if pending_refunds["total"]:
            blockers.append("pending_refund_required")

        active_handoffs = _active_handoffs(conn, existing_tables, limit)
        if active_handoffs["total"]:
            warnings.append("active_handoffs_present")

        system_activity = _recent_system_activity(conn, existing_tables, limit)
        if system_activity["recent_errors"]:
            warnings.append("recent_system_errors_present")

        return {
            "status": "blocker" if blockers else "ok",
            "generated_at": now.isoformat(),
            "db": {
                "ok": True,
                "host": settings.db_host,
                "port": settings.db_port,
                "name": settings.db_name,
                "user": settings.db_user,
                "sslmode": settings.db_sslmode,
                "identity": db_identity,
            },
            "blockers": blockers,
            "warnings": warnings,
            "yclients_sync": yclients_sync,
            "runtime_counts": _table_counts(conn, existing_tables),
            "active_holds": active_holds,
            "pending_payments": pending_payments,
            "paid_payments_without_client_notification": paid_payments_unnotified,
            "paid_bookings_without_admin_notification": paid_bookings_admin_unnotified,
            "bookings_with_journal_or_yclients_errors": journal_or_yclients_errors,
            "pending_refund_required": pending_refunds,
            "active_handoffs": active_handoffs,
            "system_logs": system_activity,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only live health report.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum rows per detail section.")
    args = parser.parse_args()

    try:
        report = build_report(max(1, args.limit))
    except Exception as exc:
        report = {
            "status": "blocker",
            "db": {"ok": False},
            "blockers": ["db_health_report_failed"],
            "error": str(exc),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
        raise SystemExit(1)

    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
