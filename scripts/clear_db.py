"""Clear all application data while keeping the database schema."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import get_connection  # noqa: E402

TABLES = (
    "system_logs",
    "conversation_summaries",
    "resource_busy_intervals",
    "yclients_records",
    "yclients_sync_state",
    "bookings",
    "slot_holds",
    "messages",
    "conversations",
    "users",
)


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE "
                + ", ".join(TABLES)
                + " RESTART IDENTITY CASCADE"
            )
            for table in reversed(TABLES):
                cur.execute(f"SELECT count(1) AS total FROM {table}")
                print(f"{table}: {cur.fetchone()['total']}")


if __name__ == "__main__":
    main()
