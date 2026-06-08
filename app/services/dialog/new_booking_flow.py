from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.dialog.formatting import format_date_ru


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


def wants_additional_booking(
    text: str,
    *,
    wants_cancel_booking: Callable[[str], bool],
    wants_reschedule: Callable[[str], bool],
    wants_swap_bookings: Callable[[str], bool],
    service_type_patch: Callable[[str], dict[str, Any]],
) -> bool:
    normalized = text.lower().replace("ё", "е")
    if wants_cancel_booking(text) or wants_reschedule(text) or wants_swap_bookings(text):
        return False
    if not any(marker in normalized for marker in ("еще", "ещё", "добав", "добв", "также", "тоже", "брон", "заброни", "хочу", "нужн")):
        return False
    if service_type_patch(normalized):
        return True
    return any(
        marker in normalized
        for marker in (
            "еще одну",
            "еще одна",
            "ещё одну",
            "ещё одна",
            "еще надо",
            "ещё надо",
            "вторую брон",
            "новую брон",
            "добавить брон",
            "добавь брон",
            "добвить брон",
            "добвь брон",
            "отдельной брон",
            "отдельную брон",
            "отдельно брон",
            "отдельной заяв",
            "отдельную заяв",
            "еще брон",
            "ещё брон",
        )
    )


def starts_new_booking_request(
    text: str,
    *,
    asks_available_services: Callable[[str], bool],
    service_type_patch: Callable[[str], dict[str, Any]],
    looks_like_info_question: Callable[[str], bool],
    explicit_numeric_dates: Callable[[str, datetime], list[Any]],
    now_local: Callable[[], datetime],
) -> bool:
    normalized = text.lower().replace("ё", "е")
    if asks_available_services(text):
        return False
    if not service_type_patch(normalized):
        return False
    has_booking_signal = any(
        marker in normalized
        for marker in (
            "нужн",
            "хочу",
            "хотел",
            "хотела",
            "хотим",
            "давай",
            "заброни",
            "брон",
            "заказ",
            "оформ",
            "можно",
            "еще",
            "ещё",
            "добав",
        )
    )
    if not has_booking_signal:
        return False
    if looks_like_info_question(text):
        return any(
            marker in normalized
            for marker in ("нужн", "хочу", "заброни", "брон", "заказ", "оформ")
        ) or bool(explicit_numeric_dates(text, now_local()))
    return True


def generic_new_booking_request(
    text: str,
    *,
    wants_cancel_booking: Callable[[str], bool],
    wants_reschedule: Callable[[str], bool],
    wants_swap_bookings: Callable[[str], bool],
) -> bool:
    normalized = text.lower().replace("ё", "е")
    if wants_cancel_booking(text) or wants_reschedule(text) or wants_swap_bookings(text):
        return False
    wants_separate_booking = any(
        marker in normalized
        for marker in (
            "отдельной брон",
            "отдельную брон",
            "отдельно брон",
            "отдельной заяв",
            "отдельную заяв",
            "добавить отдель",
            "добавь отдель",
            "добвить отдель",
            "добвь отдель",
        )
    ) and any(
        marker in normalized
        for marker in ("хочу", "давай", "давайте", "оформ", "добав", "добв", "заброн", "брон", "начн")
    )
    return (
        any(
            marker in normalized
            for marker in (
                "новую заявку",
                "новая заявка",
                "новую брон",
                "новая брон",
                "следующую заявку",
                "следующая заявка",
                "следующую брон",
                "следующая брон",
                "следующуей заяв",
            )
        )
        and any(marker in normalized for marker in ("начн", "оформ", "давай", "давайте", "хочу", "приступ"))
    ) or any(
        marker in normalized
        for marker in (
            "начнем новую",
            "начнём новую",
            "давайте начнем",
            "давайте начнём",
            "оформим новую",
            "новую оформим",
            "приступим к следующ",
        )
    ) or wants_separate_booking


def context_service_for_generic_new_booking(
    conversation: dict[str, Any],
    text: str,
    *,
    generic_new_booking_request: Callable[[str], bool],
    service_exists: Callable[[Any], bool],
) -> str | None:
    if not generic_new_booking_request(text):
        return None
    service_type = (conversation.get("form_data") or {}).get("last_discussed_service_type")
    if service_exists(service_type):
        return str(service_type)
    return None


def fresh_booking_form_data_for_text(
    previous: dict[str, Any],
    text: str,
    *,
    new_booking_form_data: Callable[[dict[str, Any]], dict[str, Any]],
    service_type_patch: Callable[[str], dict[str, Any]],
    generic_new_booking_request: Callable[[str], bool],
    normalize_service_aliases: Callable[[dict[str, Any]], dict[str, Any]],
    service_exists: Callable[[Any], bool],
) -> dict[str, Any]:
    fresh = new_booking_form_data(previous)
    service_patch = service_type_patch(text)
    if not service_patch and generic_new_booking_request(text):
        service_type = previous.get("last_discussed_service_type")
        if service_exists(service_type):
            service_patch = {"service_type": str(service_type)}
    if service_patch:
        fresh.update(service_patch)
        fresh = normalize_service_aliases(fresh)
    if fresh.get("service_type") != "gazebo":
        fresh["service_variant"] = None
    return fresh


def fresh_start_immediate_reply(
    form_data: dict[str, Any],
    text: str,
    now: datetime,
    *,
    generic_new_booking_request: Callable[[str], bool],
    asks_for_free_slots: Callable[[str], bool],
    asks_nearest_free_dates: Callable[[str], bool],
    has_specific_date_signal: Callable[[str, datetime], bool],
    looks_like_same_date_reference_text: Callable[[str], bool],
    time_period_patch: Callable[[str], dict[str, Any]],
    looks_like_same_time_reference_text: Callable[[str], bool],
    service_title: Callable[[Any], str | None],
) -> tuple[str, str, str | None] | None:
    if not form_data.get("service_type") and generic_new_booking_request(text):
        return (
            "Хорошо, начнём следующую заявку ✅\n\nЧто хотите забронировать: беседку, баню или дом?",
            "service_type",
            "service_type",
        )
    if not form_data.get("service_type"):
        return None
    if asks_for_free_slots(text) or asks_nearest_free_dates(text):
        return None
    if has_specific_date_signal(text, now) or looks_like_same_date_reference_text(text):
        return None
    if time_period_patch(text) or looks_like_same_time_reference_text(text):
        return None
    if any(form_data.get(key) for key in ("date", "time", "duration", "guests_count", "event_format", "upsell_items")):
        return None
    title = service_title(form_data.get("service_type")) or "услугу"
    contact_note = ""
    if form_data.get("client_name") and form_data.get("phone"):
        contact_note = "\n\nИмя и телефон уже есть, повторно их спрашивать не буду."
    elif form_data.get("phone"):
        contact_note = "\n\nТелефон уже есть, повторно его спрашивать не буду."
    return f"Хорошо, начнём новую заявку: {title.lower()} ✅{contact_note}\n\nНа какую дату планируете?", "date", "date"


def fresh_booking_patch_from_ai(
    *,
    ai_result: Any,
    patch: dict[str, Any],
    text: str,
    now: datetime,
    filter_new_booking_patch_to_current_message: Callable[[dict[str, Any], str, datetime], dict[str, Any]],
) -> dict[str, Any]:
    fresh_patch = filter_new_booking_patch_to_current_message(patch, text, now)
    ai_patch = dict(getattr(ai_result, "form_data_patch", None) or {})
    changed_fields = set(getattr(ai_result, "changed_fields", None) or [])
    for key in ("service_type", "service_variant", "preferences"):
        if key in ai_patch:
            fresh_patch[key] = ai_patch[key]
    for key in ("date", "time", "duration", "guests_count", "event_format", "upsell_items", "phone"):
        if key in ai_patch and key in changed_fields:
            fresh_patch[key] = ai_patch[key]
    return fresh_patch


def multi_gazebo_booking_patch(
    text: str,
    now: datetime,
    *,
    service_type_patch: Callable[[str], dict[str, Any]],
    explicit_numeric_dates: Callable[[str, datetime], list[str]],
) -> dict[str, Any]:
    normalized = text.lower().replace("ё", "е")
    if (service_type_patch(normalized) or {}).get("service_type") != "gazebo":
        return {}
    if not (
        re.search(r"\b2\s*(?:бесед|брон|заяв)", normalized)
        or re.search(r"\bдве\s+(?:бесед|брон|заяв)", normalized)
        or re.search(r"\bдва\s+(?:бесед|брон|заяв)", normalized)
    ):
        return {}
    dates = explicit_numeric_dates(text, now)
    patch: dict[str, Any] = {
        "service_type": "gazebo",
        "pending_additional_bookings": [
            {"service_type": "gazebo", "date": value}
            for value in dates[1:]
        ],
        "multi_booking_mode": "sequential",
    }
    if dates:
        patch["date"] = dates[0]
    return patch


def multi_gazebo_booking_reply(text: str, form_data: dict[str, Any]) -> str:
    lines: list[str] = []
    normalized = text.lower().replace("ё", "е")
    if "мангал" in normalized or "угл" in normalized:
        lines.append("Мангал у беседок есть. Уголь можно добавить к заявке, чтобы не везти с собой.")
        lines.append("")
    pending = form_data.get("pending_additional_bookings") or []
    if form_data.get("date"):
        first = format_date_ru(form_data.get("date"))
        if pending:
            second_dates = ", ".join(format_date_ru(item.get("date")) for item in pending if item.get("date"))
            lines.append(
                f"Две беседки можно оформить, но заявки заполняем по очереди: начинаем с {first}, "
                f"а {second_dates} держу как следующую отдельную бронь."
            )
        else:
            lines.append("Две беседки можно оформить, но заявки заполняем по очереди, чтобы не смешать даты и время.")
        lines.append("")
        lines.append(f"По первой беседке на {first}: во сколько хотите приехать?")
    else:
        lines.append("Две беседки можно оформить, но заявки заполняем по очереди, чтобы не смешать даты и время.")
        lines.append("")
        lines.append("Начнём с первой беседки. На какую дату её поставить?")
    return "\n".join(lines)


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
