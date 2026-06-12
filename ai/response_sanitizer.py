from __future__ import annotations

import re


_BAD_PREFIX_PATTERNS = [
    r"^\s*конечно!?\s*вот\s+(?:дружелюбный\s+)?(?:и\s+понятный\s+)?ответ(?:\s+клиенту)?[^:\n]*[:\n]+",
    r"^\s*вот\s+(?:дружелюбный\s+)?(?:и\s+понятный\s+)?ответ(?:\s+клиенту)?[^:\n]*[:\n]+",
    r"^\s*ответ\s+клиенту[^:\n]*[:\n]+",
    r"^\s*сообщение\s+клиенту[^:\n]*[:\n]+",
]

_FORBIDDEN_TECH_REPLACEMENTS = {
    r"\bYCLIENTS\b": "система бронирования",
    r"\bbackend\b": "система",
    r"\bAPI\b": "система",
    r"\bJSON\b": "данные",
    r"\baction\b": "действие",
    r"\bdatabase\b": "база",
    r"\bsystem\b": "система",
    r"системн(?:ая|ой|ую|ые|ых)?\s+провер(?:ка|ке|ку|ки)": "проверка",
    r"предоставленн(?:ых|ые|ой|ую)\s+данн(?:ых|ые|ым)": "данные",
}


def sanitize_reply(reply: str, *, fallback: str = "Подскажите, пожалуйста, что хотите уточнить?") -> str:
    """Приводит ответ LLM к виду сообщения клиенту, а не текста для оператора."""
    text = (reply or "").strip()
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"^```(?:text|markdown)?|```$", "", text, flags=re.I | re.M).strip()
    text = re.sub(r"^[-–—]{3,}\s*", "", text).strip()

    changed = True
    while changed:
        changed = False
        for pattern in _BAD_PREFIX_PATTERNS:
            new_text = re.sub(pattern, "", text, flags=re.I | re.S).strip()
            if new_text != text:
                text = new_text
                changed = True

    # Если модель всё равно вернула текст-инструкцию, забираем часть после маркера/двоеточия.
    if re.search(r"ответ\s+клиенту|сообщение\s+клиенту|дружелюбный\s+ответ", text, flags=re.I):
        parts = re.split(r"[:\n]", text, maxsplit=1)
        if len(parts) == 2 and len(parts[1].strip()) >= 10:
            text = parts[1].strip()

    for pattern, replacement in _FORBIDDEN_TECH_REPLACEMENTS.items():
        text = re.sub(pattern, replacement, text, flags=re.I)

    text = re.sub(r"(?i)сейчас отправлю фото[^\n.]*[.\n]?", "", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if not text or re.fullmatch(r"[-–—*\s]+", text):
        return fallback
    return text
