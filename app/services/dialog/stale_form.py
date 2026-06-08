from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.services.availability_service import load_services_map
from app.services.booking_form_service import initial_form_data, next_question
from app.services.dialog.formatting import format_date_ru, format_time_duration_range


@dataclass(frozen=True)
class StaleFormTextCallbacks:
    confirmation_yes: Callable[[str], bool]
    confirmation_no: Callable[[str], bool]
    service_type_patch: Callable[[str], dict[str, Any]]
    now_local: Callable[[], datetime]
    has_specific_date_signal: Callable[[str, datetime], bool]
    relative_date_patch: Callable[[str, datetime], dict[str, Any]]
    time_period_patch: Callable[[str], dict[str, Any]]
    has_explicit_duration_signal: Callable[[str], bool]
    guests_count_patch: Callable[[str, str], dict[str, Any]]
    wants_cancel_booking: Callable[[str], bool]
    wants_reschedule: Callable[[str], bool]
    wants_swap_bookings: Callable[[str], bool]
    asks_for_free_slots: Callable[[str], bool]
    starts_new_booking_request: Callable[[str], bool]


def new_booking_form_data(previous: dict[str, Any]) -> dict[str, Any]:
    fresh = initial_form_data()
    for key in ("client_name", "phone"):
        if previous.get(key):
            fresh[key] = previous[key]
    return fresh


def has_meaningful_unfinished_form(form_data: dict[str, Any]) -> bool:
    if not form_data or form_data.get("stale_form_flow"):
        return False
    meaningful_keys = (
        "service_type",
        "service_variant",
        "date",
        "time",
        "duration",
        "guests_count",
        "event_format",
        "upsell_items",
    )
    if not any(form_data.get(key) for key in meaningful_keys):
        return False
    return next_question(form_data)[0] is not None or bool(form_data.get("last_unavailable"))


def should_offer_stale_form_choice(conversation: dict[str, Any], now: datetime) -> bool:
    status = str(conversation.get("status") or "")
    current_step = str(conversation.get("current_step") or "")
    if status in {"reserved", "payment_paid", "handoff"} or current_step in {"reserved", "payment_status", "handoff"}:
        return False
    last_message_time = conversation.get("last_message_time")
    if not last_message_time:
        return False
    if last_message_time.tzinfo is None and now.tzinfo is not None:
        last_message_time = last_message_time.replace(tzinfo=now.tzinfo)
    if now - last_message_time < timedelta(hours=2):
        return False
    return has_meaningful_unfinished_form(conversation.get("form_data") or {})


def stale_form_choice_reply(form_data: dict[str, Any]) -> str:
    summary = stale_form_summary(form_data)
    return (
        "Мы давно не общались, поэтому уточню, чтобы не подтянуть старые данные случайно.\n\n"
        f"Сейчас в анкете уже есть:\n{summary}\n\n"
        "Продолжаем эту заявку или начнём новую анкету?"
    )


def stale_form_summary(form_data: dict[str, Any]) -> str:
    lines: list[str] = []
    service_type = form_data.get("service_type")
    if service_type:
        title = (load_services_map().get(service_type) or {}).get("title") or service_type
        if form_data.get("service_variant"):
            title = f"{title}: {form_data.get('service_variant')}"
        lines.append(f"- Услуга: {title}")
    if form_data.get("date"):
        lines.append(f"- Дата: {format_date_ru(form_data.get('date'))}")
    if form_data.get("time"):
        if form_data.get("duration"):
            lines.append(f"- Время: {format_time_duration_range(form_data.get('time'), form_data.get('duration'))}")
        else:
            lines.append(f"- Время: с {form_data.get('time')}")
    if form_data.get("guests_count"):
        lines.append(f"- Гостей: {form_data.get('guests_count')}")
    if form_data.get("event_format"):
        lines.append(f"- Формат: {form_data.get('event_format')}")
    upsells = form_data.get("upsell_items") or []
    if upsells:
        lines.append(f"- Допы: {', '.join(upsells)}")
    if form_data.get("client_name"):
        lines.append(f"- Имя: {form_data.get('client_name')}")
    if form_data.get("phone"):
        lines.append(f"- Телефон: {form_data.get('phone')}")
    return "\n".join(lines) if lines else "- Данные ещё не заполнены"


def wants_continue_stale_form(text: str, callbacks: StaleFormTextCallbacks) -> bool:
    normalized = text.lower().replace("ё", "е").strip()
    return callbacks.confirmation_yes(text) or any(
        marker in normalized
        for marker in ("продолж", "стар", "с этой", "эту заявку", "давай", "давайте")
    )


def wants_new_form_after_stale(text: str, callbacks: StaleFormTextCallbacks) -> bool:
    normalized = text.lower().replace("ё", "е").strip()
    compact = re.sub(r"[^\w]+", " ", normalized).strip()
    starts_with_no = bool(re.match(r"^(?:нет|не)\b", compact))
    return (
        callbacks.confirmation_no(text)
        or any(marker in normalized for marker in ("нов", "сначала", "заново", "другую заявку", "другая заявка"))
        or (starts_with_no and stale_message_has_new_booking_details(text, callbacks))
    )


def stale_message_has_new_booking_details(text: str, callbacks: StaleFormTextCallbacks) -> bool:
    if not callbacks.service_type_patch(text):
        return False
    now = callbacks.now_local()
    return bool(
        callbacks.has_specific_date_signal(text, now)
        or callbacks.relative_date_patch(text, now)
        or callbacks.time_period_patch(text)
        or callbacks.has_explicit_duration_signal(text)
        or callbacks.guests_count_patch(text, "guests_count")
    )


def stale_message_starts_new_context(text: str, callbacks: StaleFormTextCallbacks) -> bool:
    normalized = text.lower().replace("ё", "е")
    if callbacks.wants_cancel_booking(text) or callbacks.wants_reschedule(text) or callbacks.wants_swap_bookings(text):
        return False
    if wants_new_form_after_stale(text, callbacks):
        return True
    service_patch = callbacks.service_type_patch(text)
    if not service_patch:
        return False
    if stale_message_has_new_booking_details(text, callbacks) and any(
        marker in normalized
        for marker in ("хочу", "хотел", "хотела", "хотим", "нужн", "заброн", "брон", "оформ")
    ):
        return True
    if callbacks.asks_for_free_slots(text) or callbacks.starts_new_booking_request(text):
        return True
    return any(marker in normalized for marker in ("какие", "когда", "свобод", "хочу", "нужн", "заброн", "брон"))


def explicit_new_booking_with_details(text: str, callbacks: StaleFormTextCallbacks) -> bool:
    normalized = text.lower().replace("ё", "е")
    if not stale_message_has_new_booking_details(text, callbacks):
        return False
    return any(
        marker in normalized
        for marker in (
            "я бы хотел",
            "я бы хотела",
            "хотел бы",
            "хотела бы",
            "я хочу",
            "хочу оформить",
            "хочу заброн",
            "мне нужна",
            "мне нужен",
            "мне нужно",
        )
    )


def continue_stale_form_reply(
    form_data: dict[str, Any],
    confirmation_reply_text: Callable[[dict[str, Any]], str],
) -> tuple[str, str | None]:
    cleaned = dict(form_data)
    cleaned.pop("stale_form_flow", None)
    next_key, question = next_question(cleaned)
    if next_key is None:
        return confirmation_reply_text(cleaned), "confirmation"
    return f"Хорошо, продолжаем эту заявку ✅\n\n{question}", next_key
