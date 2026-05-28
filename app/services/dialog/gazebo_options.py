from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.availability_service import load_services_map
from app.services.dialog.formatting import duration_minutes_value, format_date_ru, format_rub


def gazebo_selection_text(form_data: dict[str, Any]) -> str:
    guests = form_data.get("guests_count")
    available_variants = available_gazebo_variant_configs(form_data)
    if available_variants is not None:
        suitable = available_variants
        if guests:
            suitable = [
                variant for variant in available_variants
                if int(variant.get("capacity_max") or 0) >= int(guests)
            ]
        shown_variants = suitable if guests else available_variants
        if shown_variants:
            date_text = format_date_ru(form_data.get("date")) if form_data.get("date") else "выбранную дату"
            if guests:
                intro = f"Для {guests} гостей из свободных на {date_text} вариантов подходят:"
            else:
                intro = f"На {date_text} свободны эти варианты:"
            lines = [intro]
            for variant in shown_variants:
                lines.append(f"- {format_gazebo_variant_line(variant, date_value=form_data.get('date'))}")
            if guests:
                try:
                    guests_int = int(guests)
                except (TypeError, ValueError):
                    guests_int = 0
                if guests_int >= 20 and any("№1" in str(variant.get("title") or "") for variant in shown_variants[:1]):
                    lines.append("")
                    lines.append("Беседку №1 ставлю первой: для большой компании там комфортнее по месту ✅")
            if guests and not suitable:
                lines.append("")
                lines.append("По вместимости они могут быть тесноваты — лучше подобрать другую дату или вариант побольше.")
            elif not guests:
                lines.append("")
                lines.append("Сколько вас будет человек? Подскажу лучший вариант из свободных.")
            else:
                if len(shown_variants) == 1:
                    title = str(shown_variants[0].get("title") or "этот вариант")
                    lines.append("")
                    lines.append(f"Подходит {title}. Закрепляем её?")
                    return "\n".join(lines)
                names = " или ".join(str(variant.get("title") or "").replace("Беседка ", "") for variant in shown_variants)
                lines.append("")
                lines.append(f"Я бы выбирал из них. Какую закрепляем: {names}?")
            return "\n".join(lines)
        if guests:
            free_names = ", ".join(str(variant.get("title") or "Беседка") for variant in available_variants)
            date_text = format_date_ru(form_data.get("date")) if form_data.get("date") else "выбранную дату"
            return (
                f"На {date_text} свободны: {free_names}.\n\n"
                f"Но для {guests} гостей по вместимости они не подходят, поэтому не буду предлагать тесный вариант.\n\n"
                "Сейчас посмотрю ближайшие даты, где есть подходящие свободные варианты."
            )

    if guests:
        if form_data.get("date"):
            return (
                f"На {format_date_ru(form_data.get('date'))} подходящих свободных беседок для {guests} гостей не нашла.\n\n"
                "Сейчас посмотрю ближайшие даты, где есть подходящие свободные варианты."
            )
        return (
            f"Для {guests} гостей подберу беседку только из реально свободных вариантов ✅\n\n"
            "Напишите, пожалуйста, дату отдыха — проверю журнал и покажу свободные беседки с фото."
        )
    if form_data.get("date"):
        return (
            f"Дата есть: {format_date_ru(form_data.get('date'))}.\n\n"
            "Чтобы показать нормальный выбор беседок и не предложить вариант не по вместимости, "
            "сначала уточню количество гостей.\n\nСколько вас будет человек?"
        )
    return (
        "Беседки подбираю по свободности в журнале, чтобы не предлагать занятые варианты ✅\n\n"
        "Напишите, пожалуйста, дату отдыха — проверю свободные беседки."
    )


def looks_like_gazebo_budget_preference(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "подешев",
            "подешел",
            "дешев",
            "дешел",
            "дешов",
            "бюджет",
            "недорог",
            "не дорого",
            "поменьше по цене",
        )
    )


def gazebo_budget_selection_text(form_data: dict[str, Any]) -> str | None:
    variants = available_gazebo_variant_configs(form_data)
    checked_date = bool(form_data.get("date") and variants)
    if not variants and not form_data.get("date"):
        variants = (load_services_map().get("gazebo") or {}).get("variants") or []
    if not variants:
        return None
    guests = form_data.get("guests_count")
    if guests:
        try:
            guests_int = int(guests)
        except (TypeError, ValueError):
            guests_int = 0
        if guests_int > 0:
            variants = [
                variant for variant in variants
                if int(variant.get("capacity_max") or 0) >= guests_int
            ]
    priced = [
        variant for variant in variants
        if variant.get("price") not in (None, "")
    ]
    if not priced:
        return None
    min_price = min(int(variant.get("price") or 0) for variant in priced)
    cheapest = [
        variant for variant in priced
        if int(variant.get("price") or 0) == min_price
    ]
    if not cheapest:
        return None
    if checked_date:
        lines = ["Из свободных подходящих вариантов самые недорогие:"]
    else:
        lines = ["По цене из подходящих вариантов самые недорогие:"]
    for variant in cheapest:
        lines.append(f"- {format_gazebo_variant_line(variant, date_value=form_data.get('date'))}")
    lines.append("")
    if not checked_date:
        lines.append("Назовите дату — проверю по журналу, какие из них свободны.")
        return "\n".join(lines)
    if len(cheapest) == 1:
        title = str(cheapest[0].get("title") or "этот вариант")
        lines.append(f"Можно закрепить {title}. Подойдёт?")
    else:
        names = " или ".join(str(variant.get("title") or "").replace("Беседка ", "") for variant in cheapest)
        lines.append(f"Какую закрепляем: {names}?")
    return "\n".join(lines)


def normalize_gazebo_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def gazebo_title_from_slot(slot: str) -> str:
    return str(slot).split(":", 1)[0].strip()


def available_gazebo_titles(form_data: dict[str, Any]) -> list[str]:
    raw = form_data.get("last_available_gazebo_variants") or []
    if not isinstance(raw, list):
        return []
    titles: list[str] = []
    seen: set[str] = set()
    for item in raw:
        title = str(item or "").strip()
        key = normalize_gazebo_title(title)
        if title and key not in seen:
            titles.append(title)
            seen.add(key)
    return titles


def suitable_available_gazebo_titles(form_data: dict[str, Any]) -> list[str]:
    variants = available_gazebo_variant_configs(form_data)
    guests = form_data.get("guests_count")
    if variants is None or not guests:
        return []
    suitable: list[str] = []
    for variant in variants:
        capacity = int(variant.get("capacity_max") or 0)
        title = str(variant.get("title") or "").strip()
        if title and capacity >= int(guests):
            suitable.append(title)
    return suitable


def available_gazebo_variant_configs(form_data: dict[str, Any]) -> list[dict[str, Any]] | None:
    if form_data.get("service_type") != "gazebo":
        return None
    titles = available_gazebo_titles(form_data)
    if not titles:
        return None
    wanted = {normalize_gazebo_title(title) for title in titles}
    variants = (load_services_map().get("gazebo") or {}).get("variants") or []
    matched = [
        variant for variant in variants
        if normalize_gazebo_title(variant.get("title")) in wanted
    ]
    if matched:
        return matched
    return [{"title": title} for title in titles]


def suitable_gazebo_slots(slots: list[str], guests_count: Any) -> list[str]:
    if not guests_count:
        return slots
    try:
        guests = int(guests_count)
    except (TypeError, ValueError):
        return slots
    variants = (load_services_map().get("gazebo") or {}).get("variants") or []
    capacity_by_title = {
        normalize_gazebo_title(variant.get("title")): int(variant.get("capacity_max") or 0)
        for variant in variants
    }
    result: list[str] = []
    for slot in slots:
        title = gazebo_title_from_slot(slot)
        capacity = capacity_by_title.get(normalize_gazebo_title(title), 0)
        if capacity >= guests:
            result.append(slot)
    return result


def remember_available_gazebo_variants(
    form_data: dict[str, Any],
    slots: list[str],
) -> dict[str, Any]:
    updated = form_data.copy()
    if updated.get("service_type") != "gazebo":
        updated.pop("last_available_gazebo_variants", None)
        return updated
    if updated.get("service_variant") and updated.get("last_available_gazebo_variants"):
        return updated
    if updated.get("service_variant"):
        return updated
    titles: list[str] = []
    seen: set[str] = set()
    for slot in slots:
        title = gazebo_title_from_slot(slot)
        key = normalize_gazebo_title(title)
        if title and key not in seen:
            titles.append(title)
            seen.add(key)
    if titles:
        updated["last_available_gazebo_variants"] = titles
    return updated


def auto_select_single_available_gazebo(form_data: dict[str, Any]) -> dict[str, Any]:
    if form_data.get("service_type") != "gazebo" or form_data.get("service_variant"):
        return form_data
    titles = available_gazebo_titles(form_data)
    if len(titles) != 1:
        return form_data
    return {
        **form_data,
        "service_variant": titles[0],
        "single_available_gazebo_variant_auto": True,
    }


def clear_available_gazebo_variants(form_data: dict[str, Any]) -> dict[str, Any]:
    updated = form_data.copy()
    updated.pop("last_available_gazebo_variants", None)
    updated.pop("single_available_gazebo_variant_auto", None)
    return updated


def gazebo_discount_price(price: Any, date_value: Any) -> int | None:
    if not price or not date_value:
        return None
    try:
        weekday = datetime.fromisoformat(str(date_value)).weekday()
        base_price = int(price)
    except (TypeError, ValueError):
        return None
    if weekday in {0, 1, 2, 3}:
        return int(base_price * 0.5)
    return None


def format_gazebo_variant_line(variant: dict[str, Any], *, date_value: Any = None) -> str:
    title = str(variant.get("title") or "Беседка").strip()
    capacity = variant.get("capacity_max")
    price = variant.get("price")
    description_by_title = {
        "беседка №1": "просторная, для больших компаний и праздников",
        "беседка №2": "простая, с мангалом, без света и розеток",
        "беседка №3": "со светом, розетками, шторами/мягкими стеклами и мангалом",
        "беседка №4": "простая, с мангалом, без света и розеток",
        "беседка №5": "компактная, с мангалом",
        "беседка №6": "простая, с мангалом",
        "беседка №8": "полуоткрытая, со светом, розетками и мангалом",
        "крытая беседка": "со светом, розетками, шторами/мягкими стеклами и мангалом",
    }
    parts = [title]
    if capacity:
        parts.append(f"до {capacity} человек")
    if price:
        discount_price = gazebo_discount_price(price, date_value)
        if discount_price is not None:
            parts.append(f"{format_rub(price)} ₽, по будней скидке 50% — {format_rub(discount_price)} ₽")
        else:
            parts.append(f"{format_rub(price)} ₽")
    description = description_by_title.get(normalize_gazebo_title(title))
    if description:
        parts.append(description)
    return title if len(parts) == 1 else f"{parts[0]}: {', '.join(parts[1:])}"


def gazebo_variant_config_by_title(title: Any) -> dict[str, Any] | None:
    normalized = normalize_gazebo_title(title)
    if not normalized:
        return None
    variants = (load_services_map().get("gazebo") or {}).get("variants") or []
    for variant in variants:
        if normalize_gazebo_title(variant.get("title")) == normalized:
            return variant
    return None


def selected_gazebo_capacity_issue(form_data: dict[str, Any]) -> tuple[dict[str, Any], int, int] | None:
    if form_data.get("service_type") != "gazebo":
        return None
    if not form_data.get("service_variant") or not form_data.get("guests_count"):
        return None
    variant = gazebo_variant_config_by_title(form_data.get("service_variant"))
    if not variant:
        return None
    try:
        guests = int(form_data.get("guests_count") or 0)
        capacity = int(variant.get("capacity_max") or 0)
    except (TypeError, ValueError):
        return None
    if capacity and guests > capacity:
        return variant, guests, capacity
    return None


def selected_variant_config(form_data: dict[str, Any]) -> dict[str, Any]:
    service_type = form_data.get("service_type")
    config = load_services_map().get(service_type) or {}
    variants = config.get("variants") or []
    available = available_gazebo_variant_configs(form_data)
    if service_type == "gazebo" and available:
        variants = available
    variant_name = str(form_data.get("service_variant") or "").lower().replace("ё", "е")
    for variant in config.get("variants") or []:
        title = str(variant.get("title") or "").lower().replace("ё", "е")
        if title and title in variant_name:
            return variant
    if variants and service_type != "gazebo":
        duration_minutes = duration_minutes_value(form_data.get("duration"))
        weekday = None
        if form_data.get("date"):
            try:
                weekday = datetime.fromisoformat(str(form_data["date"])).weekday()
            except ValueError:
                weekday = None
        candidates = []
        for variant in variants:
            variant_duration = variant.get("duration_minutes")
            if duration_minutes and variant_duration and int(variant_duration) != int(duration_minutes):
                continue
            weekdays = variant.get("weekdays")
            if weekdays and weekday is not None and weekday not in weekdays:
                continue
            candidates.append(variant)
        if candidates:
            return candidates[0]
    if service_type == "gazebo" and "крыт" in variant_name:
        for variant in config.get("variants") or []:
            if "крыт" in str(variant.get("title") or "").lower().replace("ё", "е"):
                return variant
    if service_type == "gazebo" and variants:
        guests = int(form_data.get("guests_count") or 0)
        if "больш" in variant_name or guests > 20:
            return max(variants, key=lambda item: int(item.get("capacity_max") or 0))
        if "прост" in variant_name or "мангал" in variant_name:
            for variant in variants:
                title = str(variant.get("title") or "").lower()
                if "№2" in title:
                    return variant
        if "свет" in variant_name or "розет" in variant_name:
            for variant in variants:
                title = str(variant.get("title") or "").lower()
                if "крыт" in title:
                    return variant
        if guests:
            suitable = [
                item for item in variants
                if int(item.get("capacity_max") or 0) >= guests
            ]
            if suitable:
                return min(suitable, key=lambda item: int(item.get("capacity_max") or 9999))
    return config


def normalize_gazebo_variant(form_data: dict[str, Any]) -> dict[str, Any]:
    if form_data.get("service_type") != "gazebo":
        return form_data
    variant = str(form_data.get("service_variant") or "").strip()
    if variant:
        if is_concrete_gazebo_variant(variant):
            return form_data
        updated = dict(form_data)
        updated["service_variant"] = None
        updated["preferences"] = _join_preferences(updated.get("preferences"), variant)
        return updated
    return form_data


def is_concrete_gazebo_variant(value: str) -> bool:
    normalized = normalize_gazebo_title(value)
    variants = (load_services_map().get("gazebo") or {}).get("variants") or []
    return any(normalize_gazebo_title(variant.get("title")) == normalized for variant in variants)


def _join_preferences(current: Any, value: str) -> str:
    text = str(current or "").strip()
    if not text:
        return value
    if value.lower() in text.lower():
        return text
    return f"{text}; {value}"
