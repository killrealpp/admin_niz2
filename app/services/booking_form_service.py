from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import PROJECT_ROOT
from app.core.constants import EMPTY_FORM_DATA
from app.services.dialog.time_parsing import normalize_duration_value

FORM_PATH = PROJECT_ROOT / "config" / "booking_form.yaml"


@lru_cache
def load_booking_fields() -> list[dict[str, Any]]:
    data = yaml.safe_load(FORM_PATH.read_text(encoding="utf-8")) or {}
    return list(data.get("fields", []))


def initial_form_data() -> dict[str, Any]:
    form_data = EMPTY_FORM_DATA.copy()
    form_data["upsell_items"] = []
    return form_data


def merge_form_data(
    current: dict[str, Any] | None,
    patch: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = initial_form_data()
    if current:
        merged.update(current)

    for key, value in (patch or {}).items():
        if key not in merged:
            continue
        if value is None:
            continue
        if value == "" or value == []:
            continue
        if key == "duration":
            normalized_duration = normalize_duration_value(value)
            if normalized_duration is None:
                continue
            merged[key] = normalized_duration
            continue
        merged[key] = value
    return _normalize_form_data(merged)


def _normalize_form_data(form_data: dict[str, Any]) -> dict[str, Any]:
    value = form_data.get("duration")
    if value in (None, ""):
        return form_data
    normalized_duration = normalize_duration_value(value)
    if normalized_duration is None:
        form_data["duration"] = None
    else:
        form_data["duration"] = normalized_duration
    return form_data


def missing_fields(form_data: dict[str, Any], *, for_booking: bool = True) -> list[str]:
    flag = "required_for_booking" if for_booking else "required_for_availability"
    missing: list[str] = []
    for field in load_booking_fields():
        key = field["key"]
        if key == "service_variant" and form_data.get("service_type") != "gazebo":
            continue
        if not field.get(flag):
            continue
        value = form_data.get(key)
        if value is None or value == "" or value == []:
            missing.append(key)
    if form_data.get("service_type") == "gazebo" and "date" in missing and "service_variant" in missing:
        missing.remove("date")
        insert_at = missing.index("service_variant")
        missing.insert(insert_at, "date")
    if (
        form_data.get("service_type") == "gazebo"
        and "service_variant" in missing
        and "guests_count" in missing
    ):
        missing.remove("guests_count")
        insert_at = missing.index("service_variant")
        missing.insert(insert_at, "guests_count")
    return missing


def next_question(form_data: dict[str, Any]) -> tuple[str | None, str | None]:
    missing = missing_fields(form_data, for_booking=True)
    if not missing:
        return None, None

    next_key = missing[0]
    if next_key == "upsell_items":
        return next_key, _upsell_question(form_data)
    for field in load_booking_fields():
        if field["key"] == next_key:
            return next_key, field["label"]
    return next_key, None


def _upsell_question(form_data: dict[str, Any]) -> str:
    service_type = form_data.get("service_type")
    event = str(form_data.get("event_format") or "").lower()
    guests = form_data.get("guests_count")
    if service_type == "bathhouse":
        return (
            "К бане обычно удобно подготовить воду, лёд и посуду — после парной это самое ходовое 🧊\n"
            "Если планируете посидеть подольше, можно добавить кальян.\n\n"
            "Что подготовить для вас?"
        )
    if service_type == "house":
        return (
            "Для дома чаще берут воду, посуду, лёд и кальян: удобно, когда компания остаётся надолго "
            "и не нужно думать о мелочах 🏡\n\n"
            "Что подготовить для вас?"
        )
    if service_type == "warm_gazebo":
        return (
            "К тёплой беседке чаще всего берут воду, лёд, посуду и мангальный набор — "
            "так стол и мангал можно собрать без лишней суеты 🔥\n\n"
            "Что подготовить для вас?"
        )
    if service_type == "gazebo":
        if "день рождения" in event or "свад" in event or "празд" in event:
            return (
                "Для праздника в беседке обычно берут мангальный набор, лёд, посуду и кальян 🎉\n"
                "Так стол и мангал можно собрать сразу, без заездов по магазинам.\n\n"
                "Что подготовить для вас?"
            )
        if guests:
            try:
                guest_count = int(guests)
            except (TypeError, ValueError):
                guest_count = 0
            if guest_count >= 15:
                return (
                    "На такую компанию к беседке чаще берут мангальный набор, лёд, посуду и воду 🔥\n"
                    "Это те мелочи, которые удобнее подготовить заранее, пока все собираются.\n\n"
                    "Что подготовить для вас?"
                )
        return (
            "К беседке чаще всего берут мангальный минимум — уголь, розжиг, решётку или шампуры — "
            "плюс лёд, посуду или кальян по желанию 🔥\n\n"
            "Что подготовить для вас?"
        )
    return (
        "Можно заранее подготовить воду, лёд, посуду, кальян или мангальный набор ✅\n\n"
        "Что подготовить для вас?"
    )


def describe_fields_for_prompt() -> str:
    lines: list[str] = []
    for field in load_booking_fields():
        parts = [
            f"- {field['key']}",
            f"type={field.get('type')}",
            f"required_for_booking={field.get('required_for_booking', False)}",
            f"question={field.get('label')}",
        ]
        allowed = field.get("allowed_values")
        if allowed:
            parts.append(f"allowed_values={allowed}")
        lines.append("; ".join(parts))
    return "\n".join(lines)
