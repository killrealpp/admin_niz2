import re
from typing import Any

from app.services.dialog.form_patches import looks_like_name
from app.services.dialog.formatting import format_date_ru, format_duration


def extract_corrected_client_name(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text.strip())
    lowered = normalized.lower().replace("ё", "е")
    if not any(marker in lowered for marker in ("имя", "фио", "зовут", "назови", "запиши", "укажи")):
        return None
    if re.search(r"(?:меня\s+зовут|зовут)\s+не\b", lowered) and not re.search(r"\bа\s+[a-zа-яё]", lowered):
        return None

    patterns = (
        r"(?:заменить|замени|заменим|поменять|поменяй|поменяем|изменить|измени|изменим|поправить|поправь|поправим)\s+(?:имя|фио)\s+(?:на\s+)?([A-Za-zА-Яа-яЁё -]{2,40})",
        r"(?:имя|фио)\s+(?:заменить|замени|заменим|поменять|поменяй|поменяем|изменить|измени|изменим|поправить|поправь|поправим)\s+(?:на\s+)?([A-Za-zА-Яа-яЁё -]{2,40})",
        r"(?:меня\s+зовут|зовут)\s+не\s+[A-Za-zА-Яа-яЁё -]{2,40}?[,\s]+(?:а|а\s+именно)\s+([A-Za-zА-Яа-яЁё -]{2,40})",
        r"(?:меня\s+зовут|зовут)\s+(?:как\s+)?([A-Za-zА-Яа-яЁё -]{2,40})",
        r"(?:имя|фио)\s*(?:будет|пусть\s+будет|:|-|=)?\s*([A-Za-zА-Яа-яЁё -]{2,40})",
        r"(?:запиши|укажи|поставь)\s+(?:имя\s+)?([A-Za-zА-Яа-яЁё -]{2,40})",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = clean_name_candidate(match.group(1))
        if candidate:
            return candidate
    return None


def clean_name_candidate(value: str) -> str | None:
    candidate = re.sub(r"\s+", " ", value.strip(" .,!?:;\"'«»"))
    candidate = re.sub(r"^(?:на|как|не|а)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"^(?:заменить|замени|заменим|поменять|поменяй|поменяем|изменить|измени|изменим|поправить|поправь|поправим)\s+(?:на\s+)?",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+(?:пожалуйста|плиз)$", "", candidate, flags=re.IGNORECASE)
    blocked = {
        "имя",
        "не",
        "нет",
        "поменять",
        "заменить",
        "изменить",
        "не даша",
    }
    if not candidate or candidate.lower().replace("ё", "е") in blocked:
        return None
    if not looks_like_name(candidate):
        return None
    if re.fullmatch(r"[A-Z -]{2,40}", candidate):
        return candidate
    return candidate.title()


def maybe_name_correction_without_value(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("имя", "фио", "зовут")) and any(
        marker in normalized for marker in ("не ", "невер", "ошиб", "не так")
    )


def correction_ack_text(patch: dict[str, Any]) -> str:
    labels: list[str] = []
    if "date" in patch:
        labels.append(f"дату на {format_date_ru(patch['date'])}")
    if "time" in patch:
        labels.append(f"время на {patch['time']}")
    if "duration" in patch:
        labels.append(f"длительность на {format_duration(patch['duration'])}")
    if "service_variant" in patch:
        labels.append(f"беседку на {patch['service_variant']}")
    if "client_name" in patch:
        labels.append(f"имя на {patch['client_name']}")
    if "phone" in patch:
        labels.append(f"телефон на {patch['phone']}")
    if "guests_count" in patch:
        labels.append(f"количество гостей на {patch['guests_count']}")
    if "event_format" in patch:
        labels.append(f"формат отдыха на {patch['event_format']}")
    if "upsell_items" in patch:
        items = patch.get("upsell_items") or []
        labels.append("допы: " + (", ".join(items) if items else "не нужны"))
    if not labels:
        return "Поняла, обновила данные ✅"
    return "Поняла, обновила " + "; ".join(labels) + " ✅"
