"""Print safe database status and row counts."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.connection import get_connection  # noqa: E402

TABLES = (
    "users",
    "conversations",
    "messages",
    "conversation_summaries",
    "slot_holds",
    "bookings",
    "yclients_sync_state",
    "yclients_records",
    "resource_busy_intervals",
    "system_logs",
)


def main() -> None:
    settings = get_settings()
    print(
        {
            "host": settings.db_host,
            "port": settings.db_port,
            "db": settings.db_name,
            "user": settings.db_user,
            "sslmode": settings.db_sslmode,
        }
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_database() AS db, current_user AS usr, current_schema() AS schema"
            )
            print(dict(cur.fetchone()))
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            )
            print("tables:", [row["table_name"] for row in cur.fetchall()])
            for table in TABLES:
                cur.execute(f"SELECT count(1) AS total FROM {table}")
                print(f"{table}: {cur.fetchone()['total']}")


if __name__ == "__main__":
    main()
