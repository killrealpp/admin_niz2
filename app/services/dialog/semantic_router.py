from __future__ import annotations

from typing import Any

from app.services.availability_service import load_services_map


def build_semantic_router_knowledge(form_data: dict[str, Any] | None = None) -> str:
    """Compact context for the first AI pass.

    The semantic router only needs to understand intent and extract fields.
    Full company knowledge is intentionally left for the dedicated info-answer
    step, otherwise every normal booking message pays for a large prompt.
    """
    current = form_data or {}
    services = load_services_map()
    service_lines: list[str] = []
    for key, service in services.items():
        title = service.get("title") or key
        variants = service.get("variants") or []
        if variants:
            variant_titles = ", ".join(
                str(variant.get("title") or "").strip()
                for variant in variants[:12]
                if variant.get("title")
            )
            service_lines.append(f"- {key}: {title}. Варианты: {variant_titles}.")
        else:
            price = service.get("price")
            suffix = f" Цена: {price}." if price else ""
            service_lines.append(f"- {key}: {title}.{suffix}")

    current_service = current.get("service_type") or "не выбрана"
    current_variant = current.get("service_variant") or "не выбрана"
    current_date = current.get("date") or "не выбрана"
    current_time = current.get("time") or "не выбрано"
    current_duration = current.get("duration") or "не выбрана"
    current_guests = current.get("guests_count") or "не указано"

    return f"""
Ты сейчас работаешь как semantic_router, а не как автор финального текста.
Главная задача: понять смысл сообщения клиента, вернуть intent/action/form_data_patch и не выдумывать факты.

Короткая карта услуг:
{chr(10).join(service_lines)}

Текущая анкета:
- service_type: {current_service}
- service_variant: {current_variant}
- date: {current_date}
- time: {current_time}
- duration: {current_duration}
- guests_count: {current_guests}

Правила маршрутизации:
- Если клиент хочет забронировать, перенести, отменить, узнать свободность, цену, оплату или задать вопрос по компании, определи это по смыслу фразы, а не только по ключевым словам.
- Мысленно сначала выбери крупную ветку: info = информационный вопрос по базе знаний/ценам/правилам; check_availability = вопрос, где нужна проверка локального журнала YCLIENTS; booking_form = ответ на текущий шаг анкеты; post_booking = отмена/перенос/текущие брони; other = всё остальное.
- Если клиент называет дату, время, количество гостей, объект, имя, телефон или допы, извлеки это в form_data_patch.
- Если клиент спрашивает информационный вопрос, верни action=answer_info. Не нужно самому подробно отвечать: backend подключит полную базу знаний.
- Если нужна реальная свободность, верни action=check_availability. Свободность проверяет backend по локальной БД, AI ее не придумывает.
- Если данных не хватает для брони, верни action=ask_next_question и missing_fields/next_step.
- Эмоциональные слова и разговорный мат сами по себе не означают конфликт и не требуют handoff. Handoff нужен только при жалобе, агрессии в адрес компании/бота, споре, возврате денег или явной просьбе человека.
- Если клиент на шаге выбора беседки пишет "подешевле", "дешевле", "недорого", "бюджетно", это object_selection_help/action=answer_info: нужно помочь выбрать из уже проверенных свободных вариантов, а не повторять весь список.
- Если клиент на шаге допов отказывается неформально ("неа", "не", "нет же", "ничего", опечатка), это ответ на upsell_items, а не имя/телефон/новый вопрос.
- Для беседок service_variant ставь только если клиент явно выбрал номер/название или backend уже оставил один вариант.
- Для бани, дома и теплой беседки service_variant обычно не нужен.
- Не наследуй старые date/time/duration/guests/event_format/upsell_items для новой услуги, если клиент явно не подтвердил продолжение старой анкеты.
""".strip()
