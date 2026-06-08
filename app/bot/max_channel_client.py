from __future__ import annotations

import asyncio
from collections.abc import Sequence
import logging
from pathlib import Path
import re
from typing import Any

from app.bot.channel_types import DeliveryTarget
from app.core.constants import CHANNEL_MAX
from app.db.connection import get_connection
from app.db.repositories import system_logs_repo
from app.integrations.max_client import MAX_MESSAGE_TEXT_LIMIT, MaxApiClient
from app.integrations.max_client import MaxApiError

logger = logging.getLogger(__name__)
MAX_LINK_BUTTON_URL_LIMIT = 2048
MAX_MEDIA_FALLBACK_TEXT = (
    "Фото сейчас не получилось отправить в MAX. "
    "Продолжу бронь текстом, а фото пришлем позже."
)
MAX_MEDIA_SEND_LIMIT = 10
ATTACHMENT_NOT_READY_CODE = "attachment.not.ready"
DEFAULT_ATTACHMENT_RETRY_DELAYS = (1.0, 2.0, 4.0)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".tiff", ".bmp", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".matroska"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus"}
URL_RE = re.compile(r"https?://[^\s<>()\[\]{}]+")


class MaxChannelClient:
    def __init__(
        self,
        api_client: MaxApiClient | None = None,
        *,
        attachment_retry_delays: Sequence[float] | None = None,
    ) -> None:
        self._api_client = api_client or MaxApiClient()
        self._attachment_retry_delays = tuple(
            DEFAULT_ATTACHMENT_RETRY_DELAYS
            if attachment_retry_delays is None
            else attachment_retry_delays
        )

    async def send_text(
        self,
        target: DeliveryTarget,
        text: str,
        **options: Any,
    ) -> None:
        _ensure_max_target(target)
        attachments = _attachments_from_options(text, options)
        for chunk in split_max_text(text):
            await asyncio.to_thread(
                self._api_client.send_message,
                text=chunk,
                user_id=None if target.chat_id else target.external_id,
                chat_id=target.chat_id,
                attachments=attachments,
                text_format=options.get("parse_mode"),
                notify=options.get("notify"),
                disable_link_preview=options.get("disable_link_preview"),
            )
            attachments = None

    async def send_media(
        self,
        target: DeliveryTarget,
        media_paths: Sequence[str],
        caption: str | None = None,
        **options: Any,
    ) -> None:
        _ensure_max_target(target)
        paths = [Path(path) for path in media_paths if path]
        if not paths:
            return
        try:
            attachments = await self._upload_media_attachments(paths[:MAX_MEDIA_SEND_LIMIT])
            await self._send_message_with_attachment_retry(
                target,
                text=caption or None,
                attachments=attachments,
                text_format=options.get("parse_mode"),
                notify=options.get("notify"),
            )
        except Exception as exc:
            logger.exception(
                "MAX media delivery failed target=%s count=%s",
                target.address,
                len(paths),
            )
            _record_max_media_failure(target, paths, exc)
            try:
                await self.send_text(target, MAX_MEDIA_FALLBACK_TEXT)
            except Exception:
                logger.exception("MAX media fallback text failed target=%s", target.address)

    async def _upload_media_attachments(self, paths: Sequence[Path]) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        for path in paths:
            upload_type = _upload_type_for_path(path)
            payload = await asyncio.to_thread(
                self._api_client.upload_file,
                path,
                upload_type=upload_type,
            )
            attachments.append({"type": upload_type, "payload": payload})
        return attachments

    async def _send_message_with_attachment_retry(
        self,
        target: DeliveryTarget,
        *,
        text: str | None,
        attachments: Sequence[dict[str, Any]],
        text_format: str | None = None,
        notify: bool | None = None,
    ) -> None:
        delays = self._attachment_retry_delays
        for attempt in range(len(delays) + 1):
            try:
                await asyncio.to_thread(
                    self._api_client.send_message,
                    text=text,
                    user_id=None if target.chat_id else target.external_id,
                    chat_id=target.chat_id,
                    attachments=attachments,
                    text_format=text_format,
                    notify=notify,
                )
                return
            except MaxApiError as exc:
                if not _is_attachment_not_ready(exc) or attempt >= len(delays):
                    raise
                await asyncio.sleep(max(0.0, float(delays[attempt])))

    async def send_typing(self, target: DeliveryTarget) -> None:
        _ensure_max_target(target)
        if not target.chat_id:
            logger.debug("MAX typing skipped: target has no chat_id external_id=%s", target.external_id)
            return
        try:
            await asyncio.to_thread(
                self._api_client.send_chat_action,
                chat_id=target.chat_id,
                action="typing_on",
            )
        except Exception:
            logger.debug("MAX typing failed target=%s", target.address, exc_info=True)

    async def answer_callback(
        self,
        callback_id: str,
        message: str | None = None,
        notification: str | None = None,
    ) -> None:
        logger.info("MAX callbacks are not supported in text-only MVP")


def split_max_text(
    text: str,
    *,
    limit: int = MAX_MESSAGE_TEXT_LIMIT,
) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("MAX text limit must be positive")
    if not text:
        return ()
    return tuple(text[index : index + limit] for index in range(0, len(text), limit))


def _ensure_max_target(target: DeliveryTarget) -> None:
    if target.channel != CHANNEL_MAX:
        raise ValueError(f"MaxChannelClient cannot send to channel={target.channel!r}")


def _attachments_from_options(text: str, options: dict[str, Any]) -> list[dict[str, Any]] | None:
    attachments = _existing_attachments(options)
    link_button = _link_button_attachment_from_options(text, options)
    if link_button is not None:
        attachments.append(link_button)
    return attachments or None


def _existing_attachments(options: dict[str, Any]) -> list[dict[str, Any]]:
    raw = options.get("attachments") or options.get("max_attachments")
    if not raw:
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _link_button_attachment_from_options(
    text: str,
    options: dict[str, Any],
) -> dict[str, Any] | None:
    url = (
        str(options.get("link_button_url") or options.get("max_link_button_url") or "").strip()
        or _payment_link_from_text(text)
    )
    if not url or len(url) > MAX_LINK_BUTTON_URL_LIMIT:
        return None
    label = str(
        options.get("link_button_text")
        or options.get("max_link_button_text")
        or "Оплатить"
    ).strip() or "Оплатить"
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {
                        "type": "link",
                        "text": label,
                        "url": url,
                    }
                ]
            ]
        },
    }


def _payment_link_from_text(text: str) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("оплат", "предоплат")):
        return None
    for match in URL_RE.finditer(text):
        return _strip_url(match.group(0))
    return None


def _strip_url(value: str) -> str:
    return value.rstrip(".,;:!?)]}>\"'")


def _upload_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return "file"


def _is_attachment_not_ready(exc: MaxApiError) -> bool:
    return ATTACHMENT_NOT_READY_CODE in str(exc)


def _record_max_media_failure(
    target: DeliveryTarget,
    paths: Sequence[Path],
    exc: Exception,
) -> None:
    try:
        with get_connection() as conn:
            system_logs_repo.create(
                conn,
                level="warning",
                event_type="max_media_delivery_failed",
                message=str(exc)[:1000],
                payload={
                    "user_channel": target.channel,
                    "user_external_id": target.external_id,
                    "chat_id": target.chat_id,
                    "media_count": len(paths),
                    "media_paths": [path.name for path in paths[:MAX_MEDIA_SEND_LIMIT]],
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                },
            )
    except Exception:
        logger.exception("Failed to record MAX media delivery failure")


__all__ = [
    "MAX_MEDIA_FALLBACK_TEXT",
    "MaxChannelClient",
    "split_max_text",
]
