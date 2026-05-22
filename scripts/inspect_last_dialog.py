"""Print the latest conversation and all of its messages."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import get_connection  # noqa: E402


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM conversations
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            conversation = cur.fetchone()
            if not conversation:
                print("no conversations")
                return
            print("--- conversation ---")
            print(dict(conversation))
            print("--- messages ---")
            cur.execute(
                """
                SELECT id, sender, text, created_at
                FROM messages
                WHERE conversation_id = %s
                ORDER BY id ASC
                """,
                (conversation["id"],),
            )
            for row in cur.fetchall():
                print(dict(row))


if __name__ == "__main__":
    main()
