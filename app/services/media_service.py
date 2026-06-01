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
    "Беседка №8": IMAGES_DIR / "besedka8.jpg",
    "Крытая беседка": IMAGES_DIR / "besedka_krytaya.jpg",
    "Тёплая беседка": IMAGES_DIR / "besedka_teplaya.jpg",
}

SERVICE_IMAGE_BY_TYPE = {
    "bathhouse": IMAGES_DIR / "banya.jpg",
    "house": IMAGES_DIR / "dom_gostevoy.jpg",
    "warm_gazebo": IMAGES_DIR / "besedka_teplaya.jpg",
}

SERVICE_TITLE_BY_TYPE = {
    "bathhouse": "Баня",
    "house": "Гостевой дом",
    "warm_gazebo": "Тёплая беседка",
}


def media_for_client_message(text: str, reply: str) -> list[Path]:
    normalized_text = _normalize(text)
    normalized_reply = _normalize(reply)
    combined = f"{normalized_text}\n{normalized_reply}"
    if not _mentions_media_subject(combined):
        return []

    explicit_photo_request = is_explicit_photo_request(text)
    if explicit_photo_request:
        explicit_paths: list[Path] = []
        requested_service_paths = media_for_service_types(_service_types_from_text(normalized_text))
        if requested_service_paths:
            explicit_paths.extend(requested_service_paths)
        requested_variants = _gazebo_variants_from_text(normalized_text)
        if requested_variants:
            explicit_paths.extend(media_for_gazebo_titles(requested_variants))
        if explicit_paths:
            return _existing(explicit_paths)
        reply_service_paths = media_for_service_types(_service_types_from_text(normalized_reply))
        if reply_service_paths:
            return reply_service_paths
        reply_variants = _gazebo_variants_from_text(normalized_reply)
        if reply_variants:
            return media_for_gazebo_titles(reply_variants)

    reply_variants = _gazebo_variants_for_auto_media(normalized_reply)
    if (
        reply_variants
        and _reply_has_concrete_gazebo_context(normalized_reply)
        and _reply_lists_available_options(normalized_reply)
        and _reply_has_date_and_guest_count(normalized_reply)
    ):
        return media_for_gazebo_titles(reply_variants)
    if _reply_is_booking_list(normalized_reply):
        booking_list_paths = media_for_gazebo_titles(_gazebo_variants_from_text(normalized_reply))
        booking_list_paths.extend(media_for_service_types(_service_types_from_text(normalized_reply)))
        return _existing(booking_list_paths)
    service_types = _service_types_for_auto_media(normalized_reply)
    if service_types:
        return media_for_service_types(service_types)
    return []


def missing_media_titles_for_client_message(text: str, reply: str) -> list[str]:
    normalized_text = _normalize(text)
    normalized_reply = _normalize(reply)
    combined = f"{normalized_text}\n{normalized_reply}"
    if not _mentions_media_subject(combined):
        return []

    titles: list[str] = []
    if is_explicit_photo_request(text):
        missing = _missing_service_media_titles(_service_types_from_text(normalized_text))
        if missing:
            return missing
        titles = _gazebo_variants_from_text(normalized_text)
        if not titles:
            missing = _missing_service_media_titles(_service_types_from_text(normalized_reply))
            if missing:
                return missing
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


def media_for_service_types(service_types: list[str]) -> list[Path]:
    return _existing(
        [
            path
            for service_type in service_types
            if (path := SERVICE_IMAGE_BY_TYPE.get(service_type))
        ]
    )


def _missing_service_media_titles(service_types: list[str]) -> list[str]:
    missing: list[str] = []
    seen: set[str] = set()
    for service_type in service_types:
        title = SERVICE_TITLE_BY_TYPE.get(service_type, service_type)
        path = SERVICE_IMAGE_BY_TYPE.get(service_type)
        if path and not path.exists() and title not in seen:
            missing.append(title)
            seen.add(title)
    return missing


def _gazebo_variants_for_auto_media(text: str) -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()
    alternatives_block = False
    capacity_rejected = _reply_rejects_capacity(text) or any(
        marker in text for marker in ("не закреп", "не вижу подход", "тесно")
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(marker in line for marker in ("ближайшие даты", "где есть беседки", "подходящие варианты")):
            alternatives_block = True
        line_variants = _gazebo_variants_from_text(line)
        if not line_variants:
            continue
        if _line_rejects_gazebo_option(line):
            continue
        if capacity_rejected and not alternatives_block and not _line_has_suitable_capacity_claim(line):
            continue
        if not alternatives_block and not _line_supports_auto_media(line):
            continue
        for title in line_variants:
            canonical = _canonical_gazebo_title(title)
            if canonical not in seen:
                variants.append(canonical)
                seen.add(canonical)
    if variants:
        return variants
    if capacity_rejected:
        return []
    return _gazebo_variants_from_text(text)


def _line_has_suitable_capacity_claim(line: str) -> bool:
    return any(
        marker in line
        for marker in (
            "подойдет",
            "подойдёт",
            "подойдут",
            "подходят",
            "подходящие",
        )
    )


def _line_supports_auto_media(line: str) -> bool:
    return any(
        marker in line
        for marker in (
            "свобод",
            "подойдет",
            "подойдёт",
            "подойдут",
            "подходят",
            "подходящие",
            "вариант",
            "выбран",
            "выбрали",
            "закреп",
        )
    )


def _line_rejects_gazebo_option(line: str) -> bool:
    return any(
        marker in line
        for marker in (
            "рассчитан",
            "а вас будет",
            "не закреп",
            "не подходит",
            "не подойдут",
            "не подойдет",
            "не подойдёт",
            "не подходят",
            "не вижу подход",
            "тесно",
            "тесноват",
        )
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
    service_type = str(booking.get("service_type") or "")
    if service_type in SERVICE_IMAGE_BY_TYPE:
        return SERVICE_IMAGE_BY_TYPE[service_type]
    if service_type != "gazebo":
        return None
    title = _booking_title(booking)
    return GAZEBO_IMAGE_BY_VARIANT.get(title)


def _booking_title(booking: dict[str, Any]) -> str:
    title = str(
        booking.get("service_variant")
        or booking.get("object_title")
        or booking.get("service_title")
        or booking.get("title")
        or booking.get("preferences")
        or ""
    )
    fallback_title = str(booking.get("preferences") or "")
    if fallback_title and fallback_title not in title:
        title = f"{title} {fallback_title}".strip()
    if "крыт" in title.lower().replace("ё", "е"):
        return "Крытая беседка"
    service_id = str(
        booking.get("hold_yclients_service_id")
        or booking.get("yclients_service_id")
        or booking.get("service_id")
        or ""
    )
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
        "18201071": "Тёплая беседка",
    }
    return service_to_title.get(service_id, title)


def _gazebo_variants_from_text(text: str) -> list[str]:
    variants: list[str] = []
    patterns = (
        r"\bбеседк[а-яё]*\s*(?:№|номер\s*)?([1-8])\b",
        r"(?:№|номер\s*)([1-8])\b",
        r"\b([1-8])\s*-?\s*(?:й|я|ю|ую|ая|ей|ею)\b(?=.*бесед)",
        r"\b([1-8])\s*(?:-?\s*)?(?:ю|ую|ая|я)?\s+беседк[а-яё]*",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            variant = f"Беседка №{match.group(1)}"
            if variant not in variants:
                variants.append(variant)
    for match in re.finditer(r"\b(?:первая|первую|вторая|вторую|третья|третью|третьей|четвертая|четвертую|пятая|пятую|шестая|шестую|восьмая|восьмую)\s+беседк[а-яё]*", text):
        number = {
            "первая": "1",
            "первую": "1",
            "вторая": "2",
            "вторую": "2",
            "третья": "3",
            "третью": "3",
            "третьей": "3",
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
    if "тепл" in text and "бесед" in text and "Тёплая беседка" not in variants:
        variants.append("Тёплая беседка")
    return variants


def _canonical_gazebo_title(title: str) -> str:
    normalized = _normalize(title)
    if "крыт" in normalized and "бесед" in normalized:
        return "Крытая беседка"
    if "тепл" in normalized and "бесед" in normalized:
        return "Тёплая беседка"
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


def _reply_has_date_and_guest_count(text: str) -> bool:
    has_date = bool(
        re.search(
            r"\b\d{1,2}\s*(?:мая|июня|июля|августа|сентября|октября|ноября|декабря|января|февраля|марта|апреля)\b",
            text,
        )
    ) or "выбранную дату" in text
    has_guests = bool(re.search(r"\b\d{1,3}\s*(?:гостей|гостя|гость|человек|чел)\b", text))
    return has_date and has_guests


def _reply_rejects_capacity(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "не подходят",
            "не подойдет",
            "не подойдёт",
            "не закреп",
            "тесноват",
            "тесно",
            "по вместимости они могут",
            "по вместимости они не",
        )
    )


def _mentions_gazebo(text: str) -> bool:
    return "бесед" in text


def _mentions_media_subject(text: str) -> bool:
    return _mentions_gazebo(text) or bool(_service_types_from_text(text))


def _service_types_from_text(text: str) -> list[str]:
    result: list[str] = []
    if "бан" in text or "саун" in text:
        result.append("bathhouse")
    if "гостев" in text and "дом" in text:
        result.append("house")
    elif re.search(r"\bдом(?:ик|а|е|ом|у)?\b", text) and "домой" not in text:
        result.append("house")
    if "тепл" in text and "бесед" in text:
        result.append("warm_gazebo")
    return _unique(result)


def _service_types_for_auto_media(text: str) -> list[str]:
    if not _reply_has_positive_media_context(text):
        return []
    if not _reply_has_date(text):
        return []
    return _service_types_from_text(text)


def _reply_has_positive_media_context(text: str) -> bool:
    if any(
        marker in text
        for marker in (
            "не наш",
            "нет свобод",
            "свободных вариантов не",
            "не вижу свобод",
            "не получилось",
        )
    ):
        return False
    return any(
        marker in text
        for marker in (
            "свобод",
            "подходит",
            "подойдут",
            "выбрали",
            "выбран",
            "бронь",
            "заброниров",
            "закреп",
        )
    )


def _reply_has_date(text: str) -> bool:
    return bool(
        re.search(
            r"\b\d{1,2}\s*(?:мая|июня|июля|августа|сентября|октября|ноября|декабря|января|февраля|марта|апреля)\b",
            text,
        )
    ) or "выбранную дату" in text


def _reply_is_booking_list(text: str) -> bool:
    return bool(
        re.search(r"\bу вас\s+\d+\s+брон", text)
        or ("у вас" in text and "бронь" in text and "оплата" in text)
    )


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


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
