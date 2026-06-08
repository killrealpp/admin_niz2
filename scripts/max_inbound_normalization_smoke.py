"""Smoke-test MAX inbound normalization without live MAX calls or secrets."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bot.max_polling_runner import normalize_max_text_update  # noqa: E402
from app.bot import client_message_processor as shared_processor  # noqa: E402
from app.bot.max_message_processor import (  # noqa: E402
    MAX_UNSUPPORTED_MESSAGE_FALLBACK_TEXT,
    MAX_VOICE_FALLBACK_TEXT,
    process_max_update,
)
from app.bot.max_router import (  # noqa: E402
    max_delivery_target_from_incoming,
    normalize_max_update,
)
from app.core.constants import CHANNEL_MAX  # noqa: E402


def message_created_payload() -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "message": {
            "id": "msg-1",
            "body": {"text": "  hello from MAX  "},
            "sender": {
                "user_id": 123,
                "first_name": "Max",
                "last_name": "Tester",
            },
            "recipient": {"chat_id": "chat-1"},
            "timestamp": 1_771_000_000_000,
        },
    }


def nested_message_created_payload() -> dict[str, Any]:
    return {
        "type": "message_created",
        "message_created": {
            "mid": "msg-2",
            "body": "plain body text",
            "user": {"id": "user-2", "username": "tester2"},
            "chat": {"id": "chat-2"},
        },
        "timestamp": "2026-06-04T09:10:11+00:00",
    }


def bot_started_payload() -> dict[str, Any]:
    return {
        "event_type": "bot_started",
        "bot_started": {
            "payload": "booking-42",
            "user": {"user_id": "user-3", "name": "Start User"},
            "chat_id": "chat-3",
            "created_at": "2026-06-04T12:00:00Z",
        },
    }


def assert_message_created() -> None:
    payload = message_created_payload()
    incoming = normalize_max_update(payload)
    assert incoming is not None
    assert incoming.channel == CHANNEL_MAX
    assert incoming.external_user_id == "123"
    assert incoming.user_name == "Max Tester"
    assert incoming.text == "hello from MAX"
    assert incoming.message_time == datetime.fromtimestamp(1_771_000_000, tz=timezone.utc)
    assert incoming.raw_payload["update_type"] == "message_created"
    assert incoming.raw_payload["message_id"] == "msg-1"
    assert incoming.raw_payload["chat_id"] == "chat-1"
    assert incoming.raw_payload["payload"] is None
    assert incoming.raw_payload["update"] == payload

    target = max_delivery_target_from_incoming(incoming)
    assert target.channel == CHANNEL_MAX
    assert target.external_id == "123"
    assert target.chat_id == "chat-1"


def assert_nested_message_created() -> None:
    incoming = normalize_max_update(nested_message_created_payload())
    assert incoming is not None
    assert incoming.external_user_id == "user-2"
    assert incoming.user_name == "tester2"
    assert incoming.text == "plain body text"
    assert incoming.raw_payload["message_id"] == "msg-2"
    assert incoming.raw_payload["chat_id"] == "chat-2"
    assert incoming.message_time == datetime(2026, 6, 4, 9, 10, 11, tzinfo=timezone.utc)


def assert_bot_started() -> None:
    payload = bot_started_payload()
    incoming = normalize_max_update(payload)
    assert incoming is not None
    assert incoming.channel == CHANNEL_MAX
    assert incoming.external_user_id == "user-3"
    assert incoming.user_name == "Start User"
    assert incoming.text == "/start booking-42"
    assert incoming.raw_payload["update_type"] == "bot_started"
    assert incoming.raw_payload["payload"] == "booking-42"
    assert incoming.raw_payload["chat_id"] == "chat-3"
    assert incoming.raw_payload["update"] == payload
    assert incoming.message_time == datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)


def assert_ignored_shapes() -> None:
    assert normalize_max_update({"update_type": "message_removed"}) is None
    assert (
        normalize_max_update(
            {
                "update_type": "message_created",
                "message": {
                    "id": "photo-1",
                    "attachments": [{"type": "image"}],
                    "sender": {"user_id": "user-4"},
                },
            }
        )
        is None
    )
    assert normalize_max_update({"update_type": "bot_started", "payload": "x"}) is None


def assert_polling_wrapper_still_text_only() -> None:
    normalized = normalize_max_text_update(message_created_payload())
    assert normalized is not None
    incoming, target = normalized
    assert incoming.text == "hello from MAX"
    assert incoming.raw_payload["source"] == "max_polling"
    assert target.external_id == "123"
    assert target.chat_id == "chat-1"
    assert normalize_max_text_update(bot_started_payload()) is None


class RecordingChannelClient:
    def __init__(self) -> None:
        self.sent_texts: list[str] = []
        self.typing_count = 0

    async def send_text(self, _target: Any, text: str, **_options: Any) -> None:
        self.sent_texts.append(text)

    async def send_media(
        self,
        _target: Any,
        _media_paths: Any,
        caption: str | None = None,
        **_options: Any,
    ) -> None:
        return None

    async def send_typing(self, _target: Any) -> None:
        self.typing_count += 1

    async def answer_callback(
        self,
        callback_id: str,
        message: str | None = None,
        notification: str | None = None,
    ) -> None:
        return None


class FakeMaxApiClient:
    def __init__(self) -> None:
        self.downloaded_urls: list[str] = []

    def get_message(self, message_id: str) -> dict[str, Any]:
        return {"message": {"id": message_id}}

    def download_file_url(self, url: str, *, max_bytes: int) -> bytes:
        self.downloaded_urls.append(url)
        return b"fake audio"


def audio_payload() -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "message": {
            "id": "voice-1",
            "sender": {"user_id": "user-voice", "name": "Voice User"},
            "recipient": {"chat_id": "chat-voice"},
            "attachments": [
                {
                    "type": "audio",
                    "payload": {
                        "url": "https://cdn.example.test/voice.ogg",
                        "duration": 5,
                    },
                    "filename": "voice.ogg",
                }
            ],
        },
    }


async def assert_non_text_fallback_and_audio_path() -> None:
    image_channel = RecordingChannelClient()
    image_reply = await process_max_update(
        {
            "update_type": "message_created",
            "message": {
                "id": "photo-1",
                "attachments": [{"type": "image"}],
                "sender": {"user_id": "user-4"},
                "recipient": {"chat_id": "chat-4"},
            },
        },
        channel_client=image_channel,
        api_client=FakeMaxApiClient(),
    )
    assert image_reply == MAX_UNSUPPORTED_MESSAGE_FALLBACK_TEXT
    assert image_channel.sent_texts == [MAX_UNSUPPORTED_MESSAGE_FALLBACK_TEXT]

    import app.bot.max_message_processor as max_processor

    original_handle_incoming = shared_processor.handle_incoming
    original_transcribe = max_processor.transcribe_audio_bytes
    audio_channel = RecordingChannelClient()
    seen: list[Any] = []

    async def fake_transcribe(_audio_bytes: bytes, *, filename: str = "voice.ogg") -> str:
        assert filename == "voice.ogg"
        return "хочу беседку голосом"

    def fake_handle_incoming(incoming: Any) -> str:
        seen.append(incoming)
        assert incoming.channel == CHANNEL_MAX
        assert incoming.external_user_id == "user-voice"
        assert incoming.raw_payload["content_type"] == "voice"
        assert incoming.text == "хочу беседку голосом"
        return "shared voice reply"

    try:
        max_processor.transcribe_audio_bytes = fake_transcribe
        shared_processor.handle_incoming = fake_handle_incoming
        audio_reply = await process_max_update(
            audio_payload(),
            channel_client=audio_channel,
            api_client=FakeMaxApiClient(),
            send_related_media=False,
        )
    finally:
        max_processor.transcribe_audio_bytes = original_transcribe
        shared_processor.handle_incoming = original_handle_incoming

    assert audio_reply == "shared voice reply"
    assert audio_channel.sent_texts == ["shared voice reply"]
    assert seen


def main() -> None:
    assert_message_created()
    assert_nested_message_created()
    assert_bot_started()
    assert_ignored_shapes()
    assert_polling_wrapper_still_text_only()
    import asyncio

    asyncio.run(assert_non_text_fallback_and_audio_path())
    print("max_inbound_normalization_smoke=ok")


if __name__ == "__main__":
    main()
