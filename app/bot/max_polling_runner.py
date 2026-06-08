from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.bot.channel_types import DeliveryTarget
from app.bot.client_message_processor import process_client_message
from app.bot.max_router import (
    max_delivery_target_from_incoming,
    max_update_type,
    normalize_max_update,
)
from app.core.config import get_settings
from app.integrations.max_client import MaxApiClient, MaxApiError
from app.services.message_handler import IncomingMessage

MAX_POLLING_SMOKE_ERROR = "MAX polling smoke processing failed. Try again later."


class MaxPollingBlocked(RuntimeError):
    pass


@dataclass(slots=True)
class DryRunMaxChannelClient:
    sent_texts: list[str] = field(default_factory=list)
    sent_media_count: int = 0
    typing_count: int = 0

    async def send_text(
        self,
        target: DeliveryTarget,
        text: str,
        **_options: Any,
    ) -> None:
        self.sent_texts.append(text)

    async def send_media(
        self,
        target: DeliveryTarget,
        media_paths: Sequence[Any],
        caption: str | None = None,
        **_options: Any,
    ) -> None:
        self.sent_media_count += 1

    async def send_typing(self, target: DeliveryTarget) -> None:
        self.typing_count += 1

    async def answer_callback(
        self,
        callback_id: str,
        message: str | None = None,
        notification: str | None = None,
    ) -> None:
        return None


async def run_max_dev_polling_smoke(
    *,
    marker: int | None = None,
    limit: int = 10,
    timeout: int = 5,
) -> dict[str, Any]:
    settings = get_settings()
    summary = _base_summary(settings)
    if not settings.max_bot_token.strip():
        return {
            **summary,
            "status": "skipped",
            "reason": "MAX_BOT_TOKEN is not configured",
            "max_configured": False,
        }

    client = MaxApiClient(timeout=max(20.0, float(timeout) + 10.0))
    try:
        client.get_me()
        subscriptions = client.get_subscriptions()
        _ensure_dev_polling_allowed(settings, subscriptions)
        updates_payload = client.get_updates(
            marker=marker,
            limit=limit,
            timeout=timeout,
            types=("message_created",),
        )
    except MaxPollingBlocked as exc:
        return {
            **summary,
            "status": "blocker",
            "reason": str(exc),
            "max_configured": True,
        }
    except MaxApiError as exc:
        return {
            **summary,
            "status": "blocker",
            "reason": str(exc),
            "max_configured": True,
        }

    updates = extract_max_updates(updates_payload)
    update_types = [_update_type(update) for update in updates]
    result = {
        **summary,
        "status": "skipped",
        "reason": "MAX polling returned no updates",
        "max_configured": True,
        "updates_count": len(updates),
        "update_types": update_types,
        "marker": updates_payload.get("marker"),
    }
    if not updates:
        return result

    skipped_update_types: list[str] = []
    normalized: tuple[IncomingMessage, DeliveryTarget] | None = None
    for update in updates:
        normalized = normalize_max_text_update(update)
        if normalized is not None:
            break
        skipped_update_types.append(_update_type(update))

    if normalized is None:
        return {
            **result,
            "reason": "MAX polling returned no text message_created updates",
            "skipped_update_types": skipped_update_types,
        }

    incoming, target = normalized
    channel_client = DryRunMaxChannelClient()
    reply = await process_client_message(
        incoming,
        target,
        channel_client,
        error_text=MAX_POLLING_SMOKE_ERROR,
        send_related_media=False,
        log_context="max dev polling smoke",
    )
    await asyncio.sleep(0)
    if reply is None:
        return {
            **result,
            "status": "blocker",
            "reason": "process_client_message returned no reply",
            "processed_count": 0,
            "sent_text_count": len(channel_client.sent_texts),
            "typing_count": channel_client.typing_count,
            "sent_media_count": channel_client.sent_media_count,
        }

    return {
        **result,
        "status": "ok",
        "reason": None,
        "processed_count": 1,
        "processed_update_type": incoming.raw_payload.get("update_type"),
        "reply_captured": True,
        "reply_length": len(reply),
        "sent_text_count": len(channel_client.sent_texts),
        "sent_text_lengths": [len(text) for text in channel_client.sent_texts],
        "typing_count": channel_client.typing_count,
        "sent_media_count": channel_client.sent_media_count,
    }


def extract_max_updates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    updates = payload.get("updates")
    if isinstance(updates, list):
        return [item for item in updates if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("updates"), list):
        return [item for item in data["updates"] if isinstance(item, dict)]
    return []


def normalize_max_text_update(
    update: dict[str, Any],
) -> tuple[IncomingMessage, DeliveryTarget] | None:
    if _update_type(update) != "message_created":
        return None
    incoming = normalize_max_update(update)
    if incoming is None:
        return None
    incoming.raw_payload["source"] = "max_polling"
    return incoming, max_delivery_target_from_incoming(incoming)


def _ensure_dev_polling_allowed(settings: Any, subscriptions: dict[str, Any]) -> None:
    app_env = settings.app_env.strip().lower()
    if app_env in {"production", "prod"}:
        raise MaxPollingBlocked("MAX polling is forbidden when APP_ENV=production")
    if settings.max_webhook_enabled:
        raise MaxPollingBlocked("MAX polling is forbidden when MAX_WEBHOOK_ENABLED=true")
    if settings.max_mode.strip().lower() != "polling":
        raise MaxPollingBlocked("MAX polling smoke requires MAX_MODE=polling")
    subscription_items = _subscription_items(subscriptions)
    if subscription_items:
        raise MaxPollingBlocked(
            "MAX bot has webhook subscriptions; disable webhook before polling"
        )


def _subscription_items(payload: dict[str, Any]) -> list[Any]:
    subscriptions = payload.get("subscriptions")
    if isinstance(subscriptions, list):
        return subscriptions
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("subscriptions"), list):
        return data["subscriptions"]
    return []


def _base_summary(settings: Any) -> dict[str, Any]:
    return {
        "base_url": settings.max_api_base_url,
        "app_env": settings.app_env,
        "max_mode": settings.max_mode,
        "max_webhook_enabled": settings.max_webhook_enabled,
    }


def _update_type(update: dict[str, Any]) -> str:
    return max_update_type(update)


__all__ = [
    "DryRunMaxChannelClient",
    "MaxPollingBlocked",
    "extract_max_updates",
    "normalize_max_text_update",
    "run_max_dev_polling_smoke",
]
