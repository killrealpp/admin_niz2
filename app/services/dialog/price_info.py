from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.config import get_settings
from app.services.availability_service import load_services_map
from app.services.bathhouse_pricing import bathhouse_price_components
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
    if asks_all_addons or any(marker in normalized for marker in ("кальян", "кальяна", "кальянчик", "калик", "калян", "калиан")):
        lines.append("Кальян — 1 500 ₽: одна заправка и 5 углей. Дополнительная заправка с углём — 600 ₽.")
    if asks_all_addons or any(marker in normalized for marker in ("решет", "решот", "шампур", "мангал", "уголь", "розжиг")):
        lines.append("Мангальный набор №1 — 500 ₽: решётка, кочерга, опахало.")
        lines.append("Мангальный набор №2 — 1 000 ₽: шампуры, кочерга, опахало.")
        lines.append("Малый мангальный набор — 400 ₽: маленькие шампуры, кочерга, опахало.")
        if "уголь" in normalized:
            lines.append("Уголь 3 кг — 250 ₽.")
        if "розжиг" in normalized:
            lines.append("По розжигу отдельной точной цены в базе нет, поэтому сумму уточним по факту.")
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
            "- 7 часов: 14 700 ₽ в будни / 18 550 ₽ в пятницу-воскресенье\n"
            "После 7 часов каждый следующий час +1 500 ₽."
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
            "По бане доступны базовые пакеты 3, 4, 5, 6 или 7 часов.\n\n"
            "Если нужно дольше 7 часов, считаю 7-часовой пакет по дню недели + 1 500 ₽ за каждый следующий час."
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


def bathhouse_extended_price_reply(text: str, form_data: dict[str, Any]) -> str | None:
    if form_data.get("service_type") != "bathhouse":
        return None
    normalized = text.lower().replace("ё", "е")
    if not looks_like_price_question_text(text):
        return None
    requested_hours = None
    match = re.search(r"\b(\d{1,2})\s*(?:час|ч)\b", normalized)
    if match:
        requested_hours = int(match.group(1))
    elif form_data.get("duration"):
        try:
            requested_hours = int(float(form_data["duration"]))
        except (TypeError, ValueError):
            requested_hours = None
    if not requested_hours or requested_hours <= 7:
        return None

    services = load_services_map()
    config = services.get("bathhouse") or {}
    date_value = form_data.get("date")
    components = bathhouse_price_components(config, date_value=date_value, duration_value=requested_hours)
    if components and date_value:
        date_text = format_date_ru(date_value)
        return (
            f"Баня на {requested_hours} часов на {date_text}: считаю как 7-часовой пакет "
            f"{format_rub(components['base_price'])} ₽ + {components['extra_hours']} × 1 500 ₽ = "
            f"{format_rub(components['total_price'])} ₽."
        )

    weekday_components = bathhouse_price_components(config, date_value="2026-06-15", duration_value=requested_hours)
    weekend_components = bathhouse_price_components(config, date_value="2026-06-19", duration_value=requested_hours)
    extra_hours = max(0, int(requested_hours) - 7)
    if weekday_components and weekend_components:
        return (
            f"Баня на {requested_hours} часов считается как цена 7-часового пакета + "
            f"{extra_hours} × 1 500 ₽.\n\n"
            f"Ориентир: {format_rub(weekday_components['total_price'])} ₽ в будни / "
            f"{format_rub(weekend_components['total_price'])} ₽ в пятницу-воскресенье."
        )
    return None


def policy_or_common_info_reply(text: str) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if looks_like_forbidden_broom_request(text):
        return (
            "Веники использовать нельзя ни в коем случае: за это предусмотрен штраф.\n\n"
            "В заявку их не добавляю."
        )
    lines: list[str] = []
    if _has_child_reference(normalized):
        lines.append(
            "С детьми можно ✅ Только просим следить за ними у воды, возле мангала и на территории."
        )
    if any(marker in normalized for marker in ("животн", "собак", "кошк", "питомц")):
        lines.append(
            "По животным точного общего правила в базе нет. Лучше уточнить под конкретный объект и формат отдыха."
        )
    if lines and "парков" in normalized:
        lines.append("Парковка есть рядом с зоной отдыха.")
    if lines:
        return "\n\n".join(lines)
    if any(marker in normalized for marker in ("комар", "камар", "камор", "мошк", "насеком")):
        return (
            "Территорию обрабатывают от комаров раз в неделю ✅\n\n"
            "Но место природное, поэтому вечером комары и мошки всё равно могут появляться. "
            "Лучше взять репеллент на всякий случай."
        )
    return None


def _has_child_reference(normalized: str) -> bool:
    return bool(
        re.search(
            r"\b(?:дети|детей|детям|детьми|детях|ребенок|ребенка|ребенком|ребенку|ребенке|ребят(?:а|ам|ами|ах)?|малыш\w*)\b",
            normalized,
        )
    )


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
        reply = _prepayment_reply()
        return f"{reply}\n\n{question}" if question and _should_append_question(form_data, "price") else reply
    addon_reply = addon_price_reply(text)
    if not addon_reply and is_addon_price_context(text, form_data):
        addon_reply = addon_price_reply("сколько стоят допы")
    if addon_reply:
        followup = addon_price_followup(form_data) if is_addon_price_context(text, form_data) else question
        return f"{addon_reply}\n\n{followup}" if followup else addon_reply
    bathhouse_extended = bathhouse_extended_price_reply(text, form_data)
    if bathhouse_extended:
        return f"{bathhouse_extended}\n\n{question}" if question and _should_append_question(form_data, "price") else bathhouse_extended
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
    effective_price = price
    price_text = f"По текущей карте услуг {title.lower()} {date_text}{duration_text} стоит {format_rub(price)} ₽."
    if form_data.get("service_type") == "bathhouse":
        components = bathhouse_price_components(
            load_services_map().get("bathhouse") or {},
            date_value=form_data.get("date"),
            duration_value=form_data.get("duration") or variant.get("duration_minutes"),
        )
        if components:
            effective_price = components["total_price"]
            if components["extra_hours"]:
                price_text = (
                    f"Баня {date_text}{duration_text}: 7-часовой пакет "
                    f"{format_rub(components['base_price'])} ₽ + "
                    f"{components['extra_hours']} × 1 500 ₽ = "
                    f"{format_rub(components['total_price'])} ₽."
                )
            else:
                price_text = (
                    f"По текущей карте услуг {title.lower()} {date_text}{duration_text} "
                    f"стоит {format_rub(components['total_price'])} ₽."
                )
    if form_data.get("service_type") == "gazebo" and form_data.get("date"):
        try:
            weekday = datetime.fromisoformat(str(form_data.get("date"))).weekday()
        except ValueError:
            weekday = None
        if weekday in {0, 1, 2, 3}:
            discount_price = int(int(price) * 0.5)
            effective_price = discount_price
            price_text = (
                f"На {date_text} действует будняя скидка 50% на беседки ✅\n\n"
                f"{title}: базовая цена {format_rub(price)} ₽, со скидкой {format_rub(discount_price)} ₽."
            )
    prepayment = _prepayment_summary(effective_price)
    return (
        f"{price_text}\n\n"
        f"{prepayment}, остаток оплачивается на месте.\n\n"
        f"{question or 'Если всё верно, можем продолжать оформление.'}"
    )


def discount_reply_if_known(
    text: str,
    form_data: dict[str, Any],
    *,
    selected_variant_config: SelectedVariantConfig,
) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("скид", "акци", "со скид")):
        return None

    _, question = next_question(form_data)
    service_type = form_data.get("service_type")
    if service_type and service_type != "gazebo":
        reply = (
            "Скидка 50% в базе указана именно на аренду беседок с понедельника по четверг.\n\n"
            "По выбранной услуге отдельную скидку не обещаю без подтверждения."
        )
        return f"{reply}\n\n{question}" if question and _should_append_question(form_data, "discount") else reply

    if service_type == "gazebo" and form_data.get("service_variant") and form_data.get("date"):
        variant = selected_variant_config(form_data)
        price = variant.get("price")
        title = variant.get("title") or form_data.get("service_variant") or "выбранная беседка"
        try:
            weekday = datetime.fromisoformat(str(form_data.get("date"))).weekday()
        except ValueError:
            weekday = None
        if price and weekday in {0, 1, 2, 3}:
            discount_price = int(int(price) * 0.5)
            reply = (
                f"Да, на {format_date_ru(form_data.get('date'))} действует будняя скидка 50% на беседки ✅\n\n"
                f"{title}: базовая цена {format_rub(price)} ₽, со скидкой {format_rub(discount_price)} ₽."
            )
            return f"{reply}\n\n{question}" if question and _should_append_question(form_data, "discount") else reply
        if price and weekday in {4, 5, 6}:
            reply = (
                f"Скидка 50% на беседки действует с понедельника по четверг.\n\n"
                f"На {format_date_ru(form_data.get('date'))} для {str(title).lower()} ориентир по базе — {format_rub(price)} ₽."
            )
            return f"{reply}\n\n{question}" if question and _should_append_question(form_data, "discount") else reply

    reply = (
        "На беседки действует скидка 50% с понедельника по четверг.\n\n"
        "Чтобы точно посчитать сумму со скидкой, нужна дата и выбранная беседка."
    )
    return f"{reply}\n\n{question}" if question and _should_append_question(form_data, "discount") else reply


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


def _prepayment_reply() -> str:
    settings = get_settings()
    if str(settings.prepayment_mode or "fixed").lower() == "percent":
        return (
            f"Предоплата для закрепления брони — {settings.prepayment_percent}% от стоимости основной услуги или пакета.\n\n"
            "Допы в аванс пока не включаем. После оплаты мы пришлём подтверждение, остаток оплачивается на месте."
        )
    amount = format_rub(settings.prepayment_amount_rub)
    return (
        f"Предоплата для закрепления брони — {amount} ₽.\n\n"
        "После оплаты мы пришлём подтверждение, а остаток оплачивается на месте."
    )


def _prepayment_summary(base_price: Any) -> str:
    settings = get_settings()
    if str(settings.prepayment_mode or "fixed").lower() == "percent":
        percent = Decimal(str(settings.prepayment_percent))
        try:
            amount = (Decimal(str(base_price)) * percent / Decimal("100")).quantize(Decimal("0.01"))
        except Exception:
            return f"Предоплата для закрепления брони — {settings.prepayment_percent}% от стоимости основной услуги"
        return f"Предоплата для закрепления брони — {format_rub(amount)} ₽ ({settings.prepayment_percent}% от основной услуги)"
    return f"Предоплата для закрепления брони — {format_rub(settings.prepayment_amount_rub)} ₽"
