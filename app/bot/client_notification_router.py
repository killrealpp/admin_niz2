from __future__ import annotations

from typing import Any

from aiogram import Bot

from app.bot.max_channel_client import MaxChannelClient
from app.bot.notification_router import NotificationRouter
from app.bot.telegram_channel_client import TelegramChannelClient
from app.core.config import get_settings
from app.core.constants import CHANNEL_MAX, CHANNEL_TELEGRAM


def build_client_notification_router(bot: Bot | None = None) -> NotificationRouter:
    settings = get_settings()
    clients: dict[str, Any] = {}
    if bot is not None:
        clients[CHANNEL_TELEGRAM] = TelegramChannelClient(bot)
    if settings.max_bot_token:
        clients[CHANNEL_MAX] = MaxChannelClient()
    return NotificationRouter(clients)


def ensure_client_notification_router(
    notifier: NotificationRouter | Bot,
) -> NotificationRouter:
    if isinstance(notifier, NotificationRouter):
        return notifier
    return build_client_notification_router(notifier)


__all__ = ["build_client_notification_router", "ensure_client_notification_router"]
