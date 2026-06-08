from __future__ import annotations

from datetime import date, datetime
from math import ceil
from typing import Any

from app.services.dialog.formatting import duration_minutes_value


BATHHOUSE_MAX_PACKAGE_MINUTES = 7 * 60
BATHHOUSE_EXTRA_HOUR_PRICE_RUB = 1500


def bathhouse_package_minutes(duration_minutes: int | None) -> int | None:
    if duration_minutes is None:
        return None
    if duration_minutes > BATHHOUSE_MAX_PACKAGE_MINUTES:
        return BATHHOUSE_MAX_PACKAGE_MINUTES
    return duration_minutes


def bathhouse_variant_for_duration(
    service_config: dict[str, Any],
    *,
    date_value: Any = None,
    duration_value: Any = None,
    duration_minutes: int | None = None,
) -> dict[str, Any] | None:
    variants = list(service_config.get("variants") or [])
    if not variants:
        return None

    requested_minutes = duration_minutes
    if requested_minutes is None:
        requested_minutes = duration_minutes_value(duration_value)
    package_minutes = bathhouse_package_minutes(requested_minutes)
    weekday = _weekday(date_value)

    candidates = _matching_variants(variants, package_minutes=package_minutes, weekday=weekday)
    if candidates:
        return candidates[0]
    if weekday is not None:
        candidates = _matching_variants(variants, package_minutes=package_minutes, weekday=None)
        if candidates:
            return candidates[0]
    return None


def bathhouse_price_components(
    service_config: dict[str, Any],
    *,
    date_value: Any = None,
    duration_value: Any = None,
    duration_minutes: int | None = None,
) -> dict[str, int] | None:
    requested_minutes = duration_minutes
    if requested_minutes is None:
        requested_minutes = duration_minutes_value(duration_value)
    if requested_minutes is None:
        return None

    variant = bathhouse_variant_for_duration(
        service_config,
        date_value=date_value,
        duration_minutes=requested_minutes,
    )
    if not variant or variant.get("price") in (None, ""):
        return None

    base_price = int(variant["price"])
    extra_minutes = max(0, requested_minutes - BATHHOUSE_MAX_PACKAGE_MINUTES)
    extra_hours = ceil(extra_minutes / 60) if extra_minutes else 0
    extra_price = extra_hours * BATHHOUSE_EXTRA_HOUR_PRICE_RUB
    return {
        "base_price": base_price,
        "extra_hours": extra_hours,
        "extra_price": extra_price,
        "total_price": base_price + extra_price,
        "package_minutes": bathhouse_package_minutes(requested_minutes) or requested_minutes,
        "requested_minutes": requested_minutes,
    }


def _matching_variants(
    variants: list[dict[str, Any]],
    *,
    package_minutes: int | None,
    weekday: int | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for variant in variants:
        variant_duration = variant.get("duration_minutes")
        if package_minutes and variant_duration and int(variant_duration) != int(package_minutes):
            continue
        weekdays = variant.get("weekdays")
        if weekdays and weekday is not None and weekday not in weekdays:
            continue
        candidates.append(variant)
    return candidates


def _weekday(value: Any) -> int | None:
    if isinstance(value, datetime):
        return value.weekday()
    if isinstance(value, date):
        return value.weekday()
    if value:
        try:
            return datetime.fromisoformat(str(value)).weekday()
        except ValueError:
            return None
    return None
