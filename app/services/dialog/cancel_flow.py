from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from app.services.dialog.booking_texts import booking_line_short, booking_object_title
from app.services.dialog.formatting import format_date_ru

CancelFlowResult = tuple[str, str, str, str | None, dict[str, Any]]


@dataclass(frozen=True)
class CancelFlowCallbacks:
    active_user_bookings: Callable[..., list[dict[str, Any]]]
    get_booking_by_id: Callable[..., dict[str, Any] | None]
    cancel_booking_by_id: Callable[..., Any]
    delete_yclients_record_for_booking: Callable[..., bool]
    get_user_by_id: Callable[..., dict[str, Any] | None]
    start_user_handoff: Callable[..., Any]
    handoff_reply: Callable[[], str]
    confirmation_yes: Callable[[str], bool]
    confirmation_no: Callable[[str], bool]
    record_refund_required: Callable[..., Any] | None = None


def wants_cancel_booking(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if "доп" in normalized:
        return False
    if (
        any(marker in normalized for marker in ("откаж", "отказ"))
        and any(marker in normalized for marker in ("брон", "заявк", "запис", "оформ"))
    ):
        return True
    negative_cancel = (
        bool(re.search(r"\bне\s+(?:нужн\w*|надо|актуальн\w*)\b", normalized))
        or "планы поменялись" in normalized
        or "планы изменились" in normalized
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


def start_cancel_booking_flow(
    conn: Any,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    status: str,
    now: datetime,
    callbacks: CancelFlowCallbacks,
) -> CancelFlowResult:
    bookings = callbacks.active_user_bookings(conn, conversation, form_data, now)
    if not bookings:
        return (
            "Активной брони для отмены не нашла. Если нужно оформить новую бронь или проверить дату, напишите услугу и дату.",
            status,
            "reserved",
            "payment_status",
            form_data,
        )

    selected = select_cancel_bookings(bookings, None, text)
    booking = selected[0] if len(selected) == 1 else None
    flow: dict[str, Any] = {"stage": "confirm_cancel"}
    if len(selected) > 1:
        flow["booking_ids"] = [booking["id"] for booking in selected]
    elif booking:
        flow["booking_id"] = booking.get("id")
    else:
        flow["booking_id"] = None

    updated = {**form_data, "cancel_flow": flow}
    if len(selected) > 1:
        return cancel_many_confirmation_reply(selected, now), status, "reserved", "payment_status", updated
    if not booking:
        return cancel_selection_prompt(bookings), status, "reserved", "payment_status", updated
    return cancel_confirmation_reply(booking, now), status, "reserved", "payment_status", updated


def handle_cancel_booking_flow(
    conn: Any,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    now: datetime,
    callbacks: CancelFlowCallbacks,
) -> CancelFlowResult:
    bookings = callbacks.active_user_bookings(conn, conversation, form_data, now)
    status = (
        "payment_paid"
        if conversation.get("status") == "payment_paid" or any(booking.get("payment_status") == "paid" for booking in bookings)
        else "reserved"
    )
    flow = dict(form_data.get("cancel_flow") or {})
    flow_booking_ids = [int(item) for item in (flow.get("booking_ids") or [])]
    if flow.get("booking_id"):
        flow_booking_ids.append(int(flow["booking_id"]))
    if flow_booking_ids:
        known_ids = {int(booking["id"]) for booking in bookings}
        for booking_id in flow_booking_ids:
            if booking_id in known_ids:
                continue
            booking = callbacks.get_booking_by_id(conn, booking_id)
            if booking and booking.get("status") != "cancelled":
                bookings.append(booking)
                known_ids.add(booking_id)
    selected = select_cancel_bookings(bookings, flow, text)
    booking = selected[0] if len(selected) == 1 else None

    if not selected:
        flow = flow | {"stage": "confirm_cancel"}
        return cancel_selection_prompt(bookings), status, "reserved", "payment_status", {**form_data, "cancel_flow": flow}

    if not flow.get("booking_id") and not flow.get("booking_ids"):
        if len(selected) > 1:
            flow = flow | {"booking_ids": [item["id"] for item in selected], "stage": "confirm_cancel"}
            return cancel_many_confirmation_reply(selected, now), status, "reserved", "payment_status", {
                **form_data,
                "cancel_flow": flow,
            }
        flow = flow | {"booking_id": booking["id"], "stage": "confirm_cancel"}
        return cancel_confirmation_reply(booking, now), status, "reserved", "payment_status", {
            **form_data,
            "cancel_flow": flow,
        }

    if callbacks.confirmation_no(text):
        cleared = {**form_data, "cancel_flow": None}
        return "Хорошо, бронь оставила без изменений ✅", status, "reserved", "payment_status", cleared

    if not callbacks.confirmation_yes(text):
        if len(selected) > 1:
            return cancel_many_confirmation_reply(selected, now), status, "reserved", "payment_status", {
                **form_data,
                "cancel_flow": flow,
            }
        return cancel_confirmation_reply(booking, now), status, "reserved", "payment_status", {
            **form_data,
            "cancel_flow": flow,
        }

    if len(selected) > 1:
        for item in selected:
            old_booking = callbacks.get_booking_by_id(conn, int(item["id"])) or item
            if not callbacks.delete_yclients_record_for_booking(conn, old_booking):
                _handoff_on_cancel_error(
                    conn,
                    conversation=conversation,
                    text=text,
                    now=now,
                    reason="техническая ошибка: не удалось удалить несколько записей в журнале",
                    callbacks=callbacks,
                )
                return callbacks.handoff_reply(), "handoff", "handoff", "handoff", form_data
        for item in selected:
            callbacks.cancel_booking_by_id(conn, int(item["id"]), now)
            _record_refund_if_needed(conn, item, now, callbacks)
        cleared = {**form_data, "cancel_flow": None}
        return cancel_many_done_reply(selected, now), "payment_paid", "reserved", "payment_status", cleared

    old_booking = callbacks.get_booking_by_id(conn, int(booking["id"])) or booking
    if not callbacks.delete_yclients_record_for_booking(conn, old_booking):
        _handoff_on_cancel_error(
            conn,
            conversation=conversation,
            text=text,
            now=now,
            reason="техническая ошибка: не удалось удалить запись в журнале",
            callbacks=callbacks,
        )
        return callbacks.handoff_reply(), "handoff", "handoff", "handoff", form_data

    callbacks.cancel_booking_by_id(conn, int(booking["id"]), now)
    _record_refund_if_needed(conn, booking, now, callbacks)
    cleared = {**form_data, "cancel_flow": None}
    return cancel_done_reply(booking, now), "payment_paid", "reserved", "payment_status", cleared


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


def _record_refund_if_needed(
    conn: Any,
    booking: dict[str, Any],
    now: datetime | date | None,
    callbacks: CancelFlowCallbacks,
) -> None:
    if not callbacks.record_refund_required:
        return
    if booking.get("payment_status") != "paid":
        return
    if not advance_refund_allowed(booking, now):
        return
    callbacks.record_refund_required(conn, booking, now)


def _advance_rule_text(booking: dict[str, Any], now: datetime | date | None = None) -> str:
    if advance_refund_allowed(booking, now):
        return "аванс можно вернуть по правилам отмены, потому что до даты брони 7 дней или больше."
    return "аванс по правилам не возвращается, если до брони осталось меньше 7 дней."


def _advance_rule_text_for_many(bookings: list[dict[str, Any]], now: datetime | date | None = None) -> str:
    if bookings and all(advance_refund_allowed(booking, now) for booking in bookings):
        return "авансы можно вернуть по правилам отмены, потому что до дат брони 7 дней или больше."
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


def _handoff_on_cancel_error(
    conn: Any,
    *,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    reason: str,
    callbacks: CancelFlowCallbacks,
) -> None:
    user = callbacks.get_user_by_id(conn, int(conversation["user_id"]))
    if user:
        callbacks.start_user_handoff(
            conn,
            user=user,
            conversation_id=conversation["id"],
            text=text,
            now=now,
            reason=reason,
        )


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
