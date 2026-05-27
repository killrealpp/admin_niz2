from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.services.dialog.booking_texts import booking_line_short, booking_object_title
from app.services.dialog.formatting import format_date_ru


def wants_cancel_booking(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if "доп" in normalized:
        return False
    negative_cancel = any(
        marker in normalized
        for marker in (
            "не нужна",
            "не нужен",
            "не нужно",
            "не надо",
            "не актуальна",
            "не актуально",
            "планы поменялись",
            "планы изменились",
        )
    ) and any(marker in normalized for marker in ("брон", "бан", "бесед", "дом", "услуг"))
    if negative_cancel:
        return True
    return any(
        marker in normalized
        for marker in (
            "отмен",
            "удал",
            "убери",
            "убрать",
            "убрать брон",
            "снять брон",
            "не сможем прийти",
            "не смогу прийти",
            "не получится приехать",
            "не получится прийти",
        )
    )


def wants_cancel_all_bookings(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "все брон",
            "все мои брон",
            "все записи",
            "все заявки",
            "всё брон",
            "всё мои брон",
            "всё записи",
            "всё заявки",
            "обе брон",
            "обе записи",
        )
    )


def select_cancel_bookings(
    bookings: list[dict[str, Any]],
    flow: dict[str, Any] | None,
    text: str,
) -> list[dict[str, Any]]:
    flow = flow or {}
    if flow.get("booking_ids"):
        ids = {int(booking_id) for booking_id in flow.get("booking_ids") or []}
        return [booking for booking in bookings if int(booking["id"]) in ids]
    if flow.get("booking_id"):
        booking_id = int(flow["booking_id"])
        return [booking for booking in bookings if int(booking["id"]) == booking_id]
    if wants_cancel_all_bookings(text):
        return list(bookings)

    indexes = _indexes_from_text(text, len(bookings))
    if indexes:
        return [bookings[index] for index in indexes]

    semantic_matches = _semantic_matches(bookings, text)
    if len(semantic_matches) == 1:
        return semantic_matches

    return bookings if len(bookings) == 1 else []


def cancel_selection_prompt(bookings: list[dict[str, Any]]) -> str:
    lines = ["Какую бронь отменяем?"]
    for index, item in enumerate(bookings, start=1):
        lines.append(f"{index}. {booking_line_short(item)}")
    lines.append("")
    lines.append("Напишите номер брони из списка. Можно указать несколько номеров или «все».")
    return "\n".join(lines)


def cancel_confirmation_reply(booking: dict[str, Any], now: datetime | date | None = None) -> str:
    return (
        f"Могу отменить бронь: {booking_line_short(booking)}.\n\n"
        f"Важно: {_advance_rule_text(booking, now)}\n\n"
        "Точно отменяем? Напишите «да» или «нет»."
    )


def cancel_many_confirmation_reply(bookings: list[dict[str, Any]], now: datetime | date | None = None) -> str:
    lines = ["Могу отменить эти брони:"]
    for booking in bookings:
        lines.append(f"- {booking_line_short(booking)}")
    lines.extend(
        [
            "",
            f"Важно: {_advance_rule_text_for_many(bookings, now)}",
            "",
            "Точно отменяем? Напишите «да» или «нет».",
        ]
    )
    return "\n".join(lines)


def cancel_done_reply(booking: dict[str, Any], now: datetime | date | None = None) -> str:
    return (
        f"Готово ✅\n\n"
        f"Отменила бронь: {booking_line_short(booking)}.\n\n"
        f"{_sentence_case(_advance_rule_text(booking, now))}"
    )


def cancel_many_done_reply(bookings: list[dict[str, Any]], now: datetime | date | None = None) -> str:
    lines = ["Готово ✅", "", "Отменила брони:"]
    for booking in bookings:
        lines.append(f"- {booking_line_short(booking)}")
    lines.extend(["", _sentence_case(_advance_rule_text_for_many(bookings, now))])
    return "\n".join(lines)


def advance_refund_allowed(booking: dict[str, Any], now: datetime | date | None = None) -> bool:
    booking_date = _booking_date(booking)
    if not booking_date:
        return False
    current_date = _current_date(now)
    return (booking_date - current_date).days >= 7


def _advance_rule_text(booking: dict[str, Any], now: datetime | date | None = None) -> str:
    if advance_refund_allowed(booking, now):
        return "аванс можно вернуть по правилам отмены, потому что до даты брони больше 7 дней."
    return "аванс по правилам не возвращается, если до брони осталось меньше 7 дней."


def _advance_rule_text_for_many(bookings: list[dict[str, Any]], now: datetime | date | None = None) -> str:
    if bookings and all(advance_refund_allowed(booking, now) for booking in bookings):
        return "авансы можно вернуть по правилам отмены, потому что до дат брони больше 7 дней."
    if any(advance_refund_allowed(booking, now) for booking in bookings):
        return "по части броней аванс можно вернуть за 7+ дней до даты, по ближайшим броням аванс не возвращается."
    return "авансы по правилам не возвращаются, если до брони осталось меньше 7 дней."


def _sentence_case(text: str) -> str:
    if not text:
        return text
    return text[:1].upper() + text[1:]


def _booking_date(booking: dict[str, Any]) -> date | None:
    value = booking.get("booking_date") or booking.get("slot_date") or booking.get("date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except ValueError:
            return None
    return None


def _current_date(now: datetime | date | None) -> date:
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    return date.today()


def _indexes_from_text(text: str, count: int) -> list[int]:
    normalized = text.lower().replace("ё", "е")
    indexes: list[int] = []
    for match in re.finditer(r"\b([1-9])\b", normalized):
        index = int(match.group(1)) - 1
        if 0 <= index < count and index not in indexes:
            indexes.append(index)
    ordinal_index = _ordinal_index(normalized)
    if ordinal_index is not None and 0 <= ordinal_index < count and ordinal_index not in indexes:
        indexes.append(ordinal_index)
    return indexes


def _semantic_matches(bookings: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    normalized = text.lower().replace("ё", "е")
    service_markers = {
        "bathhouse": ("бан",),
        "gazebo": ("бесед",),
        "house": ("дом", "домик", "коттедж"),
    }
    protected_services = _protected_services_from_cancel_text(normalized)
    requested_services = {
        service
        for service, markers in service_markers.items()
        if any(marker in normalized for marker in markers)
    } - protected_services
    matches = [
        booking
        for booking in bookings
        if booking.get("service_type") not in protected_services
        and (not requested_services or booking.get("service_type") in requested_services)
    ]

    variant_number = _gazebo_number(normalized)
    if variant_number:
        variant_matches = [
            booking
            for booking in matches
            if f"№{variant_number}" in booking_object_title(booking).replace(" ", "")
        ]
        if variant_matches:
            matches = variant_matches

    dated = [booking for booking in matches if _mentions_booking_date(normalized, booking)]
    if dated:
        matches = dated

    return matches


def _protected_services_from_cancel_text(normalized: str) -> set[str]:
    protected: set[str] = set()
    protections = ("не трог", "остав", "не отмен", "не удал", "пусть остан")
    service_patterns = {
        "bathhouse": r"бан[а-яё]*",
        "gazebo": r"бесед[а-яё]*",
        "house": r"(?:дом|домик|коттедж)[а-яё]*",
    }
    for service, pattern in service_patterns.items():
        if re.search(rf"{pattern}.{{0,24}}(?:{'|'.join(protections)})", normalized) or re.search(
            rf"(?:{'|'.join(protections)}).{{0,24}}{pattern}",
            normalized,
        ):
            protected.add(service)
    return protected


def _gazebo_number(normalized: str) -> str | None:
    patterns = (
        r"\bбеседк[а-яё]*\s*(?:№|номер\s*)?([1-8])\b",
        r"(?:№|номер)\s*([1-8])\b",
        r"\b([1-8])\s*(?:-?\s*)?(?:ю|ую|ая|я)?\s*беседк",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(1)
    return None


def _mentions_booking_date(normalized: str, booking: dict[str, Any]) -> bool:
    booking_date = booking.get("booking_date")
    if not booking_date:
        return False
    return format_date_ru(str(booking_date)).lower().replace("ё", "е") in normalized


def _ordinal_index(text: str) -> int | None:
    words = {
        "первую": 0,
        "первая": 0,
        "первый": 0,
        "первое": 0,
        "вторую": 1,
        "вторая": 1,
        "второй": 1,
        "второе": 1,
        "третью": 2,
        "третья": 2,
        "третий": 2,
        "третье": 2,
        "четвертую": 3,
        "четвертая": 3,
        "четвертый": 3,
        "четвертое": 3,
        "пятую": 4,
        "пятая": 4,
        "пятый": 4,
        "пятое": 4,
    }
    for word, index in words.items():
        if re.search(rf"\b{word}\b", text):
            return index
    return None
