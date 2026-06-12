from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


SERVICES_PATH = Path(__file__).resolve().with_name("services.yaml")


@lru_cache
def load_services() -> dict[str, dict[str, Any]]:
    return yaml.safe_load(SERVICES_PATH.read_text(encoding="utf-8")) or {}


def service_title(service_type: str | None) -> str:
    if not service_type:
        return "услуга"
    return (load_services().get(service_type) or {}).get("title") or service_type


def service_variants(service_type: str | None) -> list[dict[str, Any]]:
    return list((load_services().get(service_type or "") or {}).get("variants") or [])


def variant_by_title(service_type: str | None, title: str | None) -> dict[str, Any] | None:
    if not title:
        return None
    normalized = title.lower().replace("ё", "е").strip()
    for variant in service_variants(service_type):
        candidate = str(variant.get("title") or "").lower().replace("ё", "е").strip()
        if candidate == normalized or normalized in candidate or candidate in normalized:
            return variant
    return None


def normalize_service_type(value: str | None) -> str | None:
    text = (value or "").lower().replace("ё", "е")
    if not text:
        return None
    if text in load_services():
        return text
    if "бан" in text:
        return "bathhouse"
    if "дом" in text:
        return "house"
    if "тепл" in text and "бесед" in text:
        return "warm_gazebo"
    if "бесед" in text or "gazebo" in text:
        return "gazebo"
    return None
