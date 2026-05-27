"""Dry-run first cleanup for bot-created test records in YCLIENTS.

The script is intentionally conservative:
- by default it only lists candidates;
- --apply is required for deletion;
- at least one explicit selector is required unless --all-bot-bookings is used.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.connection import get_connection  # noqa: E402
from app.db.repositories import bookings_repo  # noqa: E402
from app.services.dialog.booking_texts import booking_object_title  # noqa: E402
from app.services.yclients_record_service import delete_yclients_record_for_booking  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="List/delete bot-created test records from YCLIENTS.")
    parser.add_argument("--apply", action="store_true", help="Actually delete selected records.")
    parser.add_argument("--phone", action="append", default=[], help="Client phone to include. Can be repeated.")
    parser.add_argument("--external-id", action="append", default=[], help="Exact Telegram external_id to include.")
    parser.add_argument("--external-id-prefix", action="append", default=["local_regression_"], help="External id prefix to include.")
    parser.add_argument("--name-contains", action="append", default=[], help="Case-insensitive client/user name fragment.")
    parser.add_argument("--all-bot-bookings", action="store_true", help="Include every local bot booking with yclients_record_id.")
    args = parser.parse_args()

    if not args.all_bot_bookings and not any([args.phone, args.external_id, args.external_id_prefix, args.name_contains]):
        raise SystemExit("Refusing to run without selectors. Use --phone/--external-id/--name-contains or --all-bot-bookings.")

    candidates = _load_candidates(args)
    print(f"Candidates: {len(candidates)}")
    for item in candidates:
        print(
            "#{} | YCLIENTS {} | {} | {} {} {} | tg={} | phone={} | name={}".format(
                item["id"],
                item.get("yclients_record_id") or "-",
                booking_object_title(item),
                item.get("booking_date"),
                str(item.get("booking_time") or "")[:5],
                item.get("status"),
                item.get("external_id"),
                item.get("phone"),
                item.get("client_name") or item.get("user_name"),
            )
        )

    if not args.apply:
        print("Dry-run only. Add --apply after reviewing the list.")
        return

    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    deleted = 0
    failed = 0
    with get_connection() as conn:
        for item in candidates:
            ok = delete_yclients_record_for_booking(conn, booking=item)
            if ok:
                bookings_repo.cancel_by_id(conn, booking_id=int(item["id"]), now=now)
                deleted += 1
            else:
                failed += 1
    print(f"Deleted: {deleted}, failed: {failed}")


def _load_candidates(args: argparse.Namespace) -> list[dict]:
    phones = {_digits(phone) for phone in args.phone if _digits(phone)}
    external_ids = {str(item) for item in args.external_id if str(item).strip()}
    prefixes = [str(item) for item in args.external_id_prefix if str(item)]
    name_fragments = [str(item).lower() for item in args.name_contains if str(item).strip()]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    b.*,
                    u.external_id,
                    u.name AS user_name
                FROM bookings b
                JOIN users u ON u.id = b.user_id
                WHERE b.yclients_record_id IS NOT NULL
                  AND b.status NOT IN ('cancelled', 'journal_missing')
                ORDER BY b.created_at DESC, b.id DESC
                """
            )
            rows = [dict(row) for row in cur.fetchall()]

    if args.all_bot_bookings:
        return rows

    result: list[dict] = []
    for row in rows:
        phone = _digits(row.get("phone"))
        external_id = str(row.get("external_id") or "")
        name = f"{row.get('client_name') or ''} {row.get('user_name') or ''}".lower()
        if phones and phone in phones:
            result.append(row)
            continue
        if external_id in external_ids:
            result.append(row)
            continue
        if prefixes and any(external_id.startswith(prefix) for prefix in prefixes):
            result.append(row)
            continue
        if name_fragments and any(fragment in name for fragment in name_fragments):
            result.append(row)
    return result


def _digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


if __name__ == "__main__":
    main()
