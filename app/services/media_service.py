from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT

IMAGES_DIR = PROJECT_ROOT / "app" / "images"

GAZEBO_IMAGE_BY_VARIANT = {
    "Беседка №1": IMAGES_DIR / "besedka1.jpg",
    "Беседка №2": IMAGES_DIR / "besedka2.jpg",
    "Беседка №3": IMAGES_DIR / "besedka3.jpg",
    "Беседка №4": IMAGES_DIR / "besedka4.jpg",
    "Беседка №6": IMAGES_DIR / "besedka6.jpg",
    "Беседка №8": IMAGES_DIR / "besedka8png.png",
    "Крытая беседка": IMAGES_DIR / "besedka_krytaya.jpg",
}


def media_for_client_message(text: str, reply: str) -> list[Path]:
    normalized_text = _normalize(text)
    normalized_reply = _normalize(reply)
    combined = f"{normalized_text}\n{normalized_reply}"
    if not _mentions_gazebo(combined):
        return []

    variants = _gazebo_variants_from_text(normalized_text)
    if variants:
        return _existing([GAZEBO_IMAGE_BY_VARIANT[item] for item in variants if item in GAZEBO_IMAGE_BY_VARIANT])

    if _asks_all_gazebos(normalized_text):
        return _existing(list(GAZEBO_IMAGE_BY_VARIANT.values()))

    variants = _gazebo_variants_from_text(normalized_reply)
    if variants:
        return _existing([GAZEBO_IMAGE_BY_VARIANT[item] for item in variants if item in GAZEBO_IMAGE_BY_VARIANT])

    if _asks_photo(normalized_text):
        return _existing(list(GAZEBO_IMAGE_BY_VARIANT.values()))
    return []


def media_for_bookings(bookings: list[dict[str, Any]]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for booking in bookings:
        path = _media_for_booking(booking)
        if path and path not in seen and path.exists():
            paths.append(path)
            seen.add(path)
    return paths


def _media_for_booking(booking: dict[str, Any]) -> Path | None:
    if booking.get("service_type") != "gazebo":
        return None
    title = _booking_title(booking)
    return GAZEBO_IMAGE_BY_VARIANT.get(title)


def _booking_title(booking: dict[str, Any]) -> str:
    title = str(booking.get("preferences") or "")
    if "крыт" in title.lower().replace("ё", "е"):
        return "Крытая беседка"
    service_id = str(booking.get("hold_yclients_service_id") or "")
    for name, path in GAZEBO_IMAGE_BY_VARIANT.items():
        number = re.search(r"№(\d+)", name)
        if number and number.group(1) in title:
            return name
    service_to_title = {
        "18201055": "Беседка №1",
        "18201056": "Беседка №2",
        "18201057": "Беседка №3",
        "18201058": "Беседка №4",
        "18201060": "Беседка №6",
        "18201062": "Беседка №8",
        "18201063": "Крытая беседка",
    }
    return service_to_title.get(service_id, title)


def _gazebo_variants_from_text(text: str) -> list[str]:
    variants: list[str] = []
    for match in re.finditer(r"(?:беседк[аиуы]?\s*)?(?:№|номер\s*)?([1-8])\b", text):
        variant = f"Беседка №{match.group(1)}"
        if variant not in variants:
            variants.append(variant)
    if "крыт" in text and "Крытая беседка" not in variants:
        variants.append("Крытая беседка")
    return variants


def _asks_all_gazebos(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "какие бесед",
            "какие есть бесед",
            "все бесед",
            "варианты бесед",
            "выбор бесед",
            "покажи бесед",
            "фото бесед",
        )
    )


def _asks_photo(text: str) -> bool:
    return any(marker in text for marker in ("фото", "фотк", "картин", "покажи"))


def _mentions_gazebo(text: str) -> bool:
    return "бесед" in text


def _existing(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path.exists() and path not in seen:
            result.append(path)
            seen.add(path)
    return result


def _normalize(text: str) -> str:
    return text.lower().replace("ё", "е")
