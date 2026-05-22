import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.ai.ai_orchestrator import summarize_dialog_messages
from app.ai.errors import AIProviderUnavailable
from app.core.config import get_settings
from app.db.connection import get_connection
from app.db.repositories import conversation_summaries_repo, messages_repo

logger = logging.getLogger(__name__)


async def run_message_retention_loop() -> None:
    settings = get_settings()
    if not settings.message_summary_enabled:
        logger.info("Message retention loop disabled")
        return

    interval = max(settings.message_summary_interval_seconds, 300)
    logger.info("Message retention loop started interval=%s", interval)
    while True:
        try:
            result = await asyncio.to_thread(summarize_and_delete_old_messages_once)
            if result["messages"]:
                logger.info(
                    "Message retention summarized conversations=%s messages=%s",
                    result["conversations"],
                    result["messages"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Message retention loop failed")
        await asyncio.sleep(interval)


def summarize_and_delete_old_messages_once() -> dict[str, int]:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    cutoff = now - timedelta(hours=settings.message_summary_after_hours)
    total_conversations = 0
    total_messages = 0

    with get_connection() as conn:
        batches = messages_repo.list_old_conversation_batches(
            conn,
            cutoff=cutoff,
            limit=settings.message_summary_batch_conversations,
        )
        for batch in batches:
            messages = messages_repo.list_until(
                conn,
                conversation_id=batch["conversation_id"],
                cutoff=cutoff,
            )
            if not messages:
                continue
            try:
                summary = summarize_dialog_messages(messages)
            except AIProviderUnavailable:
                logger.warning(
                    "AI unavailable while summarizing conversation_id=%s; using fallback",
                    batch["conversation_id"],
                )
                summary = _fallback_summary(messages)
            conversation_summaries_repo.create(
                conn,
                conversation_id=batch["conversation_id"],
                summary=summary,
                messages_from=messages[0]["created_at"],
                messages_to=messages[-1]["created_at"],
                messages_count=len(messages),
            )
            deleted = messages_repo.delete_ids(conn, [item["id"] for item in messages])
            total_conversations += 1
            total_messages += deleted
    return {"conversations": total_conversations, "messages": total_messages}


def _fallback_summary(messages: list[dict]) -> str:
    parts: list[str] = []
    for item in messages[-12:]:
        sender = item.get("sender") or "unknown"
        text = str(item.get("text") or "").replace("\n", " ")
        parts.append(f"{sender}: {text[:240]}")
    return "Краткая история диалога без AI-сжатия: " + " | ".join(parts)
