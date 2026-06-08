from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any

from app.bot.channel_types import DeliveryTarget
from app.core.constants import CHANNEL_MAX
from app.services.message_handler import IncomingMessage

logger = logging.getLogger(__name__)


def normalize_max_update(update: dict[str, Any]) -> IncomingMessage | None:
    update_type = max_update_type(update)
    if update_type == "message_created":
        return _normalize_message_created(update, update_type)
    if update_type == "bot_started":
        return _normalize_bot_started(update, update_type)
    logger.debug("Ignoring unsupported MAX update_type=%s", update_type)
    return None


def max_delivery_target_from_incoming(incoming: IncomingMessage) -> DeliveryTarget:
    return DeliveryTarget(
        channel=CHANNEL_MAX,
        external_id=incoming.external_user_id,
        chat_id=_string_value(incoming.raw_payload, "chat_id"),
    )


def max_delivery_target_from_update(update: dict[str, Any]) -> DeliveryTarget | None:
    message = _event_payload(update)
    user = _user_payload(update, message)
    external_user_id = _external_user_id(update, message, user)
    if not external_user_id:
        return None
    return DeliveryTarget(
        channel=CHANNEL_MAX,
        external_id=external_user_id,
        chat_id=_chat_id(update, message),
    )


def max_message_id_from_update(update: dict[str, Any]) -> str | None:
    message = _event_payload(update)
    return _message_id(update, message)


def max_message_payload(update: dict[str, Any]) -> dict[str, Any]:
    return _message_payload(update)


def normalize_max_transcribed_message(
    update: dict[str, Any],
    transcribed_text: str,
    *,
    content_type: str = "voice",
) -> IncomingMessage | None:
    text = transcribed_text.strip()
    if not text:
        return None
    update_type = max_update_type(update)
    message = _message_payload(update)
    user = _user_payload(update, message)
    external_user_id = _external_user_id(update, message, user)
    if not external_user_id:
        logger.debug("Ignoring MAX transcribed message without user id")
        return None
    chat_id = _chat_id(update, message)
    raw_payload = _raw_payload(
        update,
        update_type=update_type,
        timestamp=_timestamp_value(update, message),
        chat_id=chat_id,
        message_id=_message_id(update, message),
        payload=None,
    )
    raw_payload["content_type"] = content_type
    raw_payload["transcribed_text"] = text
    return IncomingMessage(
        channel=CHANNEL_MAX,
        external_user_id=external_user_id,
        user_name=_user_name(user),
        text=text,
        message_time=_message_time(update, message),
        raw_payload=raw_payload,
    )


def max_update_type(update: dict[str, Any]) -> str:
    return str(
        update.get("update_type")
        or update.get("type")
        or update.get("event_type")
        or "unknown"
    )


def _normalize_message_created(
    update: dict[str, Any],
    update_type: str,
) -> IncomingMessage | None:
    message = _message_payload(update)
    text = _message_text(update, message)
    if not text:
        logger.debug("Ignoring MAX message_created without text")
        return None

    user = _user_payload(update, message)
    external_user_id = _external_user_id(update, message, user)
    if not external_user_id:
        logger.debug("Ignoring MAX message_created without user id")
        return None

    chat_id = _chat_id(update, message)
    return IncomingMessage(
        channel=CHANNEL_MAX,
        external_user_id=external_user_id,
        user_name=_user_name(user),
        text=text,
        message_time=_message_time(update, message),
        raw_payload=_raw_payload(
            update,
            update_type=update_type,
            timestamp=_timestamp_value(update, message),
            chat_id=chat_id,
            message_id=_message_id(update, message),
            payload=None,
        ),
    )


def _normalize_bot_started(
    update: dict[str, Any],
    update_type: str,
) -> IncomingMessage | None:
    event = update.get("bot_started")
    if not isinstance(event, dict):
        event = update

    user = _user_payload(update, event)
    external_user_id = _external_user_id(update, event, user)
    if not external_user_id:
        logger.debug("Ignoring MAX bot_started without user id")
        return None

    payload = _start_payload(update, event)
    text = f"/start {payload}" if payload else "/start"
    return IncomingMessage(
        channel=CHANNEL_MAX,
        external_user_id=external_user_id,
        user_name=_user_name(user),
        text=text,
        message_time=_message_time(update, event),
        raw_payload=_raw_payload(
            update,
            update_type=update_type,
            timestamp=_timestamp_value(update, event),
            chat_id=_chat_id(update, event),
            message_id=_message_id(update, event),
            payload=payload,
        ),
    )


def _raw_payload(
    update: dict[str, Any],
    *,
    update_type: str,
    timestamp: Any,
    chat_id: str | None,
    message_id: str | None,
    payload: str | None,
) -> dict[str, Any]:
    return {
        "source": "max",
        "update_type": update_type,
        "timestamp": timestamp,
        "chat_id": chat_id,
        "message_id": message_id,
        "payload": payload,
        "update": copy.deepcopy(update),
    }


def _message_payload(update: dict[str, Any]) -> dict[str, Any]:
    message = update.get("message")
    if isinstance(message, dict):
        return message
    message_created = update.get("message_created")
    if isinstance(message_created, dict):
        return message_created
    return update


def _event_payload(update: dict[str, Any]) -> dict[str, Any]:
    if max_update_type(update) == "bot_started":
        event = update.get("bot_started")
        if isinstance(event, dict):
            return event
    return _message_payload(update)


def _message_text(update: dict[str, Any], message: dict[str, Any]) -> str:
    body = message.get("body")
    if isinstance(body, dict):
        text = body.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    if isinstance(body, str) and body.strip():
        return body.strip()
    for source in (message, update):
        text = source.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _user_payload(
    update: dict[str, Any],
    message: dict[str, Any],
) -> dict[str, Any]:
    for source in (message, update):
        for key in ("sender", "user", "author"):
            value = source.get(key)
            if isinstance(value, dict):
                return value
    return {}


def _external_user_id(
    update: dict[str, Any],
    message: dict[str, Any],
    user: dict[str, Any],
) -> str | None:
    return (
        _string_value(user, "user_id", "id")
        or _string_value(message, "user_id", "sender_id")
        or _string_value(update, "user_id", "sender_id")
    )


def _string_value(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _user_name(user: dict[str, Any]) -> str | None:
    direct = _string_value(user, "full_name", "name")
    if direct:
        return direct
    first_name = _string_value(user, "first_name")
    last_name = _string_value(user, "last_name")
    if first_name and last_name:
        return f"{first_name} {last_name}"
    return first_name or _string_value(user, "username")


def _chat_id(update: dict[str, Any], message: dict[str, Any]) -> str | None:
    for source in (update, message):
        value = _string_value(source, "chat_id")
        if value:
            return value
        chat = source.get("chat")
        if isinstance(chat, dict):
            value = _string_value(chat, "chat_id", "id")
            if value:
                return value
        recipient = source.get("recipient")
        if isinstance(recipient, dict):
            value = _string_value(recipient, "chat_id", "id")
            if value:
                return value
    return None


def _message_id(update: dict[str, Any], message: dict[str, Any]) -> str | None:
    return _string_value(message, "message_id", "mid", "id") or _string_value(
        update,
        "message_id",
        "mid",
        "id",
    )


def _start_payload(update: dict[str, Any], event: dict[str, Any]) -> str | None:
    return _string_value(
        event,
        "payload",
        "start_payload",
        "deep_link_payload",
    ) or _string_value(
        update,
        "payload",
        "start_payload",
        "deep_link_payload",
    )


def _timestamp_value(update: dict[str, Any], message: dict[str, Any]) -> Any:
    return (
        message.get("timestamp")
        or update.get("timestamp")
        or message.get("created_at")
        or update.get("created_at")
        or message.get("time")
        or update.get("time")
    )


def _message_time(update: dict[str, Any], message: dict[str, Any]) -> datetime:
    value = _timestamp_value(update, message)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            value = int(stripped)
        else:
            parsed = _parse_datetime_string(stripped)
            if parsed is not None:
                return parsed
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1_000_000_000_000:
            timestamp = timestamp / 1000.0
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            pass
    return datetime.now(timezone.utc)


def _parse_datetime_string(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "max_delivery_target_from_incoming",
    "max_delivery_target_from_update",
    "max_message_id_from_update",
    "max_message_payload",
    "max_update_type",
    "normalize_max_transcribed_message",
    "normalize_max_update",
]
