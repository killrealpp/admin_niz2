from __future__ import annotations

import re
from typing import Any

from app.services.dialog.formatting import format_date_ru, format_duration


def bathhouse_period_options_reply(form_data: dict[str, Any]) -> tuple[str, str] | None:
    if form_data.get("service_type") != "bathhouse" or not form_data.get("date"):
        return None
    if form_data.get("time") and form_data.get("duration"):
        return None

    date_text = format_date_ru(form_data.get("date"))
    packages = (
        "Баня бронируется пакетами от 3 до 7 часов.\n"
        "Цены: будни / пятница-воскресенье.\n"
        "- 3 часа: 6 300 / 7 950 ₽\n"
        "- 4 часа: 8 400 / 10 600 ₽\n"
        "- 5 часов: 10 500 / 13 250 ₽\n"
        "- 6 часов: 12 600 / 15 900 ₽\n"
        "- 7 часов: 14 700 / 18 550 ₽\n\n"
        "Если нужно дольше 7 часов: берём 7-часовой пакет и добавляем +1 500 ₽ за каждый следующий час."
    )
    if not form_data.get("time") and not form_data.get("duration"):
        return (
            f"Дату вижу: {date_text}. Для проверки свободности бани мне нужен период: во сколько заезжаете и до скольки отдыхаете.\n\n"
            f"{packages}\n\n"
            "Напишите одним сообщением, например: «с 18:00 до 01:00» или «с 12:00 на 5 часов».",
            "time",
        )
    if form_data.get("time"):
        return (
            f"Время вижу: {date_text} с {form_data.get('time')}. Точную свободность проверю после длительности.\n\n"
            f"{packages}\n\n"
            "На сколько часов бронируем баню? Можно написать просто «5 часов» или окончание периода, например: «до 01:00».",
            "duration",
        )
    return (
        f"Длительность вижу: {format_duration(form_data.get('duration'))} на {date_text}. "
        "Точную свободность проверю после времени старта.\n\n"
        f"{packages}\n\n"
        "Во сколько хотите приехать? Можно сразу написать полный период, например: «с 18:00 до 01:00».",
        "time",
    )


def looks_like_bathhouse_period_options_question(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("бан", "парн", "саун", "бассейн")):
        return False
    return any(
        marker in normalized
        for marker in (
            "на сколько",
            "сколько часов",
            "длительн",
            "пакет",
            "период",
            "когда свобод",
            "когда можно",
            "во сколько",
            "свободно",
            "свободна",
            "свободные",
        )
    )


def bathhouse_alcohol_reply(text: str, form_data: dict[str, Any]) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if form_data.get("service_type") != "bathhouse" and "бан" not in normalized:
        return None
    if not any(marker in normalized for marker in ("алког", "выпить", "пить", "напит", "бух")):
        return None
    return (
        "В бане можно аккуратно: напитки можно взять с собой.\n\n"
        "Просим без стекла у бассейна и с соблюдением порядка и безопасности."
    )


def bathhouse_pool_included_reply(text: str, form_data: dict[str, Any]) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if form_data.get("service_type") != "bathhouse" and "бан" not in normalized:
        return None
    if "бассейн" not in normalized:
        return None
    if not any(marker in normalized for marker in ("вмест", "входит", "включ", "идет", "идёт", "есть")):
        return None
    return "Да, это баня с бассейном, бассейн входит в бронь."


def bathhouse_separate_booking_complaint_reply(text: str, form_data: dict[str, Any]) -> str | None:
    if form_data.get("service_type") != "bathhouse":
        return None
    normalized = text.lower().replace("ё", "е")
    if "отдель" not in normalized or "брон" not in normalized:
        return None
    if not any(marker in normalized for marker in ("почему", "зачем", "че", "что", "говор")):
        return None
    if not any(marker in normalized for marker in ("бан", "бассейн")):
        return None
    return "Вы правы, баню уже оформляем; это баня с бассейном."


def bathhouse_active_reply_mentions_separate_booking(reply: str, form_data: dict[str, Any]) -> bool:
    if form_data.get("service_type") != "bathhouse":
        return False
    normalized = reply.lower().replace("ё", "е")
    return bool(
        "бан" in normalized
        and "отдель" in normalized
        and re.search(r"\bброн", normalized)
    )
