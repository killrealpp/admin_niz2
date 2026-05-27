import re
from typing import Any

from app.services.dialog.price_info import (
    looks_like_forbidden_broom_request,
    looks_like_price_question_text,
)


def service_type_patch(text: str) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    has_gazebo = "бесед" in normalized
    has_bathhouse = "бан" in normalized
    if looks_like_prior_booking_reference_text(normalized) and not explicit_new_service_request(normalized):
        if has_gazebo and not has_bathhouse:
            return {}
        if has_bathhouse and not has_gazebo:
            return {}
    if has_gazebo and has_bathhouse:
        if normalized.find("бан") < normalized.find("бесед"):
            return {"service_type": "bathhouse", "preferences": "беседка отдельной услугой"}
        return {"service_type": "gazebo", "preferences": "баня отдельной услугой"}
    if has_bathhouse:
        return {"service_type": "bathhouse"}
    if "тепл" in normalized and has_gazebo:
        return {"service_type": "warm_gazebo"}
    if "летн" in normalized and has_gazebo:
        return {"service_type": "summer_gazebo"}
    if has_gazebo:
        return {"service_type": "gazebo"}
    if "дом" in normalized or "домик" in normalized or "коттедж" in normalized:
        return {"service_type": "house"}
    return {}


def looks_like_same_time_reference_text(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    same_time = any(
        marker in normalized
        for marker in (
            "то же время",
            "тоже время",
            "такое же время",
            "в это же время",
            "время то же",
            "время такое же",
        )
    )
    if not same_time and any(marker in normalized for marker in ("час", "время")):
        same_time = any(
            marker in normalized
            for marker in (
                "те же",
                "так же",
                "также",
                "как там",
                "как было",
                "без изменений",
            )
        )
    return same_time and any(marker in normalized for marker in ("что и", "как у", "как в", "как "))


def looks_like_same_date_reference_text(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    same_date = any(
        marker in normalized
        for marker in (
            "ту же дату",
            "та же дата",
            "тот же день",
            "тем же днем",
            "тем же днём",
            "на тот же день",
            "на ту же дату",
            "в этот же день",
            "дата та же",
            "такую же дату",
        )
    )
    return same_date and any(marker in normalized for marker in ("что и", "как у", "как в", "как ", "у прошл", "в прошл"))


def looks_like_prior_booking_reference_text(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return looks_like_same_time_reference_text(normalized) or looks_like_same_date_reference_text(normalized)


def explicit_new_service_request(normalized: str) -> bool:
    return bool(
        re.search(
            r"\b(?:хочу|нужн[аоы]?|давай|давайте|можно|оформим|забронируй|забронить|забронировать)\b.*\b(?:бесед|бан|дом|домик|коттедж)\b",
            normalized,
        )
    )


def normalize_service_aliases(form_data: dict[str, Any]) -> dict[str, Any]:
    updated = dict(form_data)
    service_type = updated.get("service_type")
    if service_type == "summer_gazebo":
        updated["service_type"] = "gazebo"
        updated["preferences"] = join_preferences(updated.get("preferences"), "летняя беседка")
    elif service_type == "gazebo_bathhouse":
        updated["service_type"] = "gazebo"
        updated["preferences"] = join_preferences(updated.get("preferences"), "баня отдельной услугой")
    return updated


def join_preferences(current: Any, value: str) -> str:
    text = str(current or "").strip()
    if not text:
        return value
    if value.lower() in text.lower():
        return text
    return f"{text}; {value}"


def service_variant_patch(text: str, *, allow_bare_ordinal: bool = False) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    word_numbers = {
        "один": "1",
        "одну": "1",
        "первую": "1",
        "перую": "1",
        "перву": "1",
        "первая": "1",
        "первой": "1",
        "два": "2",
        "две": "2",
        "вторую": "2",
        "вторая": "2",
        "три": "3",
        "третью": "3",
        "третья": "3",
        "третьей": "3",
        "третьею": "3",
        "четыре": "4",
        "четвертую": "4",
        "четвертая": "4",
        "пять": "5",
        "пятую": "5",
        "пятая": "5",
        "шесть": "6",
        "шестую": "6",
        "шестая": "6",
        "семь": "7",
        "седьмую": "7",
        "седьмая": "7",
        "восемь": "8",
        "восьмую": "8",
        "восьмая": "8",
    }
    if "крыт" in normalized and "бесед" in normalized:
        return {"service_variant": "Крытая беседка"}
    if "прост" in normalized and ("мангал" in normalized or "обыч" in normalized):
        return {"preferences": "простая беседка с мангалом"}
    if "свет" in normalized or "розет" in normalized:
        return {"preferences": "беседка со светом и розетками"}
    if "больш" in normalized or "много мест" in normalized:
        return {"preferences": "большая беседка"}
    match = re.search(r"\b(?:беседк[аиуойе]*\s*)?№?\s*([1-8])\b", normalized)
    if match and "бесед" in normalized:
        return {"service_variant": f"Беседка №{match.group(1)}"}
    match = re.search(r"\b([1-8])\s*-?\s*(?:й|я|ю|ую|ая|ей|ею)\b", normalized)
    if match and (allow_bare_ordinal or "бесед" in normalized):
        return {"service_variant": f"Беседка №{match.group(1)}"}
    match = re.search(r"\b(?:номер|№|n)\s*([1-8])\b", normalized)
    if match:
        return {"service_variant": f"Беседка №{match.group(1)}"}
    match = re.search(r"\b([1-8])\s*(?:-?\s*)?(?:ю|ую|ая|я)?\s*беседк", normalized)
    if match:
        return {"service_variant": f"Беседка №{match.group(1)}"}
    for word, number in word_numbers.items():
        if re.search(rf"\b(?:номер\s+)?{word}\b", normalized) and (
            allow_bare_ordinal or "бесед" in normalized or "номер" in normalized
        ):
            return {"service_variant": f"Беседка №{number}"}
    return {}


def phone_patch(text: str) -> dict[str, str]:
    if not re.search(r"\+?\d[\d\s().-]{5,}\d", text):
        return {}
    digits = re.sub(r"\D", "", text)
    if len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return {"phone": "+" + digits}
    if 11 <= len(digits) <= 15 and not digits.startswith(("7", "8")):
        return {"phone": "+" + digits}
    return {"phone": text.strip()}


def event_format_patch(text: str) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    formats = (
        ("день рождения", ("день рождения", "др", "днюха", "юбилей")),
        ("корпоратив", ("корпоратив", "работ", "коллег")),
        ("свадьба", ("свадьб", "выездная регистрация")),
        ("семейный отдых", ("семейн", "семьей", "семья", "родствен")),
        ("компания друзей", ("друз", "компания", "с друзьями")),
        ("спокойный отдых", ("спокой", "споко", "тихий", "расслаб", "просто отдох", "просто отдых")),
    )
    for value, markers in formats:
        if any(marker in normalized for marker in markers):
            return {"event_format": value}
    return {}


def upsell_items_patch(text: str) -> dict[str, list[str]]:
    normalized = text.lower().replace("ё", "е")
    if looks_like_price_question_text(text) or looks_like_forbidden_broom_request(text):
        return {}
    cleaned = normalized.strip(" .,!?:;")
    no_extras = (
        "нет",
        "неа",
        "нте",
        "ytn",
        "не надо",
        "не нужно",
        "ничего",
        "без доп",
        "допы не нужны",
        "доп услуги не нужны",
        "дополнительные услуги не нужны",
        "свое",
        "все свое",
        "с собой",
        "сами привезем",
        "обойдемся своим",
    )
    fuzzy_no_extras = (
        "нет же",
        "ну нет",
        "ну не",
        "да нет",
        "та нет",
        "нет,",
        "нет.",
        "неа",
        "нте",
        "ytn",
        "ничего",
        "ничег",
        "нечег",
        "не надо",
        "не нужно",
        "не будем",
        "без доп",
        "свое",
        "все свое",
        "с собой",
        "сами привезем",
        "обойдемся своим",
    )
    if cleaned in no_extras or (cleaned.startswith("нет ") and "нет ли" not in cleaned) or any(marker in normalized for marker in fuzzy_no_extras):
        return {"upsell_items": ["не нужны"]}

    items: list[str] = []
    markers = {
        "базовый мангальный набор": ("базовый набор", "мангальный набор", "набор для мангала"),
        "уголь": ("уголь",),
        "розжиг": ("розжиг", "растоп"),
        "решетка/шампуры": ("решет", "шампур"),
        "лед": ("лед", "льда"),
        "посуда": ("посуд", "стакан", "тарел"),
        "кальян": ("кальян",),
        "вода": ("вода", "воду", "воды", "чай", "напит"),
    }
    for item, item_markers in markers.items():
        if any(marker in normalized for marker in item_markers):
            items.append(item)
    if items:
        return {"upsell_items": items}
    return {}


def is_upsell_negative(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    return bool(upsell_items_patch(text).get("upsell_items") == ["не нужны"]) or normalized in {
        "нет",
        "неа",
        "нте",
        "ytn",
        "не надо",
        "не нужно",
        "ничего",
        "без допов",
    }


def upsell_push_reply(form_data: dict[str, Any]) -> str:
    service_type = form_data.get("service_type")
    variants = upsell_sales_messages(service_type)
    index = int(form_data.get("upsell_offer_count") or 0) % len(variants)
    usual, soft, minimal = variants[index]
    return (
        f"Поняла ✅ Всё же подскажу по опыту: {usual}.\n\n"
        f"{soft}\n\n"
        f"{minimal}\n\n"
        "Что добавим? Если точно ничего не нужно, напишите «нет» ещё раз."
    )


def upsell_sales_messages(service_type: Any) -> list[tuple[str, str, str]]:
    if service_type == "bathhouse":
        return [
            ("к бане чаще всего берут воду, лёд для напитков, посуду и кальян", "Так компания не отвлекается на мелочи, а отдых сразу получается собранным 🧊", "Могу добавить хотя бы воду или лёд — это обычно точно пригождается."),
            ("для бани удобно сразу подготовить воду, лёд и посуду", "После парной не хочется искать стаканы или напитки — всё уже будет под рукой 💧", "Добавим минимально воду и лёд?"),
            ("к бане часто добавляют кальян и лёд", "Получается более полноценный вечер, особенно если компания остаётся отдыхать после парной.", "Могу отметить только кальян или только лёд."),
        ]
    if service_type == "gazebo":
        return [
            ("к беседке чаще всего берут базовый набор для мангала: уголь, розжиг, решётку или шампуры, плюс посуду и лёд", "Это экономит время перед заездом: не нужно срочно искать магазин перед отдыхом 🔥", "Могу поставить минимум — уголь и розжиг, а остальное не добавлять."),
            ("для шашлыков обычно берут уголь, розжиг и решётку/шампуры", "Мангал есть, а вот расходники удобнее подготовить заранее, чтобы сразу начать готовить.", "Добавим только мангальный минимум?"),
            ("на компанию часто берут лёд, посуду и воду", "Это мелочи, но именно они чаще всего вспоминаются уже на месте 🧊", "Могу отметить только лёд или посуду."),
            ("для дня рождения обычно берут мангальный набор, лёд и посуду", "Так стол и мангал можно собрать без лишних заездов по дороге.", "Добавим самый базовый набор для праздника?"),
            ("если будут дети, удобно заранее подготовить воду, посуду и мангальный набор", "Так взрослые меньше отвлекаются на бытовые мелочи, а отдых проходит спокойнее.", "Могу добавить только воду и посуду."),
        ]
    if service_type == "house":
        return [
            ("к дому обычно берут посуду, лёд, воду и кальян", "Это удобно, если компания планирует отдыхать дольше и не хочет везти всё с собой 🏡", "Могу добавить только воду или посуду, без лишнего."),
            ("для дома часто выбирают воду, посуду и лёд", "Когда всё подготовлено заранее, можно сразу заняться отдыхом, а не раскладкой мелочей.", "Добавим минимальный набор?"),
        ]
    return [
        ("обычно берут посуду, лёд, воду или кальян", "Можно добавить только то, что действительно пригодится ✅", "Могу отметить самый базовый вариант, без лишнего."),
    ]


def has_upsell_signal(text: str) -> bool:
    if looks_like_price_question_text(text) or looks_like_forbidden_broom_request(text):
        return False
    return bool(upsell_items_patch(text)) or any(
        marker in text.lower().replace("ё", "е")
        for marker in ("доп", "уголь", "розжиг", "решет", "решот", "шампур", "лед", "посуд", "кальян")
    )


def looks_like_name(text: str) -> bool:
    normalized = text.strip().replace("ё", "е")
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё -]{2,40}", normalized):
        return False
    lowered = normalized.lower()
    blocked = {
        "да",
        "нет",
        "ок",
        "окей",
        "хорошо",
        "корпоратив",
        "день рождения",
        "семейный отдых",
    }
    return lowered not in blocked and not has_upsell_signal(lowered)


def valid_phone(value: Any) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 10 and digits.startswith("9"):
        return True
    if digits.startswith(("7", "8")):
        return len(digits) == 11
    return 11 <= len(digits) <= 15


def guests_count_patch(text: str, expected_key: str | None) -> dict[str, int]:
    if expected_key != "guests_count":
        return {}
    normalized = text.lower().replace("ё", "е").strip()
    range_match = re.search(
        r"\b(\d{1,3})\s*(?:-|–|—|до)\s*(\d{1,3})\s*(?:человек|гостей|гостя|гость|чел)\b",
        normalized,
    )
    if range_match:
        guests = max(int(range_match.group(1)), int(range_match.group(2)))
        if 0 < guests <= 300:
            return {"guests_count": guests}
    match = re.fullmatch(r"(?:нас\s*)?(\d{1,3})(?:\s*(?:человек|гостей|гостя|гость|чел))?", normalized)
    if not match:
        match = re.search(r"\bнас\s+(\d{1,3})\b", normalized)
    if not match:
        match = re.search(r"\b(\d{1,3})\s*(?:человек|гостей|гостя|гость|чел)\b", normalized)
    if not match:
        match = re.search(r"\b(\d{1,3})\s*(?:взрослых|взрослые|взрослый)\b", normalized)
    if not match:
        return {}
    guests = int(match.group(1))
    if guests <= 0 or guests > 300:
        return {}
    return {"guests_count": guests}


def client_name_patch(text: str, expected_key: str | None) -> dict[str, str]:
    if expected_key != "client_name":
        return {}
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not looks_like_name(cleaned):
        return {}
    return {"client_name": cleaned.title()}
