from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.dialog.form_patches import (
    explicit_new_service_request,
    looks_like_prior_booking_reference_text,
)
from app.services.dialog.reschedule_flow import means_same_date, means_same_time


@dataclass(frozen=True)
class RouteResult:
    reply: str
    status: str
    current_step: str | None
    next_step: str | None
    form_data: dict[str, Any]
    intent: Any = None


@dataclass(frozen=True)
class ReferencePatchCallbacks:
    means_same_date: Callable[[str], bool]
    means_same_time: Callable[[str], bool]
    referenced_service_type_for_same_time: Callable[[str], str | None]
    looks_like_prior_booking_reference_text: Callable[[str], bool]
    active_user_bookings: Callable[..., list[dict[str, Any]]]
    hours_from_minutes: Callable[[Any], Any]


@dataclass(frozen=True)
class FreeDatesAfterUnavailableCallbacks:
    asks_for_free_slots: Callable[[str], bool]
    wants_new_form_after_stale: Callable[[str], bool]
    has_specific_date_signal: Callable[[str, datetime], bool]
    next_free_dates_reply: Callable[..., str | None]


@dataclass(frozen=True)
class UnavailableAlternativesCallbacks:
    looks_like_event_context_for_alternatives: Callable[[str], bool]
    alternative_services_for_unavailable_date: Callable[..., tuple[str, str] | None]
    join_preferences: Callable[[Any, str], str]


@dataclass(frozen=True)
class SameUnavailableDateCallbacks:
    asks_for_free_slots: Callable[[str], bool]
    same_unavailable_date_reply: Callable[[dict[str, Any]], tuple[str, str]]
    clear_active_slot_keep_last: Callable[[dict[str, Any]], dict[str, Any]]
    ai_process_reply: Callable[..., str]


def same_booking_reference_patch(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    now: datetime,
    callbacks: ReferencePatchCallbacks,
) -> dict[str, Any]:
    wants_same_time = callbacks.means_same_time(text)
    wants_same_date = callbacks.means_same_date(text)
    if not (wants_same_time or wants_same_date):
        return {}
    if (
        (not wants_same_date or form_data.get("date"))
        and (not wants_same_time or (form_data.get("time") and form_data.get("duration")))
    ):
        return {}
    bookings = callbacks.active_user_bookings(conn, conversation, form_data, now)
    if not bookings:
        return {}
    referenced_service = callbacks.referenced_service_type_for_same_time(text)
    explicit_reference = bool(referenced_service or callbacks.looks_like_prior_booking_reference_text(text))
    candidates = [
        booking
        for booking in bookings
        if not referenced_service or booking.get("service_type") == referenced_service
    ]
    if not candidates:
        return {}
    current_date = str(form_data.get("date") or "")
    if current_date:
        same_date = [booking for booking in candidates if str(booking.get("booking_date")) == current_date]
        if same_date:
            candidates = same_date
    booking = candidates[0]
    patch: dict[str, Any] = {}
    if wants_same_date and booking.get("booking_date") and (explicit_reference or not form_data.get("date")):
        patch["date"] = str(booking.get("booking_date"))
    if wants_same_time and booking.get("booking_time") and (explicit_reference or not form_data.get("time")):
        patch["time"] = str(booking.get("booking_time"))[:5]
    if wants_same_time and booking.get("duration_minutes") and (explicit_reference or not form_data.get("duration")):
        patch["duration"] = callbacks.hours_from_minutes(booking.get("duration_minutes"))
    return patch


def preserve_current_service_for_reference(
    patch: dict[str, Any],
    current_form_data: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    current_service = current_form_data.get("service_type")
    requested_service = patch.get("service_type")
    if not current_service or not requested_service or requested_service == current_service:
        return patch

    normalized = text.lower().replace("ё", "е")
    if explicit_new_service_request(normalized):
        return patch

    if (
        looks_like_prior_booking_reference_text(normalized)
        or means_same_date(normalized)
        or means_same_time(normalized)
    ):
        cleaned = dict(patch)
        cleaned.pop("service_type", None)
        cleaned.pop("preferences", None)
        return cleaned
    return patch


def free_dates_after_unavailable_route(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    callbacks: FreeDatesAfterUnavailableCallbacks,
) -> RouteResult | None:
    if not callbacks.asks_for_free_slots(text):
        return None
    if callbacks.wants_new_form_after_stale(text):
        return None
    if callbacks.has_specific_date_signal(text, now):
        return None
    form_data = conversation.get("form_data") or {}
    if conversation.get("current_step") != "awaiting_new_date" and not form_data.get("last_unavailable"):
        return None

    reply = callbacks.next_free_dates_reply(conn, conversation, form_data, now)
    if not reply:
        return None
    return RouteResult(
        reply=reply,
        status="waiting_user",
        current_step="awaiting_new_date",
        next_step="date",
        form_data=form_data,
    )


def unavailable_alternatives_route(
    conn,
    form_data: dict[str, Any],
    text: str,
    now: datetime,
    callbacks: UnavailableAlternativesCallbacks,
) -> RouteResult | None:
    if not form_data.get("last_unavailable"):
        return None
    if not callbacks.looks_like_event_context_for_alternatives(text):
        return None
    alternative = callbacks.alternative_services_for_unavailable_date(conn, form_data, now)
    if not alternative:
        return None
    reply, next_key = alternative
    updated = dict(form_data)
    updated["preferences"] = callbacks.join_preferences(updated.get("preferences"), text.strip())
    return RouteResult(
        reply=reply,
        status="waiting_user",
        intent="alternative_services",
        current_step="service_type",
        next_step=next_key,
        form_data=updated,
    )


def same_unavailable_date_route(
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    *,
    changed_fields: set[str],
    ai_intent: Any,
    history: list[dict[str, Any]],
    callbacks: SameUnavailableDateCallbacks,
) -> RouteResult | None:
    last_unavailable = (conversation.get("form_data") or {}).get("last_unavailable") or {}
    if (
        conversation.get("current_step") != "awaiting_new_date"
        or not form_data.get("date")
        or form_data.get("date") != last_unavailable.get("date")
        or {"time", "duration"} & changed_fields
        or callbacks.asks_for_free_slots(text)
    ):
        return None

    required, next_key = callbacks.same_unavailable_date_reply(form_data)
    updated = callbacks.clear_active_slot_keep_last(form_data)
    reply = callbacks.ai_process_reply(
        text=text,
        form_data=updated,
        history=history,
        required_meaning=required,
    )
    return RouteResult(
        reply=reply,
        status="waiting_user",
        intent=ai_intent,
        current_step="awaiting_new_date",
        next_step=next_key,
        form_data=updated,
    )
