from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.services.availability_service import load_services_map
from app.services.booking_form_service import next_question
from app.services.dialog.formatting import format_date_ru, format_time_duration_range
from app.services.dialog.gazebo_options import (
    auto_select_single_available_gazebo,
    available_gazebo_variant_configs,
    format_gazebo_variant_line,
    gazebo_selection_text,
    gazebo_title_from_slot,
    remember_available_gazebo_variants,
    suitable_gazebo_slots,
)
from app.services.dialog.reschedule_flow import gazebo_capacity_by_title


@dataclass(frozen=True)
class AvailabilityExecutionCallbacks:
    check_availability: Callable[..., Any]
    alternative_services_for_unavailable_date: Callable[..., tuple[str, str] | None]
    next_free_dates_reply: Callable[..., str | None]
    remember_waitlist_request: Callable[..., Any]
    asks_for_free_slots: Callable[[str], bool]


@dataclass(frozen=True)
class AvailabilityExecutionResult:
    reply: str
    next_key: str | None
    current_step: str | None
    form_data: dict[str, Any]
    used_alternative: bool = False


@dataclass(frozen=True)
class DirectFreeDatesLookupCallbacks:
    asks_for_free_slots: Callable[[str], bool]
    asks_nearest_free_dates: Callable[[str], bool]
    deterministic_patch: Callable[[str, datetime], dict[str, Any]]
    guests_count_patch: Callable[[str, str], dict[str, Any]]
    normalize_service_aliases: Callable[[dict[str, Any]], dict[str, Any]]
    new_booking_form_data: Callable[[dict[str, Any]], dict[str, Any]]
    merge_form_data: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    check_availability: Callable[..., Any]
    alternative_services_for_unavailable_date: Callable[..., tuple[str, str] | None]
    next_free_dates_reply: Callable[..., str | None]


def should_check_availability(action: str, changed_fields: list[str], form_data: dict[str, Any]) -> bool:
    if not form_data.get("service_type") or not form_data.get("date"):
        return False
    service_config = load_services_map().get(form_data.get("service_type")) or {}
    if service_config.get("require_duration_before_availability") and (
        not form_data.get("time") or not form_data.get("duration")
    ):
        return False
    if action == "check_availability":
        return True
    changed = set(changed_fields)
    if form_data.get("service_type") == "gazebo" and "guests_count" in changed:
        return True
    return bool({"service_type", "service_variant", "date", "time", "duration"} & changed)


def availability_reply(message: str, slots: list[str], form_data: dict[str, Any]) -> tuple[str, str | None]:
    next_key, question = next_question(form_data)
    if _duration_validation_message(message):
        return message, "duration"
    title = (load_services_map().get(form_data.get("service_type")) or {}).get("title") or "объект"
    date_text = format_date_ru(form_data.get("date"))
    if slots:
        shown = ", ".join(slots[:5])
        if (
            form_data.get("service_type") == "gazebo"
            and form_data.get("service_variant")
            and not form_data.get("guests_count")
        ):
            prefix = "свободна" if form_data.get("single_available_gazebo_variant_auto") else "свободна"
            return (
                f"На {date_text} {prefix}: {form_data['service_variant']} ✅\n\n"
                "Сколько вас будет человек? Проверю, подходит ли она по вместимости.",
                "guests_count",
            )
        if (
            form_data.get("service_type") == "gazebo"
            and form_data.get("service_variant")
            and form_data.get("guests_count")
            and not form_data.get("time")
        ):
            capacity = gazebo_capacity_by_title(str(form_data.get("service_variant")))
            capacity_note = (
                f"{form_data['service_variant']} рассчитана до {capacity} человек, "
                f"для {form_data.get('guests_count')} гостей подходит ✅"
                if capacity
                else f"{form_data.get('guests_count')} гостей для {form_data['service_variant']} подходит ✅"
            )
            return (
                f"{capacity_note}\n\n"
                "Во сколько хотите приехать? Можно сразу написать период, например: с 18:00 до 00:00.",
                "time",
            )
        if form_data.get("service_type") == "gazebo" and not form_data.get("service_variant"):
            options = ", ".join(slot.split(":", 1)[0] for slot in slots[:8])
            if not form_data.get("guests_count"):
                return (
                    f"На {date_text} свободны: {options} ✅\n\n"
                    "Сколько вас будет человек? Подскажу подходящие свободные варианты.",
                    "guests_count",
                )
            return gazebo_selection_text(form_data), "service_variant"
        if form_data.get("time") and form_data.get("duration"):
            period = format_time_duration_range(form_data.get("time"), form_data.get("duration"))
            selected_title = form_data.get("service_variant") if form_data.get("service_type") == "gazebo" else None
            object_title = selected_title or title
            availability_word = "свободна" if form_data.get("service_type") in {"gazebo", "bathhouse"} else "свободен"
            text = f"{object_title}: {period} {availability_word}."
        else:
            selected_title = form_data.get("service_variant") if form_data.get("service_type") == "gazebo" else None
            if selected_title:
                text = f"На {date_text} {selected_title} свободна ✅."
            else:
                availability_word = "свободен" if form_data.get("service_type") == "house" else "свободна"
                text = f"На {date_text} {title.lower()} {availability_word} ✅."
        if question:
            text += f"\n\n{question}"
        return text, next_key
    if (
        form_data.get("service_type") == "gazebo"
        and form_data.get("date")
        and not form_data.get("service_variant")
        and not form_data.get("guests_count")
    ):
        return (
            f"Дату записала: {date_text}. Чтобы показать подходящие свободные беседки, "
            "сначала уточню количество гостей.\n\nСколько вас будет человек?",
            "guests_count",
        )
    if question:
        return f"На {date_text} {title.lower()} свободна.\n\n{question}", next_key
    return f"На {date_text} {title.lower()} свободна.", None


def no_availability_reply(form_data: dict[str, Any]) -> tuple[str, str]:
    service_type = form_data.get("service_type")
    title = (load_services_map().get(service_type) or {}).get("title") or "объект"
    date_text = form_data.get("date")
    time_text = form_data.get("time")
    duration_text = form_data.get("duration")
    details = []
    if date_text:
        details.append(format_date_ru(date_text))
    if time_text:
        details.append(f"с {time_text}")
    if duration_text:
        details.append(f"на {duration_text} ч")
    details_text = " ".join(details) or "выбранную дату"
    if time_text or duration_text:
        return (
            f"На {details_text} свободных вариантов для «{title}» не нашёл. "
            "Напишите, пожалуйста, другую дату или другой период — проверю заново.",
            "date",
        )
    return (
        f"На {details_text} свободных вариантов для «{title}» не нашёл. "
        "Напишите, пожалуйста, другую дату — проверю свободные варианты.",
        "date",
    )


def alternative_services_for_unavailable_date(
    conn: Any,
    form_data: dict[str, Any],
    now: datetime,
    *,
    check_availability: Callable[..., Any],
) -> tuple[str, str] | None:
    service_type = form_data.get("service_type")
    if service_type not in {"house", "bathhouse", "warm_gazebo"}:
        return None
    date_value = form_data.get("date") or (form_data.get("last_unavailable") or {}).get("date")
    if not date_value:
        return None
    guests_count = form_data.get("guests_count") or (form_data.get("last_unavailable") or {}).get("guests_count")
    source_title = "гостевой дом" if service_type == "house" else (load_services_map().get(service_type) or {}).get("title") or "выбранный объект"
    date_text = format_date_ru(date_value)
    alternatives: list[str] = []

    gazebo_form = {
        **form_data,
        "service_type": "gazebo",
        "service_variant": None,
        "date": date_value,
        "guests_count": guests_count,
        "time": form_data.get("time"),
        "duration": form_data.get("duration"),
    }
    gazebo_availability = check_availability(conn, form_data=gazebo_form, now=now)
    gazebo_slots = suitable_gazebo_slots(gazebo_availability.slots, guests_count)
    if gazebo_availability.ok and gazebo_slots:
        gazebo_form = remember_available_gazebo_variants(gazebo_form, gazebo_slots)
        variants = available_gazebo_variant_configs(gazebo_form) or []
        if guests_count:
            variants = [
                variant for variant in variants
                if int(variant.get("capacity_max") or 0) >= int(guests_count)
            ]
        if variants:
            if int(guests_count or 0) >= 20:
                variants = sorted(
                    variants,
                    key=lambda item: (
                        0 if "№1" in str(item.get("title") or "") else 1,
                        int(item.get("price") or 999999),
                    ),
                )
            shown = "\n".join(
                f"- {format_gazebo_variant_line(variant, date_value=form_data.get('date'))}"
                for variant in variants[:5]
            )
            alternatives.append(f"Свободные беседки:\n{shown}")

    for alt_service in ("warm_gazebo", "bathhouse"):
        if alt_service == service_type:
            continue
        alt_config = load_services_map().get(alt_service) or {}
        if not alt_config:
            continue
        alt_form = {
            **form_data,
            "service_type": alt_service,
            "service_variant": None,
            "date": date_value,
        }
        availability = check_availability(conn, form_data=alt_form, now=now)
        if availability.ok and availability.slots:
            alternatives.append(f"{alt_config.get('title') or alt_service}: свободно")

    if not alternatives:
        return None

    reply = (
        f"На {date_text} свободных вариантов для «{source_title}» не нашла.\n\n"
        "Но на эту дату можно рассмотреть другие варианты 👇\n\n"
        + "\n\n".join(alternatives)
        + "\n\nЕсли хотите, можем переключиться на подходящую беседку или другую услугу на эту же дату."
    )
    return reply, "service_type"


def waitlist_request_text(form_data: dict[str, Any] | None) -> str:
    if not form_data:
        return "этот запрос"
    service_type = form_data.get("service_type")
    title = (load_services_map().get(service_type) or {}).get("title") or "услугу"
    parts = [title.lower()]
    if form_data.get("guests_count"):
        parts.append(f"для {form_data.get('guests_count')} гостей")
    if form_data.get("date"):
        parts.append(f"на {format_date_ru(form_data.get('date'))}")
    if form_data.get("time"):
        parts.append(f"с {form_data.get('time')}")
    if form_data.get("service_variant"):
        parts.append(str(form_data.get("service_variant")))
    return " ".join(parts)


def append_waitlist_offer(reply: str, form_data: dict[str, Any] | None = None) -> str:
    request_text = waitlist_request_text(form_data)
    return (
        f"{reply}\n\n"
        f"Я запомнила запрос: {request_text}. Если место освободится из-за отмены, мы сможем вас уведомить."
    )


def next_free_dates_reply(
    conn: Any,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
    *,
    check_availability: Callable[..., Any],
    active_user_bookings: Callable[..., list[dict[str, Any]]],
    limit: int = 5,
    days_ahead: int = 75,
) -> str | None:
    last_unavailable = form_data.get("last_unavailable") or {}
    service_type = form_data.get("service_type") or last_unavailable.get("service_type")
    if not service_type:
        return None

    service_config = load_services_map().get(service_type) or {}
    title = service_config.get("title") or service_type
    booked_dates = {
        str(booking.get("booking_date"))
        for booking in active_user_bookings(conn, conversation, form_data, now)
        if booking.get("service_type") == service_type
    }
    previously_suggested_dates = {
        str(item)
        for item in (form_data.get("last_suggested_free_dates") or [])
        if item
    }

    start = now.date()
    unavailable_date = last_unavailable.get("date") or form_data.get("date")
    anchor_date: date | None = None
    skipped_dates: set[str] = set()
    if unavailable_date:
        try:
            anchor_date = datetime.fromisoformat(str(unavailable_date)).date()
            skipped_dates.add(anchor_date.isoformat())
        except ValueError:
            pass

    time_value = form_data.get("time") or last_unavailable.get("time")
    duration_value = form_data.get("duration") or last_unavailable.get("duration")
    guests_count = form_data.get("guests_count") or last_unavailable.get("guests_count")
    service_variant = form_data.get("service_variant") or last_unavailable.get("service_variant")

    if anchor_date:
        candidate_dates: list[date] = []
        for distance in range(1, days_ahead + 1):
            previous = anchor_date - timedelta(days=distance)
            if previous >= start:
                candidate_dates.append(previous)
            candidate_dates.append(anchor_date + timedelta(days=distance))
    else:
        candidate_dates = [start + timedelta(days=offset) for offset in range(days_ahead)]

    found: list[tuple[date, list[str]]] = []
    for candidate in candidate_dates:
        if candidate.isoformat() in booked_dates:
            continue
        if candidate.isoformat() in skipped_dates:
            continue
        if candidate.isoformat() in previously_suggested_dates:
            continue
        check_form = {
            **form_data,
            "service_type": service_type,
            "service_variant": service_variant,
            "date": candidate.isoformat(),
            "time": time_value,
            "duration": duration_value,
            "guests_count": guests_count,
        }
        availability = check_availability(conn, form_data=check_form, now=now)
        slots = suitable_gazebo_slots(availability.slots, guests_count) if service_type == "gazebo" else availability.slots
        if availability.ok and slots:
            found.append((candidate, slots))
            if len(found) >= limit:
                break

    if not found:
        return (
            f"На ближайшие {days_ahead} дней свободных дат для «{title}» не нашла.\n\n"
            "Можно написать другой период или выбрать другую услугу — проверю по журналу."
        )

    if service_type == "gazebo" and guests_count:
        lines = [f"Ближайшие даты, где есть беседки для {guests_count} гостей:"]
    else:
        lines = [f"Ближайшие свободные даты для «{title}»:"]
    for candidate, slots in found:
        if service_type == "gazebo":
            variants = ", ".join(gazebo_title_from_slot(slot) for slot in slots[:5])
            lines.append(f"- {format_date_ru(candidate)}: {variants}")
        else:
            first_slot = slots[0].split(":", 1)[1].strip() if ":" in slots[0] else slots[0]
            lines.append(f"- {format_date_ru(candidate)}: {first_slot}")
    lines.append("")
    lines.append("Какую дату выбираете?")
    form_data["last_suggested_free_dates"] = sorted(
        previously_suggested_dates | {candidate.isoformat() for candidate, _ in found}
    )[-20:]
    return "\n".join(lines)


def direct_free_dates_lookup(
    conn: Any,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    callbacks: DirectFreeDatesLookupCallbacks,
    *,
    force_new: bool = False,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    if not callbacks.asks_for_free_slots(text):
        return None
    current_form_data = conversation.get("form_data") or {}
    patch = (
        callbacks.deterministic_patch(text, now)
        | callbacks.guests_count_patch(text, "guests_count")
    )
    service_patch = callbacks.normalize_service_aliases({"service_type": patch.get("service_type")})
    requested_service = service_patch.get("service_type")
    current_service = callbacks.normalize_service_aliases({"service_type": current_form_data.get("service_type")}).get("service_type")
    service_type = requested_service or current_service or (current_form_data.get("last_unavailable") or {}).get("service_type")
    if not service_type:
        return None

    if force_new or (requested_service and requested_service != current_service):
        form_data = callbacks.new_booking_form_data(current_form_data)
    else:
        form_data = dict(current_form_data)
    form_data.pop("stale_form_flow", None)
    form_data["service_type"] = service_type
    form_data = callbacks.merge_form_data(form_data, patch)
    form_data = callbacks.normalize_service_aliases(form_data)
    if patch.get("date") or patch.get("guests_count"):
        form_data.pop("last_suggested_free_dates", None)
    if form_data.get("service_type") != "gazebo":
        form_data["service_variant"] = None

    if callbacks.asks_nearest_free_dates(text):
        if not patch.get("date"):
            form_data["date"] = None
        if not patch.get("time"):
            form_data["time"] = None
        if not patch.get("duration"):
            form_data["duration"] = None

    if form_data.get("date") and not callbacks.asks_nearest_free_dates(text):
        availability = callbacks.check_availability(conn, form_data=form_data, now=now)
        if availability.ok and availability.slots:
            form_data = remember_available_gazebo_variants(form_data, availability.slots)
            form_data = auto_select_single_available_gazebo(form_data)
            reply, next_key = availability_reply(availability.message, availability.slots, form_data)
            return reply, "waiting_user", next_key or "date", next_key, form_data
        alternative = callbacks.alternative_services_for_unavailable_date(conn, form_data, now)
        if alternative:
            reply, next_key = alternative
            return reply, "waiting_user", "service_type", next_key, reset_unavailable_slot(form_data)

    reply = callbacks.next_free_dates_reply(conn, conversation, form_data, now)
    if not reply:
        return None
    return reply, "waiting_user", "awaiting_new_date", "date", form_data


def reset_unavailable_slot(form_data: dict[str, Any]) -> dict[str, Any]:
    updated = form_data.copy()
    updated["last_unavailable"] = {
        "service_type": form_data.get("service_type"),
        "date": form_data.get("date"),
        "time": form_data.get("time"),
        "duration": form_data.get("duration"),
        "guests_count": form_data.get("guests_count"),
        "service_variant": form_data.get("service_variant"),
    }
    updated["date"] = None
    updated["time"] = None
    updated["duration"] = None
    if form_data.get("last_suggested_free_dates"):
        updated["last_suggested_free_dates"] = form_data.get("last_suggested_free_dates")
    updated.pop("last_available_gazebo_variants", None)
    return updated


def clear_active_slot_keep_last(form_data: dict[str, Any]) -> dict[str, Any]:
    updated = form_data.copy()
    updated["date"] = None
    updated["time"] = None
    updated["duration"] = None
    return updated


def apply_previous_period_for_new_date(
    form_data: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    last_unavailable = form_data.get("last_unavailable") or {}
    if not patch.get("date"):
        return patch
    if patch.get("date") == last_unavailable.get("date"):
        return patch
    updated = patch.copy()
    if not updated.get("time") and last_unavailable.get("time"):
        updated["time"] = last_unavailable["time"]
    if not updated.get("duration") and last_unavailable.get("duration"):
        updated["duration"] = last_unavailable["duration"]
    return updated


def same_unavailable_date_reply(form_data: dict[str, Any]) -> tuple[str, str]:
    last_unavailable = form_data.get("last_unavailable") or {}
    date_text = last_unavailable.get("date") or "эту дату"
    time_text = last_unavailable.get("time")
    duration_text = last_unavailable.get("duration")
    period = ""
    if time_text and duration_text:
        period = f" с {time_text} на {duration_text} ч"
    elif duration_text:
        period = f" на {duration_text} ч"
    return (
        f"{date_text}{period} уже проверял: свободных вариантов не нашёл. "
        "Напишите другую дату или другой период — проверю.",
        "date",
    )


def execute_availability_check(
    conn: Any,
    conversation: dict[str, Any],
    *,
    user_id: Any,
    form_data: dict[str, Any],
    text: str,
    now: datetime,
    callbacks: AvailabilityExecutionCallbacks,
    offer_next_free_dates: bool = True,
    remember_waitlist: bool = True,
    alternative_current_step: str = "awaiting_new_date",
) -> AvailabilityExecutionResult:
    availability = callbacks.check_availability(conn, form_data=form_data, now=now)
    if availability.ok and not availability.slots:
        if _duration_validation_message(availability.message):
            updated = dict(form_data)
            updated["duration"] = None
            updated.pop("last_unavailable", None)
            return AvailabilityExecutionResult(
                reply=availability.message,
                next_key="duration",
                current_step="duration",
                form_data=updated,
            )
        alternative = callbacks.alternative_services_for_unavailable_date(conn, form_data, now)
        used_alternative = bool(alternative)
        if alternative:
            reply, next_key = alternative
        elif offer_next_free_dates and (
            callbacks.asks_for_free_slots(text)
            or (
                form_data.get("service_type") == "gazebo"
                and form_data.get("date")
                and form_data.get("guests_count")
            )
        ):
            nearest_reply = callbacks.next_free_dates_reply(conn, conversation, form_data, now)
            if nearest_reply and form_data.get("service_type") == "gazebo" and form_data.get("date") and form_data.get("guests_count"):
                reply = (
                    f"На {format_date_ru(form_data.get('date'))} подходящих свободных беседок "
                    f"для {form_data.get('guests_count')} гостей не нашла.\n\n"
                    f"{nearest_reply}"
                )
            else:
                reply = nearest_reply or no_availability_reply(form_data)[0]
            next_key = "date"
        else:
            reply, next_key = no_availability_reply(form_data)
            if remember_waitlist:
                callbacks.remember_waitlist_request(
                    conn,
                    conversation_id=conversation["id"],
                    user_id=user_id,
                    form_data=form_data,
                )
                reply = append_waitlist_offer(reply, form_data)
        updated = reset_unavailable_slot(form_data)
        return AvailabilityExecutionResult(
            reply=reply,
            next_key=next_key,
            current_step=alternative_current_step if used_alternative else "awaiting_new_date",
            form_data=updated,
            used_alternative=used_alternative,
        )

    if (
        form_data.get("service_type") == "gazebo"
        and not form_data.get("service_variant")
        and form_data.get("guests_count")
    ):
        suitable_slots = suitable_gazebo_slots(availability.slots, form_data.get("guests_count"))
        if availability.slots and not suitable_slots:
            with_available = remember_available_gazebo_variants(form_data, availability.slots)
            reply = gazebo_selection_text(with_available)
            if offer_next_free_dates:
                nearest_reply = callbacks.next_free_dates_reply(conn, conversation, with_available, now)
                if nearest_reply:
                    reply = f"{reply}\n\n{nearest_reply}"
            updated = reset_unavailable_slot(with_available)
            return AvailabilityExecutionResult(
                reply=reply,
                next_key="date",
                current_step="awaiting_new_date",
                form_data=updated,
            )

    updated = remember_available_gazebo_variants(form_data, availability.slots)
    updated = auto_select_single_available_gazebo(updated)
    reply, next_key = availability_reply(availability.message, availability.slots, updated)
    return AvailabilityExecutionResult(
        reply=reply,
        next_key=next_key,
        current_step=next_key,
        form_data=updated,
    )


def _duration_validation_message(message: str) -> bool:
    lowered = message.lower().replace("ё", "е")
    return message.startswith("Для «") and ("длительность" in lowered or "фиксирован" in lowered)
