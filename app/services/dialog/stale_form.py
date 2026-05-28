from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.availability_service import load_services_map
from app.services.booking_form_service import initial_form_data, next_question
from app.services.dialog.formatting import format_date_ru, format_time_duration_range


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
