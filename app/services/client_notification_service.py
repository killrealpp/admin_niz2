from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Mapping

from app.bot.channel_types import DeliveryTarget
from app.bot.notification_router import NotificationDeliveryError, NotificationRouter
from app.db.connection import get_connection
from app.db.repositories import system_logs_repo

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClientNotificationResult:
    delivered: bool
    target: DeliveryTarget | None = None
    reason: str | None = None


async def send_client_text_notification(
    router: NotificationRouter,
    row: Mapping[str, Any],
    text: str,
    *,
    notification_event: str,
    entity_type: str,
    entity_id: Any | None = None,
) -> ClientNotificationResult:
    target = delivery_target_from_user_row(row)
    if target is None:
        reason = "missing user_channel or user_external_id"
        record_client_notification_failure(
            row,
            notification_event=notification_event,
            entity_type=entity_type,
            entity_id=entity_id,
            reason=reason,
        )
        return ClientNotificationResult(False, reason=reason)

    try:
        await router.send_text(target, text)
    except NotificationDeliveryError as exc:
        reason = str(exc)
        record_client_notification_failure(
            row,
            notification_event=notification_event,
            entity_type=entity_type,
            entity_id=entity_id,
            reason=reason,
            exc=exc,
        )
        return ClientNotificationResult(False, target=target, reason=reason)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        record_client_notification_failure(
            row,
            notification_event=notification_event,
            entity_type=entity_type,
            entity_id=entity_id,
            reason=reason,
            exc=exc,
        )
        return ClientNotificationResult(False, target=target, reason=reason)

    return ClientNotificationResult(True, target=target)


def delivery_target_from_user_row(row: Mapping[str, Any]) -> DeliveryTarget | None:
    channel = str(row.get("user_channel") or "").strip()
    external_id = str(row.get("user_external_id") or "").strip()
    chat_id_value = row.get("user_chat_id") or row.get("chat_id")
    chat_id = str(chat_id_value).strip() if chat_id_value else None
    if not channel or not external_id:
        return None
    try:
        return DeliveryTarget(channel=channel, external_id=external_id, chat_id=chat_id)
    except ValueError:
        return None


def record_client_notification_failure(
    row: Mapping[str, Any],
    *,
    notification_event: str,
    entity_type: str,
    entity_id: Any | None,
    reason: str,
    exc: Exception | None = None,
) -> None:
    payload = {
        "notification_event": notification_event,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "user_channel": row.get("user_channel"),
        "user_external_id": row.get("user_external_id"),
    }
    if exc is not None:
        payload["error_type"] = type(exc).__name__
        payload["error"] = str(exc)[:500]

    logger.warning(
        "Client notification delivery failed event=%s entity=%s:%s channel=%s external_id=%s reason=%s",
        notification_event,
        entity_type,
        entity_id,
        row.get("user_channel"),
        row.get("user_external_id"),
        reason,
    )
    with get_connection() as conn:
        system_logs_repo.create(
            conn,
            level="warning",
            event_type="client_notification_delivery_failed",
            message=reason[:1000],
            conversation_id=row.get("conversation_id"),
            payload=payload,
        )


__all__ = [
    "ClientNotificationResult",
    "delivery_target_from_user_row",
    "record_client_notification_failure",
    "send_client_text_notification",
]
