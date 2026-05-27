from __future__ import annotations

from typing import Any


BOOKING_INTENTS = {"booking_request", "availability_question"}
BOOKING_ACTIONS = {"ask_next_question", "check_availability", "offer_slots"}
ACTIVE_FLOW_KEYS = ("cancel_flow", "reschedule_flow", "swap_reschedule_flow")


def should_start_fresh_booking(
    conversation: dict[str, Any],
    *,
    requested_service: str | None,
    starts_new_request: bool,
    wants_additional_booking: bool,
    is_existing_booking_command: bool,
) -> bool:
    if is_existing_booking_command:
        return False
    if not wants_additional_booking and not starts_new_request:
        return False
    if (
        conversation.get("current_step") in {"reserved", "payment_status"}
        or conversation.get("status") in {"reserved", "payment_paid"}
    ):
        return True

    form_data = conversation.get("form_data") or {}
    current_service = form_data.get("service_type")
    return bool(
        starts_new_request
        and requested_service
        and current_service
        and requested_service != current_service
    )


def ai_should_start_fresh_booking(
    conversation: dict[str, Any],
    *,
    requested_service: str | None,
    starts_new_request: bool,
    wants_additional_booking: bool,
    is_existing_booking_command: bool,
    ai_intent: str,
    ai_action: str,
) -> bool:
    if is_existing_booking_command:
        return False

    form_data = conversation.get("form_data") or {}
    if any(form_data.get(key) for key in ACTIVE_FLOW_KEYS):
        return False
    if ai_intent not in BOOKING_INTENTS and ai_action not in BOOKING_ACTIONS:
        return False
    if not requested_service:
        return False

    current_service = form_data.get("service_type")
    if (
        current_service
        and requested_service != current_service
        and (starts_new_request or wants_additional_booking)
    ):
        return True

    return (
        conversation.get("current_step") in {"awaiting_new_date", "reserved", "payment_status"}
        or conversation.get("status") in {"reserved", "payment_paid"}
        or bool(form_data.get("last_unavailable"))
    )
