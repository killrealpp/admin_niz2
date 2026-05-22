from __future__ import annotations

import logging

from aiogram import Bot

from app.core.config import get_settings
from app.db.connection import get_connection
from app.db.repositories import bookings_repo
from app.services.admin_notification_service import format_admin_bookings_message

logger = logging.getLogger(__name__)


async def notify_admin_about_new_bookings(bot: Bot) -> int:
    settings = get_settings()
    chat_id = settings.admin_telegram_chat_id.strip()
    if not chat_id:
        return 0

    with get_connection() as conn:
        rows = bookings_repo.list_admin_unnotified(conn)

    conversation_ids = sorted({row["conversation_id"] for row in rows})
    sent = 0
    for conversation_id in conversation_ids:
        with get_connection() as conn:
            text = format_admin_bookings_message(conn, conversation_id=conversation_id)
            bookings = bookings_repo.list_active_for_conversation(
                conn,
                conversation_id=conversation_id,
            )
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception(
                "Failed to notify admin chat_id=%s conversation_id=%s",
                chat_id,
                conversation_id,
            )
            continue
        with get_connection() as conn:
            bookings_repo.mark_admin_notified(
                conn,
                booking_ids=[booking["id"] for booking in bookings],
            )
        sent += 1
    return sent


async def notify_admin_text(bot: Bot, text: str) -> bool:
    settings = get_settings()
    chat_id = settings.admin_telegram_chat_id.strip()
    if not chat_id:
        return False
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        logger.exception("Failed to send admin text chat_id=%s", chat_id)
        return False
    return True
