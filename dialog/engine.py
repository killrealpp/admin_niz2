from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from app.ai.confirmation import is_positive_confirmation
from app.ai.parser import decide
from app.ai.response_sanitizer import sanitize_reply
from app.core.dates import now_local
from app.data.services import normalize_service_type, service_title
from app.dialog.availability import check_availability
from app.dialog.dialog_guard import next_step_question, GuardResult
from app.dialog.payment import create_prepayment
from app.dialog.state import BookingDraft, AdminDecision
from app.storage import sqlite


logger = logging.getLogger(__name__)

_LAST_REQUESTED_MEDIA_BY_CHAT: dict[str, list[str]] = {}


def pop_requested_media(chat_id: str) -> list[str]:
    return _LAST_REQUESTED_MEDIA_BY_CHAT.pop(str(chat_id), [])


def _store_requested_media(chat_id: str, requested_media: list[str] | None) -> None:
    if requested_media:
        _LAST_REQUESTED_MEDIA_BY_CHAT[str(chat_id)] = [str(item) for item in requested_media if item]
    else:
        _LAST_REQUESTED_MEDIA_BY_CHAT.pop(str(chat_id), None)


_BATHHOUSE_CAPACITY = 10


class DialogBlocked(Exception):
    pass


def handle_text(chat_id: str, user_name: str, text: str) -> str:
    logger.info("=== JSON_ENGINE HANDLE_TEXT START === chat_id=%s text=%r", chat_id, text)

    draft = BookingDraft.from_dict(sqlite.load_draft(chat_id))
    logger.info("DRAFT BEFORE: %s", _draft_log_line(draft))

    if _is_hard_reset(text):
        draft = BookingDraft()
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return "Начнём заново. " + _fallback_question(draft)

    if _is_abusive_only(text):
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return "Давайте без грубости. " + _fallback_question(draft)

    guard = GuardResult(False)
    if guard.handled:
        if guard.draft_patch:
            _apply_patch(draft, guard.draft_patch, from_user_edit=True)
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        logger.info("DRAFT AFTER GUARD: %s", _draft_log_line(draft))
        return sanitize_reply(guard.text or _fallback_question(draft))

    history = sqlite.list_recent_messages(chat_id, limit=12)
    today = now_local().date().isoformat()

    if draft.phone and not _is_valid_phone(draft.phone):
        draft.phone = None
        draft.status = "active"
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return "Номер телефона введён не полностью — должно быть 11 цифр. Проверьте и напишите ещё раз."

    if draft.phone and _is_valid_phone(draft.phone):
        draft.phone = _format_phone(draft.phone)

    if draft.ready_for_confirmation():
        if is_positive_confirmation(text, draft):
            return _create_payment_or_admin_handoff(chat_id, draft)

    if draft.status == "waiting_payment" and not is_positive_confirmation(text, draft):
        draft.status = "active"
        draft.payment_id = None
        draft.payment_url = None

    llm_text = text
    if draft.service_type and any(word in text.lower() for word in ["не обязательно", "другой вариант", "другие", "не только", "или"]):
        llm_text = f"{text} (клиент не хочет {draft.service_type}, предложи другие типы объектов: дом, баня, тёплая беседка)"

    decision = decide(llm_text, draft, today=today, history=history)
    _store_requested_media(chat_id, decision.requested_media)
    before_patch = BookingDraft.from_dict(draft.to_dict())
    _apply_patch(draft, decision.fields_patch)
    logger.info("DRAFT PROPOSED: %s", _draft_log_line(draft))

    invalid_reply = _validate_business_rules(before_patch, draft)
    if invalid_reply:
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(invalid_reply)

    availability_reply = _maybe_check_availability(chat_id, before_patch, draft)
    if availability_reply:
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(availability_reply)

    if draft.ready_for_confirmation() and decision.ready_for_confirmation:
        reply = _booking_summary(draft)
    else:
        reply = decision.reply or _fallback_question(draft)

    reply = sanitize_reply(reply, fallback=_fallback_question(draft))
    sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
    logger.info("DRAFT SAVED: %s", _draft_log_line(draft))
    return reply

def _is_valid_phone(phone: str) -> bool:
    return len(re.sub(r"\D", "", phone)) == 11


def _format_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits[0] == "8":
        return "+7" + digits[1:]
    if len(digits) == 11 and digits[0] == "7":
        return "+" + digits
    return phone


def _apply_patch(draft: BookingDraft, patch: dict[str, Any] | None, *, from_user_edit: bool = False) -> None:
    if not patch:
        return
    if from_user_edit and draft.ready_for_confirmation():
        draft.status = "active"
        draft.payment_id = None
        draft.payment_url = None
    aliases = {"guests": "guests_count", "variant": "service_variant", "format": "event_format", "name": "client_name"}
    allowed = set(BookingDraft.__dataclass_fields__)
    for raw_key, raw_value in patch.items():
        key = aliases.get(raw_key, raw_key)
        if key not in allowed:
            continue
        value = raw_value
        if key == "service_type":
            value = normalize_service_type(str(value)) if value else None
            if value and value != draft.service_type:
                draft.service_variant = None
                draft.time = None
                draft.duration = None
                draft.event_format = None
                draft.upsell_items = []
                draft.upsell_done = False
        elif key == "guests_count":
            value = _to_int(value)
        elif key == "duration":
            value = _normalize_duration(value)
            if isinstance(value, (int, float)) and value > 48:
                logger.warning(f"Duration too large: {value}, ignoring")    
                continue
        elif key == "time":
            value = _normalize_time(str(value)) if value else None
        elif key == "date":
            value = _normalize_date(str(value)) if value else None
        elif key == "upsell_items":
            value = list(value or []) if isinstance(value, list) else []
        elif key == "upsell_done":
            value = bool(value)
            logger.info("UPSEL: value=%s offer_count=%s", value, draft.upsell_offer_count)
            if value and draft.upsell_offer_count == 0:
                draft.upsell_offer_count = 1
                value = False
                logger.info("UPSEL: forced second offer")
        if value in ("", [], None) and key not in ("upsell_items", "upsell_done"):
            continue
        setattr(draft, key, value)


def _validate_business_rules(before: BookingDraft, draft: BookingDraft) -> str | None:
    if draft.service_type == "bathhouse" and draft.guests_count and draft.guests_count > _BATHHOUSE_CAPACITY:
        draft.service_type = None
        draft.service_variant = None
        draft.time = None
        draft.duration = None
        return None
    return None


def _maybe_check_availability(chat_id: str, before: BookingDraft, draft: BookingDraft) -> str | None:
    changed_keys = []
    for key in ("service_type", "service_variant", "date", "time", "duration", "guests_count"):
        if getattr(before, key) != getattr(draft, key):
            changed_keys.append(key)
    if not changed_keys:
        return None
    if not draft.service_type or not draft.date:
        return None
    if draft.service_type in {"bathhouse", "house"} and not draft.duration:
        return None
    try:
        availability = check_availability(draft, chat_id=chat_id)
    except Exception as exc:
        logger.warning("Availability check failed: %s", exc)
        return None
    
    if not availability.ok:
        draft.available_variants = availability.variants
        return None
    
    if availability.variants:
        draft.available_variants = availability.variants
    
    return None


def _ensure_next_step(reply: str, before: BookingDraft, draft: BookingDraft) -> str:
    question = next_step_question(draft)
    if not question:
        return reply
    if reply.rstrip().endswith("?"):
        return reply
    lowered = reply.lower().replace("ё", "е")
    key_words = {"date": ("дат", "числ", "когда"), "guests_count": ("сколько", "человек", "гостей"), "service_variant": ("какую", "вариант", "бесед"), "time": ("время", "во сколько", "старт"), "duration": ("сколько часов", "на сколько", "час"), "event_format": ("формат", "повод", "отдых", "день рождения"), "upsell_items": ("доп", "уголь", "розжиг", "лед", "лёд", "кальян"), "client_name": ("имя", "как вас", "записать"), "phone": ("телефон", "номер")}
    step = draft.next_step()
    if step in key_words and not any(word in lowered for word in key_words[step]):
        return f"{reply}\n\n{question[:1].upper() + question[1:]}"
        # Принудительный повтор допов если step=upsell_items и reply содержит отказ
    if step == "upsell_items" and draft.upsell_offer_count >= 2:
        return reply
    
    if step in key_words and not any(word in lowered for word in key_words[step]):
        return f"{reply}\n\n{question[:1].upper() + question[1:]}"
    return reply

def _has_refusal(reply: str) -> bool:
    lowered = reply.lower().replace("ё", "е")
    return any(word in lowered for word in ("отказ", "не надо", "не нужно", "нет", "без допов"))


def _create_payment_or_admin_handoff(chat_id: str, draft: BookingDraft) -> str:
    try:
        booking_id = sqlite.create_booking(chat_id, draft.to_dict(), status="waiting_payment")
        payment_id, payment_url = create_prepayment(draft, chat_id=chat_id, booking_id=booking_id)
        draft.payment_id = payment_id
        draft.payment_url = payment_url
        draft.status = "waiting_payment"
        sqlite.update_booking(booking_id, draft.to_dict(), status="waiting_payment")
        sqlite.save_draft(chat_id, draft.to_dict(), status="waiting_payment", current_step=draft.next_step())
        sqlite.upsert_hold(chat_id, draft.to_dict())
        return f"Отлично, бронь подготовила. Для подтверждения нужна предоплата. Ссылка на оплату:\n{payment_url}"
    except Exception as exc:
        logger.exception("Payment creation failed chat_id=%s", chat_id)
        sqlite.enqueue_admin_notification(f"Клиент подтвердил заявку, но автоматическая оплата не создалась.\nchat_id: {chat_id}\nОшибка: {exc}\nЗаявка: {draft.to_dict()}", chat_id=chat_id)
        return "Заявку собрала. Сейчас не получилось автоматически создать ссылку на оплату, передала администратору — он поможет завершить бронь."


def _booking_summary(draft: BookingDraft) -> str:
    lines = ["Проверьте, пожалуйста, заявку:"]
    lines.append(f"— Объект: {draft.service_variant or service_title(draft.service_type)}")
    lines.append(f"— Дата: {_human_date(draft.date)}")
    lines.append(f"— Время: {draft.time}")
    if isinstance(draft.duration, (int, float)):
        if draft.duration == 24:
            lines.append("— Длительность: сутки")
        elif draft.duration == int(draft.duration):
            lines.append(f"— Длительность: {int(draft.duration)} ч")
        else:
            lines.append(f"— Длительность: {draft.duration} ч")
    elif draft.duration:
        lines.append(f"— Длительность: {draft.duration}")
    else:
        lines.append("— Длительность: не указана")
    lines.append(f"— Гостей: {draft.guests_count}")
    lines.append(f"— Формат: {draft.event_format}")
    lines.append(f"— Допы: {', '.join(draft.upsell_items) if draft.upsell_items else 'без допов'}")
    lines.append(f"— Имя: {draft.client_name}")
    lines.append(f"— Телефон: {draft.phone}")
    lines.append("\nЕсли всё верно — напишите «да», и я подготовлю оплату.")
    return "\n".join(lines)


def _fallback_question(draft: BookingDraft) -> str:
    question = next_step_question(draft)
    return question[:1].upper() + question[1:] if question else "Чем могу помочь?"


def _to_int(value: Any) -> int | None:
    if isinstance(value, int): return value
    if isinstance(value, float): return int(value)
    if isinstance(value, str):
        digits = re.findall(r"\d+", value)
        if digits: return max(int(x) for x in digits)
    return None


def _normalize_duration(value: Any) -> int | float | None:
    if isinstance(value, (int, float)):
        number = int(value) if float(value).is_integer() else float(value)
        if number > 48: number = number / 60
        return int(number) if float(number).is_integer() else float(number)
    if isinstance(value, str):
        value_lower = value.lower()
        if any(word in value_lower for word in ["сутк", "день", "дня"]): return 24
        if "полтор" in value_lower: return 1.5
        match = re.search(r"\d+(?:[,.]\d+)?", value)
        if match:
            number = float(match.group(0).replace(",", "."))
            if number > 48: number = number / 60
            return int(number) if number.is_integer() else number
    return None


def _normalize_time(value: str) -> str | None:
    raw = value.strip().lower().replace(".", ":")
    match = re.search(r"(\d{1,2})[:\s]?(\d{2})?", raw)
    if not match: return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if 0 <= hour <= 23 and 0 <= minute <= 59: return f"{hour:02d}:{minute:02d}"
    return None


def _normalize_date(value: str) -> str | None:
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value): return value
    return None


def _human_date(value: str | None) -> str:
    if not value: return "не указана"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    months = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня", 7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"}
    return f"{dt.day} {months[dt.month]} {dt.year}"


def _is_hard_reset(text: str) -> bool:
    lowered = text.lower().replace("ё", "е").strip()
    return lowered == "/start" or lowered in {"заново", "начать заново", "по новой", "сначала"}


def _is_abusive_only(text: str) -> bool:
    lowered = text.lower().replace("ё", "е").strip()
    abusive = ("иди нах", "пошел", "пошла", "сука", "блять", "ебан", "хуй")
    return any(word in lowered for word in abusive) and len(lowered.split()) <= 5


def _draft_log_line(draft: BookingDraft) -> str:
    return (f"service_type={draft.service_type} date={draft.date} guests={draft.guests_count} variant={draft.service_variant} time={draft.time} duration={draft.duration} format={draft.event_format} upsell_done={draft.upsell_done} name={draft.client_name} phone={draft.phone} status={draft.status} next={draft.next_step()}")