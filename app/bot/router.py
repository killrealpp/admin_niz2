from datetime import datetime, timezone
from typing import Any

from aiogram.types import Message

from app.core.constants import CHANNEL_TELEGRAM
from app.services.message_handler import IncomingMessage


def normalize_telegram_message(message: Message) -> IncomingMessage:
    user = message.from_user
    if not user:
        raise ValueError("Telegram message has no from_user")

    text = (message.text or message.caption or "").strip()
    if not text:
        text = "[пустое сообщение]"

    msg_time = message.date
    if msg_time.tzinfo is None:
        msg_time = msg_time.replace(tzinfo=timezone.utc)

    return IncomingMessage(
        channel=CHANNEL_TELEGRAM,
        external_user_id=str(user.id),
        user_name=user.full_name or user.username,
        text=text,
        message_time=msg_time,
        raw_payload={
            "message_id": message.message_id,
            "chat_id": message.chat.id,
            "username": user.username,
        },
    )


def normalize_incoming(channel: str, payload: dict[str, Any]) -> IncomingMessage:
    """Unified entry for future MAX / VK adapters."""
    if channel == CHANNEL_TELEGRAM:
        raise ValueError("Use normalize_telegram_message for Telegram")
    raise NotImplementedError(f"Channel not supported: {channel}")
