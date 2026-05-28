from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from app.services.availability_service import load_services_map
from app.services.dialog.booking_texts import booking_line_short, booking_object_title
from app.services.dialog.date_parsing import (
    date_patch_after_marker,
    date_patch_in_segment,
    last_explicit_date_patch,
    relative_date_patch,
    reschedule_source_target_day_patch,
)
from app.services.dialog.formatting import format_date_ru, format_duration, hours_from_minutes
from app.services.dialog.form_patches import (
    looks_like_prior_booking_reference_text,
    service_type_patch,
    service_variant_patch,
)
from app.services.dialog.gazebo_options import (
    available_gazebo_variant_configs,
    format_gazebo_variant_line,
    normalize_gazebo_title,
    remember_available_gazebo_variants,
    selected_variant_config,
)
from app.services.dialog.time_parsing import time_period_patch

RescheduleFlowResult = tuple[str, str, str, str | None, dict[str, Any]]


@dataclass(frozen=True)
class RescheduleExecutionCallbacks:
    get_booking_by_id: Callable[..., dict[str, Any] | None]
    delete_yclients_record_for_booking: Callable[..., bool]
    duration_minutes_value: Callable[[Any], int]
    update_booking_schedule: Callable[..., dict[str, Any] | None]
    update_booking_details: Callable[..., dict[str, Any] | None]
    update_slot: Callable[..., dict[str, Any] | None]
    now_local: Callable[[], datetime]
    upsert_local_busy_interval_for_booking: Callable[..., Any]
    create_yclients_record_for_booking: Callable[..., Any]
    staff_id_for_service_id: Callable[[str | None, str | None], str]
    get_user_by_id: Callable[..., dict[str, Any] | None]
    start_user_handoff: Callable[..., Any]
    handoff_reply: Callable[[], str]
    log_exception: Callable[..., Any]


@dataclass(frozen=True)
class SwapRescheduleCallbacks:
    active_user_bookings: Callable[..., list[dict[str, Any]]]
    conversation_bookings_for_active_flow: Callable[..., list[dict[str, Any]]]
    confirmation_yes: Callable[[str], bool]
    confirmation_no: Callable[[str], bool]
    check_availability: Callable[..., Any]
    append_waitlist_offer: Callable[[str, dict[str, Any] | None], str]
    start_reschedule_flow: Callable[[Any, dict[str, Any], str, dict[str, Any], str, datetime], RescheduleFlowResult]
    execute_swap_reschedule: Callable[
        [Any, dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]],
        RescheduleFlowResult,
    ]


def wants_reschedule(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "перенес",
            "перенеси",
            "перенести",
            "перенесешь",
            "перенесёшь",
            "пернести",
            "перенос",
            "сдвин",
            "смест",
            "поменять дату",
            "изменить дату",
            "другую дату",
            "поменять время",
            "изменить время",
            "поменять местами",
            "местами",
            "поменять брони",
        )
    )


def wants_swap_bookings(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return (
        "местами" in normalized
        and any(marker in normalized for marker in ("брон", "дат", "бесед", "бан", "помен", "обмен"))
    ) or (
        "поменять даты" in normalized
        and any(marker in normalized for marker in ("две", "2", "обе", "брон"))
    )


def wants_multi_booking_reschedule(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("обе", "оба", "все брони", "все брон", "две брони", "2 брони")) or (
        "обе" in normalized and any(marker in normalized for marker in ("бесед", "бан", "услуг"))
    )


def asks_reschedule_options(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return (
        "как" in normalized
        and any(marker in normalized for marker in ("перенест", "перенес", "пернос", "поменять"))
    ) or (
        "вариант" in normalized
        and any(marker in normalized for marker in ("перенос", "перенест", "поменять"))
    )


def reschedule_options_reply(bookings: list[dict[str, Any]]) -> str:
    lines = [
        "Можно перенести одну бронь или несколько сразу ✅",
        "",
        "Напишите в свободной форме, например:",
        "- «первую бронь на 27 июня»",
        "- «обе брони на 29 июня»",
        "- «Беседку №4 на 27 июня, Беседку №1 на 29 июня»",
        "",
        "Я проверю журнал и скажу, получится ли так перенести.",
    ]
    if bookings:
        lines.extend(["", "Сейчас вижу такие брони:"])
        for index, booking in enumerate(bookings, start=1):
            lines.append(f"{index}. {booking_line_short(booking)}")
    return "\n".join(lines)


def swap_collect_reply(bookings: list[dict[str, Any]]) -> str:
    lines = [
        "Поняла, хотите изменить несколько броней ✅",
        "",
        "Напишите, пожалуйста, конкретно что куда переносим. Например:",
        "«Беседка №4 на 26 июня, Беседка №1 на 29 мая»",
        "или «обе брони на 27 июня».",
        "",
        "Сейчас вижу такие брони:",
    ]
    for index, booking in enumerate(bookings, start=1):
        lines.append(f"{index}. {booking_line_short(booking)}")
    return "\n".join(lines)


def swap_confirmation_reply(bookings: list[dict[str, Any]], assignments: list[dict[str, Any]]) -> str:
    by_id = {int(booking["id"]): booking for booking in bookings}
    lines = ["Проверила по журналу, такой перенос возможен ✅", "", "Подтвердите, пожалуйста:"]
    for assignment in assignments:
        booking = by_id.get(int(assignment["booking_id"]))
        if not booking:
            continue
        lines.append(
            f"- {booking_line_short(booking)} → {format_date_ru(assignment['date'])}, "
            f"с {assignment['time']} на {format_duration(assignment.get('duration'))}"
        )
    lines.extend(["", "Авансы сохраняются. Подтверждаете перенос? Напишите «да» или «нет»."])
    return "\n".join(lines)


def parse_swap_assignments(text: str, bookings: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    normalized = text.lower().replace("ё", "е")
    positions: list[tuple[int, int, dict[str, Any]]] = []
    used: set[int] = set()
    for booking in bookings:
        booking_id = int(booking["id"])
        for pattern in booking_reference_patterns(booking, bookings):
            match = re.search(pattern, normalized)
            if match and booking_id not in used:
                positions.append((match.start(), match.end(), booking))
                used.add(booking_id)
                break
    positions.sort(key=lambda item: item[0])
    assignments: list[dict[str, Any]] = []
    last_target: dict[str, Any] | None = None
    for index, (_start, end, booking) in enumerate(positions):
        next_start = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        segment = text[end:next_start]
        base_date = booking.get("booking_date") if isinstance(booking.get("booking_date"), date) else None
        date_patch = date_patch_in_segment(segment, now, base_date=base_date)
        if not date_patch.get("date") and last_target and means_same_target(segment):
            date_patch = {"date": last_target["date"]}
        if not date_patch.get("date"):
            continue
        time_patch = time_period_patch(segment)
        target = {
            "booking_id": booking["id"],
            "date": date_patch["date"],
            "time": time_patch.get("time") or str(booking.get("booking_time"))[:5],
            "duration": time_patch.get("duration") or hours_from_minutes(booking.get("duration_minutes")),
        }
        assignments.append(target)
        last_target = target
    return assignments


def same_target_assignments_for_bookings(
    text: str,
    bookings: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    if len(bookings) < 2 or not wants_multi_booking_reschedule(text):
        return []
    first_booking_date = bookings[0].get("booking_date") if isinstance(bookings[0].get("booking_date"), date) else None
    date_patch = date_patch_in_segment(text, now, base_date=first_booking_date)
    if not date_patch.get("date"):
        return []
    time_patch = time_period_patch(text)
    assignments: list[dict[str, Any]] = []
    for booking in bookings:
        assignments.append(
            {
                "booking_id": booking["id"],
                "date": date_patch["date"],
                "time": time_patch.get("time") or str(booking.get("booking_time"))[:5],
                "duration": time_patch.get("duration") or hours_from_minutes(booking.get("duration_minutes")),
            }
        )
    return assignments


def means_same_target(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("тоже", "также", "туда же", "на эту же", "на тот же", "то же"))


def means_same_time(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if any(
        marker in normalized
        for marker in (
            "то же время",
            "тоже время",
            "такое же время",
            "в это же время",
            "время то же",
            "время такое же",
        )
    ):
        return True
    if any(marker in normalized for marker in ("час", "время")) and any(
        marker in normalized
        for marker in (
            "те же",
            "так же",
            "также",
            "как там",
            "как было",
            "без изменений",
        )
    ):
        return True
    return False


def means_same_date(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "ту же дату",
            "та же дата",
            "то же число",
            "на то же число",
            "число то же",
            "число такое же",
            "тот же день",
            "тем же днем",
            "тем же днём",
            "на тот же день",
            "на ту же дату",
            "в этот же день",
            "дата та же",
            "такую же дату",
        )
    )


def referenced_service_type_for_same_time(text: str) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if "бесед" in normalized:
        return "gazebo"
    if "бан" in normalized:
        return "bathhouse"
    if "дом" in normalized or "домик" in normalized or "коттедж" in normalized:
        return "house"
    return None


def preserve_current_service_for_reference(
    patch: dict[str, Any],
    current_form_data: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    current_service = current_form_data.get("service_type")
    requested_service = patch.get("service_type")
    if (
        current_service
        and requested_service
        and requested_service != current_service
        and looks_like_prior_booking_reference_text(text)
    ):
        cleaned = dict(patch)
        cleaned.pop("service_type", None)
        cleaned.pop("preferences", None)
        return cleaned
    return patch


def means_same_object(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "та же бесед",
            "ту же бесед",
            "эта же бесед",
            "эту же бесед",
            "тот же объект",
            "тот же вариант",
            "оставляем",
            "оставить",
        )
    )


def means_change_object(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "другую бесед",
            "другая бесед",
            "поменять бесед",
            "сменить бесед",
            "заменить бесед",
            "замен",
            "замеить",
            "на другую",
            "не эту",
            "поменьше",
            "меньше",
            "не такая большая",
            "не большая",
            "подешевле",
            "дешевле",
            "за 5800",
            "со светом",
            "светом",
            "розет",
        )
    )


def booking_reference_patterns(booking: dict[str, Any], bookings: list[dict[str, Any]]) -> list[str]:
    title = booking_object_title(booking).lower().replace("ё", "е")
    patterns: list[str] = []
    number_match = re.search(r"№\s*(\d+)", title)
    if number_match:
        number = number_match.group(1)
        patterns.extend(
            [
                rf"беседк[а-я\s]*(?:номер|№)?\s*{number}\b",
                rf"(?:номер|№)\s*{number}\b",
            ]
        )
        ordinal = {
            "1": "перв",
            "2": "втор",
            "3": "трет",
            "4": "четверт",
            "5": "пят",
            "6": "шест",
            "8": "восьм",
        }.get(number)
        if ordinal:
            patterns.append(rf"{ordinal}[а-я]*\s+беседк[а-я]*")
    if booking.get("service_type") == "bathhouse":
        patterns.append(r"бан[а-я]*")
    if booking.get("service_type") == "house":
        patterns.append(r"дом[а-я]*")
    try:
        index = bookings.index(booking) + 1
    except ValueError:
        index = 0
    ordinal_by_index = {1: "перв", 2: "втор", 3: "трет", 4: "четверт"}.get(index)
    if ordinal_by_index:
        patterns.append(rf"{ordinal_by_index}[а-я]*\s+(?:брон[а-я]*|беседк[а-я]*|бан[а-я]*|услуг[а-я]*)")
    ordinal_forms = {
        1: ("первую", "первая", "первой", "первую"),
        2: ("вторую", "вторая", "второй", "второе"),
        3: ("третью", "третья", "третьей", "третье"),
        4: ("четвертую", "четвертая", "четвертой", "четвертое"),
    }.get(index, ())
    patterns.extend(rf"\b{form}\b" for form in ordinal_forms)
    return patterns


def initial_reschedule_flow_patch(
    text: str,
    deterministic_patch: dict[str, Any],
) -> dict[str, Any]:
    flow_patch: dict[str, Any] = {}
    if deterministic_patch.get("date"):
        flow_patch["date"] = deterministic_patch["date"]
    if deterministic_patch.get("time"):
        flow_patch["time"] = deterministic_patch["time"]
    if deterministic_patch.get("duration"):
        flow_patch["duration"] = deterministic_patch["duration"]
    if means_same_time(text):
        flow_patch["same_time"] = True
    if means_same_object(text):
        flow_patch["same_object"] = True
    if means_change_object(text):
        flow_patch["same_object"] = False
        flow_patch["change_object"] = True
    variant = (reschedule_service_variant_patch(text) or {}).get("service_variant")
    if variant:
        flow_patch["service_variant"] = variant
        flow_patch["same_object"] = False
        flow_patch["change_object"] = True
    return flow_patch


def reschedule_service_variant_patch(text: str, *, allow_bare: bool = False) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    variants: list[tuple[int, str]] = []
    patterns = (
        r"\bбеседк[а-яё]*\s*(?:на\s*)?(?:№|номер\s*)?([1-8])\b",
        r"(?:№|номер)\s*([1-8])\b",
        r"\b([1-8])\s*(?:-?\s*)?(?:ю|ую|ая|я)?\s*беседк",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            variants.append((match.start(), f"Беседка №{match.group(1)}"))
    if "крыт" in normalized and "бесед" in normalized:
        variants.append((normalized.find("крыт"), "Крытая беседка"))
    if variants:
        variants.sort(key=lambda item: item[0])
        return {"service_variant": variants[-1][1]}
    if "бесед" in normalized:
        ordinal_patch = service_variant_patch(text, allow_bare_ordinal=True)
        if ordinal_patch.get("service_variant"):
            return {"service_variant": ordinal_patch["service_variant"]}
    if allow_bare:
        return service_variant_patch(text, allow_bare_ordinal=True)
    return {}


def filter_reschedule_gazebo_options(
    variants: list[dict[str, Any]],
    booking: dict[str, Any],
    flow: dict[str, Any],
    text: str,
) -> list[dict[str, Any]]:
    normalized = text.lower().replace("ё", "е")
    current_title = normalize_gazebo_title(booking_object_title(booking))
    current_capacity = gazebo_capacity_by_title(booking_object_title(booking))
    guests = flow.get("guests_count")
    wants_smaller = bool(flow.get("wants_smaller")) or any(
        marker in normalized for marker in ("поменьше", "меньше", "не большая", "не такая большая", "подешевле", "дешевле")
    )
    wants_light = bool(flow.get("wants_light")) or "свет" in normalized or "розет" in normalized
    price_limit = flow.get("price_limit") or price_limit_from_text(text)
    result: list[dict[str, Any]] = []
    for variant in variants:
        title = str(variant.get("title") or "")
        if normalize_gazebo_title(title) == current_title:
            continue
        capacity = int(variant.get("capacity_max") or 0)
        if guests and capacity and capacity < int(guests):
            continue
        if wants_smaller and current_capacity and capacity and capacity > current_capacity:
            continue
        if wants_light and not gazebo_variant_has_light(title):
            continue
        price = int(variant.get("price") or 0)
        if price_limit and price and price > price_limit:
            continue
        result.append(variant)
    return sorted(result, key=lambda item: (int(item.get("capacity_max") or 9999), int(item.get("price") or 999999)))


def gazebo_capacity_by_title(title: str) -> int | None:
    normalized = normalize_gazebo_title(title)
    for variant in (load_services_map().get("gazebo") or {}).get("variants") or []:
        if normalize_gazebo_title(variant.get("title")) == normalized:
            return int(variant.get("capacity_max") or 0)
    return None


def gazebo_variant_has_light(title: str) -> bool:
    normalized = normalize_gazebo_title(title)
    return any(marker in normalized for marker in ("№1", "№3", "№8", "крыт"))


def price_limit_from_text(text: str) -> int | None:
    normalized = text.lower().replace(" ", "")
    match = re.search(r"(?:за|до)?(\d{4,5})(?:р|руб|₽)?", normalized)
    if not match:
        return None
    value = int(match.group(1))
    return value if value >= 1000 else None


def execute_reschedule(
    conn: Any,
    conversation: dict[str, Any],
    booking: dict[str, Any],
    form_data: dict[str, Any],
    flow: dict[str, Any],
    callbacks: RescheduleExecutionCallbacks,
) -> RescheduleFlowResult:
    target_date = flow.get("date")
    target_time = flow.get("time")
    target_duration = flow.get("duration")
    old_booking = callbacks.get_booking_by_id(conn, int(booking["id"])) or booking
    if not callbacks.delete_yclients_record_for_booking(conn, old_booking):
        return (
            "Сейчас не получилось изменить запись в журнале.\n\n"
            "Старую бронь оставила без изменений. Напишите другую дату или время — проверю ещё раз.",
            "payment_paid",
            "reserved",
            "payment_status",
            {**form_data, "reschedule_flow": None},
        )

    new_date = datetime.fromisoformat(str(target_date)).date()
    new_time = datetime.strptime(str(target_time)[:5], "%H:%M").time()
    new_duration = callbacks.duration_minutes_value(target_duration)
    target_form = form_data_for_booking_reschedule(form_data, old_booking, flow)
    target_variant_config = selected_variant_config(target_form)
    target_yclients_service_id = str(
        target_variant_config.get("yclients_service_id")
        or old_booking.get("hold_yclients_service_id")
        or ""
    )
    target_yclients_staff_id = str(target_variant_config.get("yclients_staff_id") or "")
    updated_booking = callbacks.update_booking_schedule(
        conn,
        int(booking["id"]),
        new_date,
        new_time,
        new_duration,
    )
    if updated_booking and flow.get("guests_count"):
        updated_booking = callbacks.update_booking_details(
            conn,
            int(booking["id"]),
            int(flow["guests_count"]),
        ) or updated_booking
    if updated_booking:
        if updated_booking.get("slot_hold_id"):
            updated_hold = callbacks.update_slot(
                conn,
                int(updated_booking["slot_hold_id"]),
                target_yclients_service_id,
                target_yclients_staff_id,
                new_date,
                new_time,
                new_duration,
                callbacks.now_local(),
            )
            if updated_hold:
                target_yclients_service_id = str(updated_hold.get("yclients_service_id") or target_yclients_service_id)
        updated_booking = {
            **updated_booking,
            "hold_yclients_service_id": target_yclients_service_id,
        }
        callbacks.upsert_local_busy_interval_for_booking(conn, updated_booking)
        try:
            callbacks.create_yclients_record_for_booking(conn, updated_booking)
        except Exception:
            callbacks.log_exception(
                "Failed to create YCLIENTS record after reschedule booking_id=%s",
                booking.get("id"),
            )
            restored = restore_booking_after_failed_reschedule(conn, old_booking, callbacks)
            if restored:
                return (
                    "Новое время не получилось закрепить в журнале: похоже, слот уже занят или недоступен.\n\n"
                    f"Старую бронь восстановила: {booking_line_short(restored)}.\n\n"
                    "Напишите другую дату или время — проверю ещё раз.",
                    "payment_paid",
                    "reserved",
                    "payment_status",
                    {**form_data, "reschedule_flow": None},
                )
            _handoff_on_reschedule_restore_error(conn, conversation, booking, callbacks)
            return callbacks.handoff_reply(), "handoff", "handoff", "handoff", form_data
    cleared = {**form_data, "date": target_date, "time": target_time, "duration": target_duration, "reschedule_flow": None}
    if flow.get("guests_count"):
        cleared["guests_count"] = flow.get("guests_count")
    variant_line = ""
    if booking.get("service_type") == "gazebo" and flow.get("service_variant"):
        cleared["service_variant"] = flow.get("service_variant")
        variant_line = f"\nБеседка: {flow.get('service_variant')}."
    return (
        f"Готово ✅\n\nПеренесла бронь на {format_date_ru(target_date)}, с {target_time} "
        f"на {format_duration(target_duration)}.{variant_line}\n\n"
        "Аванс сохраняется, остаток можно будет внести на месте.",
        "payment_paid",
        "reserved",
        "payment_status",
        cleared,
    )


def restore_booking_after_failed_reschedule(
    conn: Any,
    old_booking: dict[str, Any],
    callbacks: RescheduleExecutionCallbacks,
) -> dict[str, Any] | None:
    old_date = old_booking.get("booking_date")
    old_time = old_booking.get("booking_time")
    old_duration = old_booking.get("duration_minutes")
    if not old_date or not old_time:
        return None
    restored = callbacks.update_booking_schedule(
        conn,
        int(old_booking["id"]),
        old_date,
        old_time,
        old_duration,
    )
    if not restored:
        return None
    if restored.get("slot_hold_id"):
        callbacks.update_slot(
            conn,
            int(restored["slot_hold_id"]),
            str(old_booking.get("hold_yclients_service_id") or ""),
            callbacks.staff_id_for_service_id(
                str(old_booking.get("service_type") or ""),
                str(old_booking.get("hold_yclients_service_id") or ""),
            ),
            old_date,
            old_time,
            old_duration,
            callbacks.now_local(),
        )
    restored = {
        **restored,
        "hold_yclients_service_id": old_booking.get("hold_yclients_service_id"),
    }
    try:
        callbacks.create_yclients_record_for_booking(conn, restored)
    except Exception:
        callbacks.log_exception("Failed to restore old YCLIENTS record booking_id=%s", old_booking.get("id"))
        callbacks.upsert_local_busy_interval_for_booking(conn, restored)
        return restored
    return callbacks.get_booking_by_id(conn, int(old_booking["id"])) or restored


def execute_swap_reschedule(
    conn: Any,
    conversation: dict[str, Any],
    bookings: list[dict[str, Any]],
    form_data: dict[str, Any],
    flow: dict[str, Any],
    callbacks: RescheduleExecutionCallbacks,
) -> RescheduleFlowResult:
    by_id = {int(booking["id"]): booking for booking in bookings}
    assignments = list(flow.get("assignments") or [])
    old_bookings: list[dict[str, Any]] = []
    for assignment in assignments:
        booking = callbacks.get_booking_by_id(conn, int(assignment["booking_id"])) or by_id.get(int(assignment["booking_id"]))
        if booking:
            old_bookings.append(booking)
    if len(old_bookings) < len(assignments):
        return (
            "Не смогла найти одну из броней для переноса. Напишите, пожалуйста, какие брони переносим — проверю заново.",
            "payment_paid",
            "reserved",
            "payment_status",
            {**form_data, "swap_reschedule_flow": None, "reschedule_flow": None},
        )

    deleted_old: list[dict[str, Any]] = []
    for booking in old_bookings:
        if not callbacks.delete_yclients_record_for_booking(conn, booking):
            for deleted in deleted_old:
                restore_booking_after_failed_reschedule(conn, deleted, callbacks)
            return (
                "Сейчас не получилось изменить одну из записей в журнале.\n\n"
                "Старые брони оставила без изменений. Напишите другой вариант переноса — проверю ещё раз.",
                "payment_paid",
                "reserved",
                "payment_status",
                {**form_data, "swap_reschedule_flow": None, "reschedule_flow": None},
            )
        deleted_old.append(booking)

    updated_bookings: list[dict[str, Any]] = []
    try:
        for assignment, old_booking in zip(assignments, old_bookings, strict=False):
            new_date = datetime.fromisoformat(str(assignment["date"])).date()
            new_time = datetime.strptime(str(assignment["time"])[:5], "%H:%M").time()
            new_duration = callbacks.duration_minutes_value(assignment.get("duration"))
            updated = callbacks.update_booking_schedule(
                conn,
                int(old_booking["id"]),
                new_date,
                new_time,
                new_duration,
            )
            if not updated:
                raise RuntimeError(f"booking #{old_booking.get('id')} was not updated")
            updated = callbacks.get_booking_by_id(conn, int(updated["id"])) or updated
            updated_bookings.append(updated)
        for updated in updated_bookings:
            callbacks.create_yclients_record_for_booking(conn, updated)
    except Exception:
        callbacks.log_exception("Failed to execute grouped reschedule")
        restored_lines: list[str] = []
        for old_booking in old_bookings:
            restored = restore_booking_after_failed_reschedule(conn, old_booking, callbacks)
            if restored:
                restored_lines.append(booking_line_short(restored))
        restored_text = (
            "\n".join(f"- {line}" for line in restored_lines)
            if restored_lines
            else "старые брони оставила в базе, но журнал нужно проверить вручную"
        )
        return (
            "Новое время не получилось закрепить в журнале: похоже, один из слотов уже занят или недоступен.\n\n"
            f"Старые брони восстановила:\n{restored_text}\n\n"
            "Напишите другой вариант переноса — проверю ещё раз.",
            "payment_paid",
            "reserved",
            "payment_status",
            {**form_data, "swap_reschedule_flow": None, "reschedule_flow": None},
        )

    done = [
        f"{booking_object_title(booking)} → {format_date_ru(str(booking.get('booking_date')))}, с {str(booking.get('booking_time'))[:5]}"
        for booking in updated_bookings
    ]
    cleared = {**form_data, "swap_reschedule_flow": None, "reschedule_flow": None}
    return (
        "Готово ✅\n\nОбновила брони по вашему варианту:\n"
        + "\n".join(f"- {item}" for item in done)
        + "\n\nАвансы сохраняются, разницу при необходимости можно будет доплатить на месте.",
        "payment_paid",
        "reserved",
        "payment_status",
        cleared,
    )


def prepare_swap_reschedule(
    conn: Any,
    conversation: dict[str, Any],
    bookings: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    form_data: dict[str, Any],
    status: str,
    now: datetime,
    callbacks: SwapRescheduleCallbacks,
) -> RescheduleFlowResult:
    by_id = {int(booking["id"]): booking for booking in bookings}
    normalized_assignments: list[dict[str, Any]] = []
    unavailable: list[str] = []
    ignore_source_record_ids = [
        str(booking.get("yclients_record_id"))
        for booking in bookings
        if booking.get("yclients_record_id")
    ]
    for assignment in assignments:
        booking = by_id.get(int(assignment["booking_id"]))
        if not booking:
            continue
        flow = {
            "booking_id": booking["id"],
            "date": assignment["date"],
            "time": assignment.get("time") or str(booking.get("booking_time"))[:5],
            "duration": assignment.get("duration") or hours_from_minutes(booking.get("duration_minutes")),
        }
        check_form = form_data_for_booking_reschedule(
            {**form_data, "ignore_source_record_ids": ignore_source_record_ids},
            booking,
            flow,
        )
        availability = callbacks.check_availability(conn, form_data=check_form, now=now)
        if availability.ok and not availability.slots:
            unavailable.append(f"{booking_object_title(booking)} на {format_date_ru(flow['date'])}, с {flow['time']}")
            continue
        normalized_assignments.append(flow)
    if unavailable:
        return (
            "Так перенести не получится: по журналу не свободно:\n"
            + "\n".join(f"- {item}" for item in unavailable)
            + "\n\nНапишите другой вариант переноса — проверю заново.",
            status,
            "reserved",
            "payment_status",
            {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}},
        )
    if len(normalized_assignments) < 2:
        return (
            swap_collect_reply(bookings),
            status,
            "reserved",
            "payment_status",
            {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}},
        )
    flow = {"stage": "confirm_swap", "assignments": normalized_assignments}
    return (
        swap_confirmation_reply(bookings, normalized_assignments),
        status,
        "reserved",
        "payment_status",
        {**form_data, "swap_reschedule_flow": flow, "reschedule_flow": None},
    )


def handle_swap_reschedule_flow(
    conn: Any,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    now: datetime,
    callbacks: SwapRescheduleCallbacks,
) -> RescheduleFlowResult:
    bookings = callbacks.active_user_bookings(conn, conversation, form_data, now)
    if not bookings:
        bookings = callbacks.conversation_bookings_for_active_flow(conn, conversation)
    status = (
        "payment_paid"
        if conversation.get("status") == "payment_paid" or any(booking.get("payment_status") == "paid" for booking in bookings)
        else "reserved"
    )
    flow = dict(form_data.get("swap_reschedule_flow") or {})
    if flow.get("stage") == "confirm_swap":
        if callbacks.confirmation_no(text):
            return "Хорошо, оставила брони без изменений ✅", status, "reserved", "payment_status", {**form_data, "swap_reschedule_flow": None}
        if callbacks.confirmation_yes(text):
            return callbacks.execute_swap_reschedule(conn, conversation, bookings, form_data, flow)
        return swap_confirmation_reply(bookings, flow.get("assignments") or []), status, "reserved", "payment_status", form_data

    assignments = same_target_assignments_for_bookings(text, bookings, now) or parse_swap_assignments(text, bookings, now)
    if len(assignments) < 2:
        return swap_collect_reply(bookings), status, "reserved", "payment_status", form_data
    return prepare_swap_reschedule(conn, conversation, bookings, assignments, form_data, status, now, callbacks)


def start_swap_reschedule_flow(
    conn: Any,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    status: str,
    now: datetime,
    callbacks: SwapRescheduleCallbacks,
) -> RescheduleFlowResult:
    bookings = callbacks.active_user_bookings(conn, conversation, form_data, now)
    if len(bookings) < 2:
        fallback_bookings = callbacks.conversation_bookings_for_active_flow(conn, conversation)
        if len(fallback_bookings) >= 2:
            bookings = fallback_bookings
    if len(bookings) < 2:
        return callbacks.start_reschedule_flow(conn, conversation, text, form_data, status, now)
    status = "payment_paid" if any(booking.get("payment_status") == "paid" for booking in bookings) else status
    same_target_assignments = same_target_assignments_for_bookings(text, bookings, now)
    if len(same_target_assignments) >= 2:
        updated = {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}, "reschedule_flow": None}
        return prepare_swap_reschedule(conn, conversation, bookings, same_target_assignments, updated, status, now, callbacks)
    assignments = parse_swap_assignments(text, bookings, now)
    updated = {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}, "reschedule_flow": None}
    if len(assignments) >= 2:
        return prepare_swap_reschedule(conn, conversation, bookings, assignments, updated, status, now, callbacks)
    return swap_collect_reply(bookings), status, "reserved", "payment_status", updated


def reschedule_gazebo_change_options_reply(
    conn: Any,
    conversation: dict[str, Any],
    booking: dict[str, Any],
    form_data: dict[str, Any],
    flow: dict[str, Any],
    text: str,
    now: datetime,
    *,
    check_availability: Callable[..., Any],
    append_waitlist_offer: Callable[[str, dict[str, Any] | None], str],
) -> tuple[str, dict[str, Any]] | None:
    if booking.get("service_type") != "gazebo" or not flow.get("change_object") or flow.get("service_variant"):
        return None
    target_date = flow.get("date")
    if not target_date:
        return None
    target_time = flow.get("time") or str(booking.get("booking_time") or "")[:5]
    target_duration = flow.get("duration") or hours_from_minutes(booking.get("duration_minutes"))
    lookup_flow = flow | {
        "time": target_time,
        "duration": target_duration,
        "same_time": True,
    }
    check_form = form_data_for_booking_reschedule(form_data, booking, lookup_flow)
    check_form["service_variant"] = None
    availability = check_availability(conn, form_data=check_form, now=now)
    if availability.ok and not availability.slots:
        return (
            append_waitlist_offer(
                f"На {format_date_ru(target_date)} свободных беседок для замены не нашла. Напишите другую дату или время — проверю ещё раз.",
                check_form,
            ),
            lookup_flow,
        )
    options_form = remember_available_gazebo_variants(check_form, availability.slots)
    variants = available_gazebo_variant_configs(options_form) or []
    variants = filter_reschedule_gazebo_options(variants, booking, flow, text)
    if not variants:
        return (
            "На эту дату вижу свободные беседки, но подходящих под ваши пожелания не нашла.\n\n"
            "Можно написать другое количество гостей, бюджет или конкретный номер беседки — проверю ещё раз.",
            lookup_flow,
        )
    if len(variants) == 1:
        variant = variants[0]
        title = str(variant.get("title") or "беседка")
        confirm_flow = lookup_flow | {
            "stage": "confirm_reschedule",
            "service_variant": title,
            "same_object": False,
            "change_object": True,
        }
        return (
            f"Подходит {format_gazebo_variant_line(variant)} ✅\n\n"
            f"{reschedule_confirmation_reply(booking, confirm_flow)}",
            confirm_flow,
        )
    lines = ["Из свободных вариантов под ваши пожелания подходят:"]
    for variant in variants:
        lines.append(f"- {format_gazebo_variant_line(variant)}")
    lines.append("")
    lines.append("Какую беседку ставим вместо текущей?")
    return "\n".join(lines), lookup_flow | {"stage": "choose_reschedule_variant"}


def reschedule_target_date_patch(text: str, now: datetime, booking: dict[str, Any]) -> dict[str, str]:
    booking_date = booking.get("booking_date")
    base_date = booking_date if isinstance(booking_date, date) else None
    normalized = text.lower().replace("ё", "е")
    if base_date and any(
        marker in normalized
        for marker in ("на денек позже", "на денёк позже", "день позже", "на день позже", "следующий день", "на следующий день")
    ):
        return {"date": (base_date + timedelta(days=1)).isoformat()}
    if base_date and any(
        marker in normalized
        for marker in ("на денек раньше", "на денёк раньше", "день раньше", "на день раньше", "предыдущий день", "на предыдущий день")
    ):
        return {"date": (base_date - timedelta(days=1)).isoformat()}
    for marker in (
        "перенести на",
        "перенеси на",
        "перенесите на",
        "перенесем на",
        "перенесём на",
        "пернести на",
        "пернести на",
        "поменять на",
        "изменить на",
    ):
        patch = date_patch_after_marker(text, now, marker, base_date=base_date)
        if patch:
            return patch
    patch = reschedule_source_target_day_patch(text, now, base_date)
    if patch:
        return patch
    patch = last_explicit_date_patch(text, now, exclude_date=base_date)
    if patch:
        return patch
    return {}


def reschedule_confirmation_reply(booking: dict[str, Any], flow: dict[str, Any]) -> str:
    target_date = flow.get("date")
    target_time = flow.get("time")
    target_duration = flow.get("duration")
    current_variant = booking_object_title(booking)
    target_variant = flow.get("service_variant")
    variant_line = ""
    if (
        booking.get("service_type") == "gazebo"
        and target_variant
        and normalize_gazebo_title(target_variant) != normalize_gazebo_title(current_variant)
    ):
        variant_line = f"Новая беседка: {target_variant}.\n\n"
    return (
        "Проверила, на новое время свободно ✅\n\n"
        f"Перенести бронь «{booking_line_short(booking)}» "
        f"на {format_date_ru(target_date)}, с {target_time} на {format_duration(target_duration)}?\n\n"
        f"{variant_line}"
        "Аванс сохраняется. Если по новой дате или услуге будет разница в стоимости, её можно будет доплатить на месте.\n\n"
        "Подтверждаете перенос? Напишите «да» или «нет»."
    )


def select_reschedule_booking(
    bookings: list[dict[str, Any]],
    booking_id: Any,
    text: str,
    now: datetime,
) -> dict[str, Any] | None:
    if booking_id:
        for booking in bookings:
            if int(booking["id"]) == int(booking_id):
                return booking
    normalized = text.lower().replace("ё", "е")
    match = re.search(r"\b([1-9])\b", normalized)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(bookings):
            return bookings[index]
    ordinal_index = ordinal_index_from_text(normalized)
    if ordinal_index is not None and 0 <= ordinal_index < len(bookings):
        return bookings[ordinal_index]
    service_patch = service_type_patch(text)
    service_type = service_patch.get("service_type")
    if service_type:
        matches = [booking for booking in bookings if booking.get("service_type") == service_type]
        variant = (service_variant_patch(text) or {}).get("service_variant")
        if variant:
            variant_lower = str(variant).lower().replace("ё", "е")
            variant_matches = [
                booking
                for booking in matches
                if str(booking_object_title(booking)).lower().replace("ё", "е") == variant_lower
            ]
            if variant_matches:
                matches = variant_matches
        date_patch = relative_date_patch(text, now)
        if date_patch.get("date"):
            dated = [booking for booking in matches if str(booking.get("booking_date")) == date_patch["date"]]
            if len(dated) == 1:
                return dated[0]
        if len(matches) == 1:
            return matches[0]
    return bookings[0] if len(bookings) == 1 else None


def ordinal_index_from_text(text: str) -> int | None:
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


def form_data_for_booking_reschedule(
    form_data: dict[str, Any],
    booking: dict[str, Any],
    flow: dict[str, Any],
) -> dict[str, Any]:
    service_type = booking.get("service_type")
    ignore_source_record_ids = {
        str(item)
        for item in (form_data.get("ignore_source_record_ids") or [])
        if item
    }
    if booking.get("yclients_record_id"):
        ignore_source_record_ids.add(str(booking.get("yclients_record_id")))
    updated = {
        **form_data,
        "service_type": service_type,
        "date": flow.get("date"),
        "time": flow.get("time"),
        "duration": flow.get("duration"),
        "guests_count": flow.get("guests_count") or booking.get("guests_count") or form_data.get("guests_count"),
        "ignore_source_record_ids": sorted(ignore_source_record_ids),
    }
    if service_type == "gazebo":
        updated["service_variant"] = flow.get("service_variant") or booking_object_title(booking)
    return updated


def canonical_reschedule_gazebo_variant(value: str) -> str:
    normalized = normalize_gazebo_title(value)
    variants = (load_services_map().get("gazebo") or {}).get("variants") or []
    for variant in variants:
        title = str(variant.get("title") or "")
        if normalize_gazebo_title(title) == normalized:
            return title
    return value


def single_reschedule_choice_prompt(bookings: list[dict[str, Any]]) -> str:
    lines = [
        "Конечно, перенос возможен: аванс сохраняется, остаток можно будет внести на месте.",
        "",
        "Какую бронь переносим?",
    ]
    for index, booking in enumerate(bookings, start=1):
        lines.append(f"{index}. {booking_line_short(booking)}")
    return "\n".join(lines)


def _handoff_on_reschedule_restore_error(
    conn: Any,
    conversation: dict[str, Any],
    booking: dict[str, Any],
    callbacks: RescheduleExecutionCallbacks,
) -> None:
    user = callbacks.get_user_by_id(conn, int(conversation["user_id"]))
    if user:
        callbacks.start_user_handoff(
            conn,
            user=user,
            conversation_id=conversation["id"],
            text=f"перенос брони #{booking.get('id')}",
            now=callbacks.now_local(),
            reason="не удалось восстановить старую запись после ошибки переноса",
        )
