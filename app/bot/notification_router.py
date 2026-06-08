from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.bot.channel_client import ChannelClient
from app.bot.channel_types import DeliveryTarget, OutboundMessage


class NotificationDeliveryError(RuntimeError):
    pass


class NotificationRouter:
    def __init__(self, clients: Mapping[str, ChannelClient] | None = None) -> None:
        self._clients: dict[str, ChannelClient] = dict(clients or {})

    def register(self, channel: str, client: ChannelClient) -> None:
        channel = channel.strip()
        if not channel:
            raise ValueError("channel is required")
        self._clients[channel] = client

    def has_channel(self, channel: str) -> bool:
        return channel.strip() in self._clients

    async def send_text(
        self,
        target: DeliveryTarget,
        text: str,
        **options: Any,
    ) -> None:
        client = self._client_for(target)
        await client.send_text(target, text, **options)

    async def send(self, target: DeliveryTarget, message: OutboundMessage) -> None:
        if not message.text and not message.media_paths:
            raise ValueError("OutboundMessage must include text or media")

        client = self._client_for(target)
        if message.text:
            await client.send_text(
                target,
                message.text,
                parse_mode=message.parse_mode,
                notify=message.notify,
                raw_payload=message.raw_payload,
            )
        if message.media_paths:
            await client.send_media(
                target,
                message.media_paths,
                caption=message.text or None,
                parse_mode=message.parse_mode,
                notify=message.notify,
                raw_payload=message.raw_payload,
            )

    def _client_for(self, target: DeliveryTarget) -> ChannelClient:
        client = self._clients.get(target.channel)
        if client is None:
            raise NotificationDeliveryError(
                f"No channel client registered for {target.channel!r}"
            )
        return client


__all__ = ["NotificationDeliveryError", "NotificationRouter"]
