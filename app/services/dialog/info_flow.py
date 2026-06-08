from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.core.constants import SENDER_ASSISTANT, SENDER_USER
from app.services.dialog.bathhouse_flow import (
    bathhouse_active_reply_mentions_separate_booking,
    bathhouse_alcohol_reply,
    bathhouse_period_options_reply,
    bathhouse_pool_included_reply,
    bathhouse_separate_booking_complaint_reply,
    looks_like_bathhouse_period_options_question,
)


@dataclass(frozen=True)
class InfoQuestionCallbacks:
    is_likely_form_answer: Callable[[str, str | None, datetime], bool]
    now_local: Callable[[], datetime]
    confirmation_yes: Callable[[str], bool]
    confirmation_no: Callable[[str], bool]


@dataclass(frozen=True)
class InfoFlowCallbacks:
    next_question: Callable[[dict[str, Any]], tuple[str | None, str | None]]
    reply_already_asks: Callable[[str, str | None, str | None], bool]
    explicit_photo_reply: Callable[[str, dict[str, Any]], str | None]
    discount_reply_if_known: Callable[[str, dict[str, Any]], str | None]
    price_reply_if_known: Callable[[str, dict[str, Any]], str | None]
    looks_like_gazebo_budget_preference: Callable[[str], bool]
    gazebo_budget_selection_text: Callable[[dict[str, Any]], str | None]
    current_gazebo_quality_reply: Callable[[str, dict[str, Any]], str | None]
    capacity_info_reply: Callable[[str, dict[str, Any]], str | None]
    policy_or_common_info_reply: Callable[[str], str | None]
    should_append_next_question_after_info: Callable[[dict[str, Any], str | None], bool]
    capacity_guest_patch: Callable[[str], dict[str, int]]
    clean_reply: Callable[[str], str]
    ai_process_reply: Callable[..., str]
    asks_gazebo_options: Callable[[str], bool]
    gazebo_selection_text: Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ActiveBookingInfoCallbacks:
    means_same_date: Callable[[str], bool]
    means_same_time: Callable[[str], bool]
    referenced_service_type_for_same_time: Callable[[str], str | None]
    active_user_bookings: Callable[..., list[dict[str, Any]]]
    booking_line_short: Callable[[dict[str, Any]], str]
    booking_object_title: Callable[[dict[str, Any]], str]


def reply_already_asks(reply: str, next_key: str | None, question: str | None) -> bool:
    if not question:
        return True
    lowered = reply.lower().replace("ё", "е")
    question_lowered = question.lower().replace("ё", "е")
    if question_lowered in lowered:
        return True
    if "?" in lowered and any(
        marker in lowered
        for marker in (
            "какую выбираете",
            "какую закрепляем",
            "какой вариант",
            "закрепляем",
            "подойдет",
            "подойдёт",
        )
    ):
        return True
    if next_key == "guests_count" and "сколько" in lowered and ("гост" in lowered or "человек" in lowered):
        return True
    if next_key == "event_format" and ("формат" in lowered or "какой отдых" in lowered):
        return True
    if next_key == "date" and any(marker in lowered for marker in ("какую дату", "на какую дату", "когда планируете", "назовите дату")):
        return True
    if next_key == "phone" and "телефон" in lowered:
        return True
    if next_key == "time" and (
        "во сколько" in lowered
        or "какое время" in lowered
        or "на какое время" in lowered
        or "когда хотите приехать" in lowered
        or "с какого времени" in lowered
    ):
        return True
    if next_key == "duration" and (
        "на сколько часов" in lowered
        or "сколько часов" in lowered
        or "какая длительность" in lowered
    ):
        return True
    if next_key == "service_variant" and ("какую" in lowered or "выбираете" in lowered or "какой вариант" in lowered):
        return True
    if next_key == "upsell_items" and any(marker in lowered for marker in ("доп", "дополнитель", "уголь", "розжиг", "решет", "шампур", "кальян")):
        return True
    return False


def should_append_next_question_after_info(form_data: dict[str, Any], next_key: str | None) -> bool:
    if not next_key:
        return False
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


def looks_like_info_question(
    text: str,
    *,
    expected_key: str | None = None,
    now: datetime | None = None,
    callbacks: InfoQuestionCallbacks,
) -> bool:
    if callbacks.is_likely_form_answer(text, expected_key, now or callbacks.now_local()):
        return False
    normalized = text.lower().replace("ё", "е").strip()
    if "?" in normalized:
        return True
    if callbacks.confirmation_yes(normalized) or callbacks.confirmation_no(normalized):
        return False
    question_patterns = (
        r"\bкак\b",
        r"\bкако[йея]\b",
        r"\bкакие\b",
        r"\bгде\b",
        r"\bкуда\b",
        r"\bкогда\b",
        r"\bпочем\b",
        r"\bпочему\b",
        r"\bзачем\b",
        r"\bесть ли\b",
        r"\bбудет ли\b",
        r"\bвходит\b",
        r"\bвключено\b",
        r"\bразрешено\b",
        r"\bработает\b",
        r"\bоткрыт",
        r"\bзакрыт",
        r"\bа если\b",
        r"\bа там\b",
        r"\bтам есть\b",
        r"\bу вас\b",
    )
    if any(re.search(pattern, normalized) for pattern in question_patterns):
        return True
    if "бассейн" in normalized and any(marker in normalized for marker in ("вмест", "входит", "включ", "идет", "идёт", "есть")):
        return True
    if (
        "отдель" in normalized
        and "брон" in normalized
        and any(marker in normalized for marker in ("почему", "зачем", "че", "чё", "что", "говор"))
    ):
        return True
    if re.search(r"\bсколько\b", normalized):
        return any(
            marker in normalized
            for marker in ("стоит", "стоят", "цена", "стоим", "почем", "прайс", "оплат", "денег", "руб", "₽", "уголь", "розжиг", "кальян", "доп")
        )
    if any(marker in normalized for marker in ("скольк", "скольок", "скок", "скока")):
        return any(
            marker in normalized
            for marker in ("стоит", "стоят", "цена", "стоим", "почем", "прайс", "оплат", "денег", "руб", "₽", "уголь", "розжиг", "кальян", "решет", "шампур", "доп")
        )
    if re.search(r"\bможно\b", normalized):
        return any(
            marker in normalized
            for marker in (
                "с собак",
                "с детьми",
                "детей",
                "животн",
                "курить",
                "музык",
                "свое",
                "принести",
                "привезти",
                "пить",
                "выпить",
                "алког",
                "напит",
            )
        )
    markers = (
        "что входит",
        "адрес",
        "цена",
        "стоим",
        "оплата",
        "предоплата",
        "мангал",
        "свет",
        "розет",
        "до скольки",
        "что взять",
        "парков",
        "туалет",
        "комар",
        "камар",
        "камор",
        "насеком",
        "мошк",
        "клещ",
        "веник",
        "веники",
        "венич",
        "алког",
        "выпить",
    )
    return any(marker in normalized for marker in markers)


def deterministic_info_reply(
    text: str,
    form_data: dict[str, Any],
    *,
    callbacks: InfoFlowCallbacks,
    append_next_question: bool = True,
) -> str | None:
    normalized = text.lower().replace("ё", "е")
    next_key, question = callbacks.next_question(form_data)
    if _asks_bot_name(normalized):
        reply = "Меня зовут Любовь, я помощник по бронированию 😊"
        if (
            append_next_question
            and question
            and callbacks.should_append_next_question_after_info(form_data, next_key)
            and not callbacks.reply_already_asks(reply, next_key, question)
        ):
            reply = f"{reply}\n\nПродолжим оформление: {question}"
        return reply
    bathhouse_complaint = bathhouse_separate_booking_complaint_reply(text, form_data)
    if bathhouse_complaint:
        reply = bathhouse_complaint
        if question:
            reply = f"{reply}\n\nПродолжим оформление: {question}"
        return reply
    pool_reply = bathhouse_pool_included_reply(text, form_data)
    if pool_reply:
        reply = pool_reply
        if (
            append_next_question
            and question
            and callbacks.should_append_next_question_after_info(form_data, next_key)
            and not callbacks.reply_already_asks(reply, next_key, question)
        ):
            reply = f"{reply}\n\nПродолжим оформление: {question}"
        return reply
    alcohol_reply = bathhouse_alcohol_reply(text, form_data)
    if alcohol_reply:
        reply = alcohol_reply
        if (
            append_next_question
            and question
            and callbacks.should_append_next_question_after_info(form_data, next_key)
            and not callbacks.reply_already_asks(reply, next_key, question)
        ):
            reply = f"{reply}\n\n{question}"
        return reply
    if looks_like_bathhouse_period_options_question(text):
        period_reply = bathhouse_period_options_reply(form_data)
        if period_reply:
            reply, _period_next_key = period_reply
            return reply
    photo_reply = callbacks.explicit_photo_reply(text, form_data)
    if photo_reply:
        return photo_reply
    discount_reply = callbacks.discount_reply_if_known(text, form_data)
    if discount_reply:
        return discount_reply
    price_reply = callbacks.price_reply_if_known(text, form_data)
    if price_reply:
        return price_reply
    if form_data.get("service_type") == "gazebo" and callbacks.looks_like_gazebo_budget_preference(text):
        budget_reply = callbacks.gazebo_budget_selection_text(form_data)
        if budget_reply:
            return budget_reply
    gazebo_quality_reply = callbacks.current_gazebo_quality_reply(text, form_data)
    if gazebo_quality_reply:
        return gazebo_quality_reply
    capacity_reply = callbacks.capacity_info_reply(text, form_data)
    if capacity_reply:
        reply = capacity_reply
        if (
            form_data.get("service_type") == "gazebo"
            and form_data.get("service_variant")
            and not form_data.get("guests_count")
            and not callbacks.capacity_guest_patch(text)
        ):
            return reply
        if (
            append_next_question
            and question
            and callbacks.should_append_next_question_after_info(form_data, next_key)
            and not callbacks.reply_already_asks(reply, next_key, question)
        ):
            reply = f"{reply}\n\n{question}"
        return reply
    policy_reply = callbacks.policy_or_common_info_reply(text)
    if policy_reply:
        reply = policy_reply
    elif form_data.get("service_type") == "gazebo" and any(
        marker in normalized
        for marker in (
            "до скольки",
            "после 23",
            "после 11",
            "после одиннадцати",
            "до утра",
            "сутки",
            "на сутки",
            "пользов",
            "продлить",
            "доплата за час",
            "каждый час",
        )
    ):
        reply = (
            "Беседка обычно бронируется до 08:00 утра следующего дня ✅\n\n"
            "То есть если приезжаете вечером, можно отдыхать до утра. "
            "Отдельную доплату за каждый час я не закладываю: ориентируюсь на цену выбранной беседки за бронь до 08:00."
        )
    elif "парков" in normalized:
        if "адрес" in normalized or "где" in normalized or "находит" in normalized:
            reply = (
                "Парковка есть рядом с зоной отдыха.\n\n"
                "Локация Максима Горького: город Выкса, конец улицы Максима Горького. "
                "В навигаторе можно указать: улица Максима Горького, примерно 101.\n\n"
                "Если нужна Русалочка / Беленький песочек: район улицы Ризадеевская, примерно 101."
            )
        else:
            reply = "Да, парковка есть."
    elif "мангал" in normalized:
        reply = "Да, мангал есть у беседок."
    elif "туалет" in normalized:
        reply = "Да, туалет на территории есть."
    else:
        return None
    if bathhouse_active_reply_mentions_separate_booking(reply, form_data):
        reply = "Баню уже оформляем; это баня с бассейном."
    if (
        append_next_question
        and question
        and callbacks.should_append_next_question_after_info(form_data, next_key)
        and not callbacks.reply_already_asks(reply, next_key, question)
    ):
        reply = f"{reply}\n\n{question}"
    return reply


def _asks_bot_name(normalized: str) -> bool:
    if not any(
        marker in normalized
        for marker in ("как тебя зовут", "как вас зовут", "твое имя", "твоё имя", "как звать")
    ):
        return False
    return not any(marker in normalized for marker in ("меня зовут", "мое имя", "моё имя", "запиши", "бронь"))


def contextual_photo_reply(
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    callbacks: InfoFlowCallbacks,
) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if not _looks_like_contextual_photo_request(normalized):
        return None
    if "бесед" in normalized:
        return callbacks.explicit_photo_reply(text, form_data)
    if not _recent_history_points_to_gazebos(history):
        return None
    return callbacks.explicit_photo_reply("покажите фото беседок", form_data)


def _looks_like_contextual_photo_request(normalized: str) -> bool:
    if not any(marker in normalized for marker in ("покаж", "показать", "скинь", "пришли", "отправь")):
        return False
    return any(marker in normalized for marker in ("их", "эти", "все", "варианты", "фото", "фотк", "картин", "как выгляд"))


def _recent_history_points_to_gazebos(history: list[dict[str, Any]]) -> bool:
    for item in reversed(history[-8:]):
        sender = item.get("sender")
        if sender not in {SENDER_ASSISTANT, SENDER_USER}:
            continue
        text = str(item.get("text") or "").lower().replace("ё", "е")
        if "бесед" not in text:
            continue
        if sender == SENDER_USER:
            return True
        if any(marker in text for marker in ("№1", "№2", "№3", "№4", "№5", "№6", "№8", "крытая бесед", "вариант")):
            return True
    return False


def active_booking_reference_info_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    now: datetime,
    *,
    callbacks: ActiveBookingInfoCallbacks,
) -> str | None:
    if callbacks.means_same_date(text) or callbacks.means_same_time(text):
        return None
    referenced_service = callbacks.referenced_service_type_for_same_time(text)
    current_service = form_data.get("service_type")
    if not referenced_service or referenced_service == current_service:
        return None
    bookings = [
        booking
        for booking in callbacks.active_user_bookings(conn, conversation, form_data, now)
        if booking.get("service_type") == referenced_service
    ]
    if not bookings:
        return None
    booking = bookings[0]
    line = callbacks.booking_line_short(booking)
    title = callbacks.booking_object_title(booking)
    normalized = text.lower().replace("ё", "е")
    if referenced_service == "gazebo" and any(
        marker in normalized
        for marker in ("хорош", "норм", "подойдет", "подойдёт", "что за", "какая", "как она", "как бесед")
    ):
        if "№4" in title or " 4" in title.lower():
            verdict = f"Да, {title} нормальный бюджетный вариант: мангал есть, но света и розеток нет."
        elif "№2" in title or " 2" in title.lower():
            verdict = f"Да, {title} хороший простой вариант с мангалом. Важно: без света и розеток."
        else:
            verdict = f"Да, {title} подходит для спокойного отдыха."
        return f"По активной беседке у вас: {line}.\n\n{verdict}"
    return f"По активной брони у вас: {line}."


def append_current_service_question(
    reply: str,
    form_data: dict[str, Any],
    *,
    callbacks: InfoFlowCallbacks,
) -> tuple[str, str | None]:
    next_key, question = callbacks.next_question(form_data)
    if not question or callbacks.reply_already_asks(reply, next_key, question):
        return reply, next_key
    service_cases = {
        "bathhouse": "бане",
        "gazebo": "беседке",
        "warm_gazebo": "тёплой беседке",
        "house": "дому",
    }
    title = service_cases.get(str(form_data.get("service_type") or ""), "этой заявке")
    return f"{reply}\n\nПо {title} продолжим: {question}", next_key


def answer_info_during_form(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    ai_result: Any,
    callbacks: InfoFlowCallbacks,
) -> tuple[str, str | None]:
    next_key, question = callbacks.next_question(form_data)
    ai_reply = callbacks.clean_reply((getattr(ai_result, "reply_to_user", "") or "").strip())
    contextual_photo = contextual_photo_reply(text, form_data, history, callbacks=callbacks)
    if contextual_photo:
        return contextual_photo, next_key
    photo_reply = callbacks.explicit_photo_reply(text, form_data)
    if photo_reply:
        return photo_reply, next_key
    deterministic = deterministic_info_reply(text, form_data, callbacks=callbacks)
    if deterministic:
        reply = deterministic
        if (
            form_data.get("service_type") == "gazebo"
            and form_data.get("service_variant")
            and not form_data.get("guests_count")
            and not callbacks.capacity_guest_patch(text)
        ):
            return reply, "guests_count"
    elif getattr(ai_result, "intent", "") == "price_question":
        reply = callbacks.price_reply_if_known("сколько стоит", form_data)
        if not reply:
            reply = callbacks.price_reply_if_known(text, form_data)
        if not reply:
            reply = callbacks.ai_process_reply(
                text=text,
                form_data=form_data,
                history=history,
                required_meaning=(
                    "Клиент спрашивает цену. Ответь только по базе знаний и не выдумывай сумму, "
                    "если точной цены нет."
                ),
            )
    elif form_data.get("service_type") == "gazebo" and callbacks.asks_gazebo_options(text):
        reply = callbacks.gazebo_selection_text(form_data)
        if not form_data.get("guests_count"):
            return reply, "guests_count"
    else:
        required = (
            "Клиент задал информационный вопрос во время анкеты. "
            "Сначала коротко и честно ответь только по базе знаний. "
            "Если в базе знаний нет точного ответа — так и скажи, без выдумок. "
            "Не задавай новый вопрос анкеты внутри ответа."
        )
        reply = callbacks.ai_process_reply(
            text=text,
            form_data=form_data,
            history=history,
            required_meaning=required,
        )

    if bathhouse_active_reply_mentions_separate_booking(reply, form_data):
        reply = "Баню уже оформляем; это баня с бассейном."

    if (
        question
        and callbacks.should_append_next_question_after_info(form_data, next_key)
        and not callbacks.reply_already_asks(reply, next_key, question)
    ):
        reply = f"{reply}\n\nПродолжим оформление: {question}"
    return reply, next_key
