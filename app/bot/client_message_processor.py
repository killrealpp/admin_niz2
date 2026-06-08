from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from app.bot.channel_client import ChannelClient
from app.bot.channel_types import DeliveryTarget
from app.core.config import get_settings
from app.db.connection import get_connection
from app.db.repositories import conversations_repo, users_repo
from app.services.media_service import (
    is_explicit_photo_request,
    media_for_client_message,
    missing_media_titles_for_client_message,
)
from app.services.message_handler import IncomingMessage, handle_incoming

logger = logging.getLogger(__name__)
MEDIA_SEND_TIMEOUT_SECONDS = 45
AUTO_MEDIA_RESEND_AFTER_SECONDS = 12 * 60 * 60
_PROCESSING_LOCKS: dict[str, asyncio.Lock] = {}


async def process_client_message(
    incoming: IncomingMessage,
    target: DeliveryTarget,
    channel_client: ChannelClient,
    *,
    error_text: str,
    text_options: Mapping[str, Any] | None = None,
    media_options: Mapping[str, Any] | None = None,
    send_related_media: bool = True,
    log_context: str | None = None,
) -> str | None:
    text_options_dict = dict(text_options or {})
    media_options_dict = dict(media_options or {})
    try:
        processing_task = asyncio.create_task(_process_incoming_with_lock(incoming))
        typing_task = asyncio.create_task(
            show_typing_until_done(channel_client, target, processing_task)
        )
        try:
            reply = await processing_task
        finally:
            typing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing_task
        await channel_client.send_text(target, reply, **text_options_dict)
        if send_related_media:
            _schedule_related_media(
                channel_client,
                target,
                incoming.channel,
                incoming.external_user_id,
                incoming.text,
                reply,
                media_options_dict,
            )
        return reply
    except Exception:
        logger.exception(
            "Failed to handle client message target=%s context=%s",
            target.address,
            log_context,
        )
        await channel_client.send_text(target, error_text, **text_options_dict)
        return None


async def show_typing_until_done(
    channel_client: ChannelClient,
    target: DeliveryTarget,
    task: asyncio.Task[Any],
) -> None:
    while not task.done():
        await channel_client.send_typing(target)
        await asyncio.sleep(4)


async def _process_incoming_with_lock(incoming: IncomingMessage) -> str:
    key = f"{incoming.channel}:{incoming.external_user_id}"
    lock = _PROCESSING_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        return await asyncio.to_thread(handle_incoming, incoming)


def _schedule_related_media(
    channel_client: ChannelClient,
    target: DeliveryTarget,
    channel: str,
    external_user_id: str,
    text: str,
    reply: str,
    media_options: Mapping[str, Any],
) -> None:
    task = asyncio.create_task(
        _send_related_media(
            channel_client,
            target,
            channel,
            external_user_id,
            text,
            reply,
            dict(media_options),
        )
    )
    task.add_done_callback(_log_related_media_result)


def _log_related_media_result(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Background media send failed")


async def _send_related_media(
    channel_client: ChannelClient,
    target: DeliveryTarget,
    channel: str,
    external_user_id: str,
    text: str,
    reply: str,
    media_options: Mapping[str, Any],
) -> None:
    paths = media_for_client_message(text, reply)
    if not paths:
        missing_titles = missing_media_titles_for_client_message(text, reply)
        if is_explicit_photo_request(text) and missing_titles:
            titles = ", ".join(missing_titles)
            await channel_client.send_text(
                target,
                f"Фото для {titles} пока не добавлено. Я смогу отправить его, когда файл появится в базе фото.",
                **media_options,
            )
        return

    explicit_request = is_explicit_photo_request(text)
    if not explicit_request:
        allowed = await asyncio.to_thread(
            _reserve_auto_media_send,
            channel,
            external_user_id,
            paths,
        )
        if not allowed:
            return
        paths = media_for_client_message(text, reply)
        if not paths:
            return
        note = (
            "Сейчас отправлю фото выбранного варианта 📸"
            if len(paths) == 1
            else "Сейчас отправлю фото вариантов 📸"
        )
        await channel_client.send_text(target, note, **media_options)

    logger.info("Sending related media target=%s count=%s", target.address, len(paths))
    try:
        await asyncio.wait_for(
            _send_media_paths(channel_client, target, paths, media_options),
            timeout=MEDIA_SEND_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Related media send timed out target=%s count=%s",
            target.address,
            len(paths),
        )


async def _send_media_paths(
    channel_client: ChannelClient,
    target: DeliveryTarget,
    paths: Sequence[Any],
    media_options: Mapping[str, Any],
) -> None:
    try:
        await channel_client.send_media(target, paths, **media_options)
    except Exception:
        logger.exception("Failed to send media target=%s paths=%s", target.address, paths)


def _reserve_auto_media_send(channel: str, external_user_id: str, paths: Sequence[Any]) -> bool:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    media_key = "|".join(sorted(str(getattr(path, "name", path)) for path in paths))
    if not media_key:
        return False
    media_names = set(media_key.split("|"))
    with get_connection() as conn:
        user = users_repo.find_by_external_id(conn, channel, external_user_id)
        if not user:
            return False
        conversation = conversations_repo.find_active_for_user(
            conn,
            user_id=int(user["id"]),
            ttl_hours=settings.session_ttl_hours,
            now=now,
        )
        if not conversation:
            return False
        form_data = conversation.get("form_data") or {}
        media_state = dict(form_data.get("media_state") or {})
        sent_map = {
            str(key): str(value)
            for key, value in (media_state.get("gazebo_auto_sent_map") or {}).items()
            if key and value
        }
        sent_keys = {
            str(item)
            for item in (media_state.get("gazebo_auto_sent_keys") or [])
            if item
        }
        for existing_key, existing_at in sent_map.items():
            existing_names = set(existing_key.split("|"))
            if media_names <= existing_names and not _media_resend_due(existing_at, now):
                return False
        sent_at = sent_map.get(media_key)
        if sent_at and not _media_resend_due(sent_at, now):
            return False
        if media_key in sent_keys and not sent_at:
            legacy_sent_at = str(media_state.get("gazebo_auto_sent_at") or "")
            if legacy_sent_at and not _media_resend_due(legacy_sent_at, now):
                return False
        sent_keys.add(media_key)
        sent_map[media_key] = now.isoformat()
        media_state["gazebo_auto_sent"] = True
        media_state["gazebo_auto_sent_at"] = now.isoformat()
        media_state["gazebo_auto_sent_keys"] = sorted(sent_keys)[-20:]
        media_state["gazebo_auto_sent_map"] = _prune_media_sent_map(sent_map, now)
        conversations_repo.update_after_message(
            conn,
            conversation["id"],
            now,
            form_data={**form_data, "media_state": media_state},
        )
        return True


def _media_resend_due(sent_at: str, now: datetime) -> bool:
    try:
        previous = datetime.fromisoformat(sent_at)
    except ValueError:
        return True
    if previous.tzinfo is None and now.tzinfo is not None:
        previous = previous.replace(tzinfo=now.tzinfo)
    if previous.tzinfo is not None and now.tzinfo is not None:
        previous = previous.astimezone(now.tzinfo)
    return (now - previous).total_seconds() >= AUTO_MEDIA_RESEND_AFTER_SECONDS


def _prune_media_sent_map(sent_map: dict[str, str], now: datetime) -> dict[str, str]:
    fresh: dict[str, str] = {}
    for key, value in sent_map.items():
        if not _media_resend_due(value, now):
            fresh[key] = value
    return dict(list(fresh.items())[-20:])


__all__ = [
    "MEDIA_SEND_TIMEOUT_SECONDS",
    "process_client_message",
    "show_typing_until_done",
]
