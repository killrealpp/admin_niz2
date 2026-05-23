"""Quick DB smoke test. Usage: python scripts/test_db.py"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.logger import setup_logging  # noqa: E402
from app.db.connection import get_connection  # noqa: E402
from app.db.repositories import messages_repo, users_repo  # noqa: E402
from app.services.conversation_service import get_or_create_conversation  # noqa: E402
from app.services.user_service import get_or_create_user  # noqa: E402


def main() -> None:
    setup_logging()
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        _cleanup(conn)
        user, _ = get_or_create_user(
            conn, "telegram", "test_smoke_user", "Smoke Test", now
        )
        conv, _ = get_or_create_conversation(conn, user["id"], "telegram", now, 72)
        msg = messages_repo.create(conn, conv["id"], "system", "db smoke test")
        count = users_repo.find_by_external_id(conn, "telegram", "test_smoke_user")
        _cleanup(conn)
    print(f"OK user_id={count['id']} conversation_id={conv['id']} message_id={msg['id']}")


def _cleanup(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE external_id = 'test_smoke_user'")
        user_ids = [row["id"] for row in cur.fetchall()]
        if not user_ids:
            return
        cur.execute("SELECT id FROM conversations WHERE user_id = ANY(%s)", (user_ids,))
        conversation_ids = [row["id"] for row in cur.fetchall()]
        if conversation_ids:
            cur.execute("DELETE FROM waitlist_requests WHERE conversation_id = ANY(%s)", (conversation_ids,))
            cur.execute("DELETE FROM payments WHERE conversation_id = ANY(%s)", (conversation_ids,))
            cur.execute("DELETE FROM bookings WHERE conversation_id = ANY(%s)", (conversation_ids,))
            cur.execute("DELETE FROM slot_holds WHERE conversation_id = ANY(%s)", (conversation_ids,))
            cur.execute("DELETE FROM system_logs WHERE conversation_id = ANY(%s)", (conversation_ids,))
            cur.execute("DELETE FROM messages WHERE conversation_id = ANY(%s)", (conversation_ids,))
            cur.execute("DELETE FROM conversation_summaries WHERE conversation_id = ANY(%s)", (conversation_ids,))
            cur.execute("DELETE FROM conversations WHERE id = ANY(%s)", (conversation_ids,))
        cur.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))


if __name__ == "__main__":
    main()
