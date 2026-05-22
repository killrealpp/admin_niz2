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
        user, _ = get_or_create_user(
            conn, "telegram", "test_smoke_user", "Smoke Test", now
        )
        conv, _ = get_or_create_conversation(conn, user["id"], "telegram", now, 72)
        msg = messages_repo.create(conn, conv["id"], "system", "db smoke test")
        count = users_repo.find_by_external_id(conn, "telegram", "test_smoke_user")
    print(f"OK user_id={count['id']} conversation_id={conv['id']} message_id={msg['id']}")


if __name__ == "__main__":
    main()
