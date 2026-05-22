from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import PROJECT_ROOT
from app.core.constants import EMPTY_FORM_DATA

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
        merged[key] = value
    return merged


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
    return missing


def next_question(form_data: dict[str, Any]) -> tuple[str | None, str | None]:
    missing = missing_fields(form_data, for_booking=True)
    if not missing:
        return None, None

    next_key = missing[0]
    for field in load_booking_fields():
        if field["key"] == next_key:
            return next_key, field["label"]
    return next_key, None


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
