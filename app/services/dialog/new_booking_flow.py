from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NewBookingFlowCallbacks:
    new_booking_form_data: Callable[[dict[str, Any]], dict[str, Any]]
    wants_new_form_after_stale: Callable[[str], bool]
    service_type_patch: Callable[[str], dict[str, Any]]
    asks_for_free_slots: Callable[[str], bool]
    stale_message_starts_new_context: Callable[[str], bool]
    wants_continue_stale_form: Callable[[str], bool]
    continue_stale_form_reply: Callable[[dict[str, Any]], tuple[str, str | None]]
    should_offer_stale_form_choice: Callable[[dict[str, Any], datetime], bool]
    stale_message_has_new_booking_details: Callable[[str], bool]
    stale_form_choice_reply: Callable[[dict[str, Any]], str]
    explicit_new_booking_with_details: Callable[[str], bool]
    fresh_booking_form_data_for_text: Callable[[dict[str, Any], str], dict[str, Any]]
    should_start_fresh_booking: Callable[[dict[str, Any], str], bool]
    fresh_start_immediate_reply: Callable[
        [dict[str, Any], str, datetime],
        tuple[str, str, str | None] | None,
    ]
    ai_should_start_fresh_booking: Callable[[dict[str, Any], Any, dict[str, Any], str], bool]
    fresh_booking_patch_from_ai: Callable[..., dict[str, Any]]
    next_question_key: Callable[[dict[str, Any]], str | None]


@dataclass(frozen=True)
class NewBookingFlowResult:
    reply: str | None
    status: str
    intent: str | None
    current_step: str | None
    next_step: str | None
    form_data: dict[str, Any]
    persist_context: bool = False
    started_new_booking: bool = False
    started_new_booking_from_ai: bool = False
    patch: dict[str, Any] | None = None
    expected_key_before: str | None = None


def handle_stale_new_booking_flow(
    *,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    conv_created: bool,
    current_form_data: dict[str, Any],
    callbacks: NewBookingFlowCallbacks,
) -> NewBookingFlowResult | None:
    if current_form_data.get("stale_form_flow"):
        if (
            callbacks.wants_new_form_after_stale(text)
            and not callbacks.service_type_patch(text)
            and not callbacks.asks_for_free_slots(text)
        ):
            form_data = callbacks.new_booking_form_data(current_form_data)
            return NewBookingFlowResult(
                reply="Хорошо, начнём новую анкету ✅\n\nЧто хотите забронировать?",
                status="waiting_user",
                intent=None,
                current_step="service_type",
                next_step="service_type",
                form_data=form_data,
            )
        if callbacks.stale_message_starts_new_context(text):
            form_data = callbacks.fresh_booking_form_data_for_text(current_form_data, text)
            return NewBookingFlowResult(
                reply=None,
                status="waiting_user",
                intent=None,
                current_step=None,
                next_step=None,
                form_data=form_data,
                persist_context=True,
            )
        if current_form_data.get("stale_form_flow") and callbacks.wants_continue_stale_form(text):
            reply, next_key = callbacks.continue_stale_form_reply(current_form_data)
            form_data = dict(current_form_data)
            form_data.pop("stale_form_flow", None)
            status = "awaiting_confirmation" if next_key == "confirmation" else "waiting_user"
            current_step = "awaiting_confirmation" if next_key == "confirmation" else next_key
            return NewBookingFlowResult(
                reply=reply,
                status=status,
                intent=None,
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
        if current_form_data.get("stale_form_flow"):
            return NewBookingFlowResult(
                reply="Уточните, пожалуйста: продолжаем старую заявку или начинаем новую?",
                status="waiting_user",
                intent=None,
                current_step="stale_form_choice",
                next_step="stale_form_choice",
                form_data=current_form_data,
            )

    if not conv_created and callbacks.should_offer_stale_form_choice(conversation, now):
        if (
            callbacks.stale_message_has_new_booking_details(text)
            and callbacks.stale_message_starts_new_context(text)
        ):
            form_data = callbacks.fresh_booking_form_data_for_text(current_form_data, text)
            return NewBookingFlowResult(
                reply=None,
                status="waiting_user",
                intent=None,
                current_step=None,
                next_step=None,
                form_data=form_data,
                persist_context=True,
            )
        if not (callbacks.wants_new_form_after_stale(text) and callbacks.asks_for_free_slots(text)):
            form_data = {
                **current_form_data,
                "stale_form_flow": {
                    "started_at": now.isoformat(),
                    "previous_step": conversation.get("current_step"),
                },
            }
            return NewBookingFlowResult(
                reply=callbacks.stale_form_choice_reply(current_form_data),
                status="waiting_user",
                intent=None,
                current_step="stale_form_choice",
                next_step="stale_form_choice",
                form_data=form_data,
            )

    return None


def handle_fresh_start_before_post_booking(
    *,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    current_flow_form: dict[str, Any],
    has_change_flow: bool,
    can_start_from_current_state: bool,
    callbacks: NewBookingFlowCallbacks,
) -> NewBookingFlowResult | None:
    if (
        not has_change_flow
        and callbacks.explicit_new_booking_with_details(text)
        and any(
            current_flow_form.get(key)
            for key in ("service_type", "date", "time", "duration", "guests_count", "event_format", "upsell_items")
        )
    ):
        fresh_form_data = callbacks.fresh_booking_form_data_for_text(current_flow_form, text)
        return NewBookingFlowResult(
            reply=None,
            status="waiting_user",
            intent=None,
            current_step=None,
            next_step=None,
            form_data=fresh_form_data,
            started_new_booking=True,
        )

    if (
        not has_change_flow
        and can_start_from_current_state
        and callbacks.should_start_fresh_booking(conversation, text)
    ):
        return _fresh_start_result(
            conversation=conversation,
            text=text,
            now=now,
            previous_form_data=current_flow_form,
            callbacks=callbacks,
        )

    return None


def handle_fresh_start_after_confirmation(
    *,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    callbacks: NewBookingFlowCallbacks,
) -> NewBookingFlowResult | None:
    form_data = conversation.get("form_data") or {}
    if any(form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow")):
        return None
    if not callbacks.should_start_fresh_booking(conversation, text):
        return None
    return _fresh_start_result(
        conversation=conversation,
        text=text,
        now=now,
        previous_form_data=form_data,
        callbacks=callbacks,
    )


def handle_ai_fresh_start(
    *,
    conversation: dict[str, Any],
    ai_result: Any,
    patch: dict[str, Any],
    text: str,
    now: datetime,
    started_new_booking: bool,
    callbacks: NewBookingFlowCallbacks,
) -> NewBookingFlowResult | None:
    if started_new_booking:
        return None
    if not callbacks.ai_should_start_fresh_booking(conversation, ai_result, patch, text):
        return None

    fresh_form_data = callbacks.fresh_booking_form_data_for_text(conversation.get("form_data") or {}, text)
    fresh_patch = callbacks.fresh_booking_patch_from_ai(
        ai_result=ai_result,
        patch=patch,
        text=text,
        now=now,
    )
    return NewBookingFlowResult(
        reply=None,
        status="waiting_user",
        intent=None,
        current_step=None,
        next_step=None,
        form_data=fresh_form_data,
        started_new_booking=True,
        started_new_booking_from_ai=True,
        patch=fresh_patch,
        expected_key_before=callbacks.next_question_key(fresh_form_data),
    )


def _fresh_start_result(
    *,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    previous_form_data: dict[str, Any],
    callbacks: NewBookingFlowCallbacks,
) -> NewBookingFlowResult:
    del conversation
    fresh_form_data = callbacks.fresh_booking_form_data_for_text(previous_form_data, text)
    immediate = callbacks.fresh_start_immediate_reply(fresh_form_data, text, now)
    if immediate:
        reply, current_step, next_key = immediate
        return NewBookingFlowResult(
            reply=reply,
            status="waiting_user",
            intent="booking_request",
            current_step=current_step,
            next_step=next_key,
            form_data=fresh_form_data,
            started_new_booking=True,
        )
    return NewBookingFlowResult(
        reply=None,
        status="waiting_user",
        intent=None,
        current_step=None,
        next_step=None,
        form_data=fresh_form_data,
        started_new_booking=True,
    )
