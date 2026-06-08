"""Smoke-check MAX outbound text without live MAX calls or secrets."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bot import client_message_processor as shared_processor  # noqa: E402
from app.bot.channel_types import DeliveryTarget  # noqa: E402
from app.bot.max_channel_client import MaxChannelClient, split_max_text  # noqa: E402
from app.bot.max_message_processor import process_max_update  # noqa: E402
from app.bot.welcome_texts import START_WELCOME_TEXT  # noqa: E402
from app.core.constants import CHANNEL_MAX  # noqa: E402
from app.integrations.max_client import (  # noqa: E402
    MAX_MESSAGE_TEXT_LIMIT,
    MaxApiClient,
    MaxApiError,
)

TOKEN = "secret-test-token"
BASE_URL = "https://platform-api.max.ru"


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        *,
        text: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def __enter__(self) -> FakeHttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> FakeResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "kwargs": kwargs,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)


class RecordingMaxApiClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []
        self.actions: list[dict[str, str]] = []

    def send_message(
        self,
        *,
        text: str | None = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        attachments: Any = None,
        text_format: str | None = None,
        notify: bool | None = None,
        disable_link_preview: bool | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "text": text,
                "user_id": user_id,
                "chat_id": chat_id,
                "attachments": attachments,
                "text_format": text_format,
                "notify": notify,
                "disable_link_preview": disable_link_preview,
            }
        )
        return {"message": {"id": f"sent-{len(self.calls)}"}}

    def send_chat_action(self, *, chat_id: str, action: str = "typing_on") -> dict[str, Any]:
        self.actions.append({"chat_id": chat_id, "action": action})
        return {"success": True}


def _client(fake: FakeHttpClient) -> MaxApiClient:
    return MaxApiClient(
        token=TOKEN,
        base_url=BASE_URL,
        http_trust_env=False,
        client_factory=lambda **_kwargs: fake,
        sleep=lambda _seconds: None,
    )


def _assert_safe_auth(request: dict[str, Any]) -> None:
    assert request["headers"]["Authorization"] == TOKEN
    assert TOKEN not in request["url"]
    assert "access_token" not in request["url"]


def assert_api_send_message_payload() -> None:
    user_http = FakeHttpClient([FakeResponse(200, {"message": {"id": "m1"}})])
    result = _client(user_http).send_message(text="hello", user_id="user-1")
    assert result == {"message": {"id": "m1"}}
    request = user_http.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == f"{BASE_URL}/messages"
    assert request["kwargs"]["params"] == {"user_id": "user-1"}
    assert request["kwargs"]["json"] == {"text": "hello"}
    _assert_safe_auth(request)

    chat_http = FakeHttpClient([FakeResponse(200, {"message": {"id": "m2"}})])
    _client(chat_http).send_message(
        text="hello chat",
        user_id="user-ignored",
        chat_id="chat-1",
    )
    request = chat_http.requests[0]
    assert request["kwargs"]["params"] == {"chat_id": "chat-1"}
    assert request["kwargs"]["json"] == {"text": "hello chat"}
    _assert_safe_auth(request)


def assert_api_guards_and_redaction() -> None:
    empty_target_http = FakeHttpClient([])
    try:
        _client(empty_target_http).send_message(text="hello")
    except MaxApiError as exc:
        assert "target" in str(exc)
    else:
        raise AssertionError("send_message must require user_id or chat_id")

    too_long_http = FakeHttpClient([])
    try:
        _client(too_long_http).send_message(
            text="x" * (MAX_MESSAGE_TEXT_LIMIT + 1),
            user_id="user-1",
        )
    except MaxApiError as exc:
        assert str(MAX_MESSAGE_TEXT_LIMIT) in str(exc)
    else:
        raise AssertionError("send_message must guard the MAX text limit")

    error_http = FakeHttpClient(
        [FakeResponse(400, text=f"bad request mentions {TOKEN}")]
    )
    try:
        _client(error_http).send_message(text="hello", user_id="user-1")
    except MaxApiError as exc:
        error_text = str(exc)
        assert TOKEN not in error_text
        assert "[redacted]" in error_text
    else:
        raise AssertionError("HTTP 400 must raise MaxApiError")


async def assert_channel_client_target_and_split() -> None:
    user_api = RecordingMaxApiClient()
    user_client = MaxChannelClient(user_api)
    await user_client.send_text(
        DeliveryTarget(channel=CHANNEL_MAX, external_id="user-1"),
        "hello",
    )
    assert user_api.calls == [
        {
            "text": "hello",
            "user_id": "user-1",
            "chat_id": None,
            "attachments": None,
            "text_format": None,
            "notify": None,
            "disable_link_preview": None,
        }
    ]

    chat_api = RecordingMaxApiClient()
    chat_client = MaxChannelClient(chat_api)
    await chat_client.send_text(
        DeliveryTarget(channel=CHANNEL_MAX, external_id="user-1", chat_id="chat-1"),
        "hello chat",
    )
    assert chat_api.calls == [
        {
            "text": "hello chat",
            "user_id": None,
            "chat_id": "chat-1",
            "attachments": None,
            "text_format": None,
            "notify": None,
            "disable_link_preview": None,
        }
    ]

    long_api = RecordingMaxApiClient()
    long_client = MaxChannelClient(long_api)
    long_text = "a" * MAX_MESSAGE_TEXT_LIMIT + "tail"
    await long_client.send_text(
        DeliveryTarget(channel=CHANNEL_MAX, external_id="user-long"),
        long_text,
    )
    assert [len(call["text"] or "") for call in long_api.calls] == [
        MAX_MESSAGE_TEXT_LIMIT,
        4,
    ]
    assert "".join(str(call["text"]) for call in long_api.calls) == long_text
    assert split_max_text("abcd", limit=2) == ("ab", "cd")

    typing_api = RecordingMaxApiClient()
    typing_client = MaxChannelClient(typing_api)
    await typing_client.send_typing(
        DeliveryTarget(channel=CHANNEL_MAX, external_id="user-1", chat_id="chat-1")
    )
    await typing_client.send_typing(DeliveryTarget(channel=CHANNEL_MAX, external_id="user-1"))
    assert typing_api.actions == [{"chat_id": "chat-1", "action": "typing_on"}]


def max_payload() -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "message": {
            "id": "msg-1",
            "body": {"text": "client text"},
            "sender": {"user_id": "user-1", "name": "Max User"},
            "recipient": {"chat_id": "chat-1"},
        },
        "timestamp": 1_771_000_000,
    }


async def assert_inbound_to_shared_processor() -> None:
    original_handle_incoming = shared_processor.handle_incoming
    seen: list[Any] = []
    api = RecordingMaxApiClient()

    def fake_handle_incoming(incoming: Any) -> str:
        seen.append(incoming)
        assert incoming.channel == CHANNEL_MAX
        assert incoming.external_user_id == "user-1"
        assert incoming.raw_payload["chat_id"] == "chat-1"
        return "shared reply"

    try:
        shared_processor.handle_incoming = fake_handle_incoming
        reply = await process_max_update(
            max_payload(),
            channel_client=MaxChannelClient(api),
            error_text="error",
        )
    finally:
        shared_processor.handle_incoming = original_handle_incoming

    assert reply == "shared reply"
    assert len(seen) == 1
    assert api.calls == [
        {
            "text": "shared reply",
            "user_id": None,
            "chat_id": "chat-1",
            "attachments": None,
            "text_format": None,
            "notify": None,
            "disable_link_preview": None,
        }
    ]


async def assert_bot_started_direct_welcome() -> None:
    original_handle_incoming = shared_processor.handle_incoming
    api = RecordingMaxApiClient()

    def fail_handle_incoming(_incoming: Any) -> str:
        raise AssertionError("bot_started must not enter shared dialog")

    payload = {
        "event_type": "bot_started",
        "bot_started": {
            "payload": "booking-42",
            "user": {"user_id": "user-start", "name": "Start User"},
            "chat_id": "chat-start",
        },
    }

    try:
        shared_processor.handle_incoming = fail_handle_incoming
        reply = await process_max_update(
            payload,
            channel_client=MaxChannelClient(api),
            error_text="error",
        )
    finally:
        shared_processor.handle_incoming = original_handle_incoming

    assert reply == START_WELCOME_TEXT
    assert api.calls and api.calls[0]["text"] == START_WELCOME_TEXT
    assert api.calls[0]["chat_id"] == "chat-start"


def main() -> None:
    assert_api_send_message_payload()
    assert_api_guards_and_redaction()
    asyncio.run(assert_channel_client_target_and_split())
    asyncio.run(assert_inbound_to_shared_processor())
    asyncio.run(assert_bot_started_direct_welcome())
    print("max_outbound_text_smoke=ok")


if __name__ == "__main__":
    main()
