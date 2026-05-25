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
    "Беседка №5": IMAGES_DIR / "besedka5.jpg",
    "Беседка №6": IMAGES_DIR / "besedka6.jpg",
    "Беседка №8": IMAGES_DIR / "besedka8png.png",
    "Крытая беседка": IMAGES_DIR / "besedka_krytaya.jpg",
}


def media_for_client_message(text: str, reply: str) -> list[Path]:
    normalized_text = _normalize(text)
    normalized_reply = _normalize(reply)
    if not _mentions_gazebo(f"{normalized_text}\n{normalized_reply}"):
        return []

    explicit_photo_request = is_explicit_photo_request(text)
    if explicit_photo_request:
        requested_variants = _gazebo_variants_from_text(normalized_text)
        if requested_variants:
            return media_for_gazebo_titles(requested_variants)
        reply_variants = _gazebo_variants_from_text(normalized_reply)
        if reply_variants:
            return media_for_gazebo_titles(reply_variants)

    reply_variants = _gazebo_variants_from_text(normalized_reply)
    if (
        reply_variants
        and _reply_has_concrete_gazebo_context(normalized_reply)
        and _reply_lists_available_options(normalized_reply)
    ):
        return media_for_gazebo_titles(reply_variants)
    return []


def missing_media_titles_for_client_message(text: str, reply: str) -> list[str]:
    normalized_text = _normalize(text)
    normalized_reply = _normalize(reply)
    if not _mentions_gazebo(f"{normalized_text}\n{normalized_reply}"):
        return []

    titles: list[str] = []
    if is_explicit_photo_request(text):
        titles = _gazebo_variants_from_text(normalized_text)
        if not titles:
            titles = _gazebo_variants_from_text(normalized_reply)
    if not titles:
        return []

    missing: list[str] = []
    seen: set[str] = set()
    for title in titles:
        canonical = _canonical_gazebo_title(title)
        path = GAZEBO_IMAGE_BY_VARIANT.get(canonical)
        if path and not path.exists() and canonical not in seen:
            missing.append(canonical)
            seen.add(canonical)
    return missing


def is_explicit_photo_request(text: str) -> bool:
    normalized = _normalize(text)
    return any(
        marker in normalized
        for marker in (
            "фото",
            "фотку",
            "фотки",
            "фотограф",
            "картин",
            "изображ",
            "покажи",
            "показать",
            "скинь",
            "скинуть",
            "пришли",
            "отправь",
            "как выглядит",
        )
    )


def media_for_gazebo_titles(titles: list[str]) -> list[Path]:
    return _existing(
        [
            path
            for title in titles
            if (path := GAZEBO_IMAGE_BY_VARIANT.get(_canonical_gazebo_title(title)))
        ]
    )


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
    for name in GAZEBO_IMAGE_BY_VARIANT:
        number = re.search(r"№(\d+)", name)
        if number and number.group(1) in title:
            return name
    service_to_title = {
        "18201055": "Беседка №1",
        "18201056": "Беседка №2",
        "18201059": "Беседка №3",
        "18201061": "Беседка №4",
        "18201062": "Беседка №5",
        "18201063": "Беседка №6",
        "18201065": "Беседка №8",
        "19196656": "Крытая беседка",
    }
    return service_to_title.get(service_id, title)


def _gazebo_variants_from_text(text: str) -> list[str]:
    variants: list[str] = []
    patterns = (
        r"\bбеседк[а-яё]*\s*(?:№|номер\s*)?([1-8])\b",
        r"(?:№|номер\s*)([1-8])\b",
        r"\b([1-8])\s*(?:-?\s*)?(?:ю|ую|ая|я)?\s+беседк[а-яё]*",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            variant = f"Беседка №{match.group(1)}"
            if variant not in variants:
                variants.append(variant)
    for match in re.finditer(r"\b(?:первая|первую|вторая|вторую|третья|третью|четвертая|четвертую|пятая|пятую|шестая|шестую|восьмая|восьмую)\s+беседк[а-яё]*", text):
        number = {
            "первая": "1",
            "первую": "1",
            "вторая": "2",
            "вторую": "2",
            "третья": "3",
            "третью": "3",
            "четвертая": "4",
            "четвертую": "4",
            "пятая": "5",
            "пятую": "5",
            "шестая": "6",
            "шестую": "6",
            "восьмая": "8",
            "восьмую": "8",
        }.get(match.group(0).split()[0])
        if number:
            variant = f"Беседка №{number}"
            if variant not in variants:
                variants.append(variant)
    if "крыт" in text and "бесед" in text and "Крытая беседка" not in variants:
        variants.append("Крытая беседка")
    return variants


def _canonical_gazebo_title(title: str) -> str:
    normalized = _normalize(title)
    if "крыт" in normalized and "бесед" in normalized:
        return "Крытая беседка"
    match = re.search(r"№\s*([1-8])\b", normalized) or re.search(r"\bбеседк[а-яё]*\s*([1-8])\b", normalized)
    if match:
        return f"Беседка №{match.group(1)}"
    return title


def _reply_has_concrete_gazebo_context(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "свобод",
            "выбранную дату",
            "подходит",
            "подойдут",
            "подойдет",
            "подойдёт",
            "закрепляем",
            "выбрали",
            "выбрана",
            "выбран",
            "бронь",
            "заброниров",
        )
    )


def _reply_lists_available_options(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "свободны",
            "свободна",
            "свободные",
            "варианты",
            "подойдут",
            "рекоменд",
            "выбираете",
            "выбрать",
        )
    )


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
