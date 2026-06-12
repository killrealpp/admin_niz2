from __future__ import annotations

from datetime import date
from typing import Any

from app.data.services import load_services, service_variants, variant_by_title
from app.dialog.state import BookingDraft


BATHHOUSE_EXTRA_HOUR_PRICE_RUB = 1500


def calculate_booking_price(draft: BookingDraft) -> int | None:
    """Возвращает итоговую стоимость бронирования в рублях.

    Важно: это только расчёт цены для клиента/админа. Логику выбора service_id
    и длительности записи в YClients здесь не трогаем.
    """
    if not draft.service_type:
        return None

    if draft.service_type == "bathhouse":
        return _calculate_bathhouse_price(draft)

    return _calculate_regular_price(draft)


def _calculate_bathhouse_price(draft: BookingDraft) -> int | None:
    duration = _duration_hours(draft.duration)
    if duration is None:
        return None

    if duration <= 7:
        return _price_for_exact_duration(
            service_type="bathhouse",
            duration_hours=duration,
            booking_date=draft.date,
        )

    base_price = _price_for_exact_duration(
        service_type="bathhouse",
        duration_hours=7,
        booking_date=draft.date,
    )
    if base_price is None:
        return None

    extra_hours = duration - 7
    return int(base_price + extra_hours * BATHHOUSE_EXTRA_HOUR_PRICE_RUB)


def _calculate_regular_price(draft: BookingDraft) -> int | None:
    variant = _find_selected_variant(draft)
    if variant and variant.get("price") is not None:
        return _to_int_price(variant.get("price"))

    config = load_services().get(draft.service_type or "") or {}
    if config.get("price") is not None:
        return _to_int_price(config.get("price"))

    return None


def _find_selected_variant(draft: BookingDraft) -> dict[str, Any] | None:
    if draft.service_variant:
        found = variant_by_title(draft.service_type, draft.service_variant)
        if found:
            return found

    variants = service_variants(draft.service_type)
    if not variants:
        return None

    duration = _duration_hours(draft.duration)
    booking_weekday = _weekday(draft.date)

    for variant in variants:
        if not _weekday_matches(variant, booking_weekday):
            continue
        if duration is not None and variant.get("duration_minutes"):
            try:
                if int(variant.get("duration_minutes") or 0) != int(duration * 60):
                    continue
            except (TypeError, ValueError):
                continue
        return variant

    return variants[0] if variants else None


def _price_for_exact_duration(
    *,
    service_type: str,
    duration_hours: int,
    booking_date: str | None,
) -> int | None:
    booking_weekday = _weekday(booking_date)

    for variant in service_variants(service_type):
        try:
            minutes = int(variant.get("duration_minutes") or 0)
        except (TypeError, ValueError):
            continue

        if minutes != int(duration_hours * 60):
            continue
        if not _weekday_matches(variant, booking_weekday):
            continue
        if variant.get("price") is not None:
            return _to_int_price(variant.get("price"))

    return None


def _weekday_matches(variant: dict[str, Any], booking_weekday: int | None) -> bool:
    weekdays = variant.get("weekdays")
    if booking_weekday is None or not weekdays:
        return True
    return booking_weekday in weekdays


def _duration_hours(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(number)


def _weekday(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).weekday()
    except ValueError:
        return None


def _to_int_price(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
