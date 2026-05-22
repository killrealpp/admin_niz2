from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import get_connection
from app.services.admin_notification_service import format_admin_bookings_message


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT conversation_id
                FROM bookings
                WHERE status NOT IN ('cancelled')
                ORDER BY id DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        if not row:
            print("Активных заявок нет.")
            return
        print(format_admin_bookings_message(conn, conversation_id=row["conversation_id"]))


if __name__ == "__main__":
    main()
