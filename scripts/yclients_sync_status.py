"""Print YCLIENTS local sync freshness diagnostics."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.connection import get_connection  # noqa: E402


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Show YCLIENTS sync-state freshness.")
    parser.add_argument("--strict", action="store_true", help="Exit with code 1 when sync is stale or missing.")
    args = parser.parse_args()

    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    max_age_seconds = max(int(settings.yclients_sync_interval_seconds) * 12, 600)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
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
                """
            )
            row = cur.fetchone()

    if not row:
        print(
            {
                "sync_name": "yclients_records",
                "fresh": False,
                "reason": "missing_sync_state",
                "max_age_seconds": max_age_seconds,
            }
        )
        if args.strict:
            raise SystemExit(1)
        return

    last_success_at = row.get("last_success_at")
    if isinstance(last_success_at, datetime):
        if last_success_at.tzinfo is None:
            last_success_at = last_success_at.replace(tzinfo=now.tzinfo)
        age_seconds = max(0, int((now - last_success_at.astimezone(now.tzinfo)).total_seconds()))
    else:
        age_seconds = None

    fresh = age_seconds is not None and age_seconds <= max_age_seconds and not row.get("last_error")
    payload = {
        "sync_name": row.get("sync_name"),
        "fresh": fresh,
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "last_success_at": _iso(row.get("last_success_at")),
        "last_started_at": _iso(row.get("last_started_at")),
        "last_finished_at": _iso(row.get("last_finished_at")),
        "records_seen": row.get("records_seen"),
        "records_upserted": row.get("records_upserted"),
        "last_error": row.get("last_error"),
    }
    print(payload)
    if args.strict and not fresh:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
