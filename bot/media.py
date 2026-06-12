from __future__ import annotations

import re
from pathlib import Path

IMAGES_DIR = Path(__file__).resolve().parents[1] / "images"

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
    "Теплая беседка": IMAGES_DIR / "besedka_teplaya.jpg",
}

SERVICE_IMAGE_BY_TYPE = {
    "bathhouse": IMAGES_DIR / "banya.jpg",
    "house": IMAGES_DIR / "dom_gostevoy.jpg",
    "warm_gazebo": IMAGES_DIR / "besedka_teplaya.jpg",
    "баня": IMAGES_DIR / "banya.jpg",
    "баня с бассейном": IMAGES_DIR / "banya.jpg",
    "гостевой дом": IMAGES_DIR / "dom_gostevoy.jpg",
    "дом": IMAGES_DIR / "dom_gostevoy.jpg",
    "тёплая беседка": IMAGES_DIR / "besedka_teplaya.jpg",
    "теплая беседка": IMAGES_DIR / "besedka_teplaya.jpg",
}

# Сколько фото максимум отправлять одним ответом. Telegram media group ограничен 10 файлами.
MAX_MEDIA_PER_REPLY = 10


def extract_media_titles_from_reply(text: str) -> list[str]:
    """Достаёт явный маркер действия от LLM из ответа бота.

    Поддерживаем варианты:
    - Фото вариантов: ...
    - Вот фото вариантов: ...

    Это не анализ сообщения пользователя. Модель сама решает, когда нужны фото,
    а код только выполняет команду из финального ответа.
    """
    marker = re.search(
        r"(?:^|\n)\s*(?:вот\s+)?фото\s+вариантов\s*:\s*(.+)",
        text,
        flags=re.IGNORECASE,
    )
    if not marker:
        return []

    raw = marker.group(1).strip().splitlines()[0].strip()
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    return _resolve_titles(requested)


def remove_media_marker_from_reply(text: str) -> str:
    """Оставлено для совместимости. Сейчас telegram.py маркер не удаляет."""
    lines: list[str] = []
    for line in text.splitlines():
        normalized = line.lower().replace("ё", "е").strip()
        if re.match(r"^(?:вот\s+)?фото\s+вариантов\s*:", normalized):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def paths_for_requested_media(requested_media: list[str]) -> list[Path]:
    """Возвращает фото по явным названиям от LLM/requested_media."""
    paths: list[Path] = []

    for item in requested_media or []:
        key = str(item).strip()
        if not key:
            continue

        path = GAZEBO_IMAGE_BY_VARIANT.get(key)
        if path:
            paths.append(path)
            continue

        service_path = SERVICE_IMAGE_BY_TYPE.get(key)
        if service_path:
            paths.append(service_path)
            continue

        normalized = _normalize_title(key)

        for title, title_path in GAZEBO_IMAGE_BY_VARIANT.items():
            if _normalize_title(title) == normalized:
                paths.append(title_path)
                break
        else:
            service_path = SERVICE_IMAGE_BY_TYPE.get(normalized)
            if service_path:
                paths.append(service_path)

    return _existing(paths)[:MAX_MEDIA_PER_REPLY]


def _resolve_titles(requested: list[str]) -> list[str]:
    known_titles = list(GAZEBO_IMAGE_BY_VARIANT.keys()) + list(SERVICE_IMAGE_BY_TYPE.keys())
    result: list[str] = []

    for title in requested:
        normalized = _normalize_title(title)
        matched: str | None = None

        for known in known_titles:
            if _normalize_title(known) == normalized:
                matched = known
                break

        if matched is None:
            # Нормализуем команды LLM, а не текст пользователя.
            # Например: "Баня с бассейном" -> bathhouse, "Гостевой дом" -> house.
            if "бан" in normalized or "бассейн" in normalized:
                matched = "bathhouse"
            elif "гост" in normalized or normalized == "дом":
                matched = "house"
            elif "тепл" in normalized:
                matched = "Тёплая беседка"
            elif "крыт" in normalized:
                matched = "Крытая беседка"
            elif "беседка" in normalized:
                # На случай если модель написала без знака №: "Беседка 1".
                number_match = re.search(r"\b(1|2|3|4|5|6|8)\b", normalized)
                if number_match:
                    matched = f"Беседка №{number_match.group(1)}"

        if matched and matched not in result:
            result.append(matched)

    return result


def _normalize_title(value: str) -> str:
    value = value.lower().replace("ё", "е")
    value = value.replace("№", "")
    value = value.replace("#", "")
    value = value.replace(".", "")
    return " ".join(value.split())


def _existing(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path.exists() and path not in seen:
            result.append(path)
            seen.add(path)
    return result
