from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from app.core.config import get_settings
from app.db.repositories import bookings_repo, system_logs_repo, users_repo
from app.services.dialog.booking_texts import booking_line_short


def handoff_active(user: dict[str, Any], now: datetime) -> bool:
    until = user.get("handoff_until")
    if not until:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=now.tzinfo)
    return until > now


def is_location_question(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    location_markers = (
        "где вы находитесь",
        "где находитесь",
        "где находится",
        "где вы",
        "какой адрес",
        "адрес",
        "как добраться",
        "куда ехать",
        "локация",
    )
    return any(marker in normalized for marker in location_markers)


def looks_like_handoff_needed(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if is_location_question(normalized):
        return False
    complaint_markers = (
        "ужас",
        "кошмар",
        "обман",
        "верните деньги",
        "возврат",
        "жалоб",
        "разберитесь",
        "плохо работает",
        "не работает",
        "вы что",
        "ты что",
        "в своем уме",
        "в своём уме",
        "почему так",
    )
    if any(marker in normalized for marker in complaint_markers):
        return True
    rude_patterns = (
        r"(?<![а-яa-z0-9])дурак(?:[а-яa-z]*)?(?![а-яa-z0-9])",
        r"(?<![а-яa-z0-9])туп(?:ой|ая|ые|о|ые|ите|ишь)?(?![а-яa-z0-9])",
        r"(?<![а-яa-z0-9])идиот(?:[а-яa-z]*)?(?![а-яa-z0-9])",
        r"(?<![а-яa-z0-9])бесит(?:е|ь)?(?![а-яa-z0-9])",
        r"(?<![а-яa-z0-9])задолбал(?:[а-яa-z]*)?(?![а-яa-z0-9])",
        r"(?<![а-яa-z0-9])хрен(?:[а-яa-z]*)?(?![а-яa-z0-9])",
        r"(?<![а-яa-z0-9])нах(?:уй|ер)?(?![а-яa-z0-9])",
    )
    return any(re.search(pattern, normalized) for pattern in rude_patterns)


def start_user_handoff(
    conn,
    *,
    user: dict[str, Any],
    conversation_id: int,
    text: str,
    now: datetime,
    reason: str = "нестандартное поведение, критика или конфликт",
) -> None:
    settings = get_settings()
    phone = user.get("phone") or ""
    bookings = bookings_repo.list_future_active_for_user(
        conn,
        user_id=int(user["id"]),
        now=now,
        limit=10,
    )
    booking_lines = "\n".join(
        f"- {booking_line_short(booking)}; статус оплаты: {booking.get('payment_status')}"
        for booking in bookings
    )
    summary = (
        f"Последнее сообщение клиента: {text[:700]}\n"
        f"Пользователь: {user.get('name') or 'не указано'}\n"
        f"Telegram ID: {user.get('external_id')}\n"
        f"Телефон: {phone or 'не указан'}\n"
        f"Активные брони:\n{booking_lines or 'нет активных будущих броней'}"
    )
    until = now + timedelta(minutes=settings.handoff_ttl_minutes)
    users_repo.set_handoff(
        conn,
        user_id=user["id"],
        until=until,
        reason=reason,
        summary=summary,
    )
    system_logs_repo.create(
        conn,
        level="warning",
        event_type="human_handoff",
        message=reason,
        conversation_id=conversation_id,
        payload={
            "user_id": user["id"],
            "external_id": user.get("external_id"),
            "text": text[:1000],
            "until": until.isoformat(),
        },
    )
