from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.services.availability_service import load_services_map
from app.services.booking_form_service import next_question
from app.services.dialog.formatting import format_date_ru, format_duration, format_rub


SelectedVariantConfig = Callable[[dict[str, Any]], dict[str, Any]]


def looks_like_price_question_text(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if any(marker in normalized for marker in ("цен", "стоимость", "стоит", "стоят", "стоим", "почем", "по чем", "по-чем", "прайс", "денег", "предоплат", "аванс", "оплат")):
        return True
    if not any(marker in normalized for marker in ("сколько", "скольк", "скольок", "скок", "скока")):
        return False
    return any(
        marker in normalized
        for marker in (
            "стоит",
            "стоят",
            "денег",
            "руб",
            "₽",
            "уголь",
            "розжиг",
            "решет",
            "решот",
            "шампур",
            "посуд",
            "лед",
            "вода",
            "кальян",
            "доп",
            "это",
            "все",
            "всё",
        )
    )


def looks_like_forbidden_broom_request(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("веник", "веники", "венич", "попариться вен"))


def addon_price_reply(text: str) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if looks_like_forbidden_broom_request(text):
        return (
            "Веники использовать нельзя ни в коем случае: за это предусмотрен штраф.\n\n"
            "В заявку их не добавляю."
        )
    asks_all_addons = bool(
        re.search(r"\b(?:доп|допы|допов|допами|доп\.|допуслуг\w*|дополнительн\w*)\b", normalized)
    ) and looks_like_price_question_text(text)
    lines: list[str] = []
    if asks_all_addons or "кальян" in normalized:
        lines.append("Кальян — 1 500 ₽: одна заправка и 5 углей. Дополнительная заправка с углём — 600 ₽.")
    if asks_all_addons or any(marker in normalized for marker in ("решет", "решот", "шампур", "мангал", "уголь", "розжиг")):
        lines.append("Мангальный набор №1 — 500 ₽: решётка, кочерга, опахало.")
        lines.append("Мангальный набор №2 — 1 000 ₽: шампуры, кочерга, опахало.")
        lines.append("Малый мангальный набор — 400 ₽: маленькие шампуры, кочерга, опахало.")
        if "уголь" in normalized or "розжиг" in normalized:
            lines.append("Отдельной точной цены угля или розжига в базе нет, поэтому отдельно цену не придумываю.")
    if asks_all_addons or any(marker in normalized for marker in ("лед", "вода", "посуд", "чай", "напит")):
        lines.append("По воде, льду, посуде и напиткам точной отдельной цены в базе нет — могу отметить в заявке, а сумму уточним по факту.")
    if not lines:
        return None
    return "\n".join(lines)


def is_addon_price_context(text: str, form_data: dict[str, Any]) -> bool:
    if not looks_like_price_question_text(text):
        return False
    next_key, _ = next_question(form_data)
    if next_key == "upsell_items":
        return True
    if int(form_data.get("upsell_offer_count") or 0) > 0 and not form_data.get("upsell_items"):
        return True
    return False


def addon_price_followup(form_data: dict[str, Any]) -> str | None:
    next_key, question = next_question(form_data)
    if next_key == "upsell_items":
        return question
    if not form_data.get("upsell_items"):
        return "Что из этого подготовить для вас? Если ничего не нужно, напишите «нет»."
    return question


def service_price_table_reply(service_type: str | None) -> str | None:
    services = load_services_map()
    if service_type == "gazebo":
        variants = (services.get("gazebo") or {}).get("variants") or []
        if not variants:
            return None
        lines = ["По беседкам цены такие:"]
        for variant in variants:
            price = variant.get("price")
            if price:
                lines.append(f"- {variant.get('title')}: {format_rub(price)} ₽")
        return "\n".join(lines)
    if service_type == "bathhouse":
        return (
            "Баня с бассейном считается по длительности и дню недели:\n"
            "- 3 часа: 6 300 ₽ в будни / 7 950 ₽ в пятницу-воскресенье\n"
            "- 4 часа: 8 400 ₽ в будни / 10 600 ₽ в пятницу-воскресенье\n"
            "- 5 часов: 10 500 ₽ в будни / 13 250 ₽ в пятницу-воскресенье\n"
            "- 6 часов: 12 600 ₽ в будни / 15 900 ₽ в пятницу-воскресенье\n"
            "- 7 часов: 14 700 ₽ в будни / 18 550 ₽ в пятницу-воскресенье"
        )
    if service_type == "house":
        return (
            "Гостевой дом:\n"
            "- 4 часа — 6 400 ₽\n"
            "- 5 часов — 8 000 ₽\n"
            "- 6 часов — 9 600 ₽\n"
            "- 7 часов — 11 200 ₽\n"
            "- сутки — 10 500 ₽ в будни / 12 600 ₽ в пятницу-воскресенье"
        )
    if service_type == "warm_gazebo":
        price = (services.get("warm_gazebo") or {}).get("price")
        return f"Тёплая беседка стоит {format_rub(price)} ₽." if price else None
    return None


def duration_price_rule_reply(text: str, form_data: dict[str, Any]) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("больше часов", "дольше", "длительн", "за каждый час", "каждый час")):
        return None
    if not any(marker in normalized for marker in ("стоит", "стоят", "цен", "денег", "дороже", "доплат", "оплат")):
        return None
    service_type = form_data.get("service_type")
    if service_type == "gazebo":
        return (
            "По беседкам цена не считается как доплата за каждый час.\n\n"
            "Обычно беседка закрепляется на выбранный период, а если отдых до утра — ориентируемся на бронь до 08:00. "
            "Стоимость зависит от конкретной беседки, а не от каждого дополнительного часа."
        )
    if service_type == "bathhouse":
        return (
            "По бане цена зависит от длительности и дня недели: чем больше часов, тем выше сумма.\n\n"
            "Минимально можно смотреть 3 часа. Если напишете нужный период, я посчитаю подходящий вариант по карте услуг."
        )
    if service_type == "house":
        return (
            "По гостевому дому цена зависит от длительности: 4, 5, 6, 7 часов или сутки.\n\n"
            "Если напишете период, я подберу подходящую длительность и сумму."
        )
    return (
        "По некоторым услугам цена зависит от длительности, по беседкам — от выбранной беседки и периода брони.\n\n"
        "Напишите услугу и время, я посчитаю по карте услуг."
    )


def policy_or_common_info_reply(text: str) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if looks_like_forbidden_broom_request(text):
        return (
            "Веники использовать нельзя ни в коем случае: за это предусмотрен штраф.\n\n"
            "В заявку их не добавляю."
        )
    if any(marker in normalized for marker in ("комар", "камар", "камор", "мошк", "насеком")):
        return (
            "Территорию обрабатывают от комаров раз в неделю ✅\n\n"
            "Но место природное, поэтому вечером комары и мошки всё равно могут появляться. "
            "Лучше взять репеллент на всякий случай."
        )
    return None


def price_reply_if_known(
    text: str,
    form_data: dict[str, Any],
    *,
    selected_variant_config: SelectedVariantConfig,
) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if not looks_like_price_question_text(text):
        return None
    _, question = next_question(form_data)
    duration_rule = duration_price_rule_reply(text, form_data)
    if duration_rule:
        return f"{duration_rule}\n\n{question}" if question and _should_append_question(form_data, "price") else duration_rule
    if any(marker in normalized for marker in ("предоплат", "аванс")):
        amount = format_rub(get_settings().prepayment_amount_rub)
        reply = (
            f"Предоплата для закрепления брони — {amount} ₽.\n\n"
            "После оплаты мы пришлём подтверждение, а остаток оплачивается на месте."
        )
        return f"{reply}\n\n{question}" if question and _should_append_question(form_data, "price") else reply
    addon_reply = addon_price_reply(text)
    if not addon_reply and is_addon_price_context(text, form_data):
        addon_reply = addon_price_reply("сколько стоят допы")
    if addon_reply:
        followup = addon_price_followup(form_data) if is_addon_price_context(text, form_data) else question
        return f"{addon_reply}\n\n{followup}" if followup else addon_reply
    if not form_data.get("service_type"):
        return None
    if form_data.get("service_type") == "gazebo" and not form_data.get("service_variant"):
        table_reply = service_price_table_reply("gazebo")
        return f"{table_reply}\n\n{question}" if table_reply and question and _should_append_question(form_data, "price") else table_reply
    variant = selected_variant_config(form_data)
    price = variant.get("price")
    if not price:
        table_reply = service_price_table_reply(form_data.get("service_type"))
        return f"{table_reply}\n\n{question}" if table_reply and question and _should_append_question(form_data, "price") else table_reply
    title = variant.get("title") or (load_services_map().get(form_data.get("service_type")) or {}).get("title") or "услуга"
    date_text = format_date_ru(form_data.get("date")) if form_data.get("date") else "на выбранную дату"
    duration = None if form_data.get("service_type") == "gazebo" else (form_data.get("duration") or variant.get("duration_minutes"))
    title_has_duration = "час" in str(title).lower()
    duration_text = f" на {format_duration(duration)}" if duration and not title_has_duration else ""
    prepayment = format_rub(get_settings().prepayment_amount_rub)
    return (
        f"По текущей карте услуг {title.lower()} {date_text}{duration_text} стоит {format_rub(price)} ₽.\n\n"
        f"Предоплата для закрепления брони — {prepayment} ₽, остаток оплачивается на месте.\n\n"
        f"{question or 'Если всё верно, можем продолжать оформление.'}"
    )


def _should_append_question(form_data: dict[str, Any], _context: str) -> bool:
    next_key, _ = next_question(form_data)
    if next_key == "service_type":
        return False
    return any(
        form_data.get(key)
        for key in (
            "service_type",
            "service_variant",
            "date",
            "time",
            "duration",
            "guests_count",
            "event_format",
            "client_name",
            "phone",
        )
    )
