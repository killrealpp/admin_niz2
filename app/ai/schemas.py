from typing import Any, Literal

from pydantic import BaseModel, Field


Intent = Literal[
    "booking_request",
    "availability_question",
    "price_question",
    "object_selection_help",
    "company_info",
    "change_booking",
    "cancel_booking",
    "payment_question",
    "human_request",
    "other",
]

Action = Literal[
    "ask_next_question",
    "answer_info",
    "check_availability",
    "offer_slots",
    "hold_slot",
    "ask_final_confirmation",
    "create_booking",
    "handoff_to_human",
    "reset_conversation",
    "send_error_message",
]


class AIResponse(BaseModel):
    intent: Intent = "other"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    action: Action = "ask_next_question"
    current_step: str | None = None
    next_step: str | None = None
    changed_fields: list[str] = Field(default_factory=list)
    form_data_patch: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    reply_to_user: str = ""
    handoff_to_human: bool = False
    handoff_reason: str | None = None


PostBookingIntent = Literal[
    "closing_ack",
    "current_booking_question",
    "change_existing_booking",
    "new_booking_request",
    "payment_status",
    "human_request",
    "other",
]

PostBookingChangeType = Literal[
    "cancel",
    "reschedule",
    "change_details",
    "unknown",
]


class PostBookingResponse(BaseModel):
    intent: PostBookingIntent = "other"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    change_type: PostBookingChangeType | None = "unknown"
    reply_to_user: str = ""
    handoff_to_human: bool = False
