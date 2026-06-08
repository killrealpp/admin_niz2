from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from app.bot.channel_client import ChannelClient
from app.bot.client_message_processor import process_client_message
from app.bot.max_channel_client import MaxChannelClient
from app.bot.max_router import (
    max_delivery_target_from_incoming,
    max_delivery_target_from_update,
    max_message_id_from_update,
    max_message_payload,
    max_update_type,
    normalize_max_transcribed_message,
    normalize_max_update,
)
from app.bot.welcome_texts import START_WELCOME_TEXT
from app.core.config import get_settings
from app.integrations.max_client import MaxApiClient, MaxApiError
from app.services.voice_transcription_service import (
    VoiceTranscriptionError,
    transcribe_audio_bytes,
)

MAX_TEXT_MVP_ERROR = "MAX message processing failed. Try again later."
MAX_VOICE_FALLBACK_TEXT = "Не получилось обработать голосовое. Напишите, пожалуйста, текстом."
MAX_UNSUPPORTED_MESSAGE_FALLBACK_TEXT = (
    "Пока могу обработать в MAX текст или голосовое. Напишите, пожалуйста, текстом."
)
MAX_AUDIO_DOWNLOAD_MAX_BYTES = 20 * 1024 * 1024
AUDIO_ATTACHMENT_TYPES = {"audio", "voice"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".webm"}
DOWNLOAD_URL_KEYS = ("download_url", "file_url", "url", "link", "src")
FILENAME_KEYS = ("filename", "file_name", "name", "title")

logger = logging.getLogger(__name__)


async def process_max_update(
    update: dict[str, Any],
    *,
    channel_client: ChannelClient | None = None,
    api_client: MaxApiClient | None = None,
    error_text: str = MAX_TEXT_MVP_ERROR,
    send_related_media: bool = True,
    log_context: str | None = None,
) -> str | None:
    channel_client = channel_client or MaxChannelClient()
    if max_update_type(update) == "bot_started":
        return await _process_bot_started(update, channel_client)

    incoming = normalize_max_update(update)
    if incoming is None:
        return await _process_non_text_update(
            update,
            channel_client,
            api_client=api_client,
            error_text=error_text,
            send_related_media=send_related_media,
            log_context=log_context,
        )
    target = max_delivery_target_from_incoming(incoming)
    return await process_client_message(
        incoming,
        target,
        channel_client,
        error_text=error_text,
        send_related_media=send_related_media,
        log_context=log_context or "max text inbound",
    )


def process_max_webhook_event(
    event: Any,
    *,
    channel_client: ChannelClient | None = None,
    error_text: str = MAX_TEXT_MVP_ERROR,
) -> str | None:
    return asyncio.run(
        process_max_update(
            event.payload,
            channel_client=channel_client,
            error_text=error_text,
            log_context=f"max webhook {event.event_type}:{event.event_key}",
        )
    )


async def _process_bot_started(
    update: dict[str, Any],
    channel_client: ChannelClient,
) -> str | None:
    target = max_delivery_target_from_update(update)
    if target is None:
        logger.debug("Ignoring MAX bot_started without delivery target")
        return None
    payload = _start_payload(update)
    logger.info(
        "Incoming MAX bot_started external_id=%s chat_id=%s payload=%r",
        target.external_id,
        target.chat_id,
        payload,
    )
    await channel_client.send_text(target, START_WELCOME_TEXT)
    return START_WELCOME_TEXT


async def _process_non_text_update(
    update: dict[str, Any],
    channel_client: ChannelClient,
    *,
    api_client: MaxApiClient | None,
    error_text: str,
    send_related_media: bool,
    log_context: str | None,
) -> str | None:
    if max_update_type(update) != "message_created":
        return None
    target = max_delivery_target_from_update(update)
    if target is None:
        logger.debug("Ignoring non-text MAX message without delivery target")
        return None

    client = api_client or MaxApiClient()
    audio = _find_audio_attachment(update)
    if audio is None:
        full_update = await _load_full_message_update(update, client)
        audio = _find_audio_attachment(full_update)
        if audio is not None:
            update = full_update

    if audio is None:
        logger.info("MAX non-text message has no supported audio attachment target=%s", target.address)
        await channel_client.send_text(target, MAX_UNSUPPORTED_MESSAGE_FALLBACK_TEXT)
        return MAX_UNSUPPORTED_MESSAGE_FALLBACK_TEXT

    settings = get_settings()
    if audio.duration_seconds and audio.duration_seconds > settings.voice_transcription_max_seconds:
        logger.info(
            "MAX voice skipped because duration is too long target=%s duration=%s",
            target.address,
            audio.duration_seconds,
        )
        await channel_client.send_text(target, MAX_VOICE_FALLBACK_TEXT)
        return MAX_VOICE_FALLBACK_TEXT

    try:
        audio_bytes = await asyncio.to_thread(
            client.download_file_url,
            audio.url,
            max_bytes=MAX_AUDIO_DOWNLOAD_MAX_BYTES,
        )
        transcribed_text = await transcribe_audio_bytes(audio_bytes, filename=audio.filename)
    except (MaxApiError, VoiceTranscriptionError) as exc:
        logger.warning("MAX voice transcription skipped target=%s reason=%s", target.address, exc)
        await channel_client.send_text(target, MAX_VOICE_FALLBACK_TEXT)
        return MAX_VOICE_FALLBACK_TEXT
    except Exception:
        logger.exception("MAX voice transcription failed target=%s", target.address)
        await channel_client.send_text(target, error_text)
        return None

    incoming = normalize_max_transcribed_message(update, transcribed_text, content_type="voice")
    if incoming is None:
        await channel_client.send_text(target, MAX_VOICE_FALLBACK_TEXT)
        return MAX_VOICE_FALLBACK_TEXT
    target = max_delivery_target_from_incoming(incoming)
    return await process_client_message(
        incoming,
        target,
        channel_client,
        error_text=error_text,
        send_related_media=send_related_media,
        log_context=log_context or "max voice inbound",
    )


async def _load_full_message_update(
    update: dict[str, Any],
    api_client: MaxApiClient,
) -> dict[str, Any]:
    message_id = max_message_id_from_update(update)
    if not message_id:
        return update
    try:
        payload = await asyncio.to_thread(api_client.get_message, message_id)
    except Exception:
        logger.debug("MAX get_message failed message_id=%s", message_id, exc_info=True)
        return update
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            message = data.get("message") if isinstance(data.get("message"), dict) else data
    if not isinstance(message, dict):
        return update
    merged = dict(update)
    merged["message"] = {**max_message_payload(update), **message}
    return merged


class _AudioAttachment:
    def __init__(self, *, url: str, filename: str, duration_seconds: int | None) -> None:
        self.url = url
        self.filename = filename
        self.duration_seconds = duration_seconds


def _find_audio_attachment(update: dict[str, Any]) -> _AudioAttachment | None:
    message = max_message_payload(update)
    for item in _iter_candidate_dicts(message):
        if not _looks_like_audio_attachment(item):
            continue
        url = _download_url(item)
        if not url:
            continue
        return _AudioAttachment(
            url=url,
            filename=_attachment_filename(item, url),
            duration_seconds=_duration_seconds(item),
        )
    return None


def _iter_candidate_dicts(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(value, dict):
        result.append(value)
        for child in value.values():
            result.extend(_iter_candidate_dicts(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_iter_candidate_dicts(child))
    return result


def _looks_like_audio_attachment(item: dict[str, Any]) -> bool:
    kind_values = [
        item.get("type"),
        item.get("attachment_type"),
        item.get("media_type"),
        item.get("content_type"),
    ]
    normalized = {str(value or "").lower().strip() for value in kind_values}
    if normalized & AUDIO_ATTACHMENT_TYPES:
        return True
    filename = " ".join(str(item.get(key) or "") for key in FILENAME_KEYS)
    suffix = Path(filename).suffix.lower()
    return bool(suffix and suffix in AUDIO_EXTENSIONS)


def _download_url(item: dict[str, Any]) -> str | None:
    for key in DOWNLOAD_URL_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
    payload = item.get("payload")
    if isinstance(payload, dict):
        return _download_url(payload)
    return None


def _attachment_filename(item: dict[str, Any], url: str) -> str:
    for key in FILENAME_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    suffix = Path(urlparse(url).path).suffix
    return f"voice{suffix or '.ogg'}"


def _duration_seconds(item: dict[str, Any]) -> int | None:
    for key in ("duration", "duration_seconds", "length"):
        value = item.get(key)
        if value is None:
            continue
        try:
            seconds = int(float(value))
        except (TypeError, ValueError):
            continue
        if seconds > 100_000:
            seconds = round(seconds / 1000)
        return max(0, seconds)
    payload = item.get("payload")
    if isinstance(payload, dict):
        return _duration_seconds(payload)
    return None


def _start_payload(update: dict[str, Any]) -> str | None:
    event = update.get("bot_started")
    if not isinstance(event, dict):
        event = update
    for source in (event, update):
        for key in ("payload", "start_payload", "deep_link_payload"):
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def make_max_webhook_event_processor(
    *,
    channel_client: ChannelClient | None = None,
    error_text: str = MAX_TEXT_MVP_ERROR,
) -> Callable[[Any], None]:
    def _processor(event: Any) -> None:
        process_max_webhook_event(
            event,
            channel_client=channel_client,
            error_text=error_text,
        )

    return _processor


__all__ = [
    "MAX_UNSUPPORTED_MESSAGE_FALLBACK_TEXT",
    "MAX_VOICE_FALLBACK_TEXT",
    "MAX_TEXT_MVP_ERROR",
    "make_max_webhook_event_processor",
    "process_max_update",
    "process_max_webhook_event",
]
