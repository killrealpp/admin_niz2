from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

from app.bot.channel_types import DeliveryTarget


@runtime_checkable
class ChannelClient(Protocol):
    async def send_text(
        self,
        target: DeliveryTarget,
        text: str,
        **options: Any,
    ) -> None:
        ...

    async def send_media(
        self,
        target: DeliveryTarget,
        media_paths: Sequence[str],
        caption: str | None = None,
        **options: Any,
    ) -> None:
        ...

    async def send_typing(self, target: DeliveryTarget) -> None:
        ...

    async def answer_callback(
        self,
        callback_id: str,
        message: str | None = None,
        notification: str | None = None,
    ) -> None:
        ...


__all__ = ["ChannelClient"]
