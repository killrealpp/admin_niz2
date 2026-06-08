"""Smoke-check post-MVP MAX media upload and link buttons without live calls."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bot import max_channel_client as max_adapter  # noqa: E402
from app.bot import client_message_processor as shared_processor  # noqa: E402
from app.bot.channel_types import DeliveryTarget  # noqa: E402
from app.bot.max_channel_client import MAX_MEDIA_FALLBACK_TEXT, MaxChannelClient  # noqa: E402
from app.bot.max_message_processor import process_max_update, process_max_webhook_event  # noqa: E402
from app.core.constants import CHANNEL_MAX  # noqa: E402
from app.integrations.max_client import MaxApiClient, MaxApiError  # noqa: E402

TOKEN = "secret-test-token"
BASE_URL = "https://platform-api.max.ru"


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, *, text: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.headers: dict[str, str] = {}

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
    def __init__(
        self,
        *,
        upload_error: Exception | None = None,
        send_errors: Sequence[Exception] = (),
    ) -> None:
        self.upload_error = upload_error
        self.send_errors = list(send_errors)
        self.uploads: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []

    def upload_file(self, file_path: str | Path, *, upload_type: str = "file") -> dict[str, Any]:
        if self.upload_error is not None:
            raise self.upload_error
        self.uploads.append({"file_path": Path(file_path), "upload_type": upload_type})
        return {"token": f"token-{len(self.uploads)}"}

    def send_message(
        self,
        *,
        text: str | None = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        attachments: Sequence[dict[str, Any]] | None = None,
        text_format: str | None = None,
        notify: bool | None = None,
        disable_link_preview: bool | None = None,
    ) -> dict[str, Any]:
        self.messages.append(
            {
                "text": text,
                "user_id": user_id,
                "chat_id": chat_id,
                "attachments": list(attachments or []),
                "text_format": text_format,
                "notify": notify,
                "disable_link_preview": disable_link_preview,
            }
        )
        if self.send_errors:
            raise self.send_errors.pop(0)
        return {"message": {"id": f"sent-{len(self.messages)}"}}


@contextmanager
def fake_connection():
    yield object()


def assert_api_upload_file() -> None:
    upload_url = "https://upload.max.test/upload"
    fake = FakeHttpClient(
        [
            FakeResponse(200, {"url": upload_url}),
            FakeResponse(200, {"token": "uploaded-token"}),
        ]
    )
    client = MaxApiClient(
        token=TOKEN,
        base_url=BASE_URL,
        http_trust_env=False,
        client_factory=lambda **_kwargs: fake,
        sleep=lambda _seconds: None,
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "photo.jpg"
        image_path.write_bytes(b"fake-image")
        payload = client.upload_file(image_path, upload_type="image")

    assert payload == {"token": "uploaded-token"}
    create_request = fake.requests[0]
    assert create_request["method"] == "POST"
    assert create_request["url"] == f"{BASE_URL}/uploads"
    assert create_request["kwargs"]["params"] == {"type": "image"}
    assert create_request["headers"]["Authorization"] == TOKEN
    assert TOKEN not in create_request["url"]

    upload_request = fake.requests[1]
    assert upload_request["method"] == "POST"
    assert upload_request["url"] == upload_url
    assert upload_request["headers"] == {}
    assert "data" in upload_request["kwargs"]["files"]


async def assert_channel_media_upload_and_retry() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "photo.jpg"
        image_path.write_bytes(b"fake-image")

        api = RecordingMaxApiClient()
        client = MaxChannelClient(api, attachment_retry_delays=())
        await client.send_media(
            DeliveryTarget(channel=CHANNEL_MAX, external_id="max-user"),
            [image_path],
        )
        assert api.uploads == [{"file_path": image_path, "upload_type": "image"}]
        assert api.messages[0]["user_id"] == "max-user"
        assert api.messages[0]["attachments"] == [
            {"type": "image", "payload": {"token": "token-1"}}
        ]

        retry_api = RecordingMaxApiClient(
            send_errors=[MaxApiError("MAX API returned code attachment.not.ready")]
        )
        retry_client = MaxChannelClient(retry_api, attachment_retry_delays=(0,))
        await retry_client.send_media(
            DeliveryTarget(channel=CHANNEL_MAX, external_id="max-user"),
            [image_path],
        )
        assert len(retry_api.messages) == 2


async def assert_payment_link_button() -> None:
    api = RecordingMaxApiClient()
    client = MaxChannelClient(api)
    await client.send_text(
        DeliveryTarget(channel=CHANNEL_MAX, external_id="max-user"),
        "Оплатить можно по ссылке:\nhttps://example.test/pay\n\nРезерв держу 10 минут.",
    )
    attachments = api.messages[0]["attachments"]
    assert attachments == [
        {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [
                        {
                            "type": "link",
                            "text": "Оплатить",
                            "url": "https://example.test/pay",
                        }
                    ]
                ]
            },
        }
    ]
    assert "https://example.test/pay" in str(api.messages[0]["text"])


async def assert_media_failure_fallback_and_log() -> None:
    api = RecordingMaxApiClient(upload_error=MaxApiError("synthetic upload failure"))
    client = MaxChannelClient(api)
    system_logs: list[dict[str, Any]] = []
    patches: list[tuple[Any, str, Any]] = []
    try:
        patch_attr(patches, max_adapter, "get_connection", fake_connection)
        patch_attr(patches, max_adapter.logger, "exception", lambda *_args, **_kwargs: None)
        patch_attr(
            patches,
            max_adapter.system_logs_repo,
            "create",
            lambda _conn, **kwargs: system_logs.append(kwargs),
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.jpg"
            image_path.write_bytes(b"fake-image")
            await client.send_media(
                DeliveryTarget(channel=CHANNEL_MAX, external_id="max-user"),
                [image_path],
            )
    finally:
        restore(patches)

    assert system_logs[0]["event_type"] == "max_media_delivery_failed"
    assert api.messages[0]["text"] == MAX_MEDIA_FALLBACK_TEXT
    assert api.messages[0]["user_id"] == "max-user"


async def assert_max_processor_auto_media() -> None:
    api = RecordingMaxApiClient()
    patches: list[tuple[Any, str, Any]] = []
    try:
        patch_attr(
            patches,
            shared_processor,
            "handle_incoming",
            lambda _incoming: "Показываю фото беседки.",
        )
        patch_attr(
            patches,
            shared_processor,
            "is_explicit_photo_request",
            lambda _text: True,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.jpg"
            image_path.write_bytes(b"fake-image")
            patch_attr(
                patches,
                shared_processor,
                "media_for_client_message",
                lambda _text, _reply: [image_path],
            )
            reply = await process_max_update(
                _max_message_payload("покажи фото беседки 1"),
                channel_client=MaxChannelClient(api, attachment_retry_delays=()),
            )
            for _attempt in range(20):
                if len(api.messages) >= 2:
                    break
                await asyncio.sleep(0.01)
    finally:
        restore(patches)

    assert reply == "Показываю фото беседки."
    assert api.uploads and api.uploads[0]["upload_type"] == "image"
    assert api.messages[0]["text"] == "Показываю фото беседки."
    assert api.messages[1]["attachments"] == [
        {"type": "image", "payload": {"token": "token-1"}}
    ]


async def assert_max_webhook_processor_sends_related_media_before_return() -> None:
    api = RecordingMaxApiClient()
    patches: list[tuple[Any, str, Any]] = []
    try:
        patch_attr(
            patches,
            shared_processor,
            "handle_incoming",
            lambda _incoming: "Показываю фото беседки.",
        )
        patch_attr(
            patches,
            shared_processor,
            "is_explicit_photo_request",
            lambda _text: True,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.jpg"
            image_path.write_bytes(b"fake-image")
            patch_attr(
                patches,
                shared_processor,
                "media_for_client_message",
                lambda _text, _reply: [image_path],
            )
            event = SimpleNamespace(
                payload=_max_message_payload("покажи фото беседки 1"),
                event_type="message_created",
                event_key="media-smoke",
            )
            reply = await asyncio.to_thread(
                process_max_webhook_event,
                event,
                channel_client=MaxChannelClient(api, attachment_retry_delays=()),
            )
    finally:
        restore(patches)

    assert reply == "Показываю фото беседки."
    assert len(api.messages) >= 2
    assert api.messages[0]["text"] == "Показываю фото беседки."
    assert api.messages[1]["attachments"] == [
        {"type": "image", "payload": {"token": "token-1"}}
    ]


def _max_message_payload(text: str) -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "message": {
            "id": "msg-media-1",
            "body": {"text": text},
            "sender": {"user_id": "max-user", "name": "Max User"},
            "recipient": {"chat_id": "chat-1"},
        },
        "timestamp": 1_771_000_000,
    }


def patch_attr(patches: list[tuple[Any, str, Any]], obj: Any, name: str, value: Any) -> None:
    patches.append((obj, name, getattr(obj, name)))
    setattr(obj, name, value)


def restore(patches: list[tuple[Any, str, Any]]) -> None:
    for obj, name, original in reversed(patches):
        setattr(obj, name, original)


async def main() -> None:
    assert_api_upload_file()
    await assert_channel_media_upload_and_retry()
    await assert_payment_link_button()
    await assert_media_failure_fallback_and_log()
    await assert_max_processor_auto_media()
    await assert_max_webhook_processor_sends_related_media_before_return()
    print("max_media_buttons_smoke=ok")


if __name__ == "__main__":
    asyncio.run(main())
