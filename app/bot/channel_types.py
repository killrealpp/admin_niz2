from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.core.constants import CHANNEL_MAX, CHANNEL_TELEGRAM


@dataclass(frozen=True, slots=True)
class DeliveryTarget:
    channel: str
    external_id: str
    chat_id: str | None = None

    def __post_init__(self) -> None:
        channel = self.channel.strip()
        external_id = self.external_id.strip()
        chat_id = self.chat_id.strip() if self.chat_id else None
        if not channel:
            raise ValueError("DeliveryTarget.channel is required")
        if not external_id:
            raise ValueError("DeliveryTarget.external_id is required")
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "external_id", external_id)
        object.__setattr__(self, "chat_id", chat_id)

    @property
    def address(self) -> str:
        return self.chat_id or self.external_id


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    text: str = ""
    media_paths: tuple[str, ...] = ()
    parse_mode: str | None = None
    notify: bool = True
    raw_payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.media_paths, tuple):
            object.__setattr__(self, "media_paths", tuple(self.media_paths or ()))


__all__ = [
    "CHANNEL_MAX",
    "CHANNEL_TELEGRAM",
    "DeliveryTarget",
    "OutboundMessage",
]
