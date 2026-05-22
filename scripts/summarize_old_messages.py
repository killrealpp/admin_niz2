"""Summarize messages older than 7 days and remove the raw rows."""

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.ai_orchestrator import summarize_dialog_messages  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.logger import setup_logging  # noqa: E402
from app.db.connection import get_connection  # noqa: E402
from app.db.repositories import conversation_summaries_repo, messages_repo  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--older-than-days", type=int, default=7)
    parser.add_argument("--limit-conversations", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    setup_logging()
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    cutoff = now - timedelta(days=args.older_than_days)

    total_messages = 0
    total_conversations = 0
    with get_connection() as conn:
        batches = messages_repo.list_old_conversation_batches(
            conn,
            cutoff=cutoff,
            limit=args.limit_conversations,
        )
        for batch in batches:
            messages = messages_repo.list_until(
                conn,
                conversation_id=batch["conversation_id"],
                cutoff=cutoff,
            )
            if not messages:
                continue
            summary = summarize_dialog_messages(messages)
            total_conversations += 1
            total_messages += len(messages)
            print(
                f"conversation={batch['conversation_id']} messages={len(messages)} "
                f"summary={summary[:200]}"
            )
            if args.dry_run:
                continue
            conversation_summaries_repo.create(
                conn,
                conversation_id=batch["conversation_id"],
                summary=summary,
                messages_from=messages[0]["created_at"],
                messages_to=messages[-1]["created_at"],
                messages_count=len(messages),
            )
            messages_repo.delete_ids(conn, [item["id"] for item in messages])

    print(f"OK: conversations={total_conversations} messages={total_messages} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
