from __future__ import annotations

import re
from typing import Any

from app.services.booking_form_service import next_question


_META_INSTRUCTION_MARKERS = (
    "задай",
    "спроси",
    "скажи",
    "подтверди",
    "начни",
    "не перечисляй",
    "не спрашивай",
    "вежливо",
    "коротко",
    "объясни",
    "сформулируй",
    "клиент указал",
)


def deterministic_process_reply(required_meaning: str) -> str | None:
    text = (required_meaning or "").strip()
    if not text:
        return None
    lowered = text.lower().replace("ё", "е")
    if "информацион" in lowered:
        return None
    if _looks_like_internal_instruction(lowered):
        return None
    if _looks_like_json_or_schema(text):
        return None
    return text


def looks_like_internal_instruction_text(text: str) -> bool:
    lowered = (text or "").strip().lower().replace("ё", "е")
    if not lowered:
        return False
    return _looks_like_internal_instruction(lowered) or _looks_like_json_or_schema(text)


def fallback_process_reply(required_meaning: str, form_data: dict[str, Any] | None = None) -> str:
    direct = deterministic_process_reply(required_meaning)
    if direct:
        return direct

    text = (required_meaning or "").strip()
    lowered = text.lower().replace("ё", "е")
    parts: list[str] = []
    form = form_data or {}
    preferences = str(form.get("preferences") or "").lower().replace("ё", "е")
    service_type = form.get("service_type")
    if service_type == "gazebo" and "бан" in preferences:
        parts.append("Беседку поняла ✅")
        parts.append("Баню оформим второй отдельной бронью после беседки.")
    elif service_type == "bathhouse" and "бесед" in preferences:
        parts.append("Баню поняла ✅")
        parts.append("Беседку оформим отдельной бронью после бани.")
    elif "втор" in lowered and "брон" in lowered:
        parts.append("Оформляем вторую бронь ✅")
    if "имя и телефон" in lowered or "телефон уже есть" in lowered:
        parts.append("Имя и телефон уже есть, повторно их спрашивать не буду.")

    question = _question_from_instruction(lowered)
    if not question:
        _, question = next_question(form_data or {})
    if question:
        parts.append(question)
    if parts:
        return "\n\n".join(parts)
    return "Поняла. Продолжим оформление?"


def _looks_like_internal_instruction(lowered: str) -> bool:
    return any(marker in lowered for marker in _META_INSTRUCTION_MARKERS)


def _question_from_instruction(lowered: str) -> str | None:
    if "на какую дату" in lowered or ("дат" in lowered and "вопрос" in lowered):
        if "бесед" in lowered:
            return "На какую дату нужна беседка?"
        if "бан" in lowered:
            return "На какую дату нужна баня?"
        return "На какую дату планируете отдых?"
    if "во сколько" in lowered or "время" in lowered:
        return "Во сколько хотите приехать? Можно сразу написать период, например: с 18:00 до 00:00."
    if "сколько" in lowered and ("гост" in lowered or "человек" in lowered):
        return "Сколько вас будет человек?"
    if "формат" in lowered:
        return "Какой формат отдыха: день рождения, корпоратив, семейный отдых, компания друзей или спокойный вечер?"
    if "телефон" in lowered:
        return "Телефон для бронирования?"
    if "имя" in lowered or "как вас зовут" in lowered:
        return "На какое имя записать бронь?"
    if "подтвержд" in lowered and "брон" in lowered:
        return "Подтверждаете бронь?"
    return None


def _looks_like_json_or_schema(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        return True
    return bool(re.search(r"\b(intent|action|form_data|current_step)\s*[:=]", stripped, flags=re.IGNORECASE))
