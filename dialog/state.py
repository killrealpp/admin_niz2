from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


BOOKING_STEPS = [
    "service_type",
    "date",
    "guests_count",
    "service_variant",
    "time",
    "duration",
    "event_format",
    "upsell_items",
    "client_name",
    "phone",
    "confirmation",
]


@dataclass
class BookingDraft:
    service_type: str | None = None
    date: str | None = None
    guests_count: int | None = None
    service_variant: str | None = None
    time: str | None = None
    duration: int | float | None = None
    event_format: str | None = None
    upsell_items: list[str] = field(default_factory=list)
    upsell_offer_count: int = 0
    upsell_done: bool = False
    client_name: str | None = None
    phone: str | None = None
    status: str = "collecting"
    available_variants: list[str] = field(default_factory=list)
    payment_id: str | None = None
    payment_url: str | None = None
    yclients_record_id: str | None = None
    reschedule_booking_id: int | None = None
    blocked_until: str | None = None
    block_reason: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "BookingDraft":
        allowed = set(cls.__dataclass_fields__)
        payload = {key: value for key, value in (data or {}).items() if key in allowed}
        if payload.get("upsell_items") is None:
            payload["upsell_items"] = []
        if payload.get("available_variants") is None:
            payload["available_variants"] = []
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def reset(self) -> None:
        fresh = BookingDraft()
        self.__dict__.update(fresh.__dict__)

    def next_step(self) -> str | None:
        if not self.service_type:
            return "service_type"
        if not self.date:
            return "date"
        if self.service_type == "gazebo" and not self.service_variant:
            return "service_variant"
        if not self.time:
            return "time"
        if not self.duration:
            return "duration"
        if not self.guests_count:
            return "guests_count"
        if not self.event_format:
            return "event_format"
        if not self.upsell_done:
            return "upsell_items"
        # Если клиент не выбрал допы, но предложение было сделано меньше двух раз,
        # не считаем шаг допов закрытым. next_step не должен менять состояние,
        # он только сообщает следующий шаг.
        if self.upsell_done and not self.upsell_items and self.upsell_offer_count < 2:
            return "upsell_items"
        if not self.client_name:
            return "client_name"
        if not self.phone:
            return "phone"
        if self.status == "collecting":
            return "confirmation"
        return None
    def ready_for_confirmation(self) -> bool:
        return self.next_step() == "confirmation"


@dataclass
class ParsedMessage:
    intent: str = "unknown"
    fields: dict[str, Any] = field(default_factory=dict)
    question: str | None = None
    answer: str | None = None
    confidence: float = 0.0


@dataclass
class AdminAction:
    type: str = "none"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdminDecision:
    reply: str = ""
    intent: str = "unknown"
    fields_patch: dict[str, Any] = field(default_factory=dict)
    action: AdminAction = field(default_factory=AdminAction)
    missing_fields: list[str] = field(default_factory=list)
    confidence: float = 0.0
    requested_media: list[str] = field(default_factory=list)
    ready_for_confirmation: bool = False
