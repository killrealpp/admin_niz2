"""Smoke-check passive channel transport contract."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bot.channel_types import (  # noqa: E402
    CHANNEL_MAX,
    CHANNEL_TELEGRAM,
    DeliveryTarget,
    OutboundMessage,
)
from app.bot.notification_router import (  # noqa: E402
    NotificationDeliveryError,
    NotificationRouter,
)


class FakeChannelClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, DeliveryTarget, Any]] = []

    async def send_text(
        self,
        target: DeliveryTarget,
        text: str,
        **options: Any,
    ) -> None:
        self.sent.append(("text", target, {"text": text, "options": options}))

    async def send_media(
        self,
        target: DeliveryTarget,
        media_paths: Sequence[str],
        caption: str | None = None,
        **options: Any,
    ) -> None:
        self.sent.append(
            (
                "media",
                target,
                {
                    "media_paths": tuple(media_paths),
                    "caption": caption,
                    "options": options,
                },
            )
        )

    async def send_typing(self, target: DeliveryTarget) -> None:
        self.sent.append(("typing", target, {}))

    async def answer_callback(
        self,
        callback_id: str,
        message: str | None = None,
        notification: str | None = None,
    ) -> None:
        self.sent.append(
            (
                "callback",
                DeliveryTarget(channel=CHANNEL_TELEGRAM, external_id=callback_id),
                {"message": message, "notification": notification},
            )
        )


async def main() -> None:
    telegram = FakeChannelClient()
    max_client = FakeChannelClient()
    router = NotificationRouter(
        {
            CHANNEL_TELEGRAM: telegram,
            CHANNEL_MAX: max_client,
        }
    )

    telegram_target = DeliveryTarget(
        channel=CHANNEL_TELEGRAM,
        external_id="user-1",
        chat_id="chat-1",
    )
    max_target = DeliveryTarget(channel=CHANNEL_MAX, external_id="max-user-1")
    assert telegram_target.address == "chat-1"
    assert max_target.address == "max-user-1"

    await router.send_text(telegram_target, "hello")
    await router.send(
        max_target,
        OutboundMessage(
            text="photo",
            media_paths=["photo.jpg"],
            parse_mode="html",
            notify=False,
        ),
    )

    assert telegram.sent[0][0] == "text"
    assert telegram.sent[0][2]["text"] == "hello"
    assert max_client.sent[0][0] == "text"
    assert max_client.sent[1][0] == "media"
    assert max_client.sent[1][2]["media_paths"] == ("photo.jpg",)

    try:
        await router.send_text(
            DeliveryTarget(channel="unknown", external_id="user-2"),
            "hello",
        )
    except NotificationDeliveryError:
        pass
    else:
        raise AssertionError("unknown channel must fail")

    print("channel_contract_smoke=ok")


if __name__ == "__main__":
    asyncio.run(main())
