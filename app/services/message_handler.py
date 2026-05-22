import logging
import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.ai.ai_orchestrator import (
    call_ai,
    classify_post_booking_message,
    generate_process_reply,
)
from app.ai.errors import AIProviderUnavailable
from app.core.config import get_settings
from app.core.constants import SENDER_ASSISTANT, SENDER_USER
from app.db.connection import get_connection
from app.db.repositories import (
    bookings_repo,
    conversation_summaries_repo,
    conversations_repo,
    messages_repo,
    payments_repo,
    slot_holds_repo,
    system_logs_repo,
    users_repo,
)
from app.services.availability_service import check_availability, load_services_map
from app.services.booking_form_service import initial_form_data, merge_form_data, next_question
from app.services.conversation_service import get_or_create_conversation
from app.services.knowledge_service import load_knowledge
from app.services.payment_service import (
    create_payment_link_for_bookings,
    create_payment_link_for_holds,
    sync_payment_statuses,
)
from app.services.user_service import get_or_create_user
from app.services.waitlist_service import remember_waitlist_request
from app.services.yclients_record_service import (
    create_missing_yclients_records,
    delete_yclients_record_for_booking,
    upsert_local_busy_interval_for_booking,
)

logger = logging.getLogger(__name__)

WEEKDAY_ALIASES = {
    "понедельник": 0,
    "понедельника": 0,
    "вторник": 1,
    "вторника": 1,
    "среду": 2,
    "среда": 2,
    "четверг": 3,
    "четверга": 3,
    "пятницу": 4,
    "пятница": 4,
    "субботу": 5,
    "суббота": 5,
    "воскресенье": 6,
    "воскресенья": 6,
}

MONTH_NAMES_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

MONTH_NUMBERS_RU = {
    "января": 1,
    "январь": 1,
    "февраля": 2,
    "февраль": 2,
    "марта": 3,
    "март": 3,
    "апреля": 4,
    "апрель": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июля": 7,
    "июль": 7,
    "августа": 8,
    "август": 8,
    "сентября": 9,
    "сентябрь": 9,
    "октября": 10,
    "октябрь": 10,
    "ноября": 11,
    "ноябрь": 11,
    "декабря": 12,
    "декабрь": 12,
}


@dataclass
class IncomingMessage:
    channel: str
    external_user_id: str
    user_name: str | None
    text: str
    message_time: datetime
    raw_payload: dict[str, Any]


def _now_local() -> datetime:
    settings = get_settings()
    return datetime.now(ZoneInfo(settings.app_timezone))


def _effective_message_time(message_time: datetime | None, tz: ZoneInfo) -> datetime:
    now = message_time or _now_local()
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    real_now = _now_local().astimezone(tz)
    if abs((now - real_now).total_seconds()) > 30 * 24 * 60 * 60:
        logger.warning(
            "Message timestamp differs from system time by more than 30 days: message=%s system=%s",
            now.isoformat(),
            real_now.isoformat(),
        )
        return real_now
    return now


def _handoff_active(user: dict[str, Any], now: datetime) -> bool:
    until = user.get("handoff_until")
    if not until:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=now.tzinfo)
    return until > now


def _handoff_reply() -> str:
    return (
        "Простите, пожалуйста 🙏\n\n"
        "Передала ситуацию команде. Ваш номер сохранён, с вами свяжутся в ближайшее время."
    )


def _seed_form_data_from_user(form_data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    updated = dict(form_data)
    if not updated.get("phone") and user.get("phone"):
        updated["phone"] = user["phone"]
    if not updated.get("client_name") and user.get("name"):
        updated["client_name"] = user["name"]
    return updated


def _persist_user_profile(conn, *, user_id: int, form_data: dict[str, Any]) -> None:
    phone = form_data.get("phone")
    if phone and _valid_phone(phone):
        users_repo.update_phone(conn, user_id, str(phone))


def _looks_like_handoff_needed(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    complaint_markers = (
        "ужас",
        "кошмар",
        "обман",
        "верните деньги",
        "возврат",
        "жалоб",
        "разберитесь",
        "плохо работает",
        "не работает",
        "вы что",
        "почему так",
    )
    rude_markers = (
        "дурак",
        "тупой",
        "идиот",
        "бесит",
        "задолбал",
        "хрен",
        "нах",
        "бля",
    )
    return any(marker in normalized for marker in complaint_markers + rude_markers)


def _start_user_handoff(
    conn,
    *,
    user: dict[str, Any],
    conversation_id: int,
    text: str,
    now: datetime,
    reason: str = "нестандартное поведение, критика или конфликт",
) -> None:
    settings = get_settings()
    phone = user.get("phone") or ""
    bookings = bookings_repo.list_future_active_for_user(
        conn,
        user_id=int(user["id"]),
        phone=str(phone) if phone else None,
        now=now,
        limit=10,
    )
    booking_lines = "\n".join(f"- {_booking_line_short(booking)}; статус оплаты: {booking.get('payment_status')}" for booking in bookings)
    summary = (
        f"Последнее сообщение клиента: {text[:700]}\n"
        f"Пользователь: {user.get('name') or 'не указано'}\n"
        f"Telegram ID: {user.get('external_id')}\n"
        f"Телефон: {phone or 'не указан'}\n"
        f"Активные брони:\n{booking_lines or 'нет активных будущих броней'}"
    )
    users_repo.set_handoff(
        conn,
        user_id=user["id"],
        until=now + timedelta(minutes=settings.handoff_ttl_minutes),
        reason=reason,
        summary=summary,
    )
    system_logs_repo.create(
        conn,
        level="warning",
        event_type="human_handoff",
        message=reason,
        conversation_id=conversation_id,
        payload={
            "user_id": user["id"],
            "external_id": user.get("external_id"),
            "text": text[:1000],
            "until": (now + timedelta(minutes=settings.handoff_ttl_minutes)).isoformat(),
        },
    )


def _bare_weekday_candidate(text: str, now: datetime) -> tuple[str, date] | None:
    normalized = text.lower().replace("ё", "е")
    if any(marker in normalized for marker in ("завтра", "послезавтра", "сегодня", "следующ", "ближайш", "эту ", "этот ")):
        return None
    for word, weekday in WEEKDAY_ALIASES.items():
        if re.search(rf"\b{word}\b", normalized):
            delta = (weekday - now.date().weekday()) % 7
            if delta == 0:
                delta = 7
            candidate = now.date() + timedelta(days=delta)
            return word, candidate
    return None


def _bare_weekday_confirmation(text: str, now: datetime) -> str | None:
    candidate = _bare_weekday_candidate(text, now)
    if not candidate:
        return None
    word, date_value = candidate
    return (
        f"Уточню дату: вы имеете в виду ближайшую {word}, "
        f"{_format_date_ru(date_value.isoformat())}, или другую дату?"
    )


def _clean_reply(text: str) -> str:
    cleaned = text.replace("**", "")
    cleaned = re.sub(r"(?m)^\s*[•*]\s+", "- ", cleaned)
    return cleaned.strip()


def _remove_date_question_when_guest_question_exists(text: str) -> str:
    lowered = text.lower()
    has_guest_question = "сколько" in lowered or "на сколько человек" in lowered
    if not has_guest_question or "на какую дату" not in lowered:
        return text
    lines = text.splitlines()
    filtered = [
        line for line in lines
        if "на какую дату" not in line.lower()
        and "какую дату" not in line.lower()
    ]
    return "\n".join(filtered).strip()


def _fallback_reply(form_data: dict[str, Any]) -> tuple[str, str | None]:
    next_key, question = next_question(form_data)
    if question:
        return question, next_key
    return (
        "Спасибо, основные данные собраны. Сейчас подготовлю подтверждение брони.",
        None,
    )


def _log_ai_provider_unavailable(
    conn,
    *,
    conversation_id: int,
    exc: AIProviderUnavailable,
    text: str,
    form_data: dict[str, Any],
) -> None:
    system_logs_repo.create(
        conn,
        level="error",
        event_type="ai_provider_unavailable",
        message=str(exc),
        conversation_id=conversation_id,
        payload={
            "status_code": exc.status_code,
            "provider_payload": str(exc.payload or "")[:1000],
            "user_text": text[:500],
            "current_step": next_question(form_data)[0],
        },
    )


def _has_too_many_questions(text: str) -> bool:
    lowered = text.lower()
    if text.count("?") > 1:
        return True
    return any(marker in lowered for marker in ("\n1.", "\n1)", "\n2.", "\n2)"))


def _mentions_availability(text: str) -> bool:
    lowered = text.lower()
    patterns = (
        "доступна",
        "доступен",
        "доступно",
        "свободна",
        "свободен",
        "свободно",
        "есть свобод",
        "можем забронировать",
    )
    return any(pattern in lowered for pattern in patterns)


def _must_ask_duration_before_availability(form_data: dict[str, Any]) -> bool:
    service_type = form_data.get("service_type")
    if not service_type:
        return False
    if not form_data.get("date"):
        return False
    config = load_services_map().get(service_type) or {}
    if not config.get("require_duration_before_availability"):
        return False
    return not form_data.get("duration")


def _relative_date_patch(text: str, now: datetime) -> dict[str, str]:
    normalized = text.lower()
    today = now.date()

    if re.search(r"\bсегодня\b", normalized):
        return {"date": today.isoformat()}
    if re.search(r"\bзавтра\b", normalized):
        return {"date": (today + timedelta(days=1)).isoformat()}
    if re.search(r"\bпослезавтра\b", normalized):
        return {"date": (today + timedelta(days=2)).isoformat()}

    for word, weekday in WEEKDAY_ALIASES.items():
        if re.search(rf"\b{word}\b", normalized):
            if not any(marker in normalized for marker in ("следующ", "ближайш", "эту ", "этот ")):
                return {}
            delta = (weekday - today.weekday()) % 7
            if "следующ" in normalized and delta == 0:
                delta = 7
            return {"date": (today + timedelta(days=delta)).isoformat()}
    explicit_date = re.search(
        r"\b(\d{1,2})\s+("
        r"января|январь|февраля|февраль|марта|март|апреля|апрель|мая|май|"
        r"июня|июнь|июля|июль|августа|август|сентября|сентябрь|"
        r"октября|октябрь|ноября|ноябрь|декабря|декабрь"
        r")\b",
        normalized,
    )
    if explicit_date:
        day = int(explicit_date.group(1))
        month = MONTH_NUMBERS_RU[explicit_date.group(2)]
        year = today.year
        try:
            candidate = today.replace(year=year, month=month, day=day)
        except ValueError:
            return {}
        if candidate < today:
            candidate = candidate.replace(year=year + 1)
        return {"date": candidate.isoformat()}

    day_only = re.search(r"\b(\d{1,2})\s*(?:числа|число)\b", normalized)
    if day_only:
        day = int(day_only.group(1))
        month = today.month
        year = today.year
        for _ in range(13):
            if day <= calendar.monthrange(year, month)[1]:
                candidate = today.replace(year=year, month=month, day=day)
                if candidate >= today:
                    return {"date": candidate.isoformat()}
            month += 1
            if month > 12:
                month = 1
                year += 1
    return {}


def _bare_day_patch(text: str, now: datetime, expected_key: str | None) -> dict[str, str]:
    if expected_key != "date":
        return {}
    normalized = text.lower().strip()
    match = re.fullmatch(r"\d{1,2}", normalized)
    if not match:
        return {}
    day = int(match.group(0))
    if day <= 0:
        return {}
    today = now.date()
    month = today.month
    year = today.year
    for _ in range(13):
        if day <= calendar.monthrange(year, month)[1]:
            candidate = today.replace(year=year, month=month, day=day)
            if candidate >= today:
                return {"date": candidate.isoformat()}
        month += 1
        if month > 12:
            month = 1
            year += 1
    return {}


def _service_type_patch(text: str) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    has_gazebo = "бесед" in normalized
    has_bathhouse = "бан" in normalized
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


def _normalize_service_aliases(form_data: dict[str, Any]) -> dict[str, Any]:
    updated = dict(form_data)
    service_type = updated.get("service_type")
    if service_type == "summer_gazebo":
        updated["service_type"] = "gazebo"
        updated["preferences"] = _join_preferences(updated.get("preferences"), "летняя беседка")
    elif service_type == "gazebo_bathhouse":
        updated["service_type"] = "gazebo"
        updated["preferences"] = _join_preferences(updated.get("preferences"), "баня отдельной услугой")
    return updated


def _join_preferences(current: Any, value: str) -> str:
    text = str(current or "").strip()
    if not text:
        return value
    if value.lower() in text.lower():
        return text
    return f"{text}; {value}"


def _service_variant_patch(text: str) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    word_numbers = {
        "один": "1",
        "одну": "1",
        "первую": "1",
        "первая": "1",
        "два": "2",
        "две": "2",
        "вторую": "2",
        "вторая": "2",
        "три": "3",
        "третью": "3",
        "третья": "3",
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
        return {"service_variant": "Простая беседка с мангалом"}
    if "свет" in normalized or "розет" in normalized:
        return {"service_variant": "Беседка со светом и розетками"}
    if "больш" in normalized or "много мест" in normalized:
        return {"service_variant": "Большая беседка"}
    match = re.search(r"\b(?:беседк[аиуойе]*\s*)?№?\s*([1-8])\b", normalized)
    if match and "бесед" in normalized:
        return {"service_variant": f"Беседка №{match.group(1)}"}
    match = re.search(r"\b(?:номер|№|n)\s*([1-8])\b", normalized)
    if match:
        return {"service_variant": f"Беседка №{match.group(1)}"}
    match = re.search(r"\b([1-8])\s*(?:-?\s*)?(?:ю|ую|ая|я)?\s*беседк", normalized)
    if match:
        return {"service_variant": f"Беседка №{match.group(1)}"}
    for word, number in word_numbers.items():
        if re.search(rf"\b(?:номер\s+)?{word}\b", normalized):
            return {"service_variant": f"Беседка №{number}"}
    return {}


def _phone_patch(text: str) -> dict[str, str]:
    if not re.search(r"\+?\d[\d\s().-]{5,}\d", text):
        return {}
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if 10 <= len(digits) <= 15:
        return {"phone": "+" + digits}
    return {"phone": text.strip()}


def _event_format_patch(text: str) -> dict[str, str]:
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


def _upsell_items_patch(text: str) -> dict[str, list[str]]:
    normalized = text.lower().replace("ё", "е")
    cleaned = normalized.strip(" .,!?:;")
    no_extras = (
        "нет",
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
        "ничего",
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
    if cleaned in no_extras or any(marker in normalized for marker in fuzzy_no_extras):
        return {"upsell_items": ["не нужны"]}

    items: list[str] = []
    markers = {
        "уголь": ("уголь",),
        "розжиг": ("розжиг", "растоп"),
        "решетка/шампуры": ("решет", "шампур"),
        "лед": ("лед", "льда"),
        "посуда": ("посуд", "стакан", "тарел"),
        "кальян": ("кальян",),
        "продление": ("продлен", "продлить"),
        "уборка": ("уборк",),
        "вода": ("вода", "воду", "воды", "чай", "напит"),
    }
    for item, item_markers in markers.items():
        if any(marker in normalized for marker in item_markers):
            items.append(item)
    if items:
        return {"upsell_items": items}
    return {}


def _is_upsell_negative(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    return bool(_upsell_items_patch(text).get("upsell_items") == ["не нужны"]) or normalized in {
        "нет",
        "не надо",
        "не нужно",
        "ничего",
        "без допов",
    }


def _upsell_push_reply(form_data: dict[str, Any]) -> str:
    service_type = form_data.get("service_type")
    if service_type == "bathhouse":
        usual = "к бане обычно берут лёд для напитков, посуду, воду и кальян"
        soft = "На день рождения это особенно удобно: не нужно везти мелочи с собой."
    elif service_type == "gazebo":
        usual = "к беседке чаще всего берут уголь, розжиг, решётку или шампуры, посуду и кальян"
        soft = "Так отдых начинается сразу, без лишних заездов в магазин."
    elif service_type == "house":
        usual = "к дому обычно берут посуду, лёд, воду, кальян и иногда продление"
        soft = "Это удобно, если компания планирует отдыхать дольше."
    else:
        usual = "обычно берут посуду, лёд, воду, кальян или продление"
        soft = "Можно добавить только то, что действительно пригодится."
    return (
        f"Поняла. Всё же подскажу: {usual}.\n\n"
        f"{soft} Может, отметим хотя бы что-то из этого? Если точно ничего не нужно, напишите «нет» ещё раз."
    )


def _has_upsell_signal(text: str) -> bool:
    return bool(_upsell_items_patch(text)) or any(
        marker in text.lower().replace("ё", "е")
        for marker in ("доп", "уголь", "розжиг", "решет", "шампур", "лед", "посуд", "кальян")
    )


def _looks_like_name(text: str) -> bool:
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
    return lowered not in blocked and not _has_upsell_signal(lowered)


def _valid_phone(value: Any) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    return 10 <= len(digits) <= 15


def _time_period_patch(text: str) -> dict[str, Any]:
    normalized = text.lower().replace(",", ".")
    normalized = normalized.replace("утра", "").replace("дня", "").replace("вечера", "").replace("вечер", "")
    normalized = re.sub(r"\b(?:полночь|полночи|полноч)\b", "00", normalized)
    match = re.search(
        r"(?:с\s*)?(\d{1,2})(?:[:.\-]\s*(\d{2}))?\s*(?:до|\-)\s*(\d{1,2})(?:[:.]\s*(\d{2}))?",
        normalized,
    )
    if not match:
        return {}
    start_hour = int(match.group(1))
    start_minute = int(match.group(2) or 0)
    end_hour = int(match.group(3))
    end_minute = int(match.group(4) or 0)
    original = text.lower().replace("ё", "е")
    start_context = original[max(0, original.find(match.group(1)) - 3) : original.find(match.group(1)) + 16]
    if start_hour < 12 and any(marker in start_context for marker in ("вечера", "вечер", "дня")):
        start_hour += 12
    if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
        return {}
    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute
    if end_total <= start_total:
        end_total += 24 * 60
    duration_hours = round((end_total - start_total) / 60, 2)
    duration_value: int | float = int(duration_hours) if duration_hours.is_integer() else duration_hours
    return {
        "time": f"{start_hour:02d}:{start_minute:02d}",
        "duration": duration_value,
    }


def _guests_count_patch(text: str, expected_key: str | None) -> dict[str, int]:
    if expected_key != "guests_count":
        return {}
    normalized = text.lower().replace("ё", "е").strip()
    match = re.fullmatch(r"(?:нас\s*)?(\d{1,3})(?:\s*(?:человек|гостей|гостя|гость|чел))?", normalized)
    if not match:
        match = re.search(r"\bнас\s+(\d{1,3})\b", normalized)
    if not match:
        match = re.search(r"\b(\d{1,3})\s*(?:человек|гостей|гостя|гость|чел)\b", normalized)
    if not match:
        return {}
    guests = int(match.group(1))
    if guests <= 0 or guests > 300:
        return {}
    return {"guests_count": guests}


def _last_assistant_asked_guest_count(history: list[dict[str, Any]]) -> bool:
    for item in reversed(history):
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        text = str(item.get("text") or "").lower().replace("ё", "е")
        return "сколько вас" in text or "сколько примерно гостей" in text
    return False


def _client_name_patch(text: str, expected_key: str | None) -> dict[str, str]:
    if expected_key != "client_name":
        return {}
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not _looks_like_name(cleaned):
        return {}
    return {"client_name": cleaned.title()}


def _duration_from_text(text: str) -> int | float | None:
    normalized = text.lower().replace(",", ".")
    match = re.search(r"(?:на\s*)?(\d+(?:\.\d+)?)\s*(?:час|часа|часов|ч\b)", normalized)
    if not match:
        return None
    value = float(match.group(1))
    return int(value) if value.is_integer() else value


def _duration_minutes_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(float(value) * 60) if float(value) < 24 else int(value)
    text = str(value).lower().replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    number = float(match.group(1))
    return int(number) if "мин" in text else int(number * 60)


def _format_duration(value: Any) -> str:
    minutes = _duration_minutes_value(value)
    if minutes is None:
        return str(value or "")
    if minutes % 60 == 0:
        hours = minutes // 60
        if hours % 10 == 1 and hours % 100 != 11:
            suffix = "час"
        elif hours % 10 in (2, 3, 4) and hours % 100 not in (12, 13, 14):
            suffix = "часа"
        else:
            suffix = "часов"
        return f"{hours} {suffix}"
    return f"{minutes} минут"


def _period_conflict(text: str, patch: dict[str, Any]) -> bool:
    explicit_duration = _duration_from_text(text)
    period_duration = patch.get("duration")
    if explicit_duration is None or period_duration is None:
        return False
    return abs(float(explicit_duration) - float(period_duration)) >= 0.25


def _format_date_ru(value: Any) -> str:
    if not value:
        return "выбранную дату"
    try:
        parsed = datetime.fromisoformat(str(value)).date()
    except ValueError:
        return str(value)
    return f"{parsed.day} {MONTH_NAMES_RU[parsed.month]}"


def _confirmation_yes(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip()
    return normalized in {
        "да",
        "д",
        "+",
        "подтверждаю",
        "подтвердить",
        "ок",
        "окей",
        "хорошо",
        "верно",
        "все верно",
        "все правильно",
        "правильно",
    } or "подтверж" in normalized


def _confirmation_no(text: str) -> bool:
    normalized = text.lower().strip()
    return normalized in {"нет", "не", "не подтверждаю"} or "измен" in normalized


def _wants_additional_booking(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("еще", "ещё", "добав", "также", "тоже", "брон", "заброни", "хочу", "нужн")):
        return False
    return bool(_service_type_patch(normalized))


def _starts_new_booking_request(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if _asks_available_services(text):
        return False
    if not _service_type_patch(normalized):
        return False
    return any(
        marker in normalized
        for marker in (
            "нужн",
            "хочу",
            "давай",
            "заброни",
            "брон",
            "оформ",
            "можно",
            "еще",
            "ещё",
            "добав",
        )
    )


def _is_plain_greeting(text: str) -> bool:
    normalized = re.sub(r"[^\w\s]+", " ", text.lower().replace("ё", "е")).strip()
    words = set(normalized.split())
    return bool(words & {"привет", "здравствуйте", "добрый", "день", "вечер"}) and not _service_type_patch(normalized)


def _asks_booking_summary(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if _asks_available_services(text):
        return False
    return (
        any(
            marker in normalized
            for marker in (
                "что я забронировал",
                "что я забронил",
                "что у меня забронировано",
                "моя бронь",
                "мои брони",
                "сколько у меня брон",
                "сколько брон",
                "количество брон",
                "что сейчас в бронировании",
                "в сумме",
                "итог",
                "итого",
            )
        )
    )


def _asks_available_services(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return (
        "что" in normalized
        and any(marker in normalized for marker in ("еще", "ещё", "помимо", "кроме", "другое", "другие"))
        and any(marker in normalized for marker in ("забронировать", "забронить", "есть", "можно"))
    ) or any(
        marker in normalized
        for marker in (
            "какие услуги",
            "что можно забронировать",
            "что у вас есть",
            "какие есть варианты",
        )
    )


def _asks_specific_service_exists(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return bool(_service_type_patch(normalized)) and (
        "?" in normalized
        or any(marker in normalized for marker in ("есть", "бывают", "имеются", "можно"))
    )


def _specific_service_exists_reply(text: str) -> str:
    service_type = (_service_type_patch(text) or {}).get("service_type")
    title = (load_services_map().get(service_type) or {}).get("title") or "эта услуга"
    return (
        f"Да, {title.lower()} есть. Если хотите добавить её отдельной бронью, "
        "напишите дату — проверю свободность."
    )


def _available_services_reply() -> str:
    return (
        "Помимо бани можно забронировать беседки, дом и формат «беседка + баня». "
        "По беседкам есть разные варианты: компактные, со светом/розетками, крытые и большие для компании.\n\n"
        "Если хотите добавить вторую бронь, напишите прямо, например: «хочу ещё беседку на 25 мая»."
    )


def _asks_gazebo_options(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return (
        ("бесед" in normalized and any(marker in normalized for marker in ("какие", "какая", "какой", "вариант", "выбор", "есть")))
        or "какой у меня выбор" in normalized
        or "какие варианты" in normalized
        or "какую лучше" in normalized
        or "что лучше" in normalized
        or "посовет" in normalized
        or "предлож" in normalized
        or "подбери" in normalized
        or "подобрать" in normalized
    )


def _mentions_payment_status(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "я оплатил",
            "я оплатила",
            "оплатил",
            "оплатила",
            "оплачено",
            "оплата прошла",
            "внес предоплату",
            "внесла предоплату",
            "предоплату внес",
            "предоплату внесла",
        )
    )


def _is_closing_ack(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip()
    normalized = re.sub(r"[^\w\s]+", " ", normalized)
    words = set(normalized.split())
    return bool(words & {"спасибо", "благодарю", "хорошо", "ок", "окей", "понял", "поняла"})


def _wants_cancel_or_change_hold(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("отмен", "убер", "помен", "замен", "вместо", "перенес"))


def _date_patch_after_marker(
    text: str,
    now: datetime,
    marker: str,
    *,
    base_date: date | None = None,
) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    index = normalized.find(marker)
    if index < 0:
        return {}
    fragment = normalized[index + len(marker) :]
    patch = _relative_date_patch(fragment, now)
    if patch:
        return patch
    bare_day = re.search(r"\b(\d{1,2})\b", fragment)
    if not bare_day:
        return {}
    day = int(bare_day.group(1))
    if base_date:
        try:
            candidate = base_date.replace(day=day)
        except ValueError:
            return {}
        if candidate < now.date():
            candidate = candidate.replace(year=candidate.year + 1)
        return {"date": candidate.isoformat()}
    today = now.date()
    month = today.month
    year = today.year
    for _ in range(13):
        if day <= calendar.monthrange(year, month)[1]:
            candidate = today.replace(year=year, month=month, day=day)
            if candidate >= today:
                return {"date": candidate.isoformat()}
        month += 1
        if month > 12:
            month = 1
            year += 1
    return {}


def _new_booking_form_data(previous: dict[str, Any]) -> dict[str, Any]:
    fresh = initial_form_data()
    for key in ("client_name", "phone"):
        if previous.get(key):
            fresh[key] = previous[key]
    return fresh


def _reply_with_hold_summary(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
    *,
    prefix: str | None = None,
) -> str:
    slot_holds_repo.expire_old(conn, now)
    holds = slot_holds_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation["id"],
        now=now,
    )
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    if not holds:
        message = _format_booking_summary(bookings) if bookings else "Сейчас активных предварительных заявок не осталось. Можем оформить новую бронь."
        return f"{prefix}\n\n{message}" if prefix else message
    summary = _format_hold_summary(holds, form_data)
    if bookings:
        summary = f"{_format_booking_summary(bookings)}\n\nСейчас дополнительно в резерве:\n{summary}"
    return f"{prefix}\n\n{summary}" if prefix else summary


def _handle_reserved_hold_command(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    form_data = conversation.get("form_data") or {}
    asks_summary = _asks_booking_summary(text)
    wants_cancel_or_change = _wants_cancel_or_change_hold(text)
    active_holds = slot_holds_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation["id"],
        now=now,
    )
    if not active_holds:
        if asks_summary:
            summary = _post_booking_summary(conn, conversation, form_data, now)
            return (
                summary,
                "waiting_user",
                conversation.get("current_step") or "waiting_user",
                next_question(form_data)[0],
                form_data,
            )
        if wants_cancel_or_change:
            if _wants_reschedule(text) and _has_user_bookings(conn, conversation, form_data, now):
                return _start_reschedule_flow(
                    conn,
                    conversation,
                    text,
                    form_data,
                    "payment_paid",
                    now,
                )
            return (
                "Сейчас не вижу активной предварительной заявки, которую можно отменить или поменять. Можем оформить новую бронь.",
                "waiting_user",
                conversation.get("current_step") or "waiting_user",
                next_question(form_data)[0],
                form_data,
            )
        return None

    if asks_summary:
        reply = _reply_with_hold_summary(conn, conversation, form_data, now)
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        return reply, status, "reserved", "payment_status", form_data

    if _confirmation_yes(text):
        try:
            payment = create_payment_link_for_holds(
                conn,
                conversation_id=conversation["id"],
                user_id=conversation["user_id"],
                hold_ids=[hold["id"] for hold in active_holds],
                client_name=str(form_data.get("client_name") or "Клиент"),
                phone=str(form_data.get("phone") or ""),
            )
        except Exception:
            logger.exception("Payment link creation failed conversation_id=%s", conversation["id"])
            payment = None
        return _payment_reply_text(payment), "reserved", "reserved", "payment_status", form_data

    if not wants_cancel_or_change:
        normalized = text.lower().replace("ё", "е")
        if any(marker in normalized for marker in ("зачем", "не понял", "не понимаю")):
            reply = _reply_with_hold_summary(
                conn,
                conversation,
                form_data,
                now,
                prefix="Извините, я сбился с контекста. Новую дату писать не нужно.",
            )
            status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
            return reply, status, "reserved", "payment_status", form_data
        return None

    service_type = (_service_type_patch(text) or {}).get("service_type")
    cancel_date = _date_patch_after_marker(text, now, "вместо").get("date")
    explicit_date = _relative_date_patch(text, now).get("date")
    if not cancel_date and "отмен" in text.lower():
        cancel_date = explicit_date
    if not cancel_date and len(active_holds) == 1:
        cancel_date = active_holds[0].get("slot_date").isoformat()
    slot_date = datetime.fromisoformat(str(cancel_date)).date() if cancel_date else None
    matching_before_cancel = [
        hold
        for hold in active_holds
        if (not service_type or hold.get("service_type") == service_type)
        and (not slot_date or str(hold.get("slot_date")) == str(slot_date))
    ]
    cancelled = slot_holds_repo.cancel_matching(
        conn,
        conversation_id=conversation["id"],
        now=now,
        service_type=service_type,
        slot_date=slot_date,
    )
    for hold in matching_before_cancel:
        bookings_repo.cancel_by_hold(
            conn,
            conversation_id=conversation["id"],
            slot_hold_id=hold["id"],
            now=now,
        )

    replacement_date = explicit_date if explicit_date and explicit_date != cancel_date else None
    if replacement_date:
        new_form = form_data.copy()
        if service_type:
            new_form["service_type"] = service_type
        new_form["date"] = replacement_date
        new_form["time"] = form_data.get("time")
        new_form["duration"] = form_data.get("duration")
        availability = check_availability(conn, form_data=new_form, now=now)
        if availability.ok and availability.slots:
            reply = _confirmation_reply_text(new_form)
            return reply, "awaiting_confirmation", "awaiting_confirmation", "confirmation", new_form
        prefix = "Старую дату убрал." if cancelled else "Понял, проверил новую дату."
        return (
            f"{prefix} На {_format_date_ru(replacement_date)} свободных вариантов не нашёл. Напишите другую дату.",
            "waiting_user",
            "awaiting_new_date",
            "date",
            _reset_unavailable_slot(new_form),
        )

    prefix = "Отменил выбранную позицию." if cancelled else "Не нашёл такую активную позицию для отмены."
    reply = _reply_with_hold_summary(conn, conversation, form_data, now, prefix=prefix)
    status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
    return reply, status, "reserved", "payment_status", form_data


def _has_date_signal(text: str) -> bool:
    normalized = text.lower()
    if any(word in normalized for word in ("сегодня", "завтра", "послезавтра")):
        return True
    if any(re.search(rf"\b{word}\b", normalized) for word in WEEKDAY_ALIASES):
        return True
    return bool(re.search(r"\b\d{1,2}\s*(мая|июня|июля|августа|сентября|октября|ноября|декабря|января|февраля|марта|апреля)?\b", normalized))


def _build_reply(ai_reply: str, action: str, form_data: dict[str, Any]) -> tuple[str, str | None]:
    ai_reply = _clean_reply(ai_reply or "")
    next_key, question = next_question(form_data)

    if action in {"check_availability", "offer_slots", "hold_slot", "create_booking"}:
        if question:
            return (
                f"{ai_reply}\n\nПока уточню ещё один момент: {question}",
                next_key,
            )
        return (
            "Данные собрал. Сейчас подготовлю подтверждение брони.",
            None,
        )

    if action == "handoff_to_human":
        return (
            ai_reply
            or "Передам вопрос, чтобы вам помогли точнее.",
            next_key,
        )

    if question and _has_too_many_questions(ai_reply):
        return question, next_key

    if ai_reply:
        return ai_reply, next_key
    return _fallback_reply(form_data)


def _append_expected_question(reply: str, form_data: dict[str, Any]) -> tuple[str, str | None]:
    next_key, question = next_question(form_data)
    if not question:
        return reply, next_key
    lowered = reply.lower()
    question_lowered = question.lower()
    if question_lowered in lowered:
        return reply, next_key
    if next_key == "date" and "на какую дату" in lowered:
        return reply, next_key
    if next_key == "date" and "когда планируете" in lowered:
        return reply, next_key
    if next_key == "date" and "какую дату планируете" in lowered:
        return reply, next_key
    if next_key == "time" and ("какое время" in lowered or "на какое время" in lowered):
        return reply, next_key
    if next_key == "duration" and ("на сколько часов" in lowered or "сколько часов" in lowered):
        return reply, next_key
    if next_key == "guests_count" and ("сколько" in lowered and ("гост" in lowered or "человек" in lowered)):
        return reply, next_key
    if next_key == "event_format" and any(marker in lowered for marker in ("формат", "день рождения", "корпоратив", "семей")):
        return reply, next_key
    if next_key == "client_name" and ("как вас зовут" in lowered or "ваше имя" in lowered):
        return reply, next_key
    if next_key == "phone" and "телефон" in lowered:
        return reply, next_key
    if next_key == "upsell_items" and any(marker in lowered for marker in ("доп", "уголь", "розжиг", "решет", "шампур")):
        return reply, next_key
    return f"{reply}\n\n{question}", next_key


def _confirmation_reply_text(form_data: dict[str, Any]) -> str:
    title = (load_services_map().get(form_data.get("service_type")) or {}).get("title") or "объект"
    variant = form_data.get("service_variant")
    object_text = f"{title}, {variant}" if variant else title
    extras = ", ".join(form_data.get("upsell_items") or []) or "не указаны"
    return (
        f"Проверил и собрал заявку: {object_text}, {_format_date_ru(form_data.get('date'))}, "
        f"с {form_data.get('time')} на {_format_duration(form_data.get('duration'))}, "
        f"гостей: {form_data.get('guests_count')}, формат: {form_data.get('event_format')}, "
        f"допы: {extras}, имя: {form_data.get('client_name')}, телефон: {form_data.get('phone')}.\n\n"
        "Подтверждаете бронь?"
    )


def _price_reply_if_known(text: str, form_data: dict[str, Any]) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("цена", "стоим", "сколько стоит", "почем")):
        return None
    if not form_data.get("service_type"):
        return None
    variant = _selected_variant_config(form_data)
    price = variant.get("price")
    if not price:
        return None
    title = variant.get("title") or (load_services_map().get(form_data.get("service_type")) or {}).get("title") or "услуга"
    date_text = _format_date_ru(form_data.get("date")) if form_data.get("date") else "на выбранную дату"
    duration = form_data.get("duration") or variant.get("duration_minutes")
    duration_text = f" на {_format_duration(duration)}" if duration else ""
    return (
        f"По текущей карте услуг {title.lower()} {date_text}{duration_text} стоит {price} ₽. "
        "Финальную сумму закрепим по данным брони.\n\n"
        f"{next_question(form_data)[1] or 'Если всё верно, можем продолжать оформление.'}"
    )


def _changes_booking_core_fields(patch: dict[str, Any]) -> bool:
    return bool(
        {
            "service_type",
            "service_variant",
            "date",
            "time",
            "duration",
            "guests_count",
            "event_format",
            "client_name",
            "phone",
            "upsell_items",
        }
        & set(patch)
    )


def _deterministic_info_reply(text: str, form_data: dict[str, Any]) -> str | None:
    normalized = text.lower().replace("ё", "е")
    _, question = next_question(form_data)
    if "парков" in normalized:
        reply = "Да, парковка есть."
    elif "мангал" in normalized:
        reply = "Да, мангал есть у беседок."
    elif "туалет" in normalized:
        reply = "Да, туалет на территории есть."
    else:
        return None
    if question:
        reply = f"{reply}\n\n{question}"
    return reply


def _format_hold_summary(holds: list[dict[str, Any]], form_data: dict[str, Any]) -> str:
    lines = ["Зафиксировал заявку. Вот что сейчас в бронировании:"]
    for index, hold in enumerate(holds, start=1):
        title = (load_services_map().get(hold.get("service_type")) or {}).get("title") or hold.get("service_type")
        slot_time = str(hold.get("slot_time") or "")[:5]
        duration = _format_duration(hold.get("duration_minutes"))
        lines.append(f"{index}. {title}: {_format_date_ru(hold.get('slot_date'))}, с {slot_time} на {duration}.")
    phone = form_data.get("phone")
    if phone:
        lines.append(f"Номер {phone} сохранил для связи по брони.")
    else:
        lines.append("Контакт для связи по брони сохранил.")
    return "\n".join(lines)


def _booking_object_title(booking: dict[str, Any]) -> str:
    service_type = booking.get("service_type")
    config = load_services_map().get(service_type) or {}
    title = config.get("title") or str(service_type or "Бронь")
    if service_type != "gazebo":
        return title

    hold_service_id = str(booking.get("hold_yclients_service_id") or "").strip()
    for variant in config.get("variants") or []:
        if hold_service_id and str(variant.get("yclients_service_id") or "").strip() == hold_service_id:
            return str(variant.get("title") or title)
    return title


def _booking_status_text(booking: dict[str, Any]) -> str:
    payment_status = str(booking.get("payment_status") or "")
    status = str(booking.get("status") or "")
    if payment_status == "paid" and booking.get("yclients_record_id"):
        return "оплата прошла, бронь подтверждена"
    if payment_status == "paid":
        return "оплата прошла, бронь подтверждается в журнале"
    if payment_status == "awaiting_payment":
        return "ожидает оплаты"
    if status == "confirmed":
        return "подтверждается"
    return "зафиксирована"


def _booking_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "бронь"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "брони"
    return "броней"


def _format_booking_summary(bookings: list[dict[str, Any]]) -> str:
    active = [booking for booking in bookings if booking.get("status") != "cancelled"]
    if not active:
        return "Пока не вижу активных броней."

    count = len(active)
    lines = [f"У вас {count} {_booking_word(count)}:"]
    for index, booking in enumerate(active, start=1):
        time_text = str(booking.get("booking_time") or "")[:5]
        duration = _format_duration(booking.get("duration_minutes"))
        guests = booking.get("guests_count")
        guests_text = f", гостей: {guests}" if guests else ""
        lines.append(
            f"{index}. {_booking_object_title(booking)}: "
            f"{_format_date_ru(booking.get('booking_date'))}, с {time_text} на {duration}"
            f"{guests_text}. {_booking_status_text(booking)}."
        )
    return "\n".join(lines)


def _active_user_bookings(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    phone = form_data.get("phone")
    if not phone:
        user = users_repo.get_by_id(conn, int(conversation["user_id"]))
        phone = (user or {}).get("phone")
    bookings = bookings_repo.list_future_active_for_user(
        conn,
        user_id=int(conversation["user_id"]),
        phone=str(phone) if phone else None,
        now=now,
    )
    if bookings:
        return bookings
    return bookings_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation["id"],
    )


def _has_user_bookings(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> bool:
    return bool(_active_user_bookings(conn, conversation, form_data, now))


def _context_summaries(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    summaries = conversation_summaries_repo.list_for_conversation(
        conn,
        conversation["id"],
        limit=3,
    )
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    if bookings:
        summaries.append(
            {
                "messages_from": "active_bookings",
                "messages_to": "active_bookings",
                "summary": (
                    "Активные будущие брони этого клиента, даже если они были оформлены "
                    "в старом диалоге:\n"
                    f"{_format_booking_summary(bookings)}"
                ),
            }
        )
    return summaries


def _payment_reply_text(payment: dict[str, Any] | None) -> str:
    if not payment or not payment.get("payment_url"):
        return (
            "Ссылку на предоплату сейчас автоматически создать не получилось. "
            "Ваш номер сохранён, с вами свяжутся в ближайшее время и отправят ссылку вручную."
        )
    return (
        f"Для закрепления заявки нужна предоплата {payment.get('amount')} ₽.\n"
        f"Оплатить можно по ссылке:\n{payment['payment_url']}\n\n"
        "После оплаты дождитесь подтверждения: мы пришлём сообщение, когда платёж пройдёт ✅"
    )


def _payment_status_reply(conn, conversation: dict[str, Any], form_data: dict[str, Any]) -> tuple[str, str]:
    try:
        sync_payment_statuses(conn)
        create_missing_yclients_records(conn)
    except Exception:
        logger.exception("Payment status sync failed conversation_id=%s", conversation["id"])

    payments = payments_repo.list_for_conversation(
        conn,
        conversation_id=conversation["id"],
    )
    if not payments:
        return (
            "Я пока не вижу созданной ссылки на оплату по этой заявке. "
            "Если заявка уже подтверждена, напишите «да» ещё раз — пришлю ссылку на предоплату.",
            "reserved",
        )

    paid_payment = next((payment for payment in payments if payment.get("status") == "paid"), None)
    if paid_payment:
        if not paid_payment.get("payment_notified_at"):
            payments_repo.mark_payment_notified(conn, payment_id=paid_payment["id"])
        bookings = _active_user_bookings(conn, conversation, form_data, _now_local())
        summary = _format_booking_summary(bookings) if bookings else "Заявка зафиксирована."
        return (
            f"Да, оплата получена. Спасибо!\n\n{summary}\n\n"
            "Повторно подтверждать заявку уже не нужно.",
            "payment_paid",
        )

    latest_payment = payments[0]
    if latest_payment.get("payment_url"):
        return (
            "Пока оплата ещё не отразилась в ЮKassa. Обычно это занимает немного времени.\n\n"
            f"Если нужно, вот ссылка ещё раз:\n{latest_payment['payment_url']}",
            "reserved",
        )
    return (
        "Пока оплата ещё не отразилась в ЮKassa. Проверю её автоматически ещё раз чуть позже.",
        "reserved",
    )


def _post_booking_summary(conn, conversation: dict[str, Any], form_data: dict[str, Any], now: datetime) -> str:
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    active_holds = slot_holds_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation["id"],
        now=now,
    )
    if bookings and not active_holds:
        return _format_booking_summary(bookings)
    if bookings and active_holds:
        return f"{_format_booking_summary(bookings)}\n\nСейчас дополнительно в резерве:\n{_format_hold_summary(active_holds, form_data)}"
    if active_holds:
        summary = _format_hold_summary(active_holds, form_data)
        if conversation.get("status") == "payment_paid":
            summary = summary.replace(
                " для финального подтверждения и предоплаты",
                " для финального подтверждения",
            )
        return summary
    return "Заявка зафиксирована. Ваш номер сохранён, с вами свяжутся в ближайшее время."


def _classify_post_booking(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    now: datetime,
) -> Any:
    try:
        return classify_post_booking_message(
            text=text,
            form_data=form_data,
            history=history,
            current_datetime=now,
            knowledge=load_knowledge(),
        )
    except AIProviderUnavailable:
        raise
    except Exception:
        logger.exception("Post-booking classification failed")
        return None


def _handle_post_booking_message(
    conn,
    conversation: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    if conversation.get("current_step") != "reserved" and conversation.get("status") not in {"reserved", "payment_paid"}:
        return None

    form_data = conversation.get("form_data") or {}
    try:
        sync_payment_statuses(conn)
        create_missing_yclients_records(conn)
        payments = payments_repo.list_for_conversation(conn, conversation_id=conversation["id"])
        if any(payment.get("status") == "paid" for payment in payments):
            conversation = {**conversation, "status": "payment_paid"}
    except Exception:
        logger.exception("Post-booking payment refresh failed conversation_id=%s", conversation["id"])

    status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"

    if form_data.get("cancel_flow"):
        return _handle_cancel_booking_flow(conn, conversation, text, form_data, now)

    if form_data.get("reschedule_flow"):
        return _handle_reschedule_flow(conn, conversation, text, form_data, now)

    if _wants_cancel_booking(text):
        return _start_cancel_booking_flow(conn, conversation, text, form_data, status, now)

    if _wants_reschedule(text):
        return _start_reschedule_flow(conn, conversation, text, form_data, status, now)

    try:
        classified = _classify_post_booking(
            text=text,
            form_data=form_data,
            history=history,
            now=now,
        )
    except AIProviderUnavailable as exc:
        _log_ai_provider_unavailable(
            conn,
            conversation_id=conversation["id"],
            exc=exc,
            text=text,
            form_data=form_data,
        )
        reply = (
            _post_booking_summary(conn, conversation, form_data, now)
            if _asks_booking_summary(text)
            else _specific_service_exists_reply(text)
            if _asks_specific_service_exists(text)
            else _deterministic_info_reply(text, form_data)
            or "Спасибо! Заявка у меня сохранена. Если хотите добавить новую бронь или изменить текущую, напишите это прямо."
        )
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        return reply, status, "reserved", "payment_status", form_data
    intent = getattr(classified, "intent", "other") if classified else "other"
    reply_to_user = _clean_reply((getattr(classified, "reply_to_user", "") or "").strip()) if classified else ""
    status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
    if getattr(classified, "handoff_to_human", False):
        user = users_repo.get_by_id(conn, int(conversation["user_id"]))
        if user:
            _start_user_handoff(
                conn,
                user=user,
                conversation_id=conversation["id"],
                text=text,
                now=now,
                reason="постбронь: нужен живой ответ",
            )
        return _handoff_reply(), "handoff", "handoff", "handoff", form_data

    if intent == "new_booking_request":
        return None
    if intent == "payment_status":
        reply, payment_status = _payment_status_reply(conn, conversation, form_data)
        return reply, payment_status, "reserved", "payment_status", form_data
    if intent == "current_booking_question":
        summary = _post_booking_summary(conn, conversation, form_data, now)
        if _asks_booking_summary(text):
            reply = summary
        elif reply_to_user:
            reply = reply_to_user
        else:
            reply = summary
        return reply, status, "reserved", "payment_status", form_data
    if intent == "change_existing_booking":
        if _wants_reschedule(text):
            return _start_reschedule_flow(conn, conversation, text, form_data, status, now)
        return (
            reply_to_user
            or "Понял, хотите изменить текущую бронь. Напишите, пожалуйста, что именно меняем: дату, время, гостей, допы или сам объект.",
            status,
            "reserved",
            "payment_status",
            form_data,
        )
    if intent == "human_request":
        return (
            reply_to_user
            or "Передам запрос. Ваш номер сохранён, с вами свяжутся по текущей брони.",
            status,
            "reserved",
            "payment_status",
            form_data,
        )

    if reply_to_user:
        return reply_to_user, status, "reserved", "payment_status", form_data

    if conversation.get("status") == "payment_paid":
        reply = reply_to_user or "И вам спасибо! Бронь зафиксирована."
        return reply, "payment_paid", "reserved", "payment_status", form_data

    reply = reply_to_user or "Спасибо! Заявка зафиксирована. Если понадобится что-то изменить или добавить ещё одну бронь, просто напишите."
    return reply, status, "reserved", "payment_status", form_data


def _wants_reschedule(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("перенес", "перенести", "поменять дату", "изменить дату", "другую дату", "поменять время", "изменить время"))


def _wants_cancel_booking(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if "доп" in normalized:
        return False
    return any(marker in normalized for marker in ("отмен", "удал", "убрать брон", "снять брон"))


def _start_cancel_booking_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    if not bookings:
        return (
            "Активной брони для отмены не нашла. Если нужно оформить новую бронь или проверить дату, напишите услугу и дату.",
            status,
            "reserved",
            "payment_status",
            form_data,
        )
    booking = _select_reschedule_booking(bookings, None, text)
    flow = {"stage": "confirm_cancel", "booking_id": booking.get("id") if booking else None}
    updated = {**form_data, "cancel_flow": flow}
    if not booking:
        lines = ["Какую бронь отменяем?"]
        for index, item in enumerate(bookings, start=1):
            lines.append(f"{index}. {_booking_line_short(item)}")
        lines.append("")
        lines.append("Напишите номер брони из списка.")
        return "\n".join(lines), status, "reserved", "payment_status", updated
    return _cancel_confirmation_reply(booking), status, "reserved", "payment_status", updated


def _handle_cancel_booking_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    status = (
        "payment_paid"
        if conversation.get("status") == "payment_paid" or any(booking.get("payment_status") == "paid" for booking in bookings)
        else "reserved"
    )
    flow = dict(form_data.get("cancel_flow") or {})
    booking = _select_reschedule_booking(bookings, flow.get("booking_id"), text)
    if not booking:
        flow = flow | {"stage": "confirm_cancel"}
        lines = ["Какую бронь отменяем?"]
        for index, item in enumerate(bookings, start=1):
            lines.append(f"{index}. {_booking_line_short(item)}")
        return "\n".join(lines), status, "reserved", "payment_status", {**form_data, "cancel_flow": flow}

    if not flow.get("booking_id"):
        flow = flow | {"booking_id": booking["id"], "stage": "confirm_cancel"}
        return _cancel_confirmation_reply(booking), status, "reserved", "payment_status", {**form_data, "cancel_flow": flow}

    if _confirmation_no(text):
        cleared = {**form_data, "cancel_flow": None}
        return "Хорошо, бронь оставила без изменений ✅", status, "reserved", "payment_status", cleared

    if not _confirmation_yes(text):
        return _cancel_confirmation_reply(booking), status, "reserved", "payment_status", {**form_data, "cancel_flow": flow}

    old_booking = bookings_repo.get_by_id(conn, booking_id=int(booking["id"])) or booking
    if not delete_yclients_record_for_booking(conn, booking=old_booking):
        user = users_repo.get_by_id(conn, int(conversation["user_id"]))
        if user:
            _start_user_handoff(
                conn,
                user=user,
                conversation_id=conversation["id"],
                text=text,
                now=now,
                reason="техническая ошибка: не удалось удалить запись в журнале",
            )
        return _handoff_reply(), "handoff", "handoff", "handoff", form_data
    bookings_repo.cancel_by_id(conn, booking_id=int(booking["id"]), now=now)
    cleared = {**form_data, "cancel_flow": None}
    return (
        f"Готово ✅\n\nОтменила бронь: {_booking_line_short(booking)}.\n\nАванс по правилам не возвращается.",
        "payment_paid",
        "reserved",
        "payment_status",
        cleared,
    )


def _cancel_confirmation_reply(booking: dict[str, Any]) -> str:
    return (
        f"Могу отменить бронь: {_booking_line_short(booking)}.\n\n"
        "Важно: аванс по правилам не возвращается.\n\n"
        "Точно отменяем? Напишите «да» или «нет»."
    )


def _start_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    if not bookings:
        return (
            "Активной брони для переноса не нашла. Напишите, пожалуйста, что именно бронировали — проверю по диалогу.",
            status,
            "reserved",
            "payment_status",
            form_data,
        )
    status = "payment_paid" if any(booking.get("payment_status") == "paid" for booking in bookings) else status
    flow = {"stage": "reschedule", "booking_id": None}
    updated = {**form_data, "reschedule_flow": flow}
    if len(bookings) == 1:
        flow["booking_id"] = bookings[0]["id"]
        updated["reschedule_flow"] = flow
        return _handle_reschedule_flow(conn, conversation, text, updated, now)

    lines = ["Конечно, перенос возможен: аванс сохраняется, остаток можно будет внести на месте.", "", "Какую бронь переносим?"]
    for index, booking in enumerate(bookings, start=1):
        lines.append(f"{index}. {_booking_line_short(booking)}")
    return "\n".join(lines), status, "reserved", "payment_status", updated


def _handle_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    status = (
        "payment_paid"
        if conversation.get("status") == "payment_paid" or any(booking.get("payment_status") == "paid" for booking in bookings)
        else "reserved"
    )
    flow = dict(form_data.get("reschedule_flow") or {})
    booking = _select_reschedule_booking(bookings, flow.get("booking_id"), text)
    if not booking:
        lines = ["Какую бронь переносим?"]
        for index, item in enumerate(bookings, start=1):
            lines.append(f"{index}. {_booking_line_short(item)}")
        return "\n".join(lines), status, "reserved", "payment_status", {**form_data, "reschedule_flow": flow}

    if flow.get("stage") == "confirm_reschedule":
        if _confirmation_no(text):
            return "Хорошо, оставила бронь без изменений ✅", status, "reserved", "payment_status", {**form_data, "reschedule_flow": None}
        if not _confirmation_yes(text):
            return _reschedule_confirmation_reply(booking, flow), status, "reserved", "payment_status", {**form_data, "reschedule_flow": flow}
        return _execute_reschedule(conn, conversation, booking, form_data, flow)

    patch = _deterministic_patch(text, now)
    target_from_marker = _reschedule_target_date_patch(text, now, booking)
    if target_from_marker:
        patch["date"] = target_from_marker["date"]
    if _bare_weekday_confirmation(text, now) and not patch.get("date"):
        return _bare_weekday_confirmation(text, now) or "", status, "reserved", "payment_status", {**form_data, "reschedule_flow": flow | {"booking_id": booking["id"]}}

    target_date = patch.get("date") or flow.get("date")
    target_time = patch.get("time") or flow.get("time") or str(booking.get("booking_time"))[:5]
    target_duration = patch.get("duration") or flow.get("duration") or _hours_from_minutes(booking.get("duration_minutes"))
    flow = flow | {
        "booking_id": booking["id"],
        "date": target_date,
        "time": target_time,
        "duration": target_duration,
    }
    updated = {**form_data, "reschedule_flow": flow}
    if not target_date:
        return (
            f"Переносим {_booking_line_short(booking)}.\n\nНа какую новую дату?",
            status,
            "reserved",
            "payment_status",
            updated,
        )
    if not target_time:
        return (
            f"Поняла дату: {_format_date_ru(target_date)}.\n\nВо сколько хотите приехать? Можно сразу написать период, например: с 18:00 до 00:00.",
            status,
            "reserved",
            "payment_status",
            updated,
        )

    check_form = _form_data_for_booking_reschedule(form_data, booking, flow)
    availability = check_availability(conn, form_data=check_form, now=now)
    if availability.ok and not availability.slots:
        remember_waitlist_request(
            conn,
            conversation_id=conversation["id"],
            user_id=conversation["user_id"],
            form_data=check_form,
        )
        return (
            _append_waitlist_offer(
                f"На {_format_date_ru(target_date)} с {target_time} свободного варианта для переноса не нашла. Напишите другую дату или время — проверю ещё раз."
            ),
            status,
            "reserved",
            "payment_status",
            {**updated, "reschedule_flow": flow},
        )

    confirm_flow = flow | {"stage": "confirm_reschedule"}
    return (
        _reschedule_confirmation_reply(booking, confirm_flow),
        status,
        "reserved",
        "payment_status",
        {**updated, "reschedule_flow": confirm_flow},
    )


def _execute_reschedule(
    conn,
    conversation: dict[str, Any],
    booking: dict[str, Any],
    form_data: dict[str, Any],
    flow: dict[str, Any],
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    target_date = flow.get("date")
    target_time = flow.get("time")
    target_duration = flow.get("duration")
    old_booking = bookings_repo.get_by_id(conn, booking_id=int(booking["id"])) or booking
    if not delete_yclients_record_for_booking(conn, booking=old_booking):
        user = users_repo.get_by_id(conn, int(conversation["user_id"]))
        if user:
            _start_user_handoff(
                conn,
                user=user,
                conversation_id=conversation["id"],
                text=f"перенос брони #{booking.get('id')}",
                now=_now_local(),
                reason="не удалось автоматически удалить старую запись при переносе",
            )
        return _handoff_reply(), "handoff", "handoff", "handoff", form_data

    new_date = datetime.fromisoformat(str(target_date)).date()
    new_time = datetime.strptime(str(target_time)[:5], "%H:%M").time()
    new_duration = _duration_minutes_value(target_duration)
    updated_booking = bookings_repo.update_schedule(
        conn,
        booking_id=int(booking["id"]),
        booking_date=new_date,
        booking_time=new_time,
        duration_minutes=new_duration,
    )
    if updated_booking:
        upsert_local_busy_interval_for_booking(conn, booking=updated_booking)
        create_missing_yclients_records(conn)
    cleared = {**form_data, "date": target_date, "time": target_time, "duration": target_duration, "reschedule_flow": None}
    return (
        f"Готово ✅\n\nПеренесла бронь на {_format_date_ru(target_date)}, с {target_time} на {_format_duration(target_duration)}.\n\nАванс сохраняется, остаток можно будет внести на месте.",
        "payment_paid",
        "reserved",
        "payment_status",
        cleared,
    )


def _reschedule_target_date_patch(text: str, now: datetime, booking: dict[str, Any]) -> dict[str, str]:
    booking_date = booking.get("booking_date")
    base_date = booking_date if isinstance(booking_date, date) else None
    for marker in ("перенести на", "перенесем на", "перенесём на", "поменять на", "изменить на"):
        patch = _date_patch_after_marker(text, now, marker, base_date=base_date)
        if patch:
            return patch
    return {}


def _reschedule_confirmation_reply(booking: dict[str, Any], flow: dict[str, Any]) -> str:
    target_date = flow.get("date")
    target_time = flow.get("time")
    target_duration = flow.get("duration")
    return (
        "Проверила, на новое время свободно ✅\n\n"
        f"Перенести бронь «{_booking_line_short(booking)}» "
        f"на {_format_date_ru(target_date)}, с {target_time} на {_format_duration(target_duration)}?\n\n"
        "Аванс сохраняется. Если по новой дате или услуге будет разница в стоимости, её можно будет доплатить на месте.\n\n"
        "Подтверждаете перенос? Напишите «да» или «нет»."
    )


def _select_reschedule_booking(bookings: list[dict[str, Any]], booking_id: Any, text: str) -> dict[str, Any] | None:
    if booking_id:
        for booking in bookings:
            if int(booking["id"]) == int(booking_id):
                return booking
    normalized = text.lower().replace("ё", "е")
    match = re.search(r"\b([1-9])\b", normalized)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(bookings):
            return bookings[index]
    service_patch = _service_type_patch(text)
    service_type = service_patch.get("service_type")
    if service_type:
        matches = [booking for booking in bookings if booking.get("service_type") == service_type]
        if len(matches) == 1:
            return matches[0]
    return bookings[0] if len(bookings) == 1 else None


def _form_data_for_booking_reschedule(form_data: dict[str, Any], booking: dict[str, Any], flow: dict[str, Any]) -> dict[str, Any]:
    service_type = booking.get("service_type")
    updated = {
        **form_data,
        "service_type": service_type,
        "date": flow.get("date"),
        "time": flow.get("time"),
        "duration": flow.get("duration"),
        "guests_count": booking.get("guests_count") or form_data.get("guests_count"),
    }
    if service_type == "gazebo" and form_data.get("service_variant"):
        updated["service_variant"] = form_data.get("service_variant")
    return updated


def _booking_line_short(booking: dict[str, Any]) -> str:
    title = (load_services_map().get(booking.get("service_type")) or {}).get("title") or booking.get("service_type")
    return f"{title}: {_format_date_ru(str(booking.get('booking_date')))}, с {str(booking.get('booking_time'))[:5]} на {_format_duration(_hours_from_minutes(booking.get('duration_minutes')))}"


def _hours_from_minutes(minutes: Any) -> int | None:
    if not minutes:
        return None
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return None
    return value // 60 if value % 60 == 0 else value


def _should_check_availability(action: str, changed_fields: list[str], form_data: dict[str, Any]) -> bool:
    if not form_data.get("service_type") or not form_data.get("date"):
        return False
    if action == "check_availability":
        return True
    return bool({"service_type", "service_variant", "date", "time", "duration"} & set(changed_fields))


def _ai_process_reply(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    required_meaning: str,
) -> str:
    try:
        return _clean_reply(generate_process_reply(
            text=text,
            form_data=form_data,
            history=history,
            required_meaning=required_meaning,
            knowledge=load_knowledge(),
        ))
    except AIProviderUnavailable:
        raise
    except Exception:
        logger.exception("AI process reply generation failed")
        return required_meaning


def _availability_reply(message: str, slots: list[str], form_data: dict[str, Any]) -> tuple[str, str | None]:
    next_key, question = next_question(form_data)
    if message.startswith("Для «") and "длительность" in message:
        return "На сколько часов хотите забронировать?", "duration"
    title = (load_services_map().get(form_data.get("service_type")) or {}).get("title") or "объект"
    date_text = _format_date_ru(form_data.get("date"))
    if slots:
        shown = ", ".join(slots[:5])
        if (
            form_data.get("service_type") == "gazebo"
            and form_data.get("service_variant")
            and form_data.get("single_available_gazebo_variant_auto")
            and not form_data.get("guests_count")
        ):
            return (
                f"На {date_text} свободна: {form_data['service_variant']}.\n\n"
                "Сколько примерно гостей?",
                "guests_count",
            )
        if form_data.get("service_type") == "gazebo" and not form_data.get("service_variant"):
            options = ", ".join(slot.split(":", 1)[0] for slot in slots[:8])
            text = f"На {date_text} свободны: {options}."
            text += "\n\nКакую беседку выбираете? Если скажете количество гостей, я подскажу подходящий вариант."
            return text, "service_variant"
        if form_data.get("time") and form_data.get("duration"):
            text = f"{shown} свободно."
        else:
            text = f"На {date_text} {title.lower()} свободна."
        if question:
            text += f"\n\n{question}"
        return text, next_key
    if question:
        return f"На {date_text} {title.lower()} свободна.\n\n{question}", next_key
    return f"На {date_text} {title.lower()} свободна.", None


def _no_availability_reply(form_data: dict[str, Any]) -> tuple[str, str]:
    service_type = form_data.get("service_type")
    title = (load_services_map().get(service_type) or {}).get("title") or "объект"
    date_text = form_data.get("date")
    time_text = form_data.get("time")
    duration_text = form_data.get("duration")
    details = []
    if date_text:
        details.append(_format_date_ru(date_text))
    if time_text:
        details.append(f"с {time_text}")
    if duration_text:
        details.append(f"на {duration_text} ч")
    details_text = " ".join(details) or "выбранную дату"
    if time_text or duration_text:
        return (
            f"На {details_text} свободных вариантов для «{title}» не нашёл. "
            "Напишите, пожалуйста, другую дату или другой период — проверю заново.",
            "date",
        )
    return (
        f"На {details_text} свободных вариантов для «{title}» не нашёл. "
        "Напишите, пожалуйста, другую дату — проверю свободные варианты.",
        "date",
    )


def _append_waitlist_offer(reply: str) -> str:
    return (
        f"{reply}\n\n"
        "Я запомнила ваш запрос: если место освободится из-за отмены, мы сможем вас уведомить."
    )


def _reset_unavailable_slot(form_data: dict[str, Any]) -> dict[str, Any]:
    updated = form_data.copy()
    updated["last_unavailable"] = {
        "service_type": form_data.get("service_type"),
        "date": form_data.get("date"),
        "time": form_data.get("time"),
        "duration": form_data.get("duration"),
    }
    updated["date"] = None
    updated["time"] = None
    updated["duration"] = None
    updated.pop("last_available_gazebo_variants", None)
    return updated


def _clear_active_slot_keep_last(form_data: dict[str, Any]) -> dict[str, Any]:
    updated = form_data.copy()
    updated["date"] = None
    updated["time"] = None
    updated["duration"] = None
    return updated


def _apply_previous_period_for_new_date(
    form_data: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    last_unavailable = form_data.get("last_unavailable") or {}
    if not patch.get("date"):
        return patch
    if patch.get("date") == last_unavailable.get("date"):
        return patch
    updated = patch.copy()
    if not updated.get("time") and last_unavailable.get("time"):
        updated["time"] = last_unavailable["time"]
    if not updated.get("duration") and last_unavailable.get("duration"):
        updated["duration"] = last_unavailable["duration"]
    return updated


def _same_unavailable_date_reply(form_data: dict[str, Any]) -> tuple[str, str]:
    last_unavailable = form_data.get("last_unavailable") or {}
    date_text = last_unavailable.get("date") or "эту дату"
    time_text = last_unavailable.get("time")
    duration_text = last_unavailable.get("duration")
    period = ""
    if time_text and duration_text:
        period = f" с {time_text} на {duration_text} ч"
    elif duration_text:
        period = f" на {duration_text} ч"
    return (
        f"{date_text}{period} уже проверял: свободных вариантов не нашёл. "
        "Напишите другую дату или другой период — проверю.",
        "date",
    )


def _asks_for_free_slots(text: str) -> bool:
    normalized = text.lower()
    return any(word in normalized for word in ("свобод", "слот", "время", "во сколько", "на сколько"))


def _is_likely_form_answer(
    text: str,
    expected_key: str | None,
    now: datetime,
) -> bool:
    if not expected_key:
        return False
    if _confirmation_yes(text) or _confirmation_no(text):
        return False
    patch = _current_step_patch(text, expected_key, now)
    if patch:
        return True
    if expected_key == "phone" and _phone_patch(text):
        return True
    if expected_key == "service_type" and _service_type_patch(text):
        return True
    if expected_key == "service_variant" and _service_variant_patch(text):
        return True
    if expected_key == "upsell_items":
        normalized = text.lower().replace("ё", "е").strip()
        if _upsell_items_patch(text) or normalized in {
            "нет",
            "не надо",
            "не нужно",
            "ничего",
            "без доп",
        }:
            return True
    if expected_key == "event_format" and _event_format_patch(text):
        return True
    if expected_key in {"time", "duration"} and _time_period_patch(text):
        return True
    if expected_key == "duration" and _duration_from_text(text) is not None:
        return True
    return False


def _reply_already_asks(reply: str, next_key: str | None, question: str | None) -> bool:
    if not question:
        return True
    lowered = reply.lower().replace("ё", "е")
    question_lowered = question.lower().replace("ё", "е")
    if question_lowered in lowered:
        return True
    if next_key == "guests_count" and "сколько" in lowered and ("гост" in lowered or "человек" in lowered):
        return True
    if next_key == "event_format" and ("формат" in lowered or "какой отдых" in lowered):
        return True
    if next_key == "date" and any(marker in lowered for marker in ("какую дату", "на какую дату", "когда планируете")):
        return True
    if next_key == "phone" and "телефон" in lowered:
        return True
    if next_key == "service_variant" and ("какую" in lowered or "выбираете" in lowered or "какой вариант" in lowered):
        return True
    if next_key == "upsell_items" and any(marker in lowered for marker in ("доп", "дополнитель", "уголь", "розжиг", "решет", "шампур", "кальян")):
        return True
    return False


def _looks_like_info_question(
    text: str,
    *,
    expected_key: str | None = None,
    now: datetime | None = None,
) -> bool:
    if _is_likely_form_answer(text, expected_key, now or _now_local()):
        return False
    normalized = text.lower().replace("ё", "е").strip()
    if "?" in normalized:
        return True
    if _confirmation_yes(normalized) or _confirmation_no(normalized):
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
    if re.search(r"\bсколько\b", normalized):
        return any(
            marker in normalized
            for marker in ("стоит", "стоят", "цена", "стоим", "почем", "прайс", "оплат")
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
        "насеком",
        "мошк",
        "клещ",
    )
    return any(marker in normalized for marker in markers)


def _answer_info_during_form(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    ai_result: Any,
) -> tuple[str, str | None]:
    next_key, question = next_question(form_data)
    ai_reply = _clean_reply((getattr(ai_result, "reply_to_user", "") or "").strip())
    if form_data.get("service_type") == "gazebo" and _asks_gazebo_options(text):
        reply = _gazebo_selection_text(form_data)
        if not form_data.get("guests_count"):
            return reply, "guests_count"
    elif getattr(ai_result, "action", "") == "answer_info" and ai_reply:
        reply = ai_reply
    else:
        price_reply = _price_reply_if_known(text, form_data)
        deterministic = price_reply or _deterministic_info_reply(text, form_data)
        if deterministic:
            reply = deterministic
        else:
            required = (
            "Клиент задал информационный вопрос во время анкеты. "
            "Сначала коротко и честно ответь только по базе знаний. "
            "Если в базе знаний нет точного ответа — так и скажи, без выдумок. "
            "Не задавай новый вопрос анкеты внутри ответа."
        )
            reply = _ai_process_reply(
                text=text,
                form_data=form_data,
                history=history,
                required_meaning=required,
            )

    if question and not _reply_already_asks(reply, next_key, question):
        reply = f"{reply}\n\nПродолжим оформление: {question}"
    return reply, next_key


def _safe_reply_without_availability_claim(
    reply: str,
    form_data: dict[str, Any],
) -> tuple[str, str | None]:
    next_key, question = next_question(form_data)
    if _must_ask_duration_before_availability(form_data):
        return "На сколько часов хотите забронировать?", "duration"
    if _mentions_availability(reply):
        if question:
            return question, next_key
        return (
            "Данные собрал. Сейчас нужно проверить свободное время в расписании.",
            None,
        )
    return reply, next_key


def _gazebo_selection_text(form_data: dict[str, Any]) -> str:
    guests = form_data.get("guests_count")
    available_variants = _available_gazebo_variant_configs(form_data)
    if available_variants is not None:
        suitable = available_variants
        if guests:
            suitable = [
                variant for variant in available_variants
                if int(variant.get("capacity_max") or 0) >= int(guests)
            ]
        shown_variants = suitable or available_variants
        if shown_variants:
            if guests:
                intro = f"Для {guests} гостей из свободных на выбранную дату вариантов подходят:"
            else:
                intro = "На выбранную дату свободны эти варианты:"
            lines = [intro]
            for variant in shown_variants:
                lines.append(f"- {_format_gazebo_variant_line(variant)}")
            if guests and not suitable:
                lines.append("")
                lines.append("По вместимости они могут быть тесноваты — лучше подобрать другую дату или вариант побольше.")
            elif not guests:
                lines.append("")
                lines.append("Сколько вас будет человек? Подскажу лучший вариант из свободных.")
            else:
                names = " или ".join(str(variant.get("title") or "").replace("Беседка ", "") for variant in shown_variants)
                lines.append("")
                lines.append(f"Я бы выбирал из них. Какую закрепляем: {names}?")
            return "\n".join(lines)

    intro = "Да, беседок несколько, лучше сначала подобрать подходящую."
    if guests:
        intro = f"Для {guests} гостей можно подобрать несколько вариантов беседок."
    text = (
        f"{intro}\n\n"
        "Коротко по вариантам:\n"
        "- небольшая: беседка №5, до 10 человек, компактная, с мангалом;\n"
        "- простые: №2, №4, №6, обычно для компаний до 15 человек;\n"
        "- комфортнее: №3, №8 или крытая беседка — больше подходят для вечера, света и розеток;\n"
        "- большая: №1, если компания крупная или праздник.\n\n"
        "Что вам важнее: простая с мангалом, со светом/розетками, крытая или конкретный номер?"
    )
    if not guests:
        text += "\n\nНапишите, пожалуйста, сколько вас будет человек — я подскажу самый подходящий вариант."
    return text


def _normalize_gazebo_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def _gazebo_title_from_slot(slot: str) -> str:
    return str(slot).split(":", 1)[0].strip()


def _available_gazebo_titles(form_data: dict[str, Any]) -> list[str]:
    raw = form_data.get("last_available_gazebo_variants") or []
    if not isinstance(raw, list):
        return []
    titles: list[str] = []
    seen: set[str] = set()
    for item in raw:
        title = str(item or "").strip()
        key = _normalize_gazebo_title(title)
        if title and key not in seen:
            titles.append(title)
            seen.add(key)
    return titles


def _available_gazebo_variant_configs(form_data: dict[str, Any]) -> list[dict[str, Any]] | None:
    if form_data.get("service_type") != "gazebo":
        return None
    titles = _available_gazebo_titles(form_data)
    if not titles:
        return None
    wanted = {_normalize_gazebo_title(title) for title in titles}
    variants = (load_services_map().get("gazebo") or {}).get("variants") or []
    matched = [
        variant for variant in variants
        if _normalize_gazebo_title(variant.get("title")) in wanted
    ]
    if matched:
        return matched
    return [{"title": title} for title in titles]


def _remember_available_gazebo_variants(
    form_data: dict[str, Any],
    slots: list[str],
) -> dict[str, Any]:
    updated = form_data.copy()
    if updated.get("service_type") != "gazebo" or updated.get("service_variant"):
        updated.pop("last_available_gazebo_variants", None)
        return updated
    titles: list[str] = []
    seen: set[str] = set()
    for slot in slots:
        title = _gazebo_title_from_slot(slot)
        key = _normalize_gazebo_title(title)
        if title and key not in seen:
            titles.append(title)
            seen.add(key)
    if titles:
        updated["last_available_gazebo_variants"] = titles
    return updated


def _auto_select_single_available_gazebo(form_data: dict[str, Any]) -> dict[str, Any]:
    if form_data.get("service_type") != "gazebo" or form_data.get("service_variant"):
        return form_data
    titles = _available_gazebo_titles(form_data)
    if len(titles) != 1:
        return form_data
    return {
        **form_data,
        "service_variant": titles[0],
        "single_available_gazebo_variant_auto": True,
    }


def _clear_available_gazebo_variants(form_data: dict[str, Any]) -> dict[str, Any]:
    updated = form_data.copy()
    updated.pop("last_available_gazebo_variants", None)
    updated.pop("single_available_gazebo_variant_auto", None)
    return updated


def _format_gazebo_variant_line(variant: dict[str, Any]) -> str:
    title = str(variant.get("title") or "Беседка").strip()
    capacity = variant.get("capacity_max")
    price = variant.get("price")
    description_by_title = {
        "беседка №1": "просторная, для больших компаний и праздников",
        "беседка №2": "простая, с мангалом, без света и розеток",
        "беседка №3": "со светом, розетками, шторами/мягкими стеклами и мангалом",
        "беседка №4": "простая, с мангалом, без света и розеток",
        "беседка №5": "компактная, с мангалом",
        "беседка №6": "простая, с мангалом",
        "беседка №8": "полуоткрытая, со светом, розетками и мангалом",
        "крытая беседка": "со светом, розетками, шторами/мягкими стеклами и мангалом",
    }
    parts = [title]
    if capacity:
        parts.append(f"до {capacity} человек")
    if price:
        parts.append(f"{price} ₽")
    description = description_by_title.get(_normalize_gazebo_title(title))
    if description:
        parts.append(description)
    return title if len(parts) == 1 else f"{parts[0]}: {', '.join(parts[1:])}"


def _selected_variant_config(form_data: dict[str, Any]) -> dict[str, Any]:
    service_type = form_data.get("service_type")
    config = load_services_map().get(service_type) or {}
    variants = config.get("variants") or []
    available = _available_gazebo_variant_configs(form_data)
    if service_type == "gazebo" and available:
        variants = available
    variant_name = str(form_data.get("service_variant") or "").lower().replace("ё", "е")
    for variant in config.get("variants") or []:
        title = str(variant.get("title") or "").lower().replace("ё", "е")
        if title and title in variant_name:
            return variant
    if variants and service_type != "gazebo":
        duration_minutes = _duration_minutes_value(form_data.get("duration"))
        weekday = None
        if form_data.get("date"):
            try:
                weekday = datetime.fromisoformat(str(form_data["date"])).weekday()
            except ValueError:
                weekday = None
        candidates = []
        for variant in variants:
            variant_duration = variant.get("duration_minutes")
            if duration_minutes and variant_duration and int(variant_duration) != int(duration_minutes):
                continue
            weekdays = variant.get("weekdays")
            if weekdays and weekday is not None and weekday not in weekdays:
                continue
            candidates.append(variant)
        if candidates:
            return candidates[0]
    if service_type == "gazebo" and "крыт" in variant_name:
        for variant in config.get("variants") or []:
            if "крыт" in str(variant.get("title") or "").lower().replace("ё", "е"):
                return variant
    if service_type == "gazebo" and variants:
        guests = int(form_data.get("guests_count") or 0)
        if "больш" in variant_name or guests > 20:
            return max(variants, key=lambda item: int(item.get("capacity_max") or 0))
        if "прост" in variant_name or "мангал" in variant_name:
            for variant in variants:
                title = str(variant.get("title") or "").lower()
                if "№2" in title:
                    return variant
        if "свет" in variant_name or "розет" in variant_name:
            for variant in variants:
                title = str(variant.get("title") or "").lower()
                if "крыт" in title:
                    return variant
        if guests:
            suitable = [
                item for item in variants
                if int(item.get("capacity_max") or 0) >= guests
            ]
            if suitable:
                return min(suitable, key=lambda item: int(item.get("capacity_max") or 9999))
    return config


def _normalize_gazebo_variant(form_data: dict[str, Any]) -> dict[str, Any]:
    if form_data.get("service_type") != "gazebo":
        return form_data
    if form_data.get("service_variant"):
        return form_data
    guests = int(form_data.get("guests_count") or 0)
    if guests > 20:
        return {**form_data, "service_variant": "Беседка №1"}
    return form_data


def _booking_ready(form_data: dict[str, Any]) -> bool:
    next_key, _ = next_question(form_data)
    if next_key is not None:
        return False
    return _valid_phone(form_data.get("phone"))


def _confirmation_text(form_data: dict[str, Any]) -> str:
    title = (load_services_map().get(form_data.get("service_type")) or {}).get("title") or "объект"
    variant = form_data.get("service_variant")
    object_text = f"{title}, {variant}" if variant else title
    duration = form_data.get("duration")
    return (
        f"Данные собраны: {object_text}, {_format_date_ru(form_data.get('date'))}, "
        f"с {form_data.get('time')} на {duration} ч, гостей: {form_data.get('guests_count')}, "
        f"формат: {form_data.get('event_format')}, допы: {', '.join(form_data.get('upsell_items') or [])}, "
        f"имя: {form_data.get('client_name')}, телефон: {form_data.get('phone')}. "
        "Попроси клиента подтвердить бронь одним коротким вопросом."
    )


def _awaiting_confirmation_side_reply(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
) -> str:
    if _looks_like_info_question(text):
        price_reply = _price_reply_if_known(text, form_data)
        if price_reply:
            return price_reply
        required = (
            "Клиент задал вопрос, пока заявка ожидает финального подтверждения. "
            "Ответь на вопрос по базе знаний честно и кратко. "
            "Не повторяй всю анкету. В конце мягко напомни: если по заявке всё верно, "
            "можно подтвердить бронь словом «да», а если нужно что-то изменить — пусть напишет, что именно."
        )
        return _ai_process_reply(
            text=text,
            form_data=form_data,
            history=history,
            required_meaning=required,
        )
    return (
        "Понял. Заявка пока ожидает подтверждения. "
        "Если всё верно, напишите «да». Если нужно что-то поменять — напишите, что именно изменить."
    )


def _create_hold(conn, conversation: dict[str, Any], user: dict[str, Any], form_data: dict[str, Any], now: datetime) -> dict[str, Any]:
    settings = get_settings()
    slot_date = datetime.fromisoformat(str(form_data["date"])).date()
    slot_time = datetime.strptime(str(form_data["time"])[:5], "%H:%M").time()
    variant = _selected_variant_config(form_data)
    return slot_holds_repo.create(
        conn,
        conversation_id=conversation["id"],
        user_id=user["id"],
        service_type=form_data["service_type"],
        yclients_service_id=str(variant.get("yclients_service_id") or ""),
        slot_date=slot_date,
        slot_time=slot_time,
        duration_minutes=_duration_minutes_value(form_data.get("duration")),
        expires_at=now + timedelta(minutes=settings.hold_ttl_minutes),
    )


def _create_booking_from_hold(
    conn,
    conversation: dict[str, Any],
    user: dict[str, Any],
    form_data: dict[str, Any],
    hold: dict[str, Any],
) -> dict[str, Any]:
    return bookings_repo.create_from_hold(
        conn,
        conversation_id=conversation["id"],
        user_id=user["id"],
        slot_hold_id=hold["id"],
        service_type=hold["service_type"],
        booking_date=hold["slot_date"],
        booking_time=hold["slot_time"],
        duration_minutes=hold.get("duration_minutes"),
        client_name=str(form_data.get("client_name") or user.get("name") or "Клиент"),
        phone=str(form_data.get("phone") or user.get("phone") or ""),
        guests_count=int(form_data["guests_count"]) if form_data.get("guests_count") else None,
        event_format=form_data.get("event_format"),
        preferences=form_data.get("preferences"),
        upsell_items=list(form_data.get("upsell_items") or []),
    )


def _deterministic_patch(text: str, now: datetime) -> dict[str, Any]:
    return (
        _service_type_patch(text)
        | _service_variant_patch(text)
        | _phone_patch(text)
        | _event_format_patch(text)
        | _upsell_items_patch(text)
        | _relative_date_patch(text, now)
        | _time_period_patch(text)
    )


def _current_step_patch(text: str, expected_key: str | None, now: datetime | None = None) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if expected_key == "date":
        patch |= _bare_day_patch(text, now or _now_local(), expected_key)
    if expected_key == "guests_count":
        patch |= _guests_count_patch(text, expected_key)
    if expected_key == "service_variant":
        patch |= _service_variant_patch(text)
        patch |= _guests_count_patch(text, "guests_count")
    if expected_key == "client_name":
        patch |= _client_name_patch(text, expected_key)
    return patch


def _ai_first_patch(
    *,
    ai_result: Any,
    detected_patch: dict[str, Any],
    text: str,
    expected_key: str | None,
    now: datetime,
) -> dict[str, Any]:
    """AI decides intent first; parsers only normalize fields for that intent."""
    ai_patch = dict(getattr(ai_result, "form_data_patch", None) or {})
    action = getattr(ai_result, "action", "")
    intent = getattr(ai_result, "intent", "")
    info_like = _looks_like_info_question(text, expected_key=expected_key, now=now)
    info_intents = {
        "company_info",
        "object_selection_help",
        "price_question",
        "payment_question",
        "other",
    }
    if action == "answer_info" or (info_like and intent in info_intents):
        return ai_patch | {key: value for key, value in detected_patch.items() if key in ai_patch}
    return ai_patch | detected_patch


def _filter_new_booking_patch_to_current_message(
    patch: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    allowed: set[str] = set()
    if _service_type_patch(text):
        allowed.update({"service_type", "preferences"})
    if _service_variant_patch(text):
        allowed.add("service_variant")
    if _relative_date_patch(text, now) or _bare_day_patch(text, now, "date") or _has_date_signal(text):
        allowed.add("date")
    if _time_period_patch(text):
        allowed.update({"time", "duration"})
    if _duration_from_text(text) is not None:
        allowed.add("duration")
    if _guests_count_patch(text, "guests_count"):
        allowed.add("guests_count")
    if _event_format_patch(text):
        allowed.add("event_format")
    if _upsell_items_patch(text):
        allowed.add("upsell_items")
    if _phone_patch(text):
        allowed.add("phone")
    return {key: value for key, value in patch.items() if key in allowed}


def _fast_entry_reply(conn, text: str, form_data: dict[str, Any], now: datetime) -> tuple[str, str, str | None, str | None, dict[str, Any]] | None:
    patch = _deterministic_patch(text, now)
    updated = merge_form_data(form_data, patch)
    if updated.get("service_type") != "gazebo":
        updated["service_variant"] = None

    if _is_plain_greeting(text) and not any(updated.get(key) for key in ("service_type", "date", "time", "duration")):
        return (
            "Привет! Помогу с бронированием. Что планируете: беседку, баню, дом или беседку + баня?",
            "waiting_user",
            None,
            "service_type",
            updated,
        )

    if patch.get("service_type") and not updated.get("date"):
        title = (load_services_map().get(updated.get("service_type")) or {}).get("title") or "объект"
        return (
            f"Хорошо, {title.lower()} отметил. На какую дату планируете?",
            "waiting_user",
            "date",
            "date",
            updated,
        )

    if patch.get("service_type") and updated.get("date") and not updated.get("time"):
        availability = check_availability(conn, form_data=updated, now=now)
        if availability.ok and not availability.slots:
            reply, next_key = _no_availability_reply(updated)
            return reply, "waiting_user", "awaiting_new_date", next_key, _reset_unavailable_slot(updated)
        updated = _remember_available_gazebo_variants(updated, availability.slots)
        updated = _auto_select_single_available_gazebo(updated)
        reply, next_key = _availability_reply(availability.message, availability.slots, updated)
        return reply, "waiting_user", next_key, next_key, updated

    return None


def handle_incoming(message: IncomingMessage) -> str:
    settings = get_settings()
    tz = ZoneInfo(settings.app_timezone)
    now = _effective_message_time(message.message_time, tz)

    with get_connection() as conn:
        user, user_created = get_or_create_user(
            conn,
            channel=message.channel,
            external_id=message.external_user_id,
            name=message.user_name,
            seen_at=now,
        )
        conversation, conv_created = get_or_create_conversation(
            conn,
            user_id=user["id"],
            channel=message.channel,
            now=now,
            ttl_hours=settings.session_ttl_hours,
        )
        if conv_created:
            seeded_form_data = _seed_form_data_from_user(
                conversation.get("form_data") or {},
                user,
            )
            if seeded_form_data != (conversation.get("form_data") or {}):
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    form_data=seeded_form_data,
                )
                conversation = {**conversation, "form_data": seeded_form_data}

        messages_repo.create(
            conn,
            conversation_id=conversation["id"],
            sender=SENDER_USER,
            text=message.text,
            raw_payload=message.raw_payload,
        )
        history = messages_repo.list_recent(conn, conversation["id"], limit=20)

        if _handoff_active(user, now):
            reply = _handoff_reply()
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=reply,
            )
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                status="handoff",
                current_step="handoff",
                next_step="handoff",
                form_data=conversation.get("form_data") or {},
            )
            return reply

        if _looks_like_handoff_needed(message.text):
            _start_user_handoff(
                conn,
                user=user,
                conversation_id=conversation["id"],
                text=message.text,
                now=now,
            )
            reply = _handoff_reply()
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=reply,
            )
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                status="handoff",
                current_step="handoff",
                next_step="handoff",
                form_data=conversation.get("form_data") or {},
            )
            return reply

        form_data_snapshot = conversation.get("form_data") or {}
        current_expected_key = next_question(form_data_snapshot)[0]
        pending_date_confirmation = form_data_snapshot.get("pending_date_confirmation") or {}
        pending_date = pending_date_confirmation.get("date")
        if current_expected_key == "date" and pending_date:
            if _confirmation_yes(message.text):
                form_data = {**form_data_snapshot, "date": pending_date}
                form_data.pop("pending_date_confirmation", None)
                availability = check_availability(conn, form_data=form_data, now=now)
                if availability.ok and not availability.slots:
                    required, next_key = _no_availability_reply(form_data)
                    remember_waitlist_request(
                        conn,
                        conversation_id=conversation["id"],
                        user_id=user["id"],
                        form_data=form_data,
                    )
                    required = _append_waitlist_offer(required)
                    form_data = _reset_unavailable_slot(form_data)
                    current_step = "awaiting_new_date"
                else:
                    form_data = _remember_available_gazebo_variants(form_data, availability.slots)
                    form_data = _auto_select_single_available_gazebo(form_data)
                    required, next_key = _availability_reply(
                        availability.message,
                        availability.slots,
                        form_data,
                    )
                    current_step = next_key
                try:
                    reply = _ai_process_reply(
                        text=message.text,
                        form_data=form_data,
                        history=history,
                        required_meaning=required,
                    )
                except AIProviderUnavailable:
                    reply = required
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    intent=conversation.get("intent") or "booking_request",
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
            if _confirmation_no(message.text):
                form_data = dict(form_data_snapshot)
                form_data.pop("pending_date_confirmation", None)
                reply = "Хорошо, напишите нужную дату."
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    current_step="date",
                    next_step="date",
                    form_data=form_data,
                )
                return reply
        weekday_confirmation = (
            _bare_weekday_confirmation(message.text, now)
            if current_expected_key == "date"
            else None
        )
        if weekday_confirmation:
            weekday_candidate = _bare_weekday_candidate(message.text, now)
            form_data = dict(form_data_snapshot)
            if weekday_candidate:
                _, date_value = weekday_candidate
                form_data["pending_date_confirmation"] = {
                    "date": date_value.isoformat(),
                    "source_text": message.text,
                }
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=weekday_confirmation,
            )
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                status="waiting_user",
                current_step="date",
                next_step="date",
                form_data=form_data,
            )
            return weekday_confirmation

        started_new_booking = False
        hold_command = _handle_reserved_hold_command(conn, conversation, message.text, now)
        if hold_command is not None:
            reply, status, current_step, next_key, form_data = hold_command
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=reply,
            )
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                status=status,
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
            return reply

        post_booking = _handle_post_booking_message(
            conn,
            conversation,
            message.text,
            history,
            now,
        )
        if post_booking is not None:
            reply, status, current_step, next_key, form_data = post_booking
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=reply,
            )
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                status=status,
                intent="post_booking",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
            return reply

        if conversation.get("current_step") == "awaiting_confirmation":
            form_data = conversation.get("form_data") or {}
            if _confirmation_yes(message.text):
                availability = check_availability(conn, form_data=form_data, now=now)
                if availability.ok and availability.slots:
                    hold = _create_hold(conn, conversation, user, form_data, now)
                    active_holds = slot_holds_repo.list_active_for_conversation(
                        conn,
                        conversation_id=conversation["id"],
                        now=now,
                    )
                    settings = get_settings()
                    reply = (
                        f"Отлично, предварительно зарезервировал выбранный вариант на "
                        f"{settings.hold_ttl_minutes} минут.\n\n"
                        f"{_format_hold_summary(active_holds, form_data)}"
                    )
                    try:
                        payment = create_payment_link_for_holds(
                            conn,
                            conversation_id=conversation["id"],
                            user_id=user["id"],
                            hold_ids=[hold["id"]],
                            client_name=str(form_data.get("client_name") or user.get("name") or "Клиент"),
                            phone=str(form_data.get("phone") or user.get("phone") or ""),
                        )
                    except Exception:
                        logger.exception("Payment link creation failed conversation_id=%s", conversation["id"])
                        payment = None
                    reply = f"{reply}\n\n{_payment_reply_text(payment)}"
                    status = "reserved"
                    current_step = "reserved"
                    next_key = "payment_status"
                else:
                    remember_waitlist_request(
                        conn,
                        conversation_id=conversation["id"],
                        user_id=user["id"],
                        form_data=form_data,
                    )
                    reply = (
                        "Пока подтверждали, дата уже стала недоступна. "
                        "Напишите, пожалуйста, другую дату — проверю заново.\n\n"
                        "Я запомнила этот запрос: если место освободится из-за отмены, мы сможем вас уведомить."
                    )
                    status = "waiting_user"
                    current_step = "awaiting_new_date"
                    next_key = "date"
                    form_data = _reset_unavailable_slot(form_data)
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status=status,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
            if _confirmation_no(message.text):
                reply = "Хорошо, что нужно изменить: дату, время, беседку, гостей или телефон?"
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    current_step="change_booking",
                    next_step=None,
                    form_data=form_data,
                )
                return reply
            try:
                reply = _awaiting_confirmation_side_reply(
                    text=message.text,
                    form_data=form_data,
                    history=history,
                )
            except AIProviderUnavailable as exc:
                _log_ai_provider_unavailable(
                    conn,
                    conversation_id=conversation["id"],
                    exc=exc,
                    text=message.text,
                    form_data=form_data,
                )
                reply = (
                    "Заявка пока ожидает подтверждения. "
                    "Если всё верно, напишите «да». Если нужно что-то поменять — напишите, что именно изменить."
                )
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=reply,
            )
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                status="awaiting_confirmation",
                intent="confirmation_side_question",
                current_step="awaiting_confirmation",
                next_step="confirmation",
                form_data=form_data,
            )
            return reply

        if conversation.get("current_step") == "reserved" and _wants_additional_booking(message.text):
            conversation = {
                **conversation,
                "form_data": _new_booking_form_data(conversation.get("form_data") or {}),
                "current_step": None,
                "next_step": None,
                "status": "waiting_user",
            }
            started_new_booking = True

        hold_command = _handle_reserved_hold_command(conn, conversation, message.text, now)
        if hold_command is not None:
            reply, status, current_step, next_key, form_data = hold_command
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=reply,
            )
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                status=status,
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
            return reply

        if (
            conversation.get("current_step") == "awaiting_new_date"
            and not _has_date_signal(message.text)
            and not _looks_like_info_question(message.text, now=now)
        ):
            form_data = conversation.get("form_data") or {}
            reply = "Напишите, пожалуйста, другую дату — сначала проверю свободное время."
            next_key = "date"
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=reply,
            )
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                status="waiting_user",
                current_step="awaiting_new_date",
                next_step=next_key,
                form_data=form_data,
            )
            return reply

        current_form_data = conversation.get("form_data") or {}
        expected_key_before = next_question(current_form_data)[0]
        if expected_key_before == "upsell_items" and _is_upsell_negative(message.text):
            offer_count = int(current_form_data.get("upsell_offer_count") or 0)
            if offer_count < 1:
                form_data = {**current_form_data, "upsell_offer_count": offer_count + 1}
                reply = _upsell_push_reply(form_data)
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    current_step="upsell_items",
                    next_step="upsell_items",
                    form_data=form_data,
                )
                return reply
        if expected_key_before == "upsell_items":
            upsell_patch = _upsell_items_patch(message.text)
            selected_items = upsell_patch.get("upsell_items") or []
            if selected_items and selected_items != ["не нужны"]:
                form_data = merge_form_data(
                    current_form_data,
                    upsell_patch | {"upsell_offer_count": int(current_form_data.get("upsell_offer_count") or 0)},
                )
                next_key, question = next_question(form_data)
                items_text = ", ".join(selected_items)
                if next_key is None:
                    reply = _confirmation_reply_text(form_data)
                    status = "awaiting_confirmation"
                    current_step = "awaiting_confirmation"
                    next_step = "confirmation"
                else:
                    reply = f"Хорошо, {items_text} добавим ✅\n\n{question}"
                    status = "waiting_user"
                    current_step = next_key
                    next_step = next_key
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status=status,
                    current_step=current_step,
                    next_step=next_step,
                    form_data=form_data,
                )
                return reply
        early_patch = _deterministic_patch(message.text, now) | _current_step_patch(
            message.text,
            expected_key_before,
            now,
        )

        summaries = _context_summaries(
            conn,
            conversation,
            conversation.get("form_data") or {},
            now,
        )
        deterministic_patch = early_patch
        try:
            ai_result = call_ai(
                text=message.text,
                form_data=conversation.get("form_data") or {},
                history=history,
                summaries=summaries,
                current_datetime=now,
                knowledge=load_knowledge(),
            )
            time_patch = _time_period_patch(message.text)
            if _period_conflict(message.text, time_patch):
                form_data = conversation.get("form_data") or {}
                required = (
                    "Клиент указал противоречивый период и длительность: по времени получается "
                    "другая длительность. Вежливо уточни: бронировать указанную длительность "
                    "или период до указанного времени?"
                )
                reply = _ai_process_reply(
                    text=message.text,
                    form_data=form_data,
                    history=messages_repo.list_recent(conn, conversation["id"], limit=20),
                    required_meaning=required,
                )
                next_key = "duration"
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    intent=ai_result.intent,
                    current_step="clarify_period",
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply

            patch = _ai_first_patch(
                ai_result=ai_result,
                detected_patch=deterministic_patch,
                text=message.text,
                expected_key=expected_key_before,
                now=now,
            )
            if started_new_booking:
                patch = _filter_new_booking_patch_to_current_message(patch, message.text, now)
            deterministic_patch = {
                key: value
                for key, value in deterministic_patch.items()
                if key in patch and patch.get(key) == value
            }
            if (
                expected_key_before == "upsell_items"
                and "upsell_items" in patch
                and "upsell_items" not in deterministic_patch
                and not _has_upsell_signal(message.text)
            ):
                patch.pop("upsell_items", None)
            if (
                expected_key_before == "upsell_items"
                and "client_name" not in patch
                and not (conversation.get("form_data") or {}).get("client_name")
                and _looks_like_name(message.text)
            ):
                patch["client_name"] = message.text.strip().title()
            changed_fields = set(ai_result.changed_fields) | set(patch.keys())
            if conversation.get("current_step") == "awaiting_new_date":
                patch = _apply_previous_period_for_new_date(
                    conversation.get("form_data") or {},
                    patch,
                )
                changed_fields |= set(patch.keys())
            form_data = merge_form_data(
                conversation.get("form_data") or {},
                patch,
            )
            if "date" in patch:
                form_data.pop("pending_date_confirmation", None)
            form_data = _normalize_service_aliases(form_data)
            if form_data.get("service_type") and form_data.get("service_type") not in load_services_map():
                required = (
                    f"Автоматическая проверка расписания для «{form_data.get('service_type')}» пока не подключена.\n\n"
                    "Я могу проверить обычные беседки, крытую беседку, баню с бассейном или гостевой дом. Что выбираем?"
                )
                reply = _ai_process_reply(
                    text=message.text,
                    form_data=form_data,
                    history=history,
                    required_meaning=required,
                )
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    intent=ai_result.intent,
                    current_step="service_type",
                    next_step="service_type",
                    form_data=form_data,
                )
                return reply
            if form_data.get("service_type") != "gazebo":
                form_data["service_variant"] = None
                form_data.pop("last_available_gazebo_variants", None)
                form_data.pop("single_available_gazebo_variant_auto", None)
            if {"service_type", "service_variant", "date", "time", "duration"} & changed_fields:
                form_data.pop("last_available_gazebo_variants", None)
                form_data.pop("single_available_gazebo_variant_auto", None)
            form_data = _normalize_gazebo_variant(form_data)
            if (
                "service_type" in changed_fields
                and form_data.get("service_type") == "gazebo"
                and not form_data.get("date")
                and not _asks_gazebo_options(message.text)
            ):
                if started_new_booking:
                    required = (
                        "Начни без приветствия. Подтверди, что оформляем вторую бронь на беседку. "
                        "Скажи, что имя и телефон уже есть, повторно их спрашивать не нужно. "
                        "Задай один вопрос: на какую дату нужна беседка. Не перечисляй варианты беседок сейчас."
                    )
                else:
                    followup = ""
                    if "бан" in str(form_data.get("preferences") or "").lower():
                        followup = " Скажи, что баню оформим второй отдельной бронью после беседки."
                    required = (
                        "Коротко поздоровайся, если клиент поздоровался. Подтверди, что беседку понял, "
                        "и задай один вопрос: на какую дату планируют отдых. Не перечисляй варианты беседок сейчас."
                        f"{followup}"
                    )
                reply = _ai_process_reply(
                    text=message.text,
                    form_data=form_data,
                    history=history,
                    required_meaning=required,
                )
                next_key = "date"
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    intent=ai_result.intent,
                    current_step="date",
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
            if "phone" in changed_fields and form_data.get("phone") and not _valid_phone(form_data.get("phone")):
                form_data["phone"] = None
                required = (
                    "Телефон получился слишком коротким или некорректным. "
                    "Попроси клиента прислать полный номер телефона для бронирования."
                )
                reply = _ai_process_reply(
                    text=message.text,
                    form_data=form_data,
                    history=history,
                    required_meaning=required,
                )
                next_key = "phone"
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    intent=ai_result.intent,
                    current_step="phone",
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
            if (
                form_data.get("service_type") == "gazebo"
                and form_data.get("service_variant")
                and form_data.get("single_available_gazebo_variant_auto")
                and "guests_count" in changed_fields
                and not form_data.get("time")
            ):
                required = (
                    f"{form_data.get('guests_count')} гостей для {form_data.get('service_variant')} подходит. "
                    "Не предлагай другие беседки, потому что по проверке свободен только этот вариант. "
                    "Задай один следующий вопрос: во сколько хотят приехать. Можно мягко подсказать, что можно сразу написать период, например с 18:00 до 00:00."
                )
                reply = _ai_process_reply(
                    text=message.text,
                    form_data=form_data,
                    history=history,
                    required_meaning=required,
                )
                next_key = "time"
                status = "waiting_user"
                intent = ai_result.intent
                current_step = "time"
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
            if (
                form_data.get("service_type") == "gazebo"
                and not form_data.get("service_variant")
                and "service_type" in changed_fields
            ):
                required = _gazebo_selection_text(form_data)
                reply = _ai_process_reply(
                    text=message.text,
                    form_data=form_data,
                    history=history,
                    required_meaning=required,
                )
                next_key = "service_variant"
                status = "waiting_user"
                intent = ai_result.intent
                current_step = "service_variant"
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
            expected_key_now = next_question(form_data)[0]
            if (
                ai_result.action == "answer_info"
                or (
                    (
                        _looks_like_info_question(
                            message.text,
                            expected_key=expected_key_now,
                            now=now,
                        )
                        or (
                            form_data.get("service_type") == "gazebo"
                            and _asks_gazebo_options(message.text)
                        )
                    )
                    and not {"service_type", "date", "time", "duration"} & changed_fields
                )
            ):
                reply, next_key = _answer_info_during_form(
                    text=message.text,
                    form_data=form_data,
                    history=history,
                    ai_result=ai_result,
                )
                status = "waiting_user"
                intent = ai_result.intent
                current_step = expected_key_now or conversation.get("current_step") or ai_result.current_step
                if _booking_ready(form_data):
                    if "напишите «да»" not in reply and 'напишите "да"' not in reply:
                        reply = (
                            f"{reply}\n\n"
                            "Если по заявке всё верно, напишите «да». "
                            "Если нужно что-то изменить — напишите, что именно."
                        )
                    status = "awaiting_confirmation"
                    current_step = "awaiting_confirmation"
                    next_key = "confirmation"
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
            last_unavailable = (conversation.get("form_data") or {}).get("last_unavailable") or {}
            if (
                conversation.get("current_step") == "awaiting_new_date"
                and form_data.get("date")
                and form_data.get("date") == last_unavailable.get("date")
                and not {"time", "duration"} & changed_fields
                and not _asks_for_free_slots(message.text)
            ):
                required, next_key = _same_unavailable_date_reply(form_data)
                form_data = _clear_active_slot_keep_last(form_data)
                reply = _ai_process_reply(
                    text=message.text,
                    form_data=form_data,
                    history=history,
                    required_meaning=required,
                )
                status = "waiting_user"
                intent = ai_result.intent
                current_step = "awaiting_new_date"
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
            if _should_check_availability(
                ai_result.action,
                list(changed_fields),
                form_data,
            ):
                availability = check_availability(conn, form_data=form_data, now=now)
                if availability.ok and not availability.slots:
                    required, next_key = _no_availability_reply(form_data)
                    remember_waitlist_request(
                        conn,
                        conversation_id=conversation["id"],
                        user_id=user["id"],
                        form_data=form_data,
                    )
                    required = _append_waitlist_offer(required)
                    form_data = _reset_unavailable_slot(form_data)
                    reply = _ai_process_reply(
                        text=message.text,
                        form_data=form_data,
                        history=history,
                        required_meaning=required,
                    )
                    current_step = "awaiting_new_date"
                else:
                    form_data = _remember_available_gazebo_variants(form_data, availability.slots)
                    form_data = _auto_select_single_available_gazebo(form_data)
                    required, next_key = _availability_reply(
                        availability.message,
                        availability.slots,
                        form_data,
                    )
                    reply = _ai_process_reply(
                        text=message.text,
                        form_data=form_data,
                        history=history,
                        required_meaning=required,
                    )
                    current_step = next_key
            else:
                reply, next_key = _build_reply(
                    ai_result.reply_to_user,
                    ai_result.action,
                    form_data,
                )
                reply, next_key = _safe_reply_without_availability_claim(
                    reply,
                    form_data,
                )
                if reply != ai_result.reply_to_user:
                    reply = _ai_process_reply(
                        text=message.text,
                        form_data=form_data,
                        history=history,
                        required_meaning=reply,
                    )
            if ai_result.handoff_to_human:
                _start_user_handoff(
                    conn,
                    user=user,
                    conversation_id=conversation["id"],
                    text=message.text,
                    now=now,
                    reason=ai_result.handoff_reason or "AI определил, что нужен живой ответ",
                )
                reply = reply or _handoff_reply()
            status = "handoff" if ai_result.handoff_to_human else "waiting_user"
            intent = ai_result.intent
            current_step = locals().get("current_step", ai_result.current_step)
            if (
                _booking_ready(form_data)
                and current_step not in {"awaiting_confirmation", "reserved"}
                and conversation.get("current_step") != "reserved"
                and conversation.get("status") not in {"reserved", "payment_paid"}
            ):
                reply = _confirmation_reply_text(form_data)
                status = "awaiting_confirmation"
                current_step = "awaiting_confirmation"
                next_key = "confirmation"
        except AIProviderUnavailable as exc:
            logger.exception("AI provider unavailable conversation_id=%s", conversation["id"])
            expected_key_before = next_question(conversation.get("form_data") or {})[0]
            deterministic_patch = deterministic_patch | _current_step_patch(message.text, expected_key_before, now)
            form_data = merge_form_data(
                conversation.get("form_data") or {},
                deterministic_patch,
            )
            if "date" in deterministic_patch:
                form_data.pop("pending_date_confirmation", None)
            if form_data.get("service_type") != "gazebo":
                form_data["service_variant"] = None
                form_data.pop("single_available_gazebo_variant_auto", None)
            form_data = _normalize_gazebo_variant(form_data)
            _log_ai_provider_unavailable(
                conn,
                conversation_id=conversation["id"],
                exc=exc,
                text=message.text,
                form_data=form_data,
            )
            changed_fields = set(deterministic_patch.keys())
            if _should_check_availability("ask_next_question", list(changed_fields), form_data):
                availability = check_availability(conn, form_data=form_data, now=now)
                if availability.ok and not availability.slots:
                    reply, next_key = _no_availability_reply(form_data)
                    remember_waitlist_request(
                        conn,
                        conversation_id=conversation["id"],
                        user_id=user["id"],
                        form_data=form_data,
                    )
                    reply = _append_waitlist_offer(reply)
                    form_data = _reset_unavailable_slot(form_data)
                    current_step = "awaiting_new_date"
                else:
                    form_data = _remember_available_gazebo_variants(form_data, availability.slots)
                    form_data = _auto_select_single_available_gazebo(form_data)
                    reply, next_key = _availability_reply(
                        availability.message,
                        availability.slots,
                        form_data,
                    )
                    current_step = next_key
            else:
                reply, next_key = _fallback_reply(form_data)
                current_step = next_key
            status = "waiting_user"
            intent = conversation.get("intent")
            if (
                _booking_ready(form_data)
                and conversation.get("current_step") != "reserved"
                and conversation.get("status") not in {"reserved", "payment_paid"}
            ):
                reply = _confirmation_reply_text(form_data)
                status = "awaiting_confirmation"
                current_step = "awaiting_confirmation"
                next_key = "confirmation"
        except Exception:
            logger.exception("AI processing failed conversation_id=%s", conversation["id"])
            expected_key_before = next_question(conversation.get("form_data") or {})[0]
            deterministic_patch = deterministic_patch | _current_step_patch(message.text, expected_key_before, now)
            form_data = merge_form_data(
                conversation.get("form_data") or {},
                deterministic_patch,
            )
            if "date" in deterministic_patch:
                form_data.pop("pending_date_confirmation", None)
            changed_fields = set(deterministic_patch.keys())
            if _should_check_availability("ask_next_question", list(changed_fields), form_data):
                availability = check_availability(conn, form_data=form_data, now=now)
                if availability.ok and not availability.slots:
                    required, next_key = _no_availability_reply(form_data)
                    remember_waitlist_request(
                        conn,
                        conversation_id=conversation["id"],
                        user_id=user["id"],
                        form_data=form_data,
                    )
                    required = _append_waitlist_offer(required)
                    form_data = _reset_unavailable_slot(form_data)
                    reply = required
                    current_step = "awaiting_new_date"
                else:
                    form_data = _remember_available_gazebo_variants(form_data, availability.slots)
                    form_data = _auto_select_single_available_gazebo(form_data)
                    reply, next_key = _availability_reply(
                        availability.message,
                        availability.slots,
                        form_data,
                    )
                    current_step = next_key
            else:
                reply, next_key = _fallback_reply(form_data)
                current_step = next_key
            status = "waiting_user"
            intent = conversation.get("intent")
            if (
                _booking_ready(form_data)
                and conversation.get("current_step") != "reserved"
                and conversation.get("status") not in {"reserved", "payment_paid"}
            ):
                reply = _confirmation_reply_text(form_data)
                status = "awaiting_confirmation"
                current_step = "awaiting_confirmation"
                next_key = "confirmation"

        reply = _remove_date_question_when_guest_question_exists(_clean_reply(reply))
        if next_key and current_step in {None, "service_type"} and form_data.get("service_type"):
            current_step = next_key
        messages_repo.create(
            conn,
            conversation_id=conversation["id"],
            sender=SENDER_ASSISTANT,
            text=reply,
        )
        _persist_user_profile(conn, user_id=user["id"], form_data=form_data)

        conversations_repo.update_after_message(
            conn,
            conversation["id"],
            now,
            status=status,
            intent=intent,
            current_step=current_step,
            next_step=next_key,
            form_data=form_data,
        )

    logger.info(
        "Handled message user_id=%s conversation_id=%s new_user=%s new_conv=%s",
        user["id"],
        conversation["id"],
        user_created,
        conv_created,
    )
    return reply
