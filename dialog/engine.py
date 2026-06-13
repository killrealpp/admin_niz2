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
from app.dialog.admin_notify import notify_admin_booking_created, notify_admin_cancel_refund_required, notify_admin_booking_rescheduled
from app.dialog.state import BookingDraft, AdminDecision
from app.storage import sqlite
from app.dialog.watchlist import WatchlistCandidate, candidate_from_action, create_watchlist
from app.integrations.yclients import YClientsClient
from app.dialog.availability import build_yclients_payload
from app.dialog.pricing import calculate_booking_price


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


def _is_payment_request(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    return any(word in lowered for word in ("оплат", "предоплат", "ссылк", "платеж", "платёж")) and not any(word in lowered for word in ("не хочу", "не надо", "не буду", "отмена"))


def _looks_like_upsell_refusal(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    refusal_markers = (
        "не надо", "не нужны", "не нужен", "без доп", "ничего не",
        "нет спасибо", "нет, спасибо", "нет спасиб", "не хочу", "отказыва",
        "no", "ne", "неа", "нет"
    )
    return any(marker in lowered for marker in refusal_markers)


def _normalize_event_format_value(value: str | None) -> str | None:
    if not value:
        return value
    text = str(value).strip()
    lowered = text.lower().replace("ё", "е")
    casual_rest = ("бух", "пьян", "тус", "посид", "отдох", "отдых", "чил", "шашлык")
    if any(marker in lowered for marker in casual_rest):
        return "отдых"
    return text


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

    pending_reply = _handle_pending_action(chat_id, text, draft)
    if pending_reply is not None:
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(pending_reply)

    # If the flow is stuck on the second upsell step and the user clearly refuses,
    # close the upsell state in code. This is state logic only: no customer-facing
    # hardcoded upsell text is generated here.
    if draft.next_step() == "upsell_items" and int(draft.upsell_offer_count or 0) >= 1 and _looks_like_upsell_refusal(text):
        draft.upsell_offer_count = 2
        draft.upsell_done = True

    if draft.ready_for_confirmation():
        if _is_payment_request(text) or is_positive_confirmation(text, draft):
            return _create_payment_or_admin_handoff(chat_id, draft)

    if draft.status == "waiting_payment" and not is_positive_confirmation(text, draft):
        draft.status = "active"
        draft.payment_id = None
        draft.payment_url = None

    llm_text = text
    if draft.service_type and any(word in text.lower() for word in ["не обязательно", "другой вариант", "другие", "не только", "или"]):
        llm_text = f"{text} (клиент не хочет {draft.service_type}, предложи другие типы объектов: дом, баня, тёплая беседка)"

    decision = decide(llm_text, draft, today=today, history=history)

    action_reply = _handle_decision_action(chat_id, decision, draft)
    if action_reply is not None:
        _store_requested_media(chat_id, decision.requested_media)
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(action_reply)

    _store_requested_media(chat_id, decision.requested_media)
    before_patch = BookingDraft.from_dict(draft.to_dict())
    _apply_patch(draft, decision.fields_patch)
    logger.info("DRAFT PROPOSED: %s", _draft_log_line(draft))

    # Если модель распознала готовность к оплате уже после применения полей,
    # не даём ей увести клиента обратно в допы/разговоры.
    if draft.ready_for_confirmation() and (getattr(decision, "wants_payment", False) or decision.action.type == "create_payment" or _is_payment_request(text)):
        return _create_payment_or_admin_handoff(chat_id, draft)

    invalid_reply = _validate_business_rules(before_patch, draft)
    if invalid_reply:
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(invalid_reply)

    availability_reply = _maybe_check_availability(chat_id, before_patch, draft)
    if availability_reply:
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(availability_reply)

    # Финальную сводку и переход к оплате формирует LLM.
    # Engine здесь не хардкодит текст заявки, чтобы не терять ответы на вопросы клиента
    # и не подменять цену, рассчитанную/переданную модели.
    reply = decision.reply or _fallback_question(draft)
    reply = _canonicalize_price_in_reply(reply, draft)
    reply = _ensure_next_step(reply, before_patch, draft)

    reply = sanitize_reply(reply, fallback=_fallback_question(draft))
    _remember_offered_dates_from_reply(draft, reply, decision)
    sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
    logger.info("DRAFT SAVED: %s", _draft_log_line(draft))
    return reply

_MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

_OBJECT_TITLE_BY_SERVICE = {
    "bathhouse": "Баня с бассейном",
    "house": "Гостевой дом",
    "warm_gazebo": "Теплая беседка",
}


def _remember_offered_dates_from_reply(draft: BookingDraft, reply: str, decision: AdminDecision) -> None:
    dates = _extract_ru_dates_from_text(reply)
    if not dates:
        return

    service_type = draft.service_type
    object_title = draft.service_variant or _OBJECT_TITLE_BY_SERVICE.get(service_type or "")

    # Если это общий список разных объектов, не затираем уже выбранный объект.
    # Для активной брони бани/дома/тёплой беседки сохраняем именно её контекст.
    draft.last_offered_dates = dates[:20]
    draft.last_offered_service_type = service_type
    draft.last_offered_object_title = object_title
    logger.info(
        "LAST_OFFERED_DATES service_type=%s object_title=%s dates=%s",
        draft.last_offered_service_type,
        draft.last_offered_object_title,
        draft.last_offered_dates,
    )


def _extract_ru_dates_from_text(text: str) -> list[str]:
    if not text:
        return []
    today = now_local().date()
    found: list[str] = []
    lowered = text.lower().replace("ё", "е")

    month_names = "|".join(_MONTHS_RU.keys())
    # Берёт именно плотную дату-фразу перед месяцем: "14 и 15 июня", "22, 23, 25 июня".
    pattern = re.compile(rf"((?:\d{{1,2}}\s*(?:,|и|или)?\s*){{1,12}})\s+({month_names})")
    for match in pattern.finditer(lowered):
        raw_days = match.group(1)
        month = _MONTHS_RU.get(match.group(2))
        if not month:
            continue
        for day_raw in re.findall(r"\d{1,2}", raw_days):
            day = int(day_raw)
            if day < 1 or day > 31:
                continue
            year = today.year
            try:
                candidate = datetime(year, month, day).date()
            except ValueError:
                continue
            # Если дата уже явно ушла далеко в прошлое, это следующий год.
            if candidate < today and (today - candidate).days > 31:
                try:
                    candidate = datetime(year + 1, month, day).date()
                except ValueError:
                    continue
            iso = candidate.isoformat()
            if iso not in found:
                found.append(iso)
    return sorted(found)


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

    # Сначала применяем счётчик предложений допов, чтобы upsell_done проверял
    # уже актуальное значение независимо от порядка ключей в JSON от LLM.
    if "upsell_offer_count" in patch:
        count = _to_int(patch.get("upsell_offer_count"))
        if count is not None:
            draft.upsell_offer_count = max(0, min(int(count), 2))

    for raw_key, raw_value in patch.items():
        key = aliases.get(raw_key, raw_key)
        if key not in allowed:
            continue
        if key == "upsell_offer_count":
            continue
        value = raw_value
        if value is None:
            if key in {"service_type", "service_variant", "date", "time", "duration", "guests_count", "event_format", "upsell_items", "upsell_done", "client_name", "phone"}:
                if key == "upsell_items":
                    setattr(draft, key, [])
                elif key == "upsell_done":
                    setattr(draft, key, False)
                else:
                    setattr(draft, key, None)
            continue
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
        elif key == "event_format":
            value = _normalize_event_format_value(str(value)) if value else None
        elif key == "upsell_items":
            value = list(value or []) if isinstance(value, list) else []
        elif key == "upsell_done":
            value = bool(value)
            logger.info("UPSEL: value=%s offer_count=%s items=%s", value, draft.upsell_offer_count, draft.upsell_items)
        if value in ("", []) and key not in ("upsell_items", "upsell_done"):
            continue
        setattr(draft, key, value)

    _reconcile_upsell_state(draft, patch)


def _reconcile_upsell_state(draft: BookingDraft, patch: dict[str, Any] | None) -> None:
    if not patch:
        return
    core_ready = bool(draft.service_type and draft.date and draft.time and draft.duration and draft.guests_count and draft.event_format)
    if not core_ready:
        return

    patched_done = bool(patch.get("upsell_done") is True)
    has_items = bool(draft.upsell_items)

    # Once upsells are closed, never reopen them just because the counter is stale.
    if draft.upsell_done and int(draft.upsell_offer_count or 0) >= 2:
        return

    if patched_done and not has_items and int(draft.upsell_offer_count or 0) < 2:
        # First attempt to close upsells too early: block only while we still lack
        # contacts. If contacts are already present, keeping the draft on upsells
        # creates an infinite loop and blocks payment.
        if draft.client_name and draft.phone:
            draft.upsell_offer_count = 2
            draft.upsell_done = True
        else:
            draft.upsell_offer_count = max(int(draft.upsell_offer_count or 0), 1)
            draft.upsell_done = False
            logger.info("UPSEL: blocked early completion until second offer")


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
    """Return the LLM reply without appending customer-facing text.

    Engine may protect state, but it must not write dialog lines for the model.
    Previously this function appended hardcoded next-step questions, including the
    second upsell question, which produced contradictory replies like asking for
    a name and then asking about extras in the same message.
    """
    return reply

def _has_refusal(reply: str) -> bool:
    lowered = reply.lower().replace("ё", "е")
    return any(word in lowered for word in ("отказ", "не надо", "не нужно", "нет", "без допов"))



def _canonicalize_price_in_reply(reply: str, draft: BookingDraft) -> str:
    if not reply:
        return reply
    price = calculate_booking_price(draft)
    if not price:
        return reply
    price_text = f"{price:,}".replace(",", " ")
    patterns = [
        r"(общая стоимость(?:\s+составит|\s*[:—-])?\s*)\d[\d\s]*(?:руб(?:\.|лей)?|₽)",
        r"(стоимость(?:\s+составит|\s*[:—-])\s*)\d[\d\s]*(?:руб(?:\.|лей)?|₽)",
        r"(итого(?:\s*[:—-])?\s*)\d[\d\s]*(?:руб(?:\.|лей)?|₽)",
    ]
    result = reply
    for pattern in patterns:
        result = re.sub(pattern, lambda m: f"{m.group(1)}{price_text} ₽", result, flags=re.I)
    return result

def _create_payment_or_admin_handoff(chat_id: str, draft: BookingDraft) -> str:
    availability = check_availability(draft, chat_id=chat_id)
    if not availability.ok:
        logger.warning("CREATE_PAYMENT_BLOCKED_SLOT_UNAVAILABLE draft=%s", _draft_log_line(draft))
        draft.status = "active"
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return "Это время не подтверждается в системе записи. Давайте выберем другое время приезда, чтобы не брать предоплату за неподтверждённый слот."

    try:
        booking_id = sqlite.create_booking(chat_id, draft.to_dict(), status="waiting_payment")
        payment_id, payment_url = create_prepayment(draft, chat_id=chat_id, booking_id=booking_id)
        draft.payment_id = payment_id
        draft.payment_url = payment_url
        draft.status = "waiting_payment"
        sqlite.update_booking(booking_id, draft.to_dict(), status="waiting_payment")
        sqlite.save_draft(chat_id, draft.to_dict(), status="waiting_payment", current_step=draft.next_step())
        sqlite.upsert_hold(chat_id, draft.to_dict())
        notify_admin_booking_created(chat_id=chat_id, booking_id=booking_id, draft=draft)
        return f"Отлично, бронь подготовила. Для подтверждения нужна предоплата. Ссылка на оплату:\n{payment_url}"
    except Exception as exc:
        logger.exception("Payment creation failed chat_id=%s", chat_id)
        sqlite.enqueue_admin_notification(f"Клиент подтвердил заявку, но автоматическая оплата не создалась.\nchat_id: {chat_id}\nОшибка: {exc}\nЗаявка: {draft.to_dict()}", chat_id=chat_id)
        return "Заявку собрала. Сейчас не получилось автоматически создать ссылку на оплату, передала администратору — он поможет завершить бронь."




def _handle_decision_action(chat_id: str, decision: AdminDecision, draft: BookingDraft) -> str | None:
    action_type = (decision.action.type or "none").strip()
    params = decision.action.params or {}

    if action_type == "create_payment":
        if draft.ready_for_confirmation():
            return _create_payment_or_admin_handoff(chat_id, draft)
        logger.warning("CREATE_PAYMENT_BLOCKED_NOT_READY draft=%s", _draft_log_line(draft))
        return None

    if action_type == "new_booking":
        explicit = bool(params.get("explicit") or params.get("confirmed") or params.get("confirmed_new_booking"))
        has_active_draft = bool(draft.service_type or draft.date or draft.time or draft.duration or draft.guests_count or draft.client_name or draft.phone)
        if has_active_draft and not explicit:
            logger.warning("NEW_BOOKING_ACTION_IGNORED active_draft=True params=%s", params)
            return None
        draft.reset()
        return decision.reply or "Хорошо, оформим новую бронь. Что хотите забронировать?"

    if action_type == "offer_watchlist":
        candidate = candidate_from_action(params, draft)
        if not candidate:
            return None
        draft.pending_action = {"type": "watchlist_create", "candidate": candidate.__dict__}
        return decision.reply or f"На {candidate.date} {candidate.object_title} занята. Включить уведомление, если освободится?"

    if action_type == "request_cancel_confirmation":
        booking = sqlite.latest_active_booking(chat_id)
        if not booking:
            return "Не нашла активную бронь для отмены. Напишите, какую бронь нужно отменить."
        booking_draft = BookingDraft.from_dict(__import__('json').loads(booking["draft_json"]))
        draft.pending_action = {"type": "cancel_booking", "booking_id": int(booking["id"]), "reason": params.get("reason")}
        return decision.reply or f"Правильно понимаю, нужно отменить бронь: {_object_summary(booking_draft)}?"

    if action_type == "request_reschedule_confirmation":
        booking = sqlite.latest_active_booking(chat_id)
        if not booking:
            return "Не нашла активную бронь для переноса. Напишите, какую бронь нужно перенести."
        booking_draft = BookingDraft.from_dict(__import__('json').loads(booking["draft_json"]))
        new_date = params.get("date") or params.get("date_from") or decision.fields_patch.get("date") or draft.date
        new_time = params.get("time") or decision.fields_patch.get("time") or booking_draft.time
        if not new_date:
            draft.pending_action = {"type": "await_reschedule_date", "booking_id": int(booking["id"])}
            return "На какую дату перенести бронь?"
        probe = BookingDraft.from_dict(booking_draft.to_dict())
        probe.date = _normalize_date(str(new_date)) or str(new_date)
        if new_time:
            probe.time = _normalize_time(str(new_time)) or str(new_time)
        availability = check_availability(probe, chat_id=chat_id)
        if not availability.ok:
            draft.pending_action = {"type": "await_reschedule_date", "booking_id": int(booking["id"])}
            return f"На {probe.date} этот вариант занят. Напишите другую дату — проверю и перед переносом ещё раз попрошу подтверждение."
        draft.pending_action = {
            "type": "reschedule_booking",
            "booking_id": int(booking["id"]),
            "new_date": probe.date,
            "new_time": probe.time,
        }
        return decision.reply or f"Проверила, на {probe.date} время доступно. Подтвердить перенос брони на {probe.date} {probe.time or ''}?".strip()

    return None


def _handle_pending_action(chat_id: str, text: str, draft: BookingDraft) -> str | None:
    pending = draft.pending_action or {}
    if not pending:
        return None

    action_type = str(pending.get("type") or "")
    if _looks_negative(text):
        draft.pending_action = {}
        return "Хорошо, действие отменила. Чем ещё помочь?"

    if action_type == "watchlist_create":
        if not _looks_positive(text):
            return None
        raw = pending.get("candidate") or {}
        candidate = WatchlistCandidate(
            service_type=raw.get("service_type"),
            object_title=str(raw.get("object_title") or ""),
            date=str(raw.get("date") or ""),
        )
        watch_id = create_watchlist(chat_id, candidate)
        draft.pending_action = {}
        return f"Готово, включила уведомление. Если {candidate.object_title} на {candidate.date} освободится, я напишу вам."

    if action_type == "cancel_booking":
        if not _looks_positive(text):
            return None
        booking_id = int(pending.get("booking_id"))
        return _perform_cancel_booking(chat_id, booking_id, draft, reason=str(pending.get("reason") or ""))

    if action_type == "reschedule_booking":
        if not _looks_positive(text):
            return None
        booking_id = int(pending.get("booking_id"))
        new_date = str(pending.get("new_date") or "")
        new_time = str(pending.get("new_time") or "") or None
        return _perform_reschedule_booking(chat_id, booking_id, new_date, new_time, draft)

    if action_type == "await_reschedule_date":
        # Дату снова извлекает LLM в обычном проходе; pending оставляем, чтобы router понимал контекст из current_draft.
        return None

    return None


def _perform_cancel_booking(chat_id: str, booking_id: int, draft: BookingDraft, *, reason: str = "") -> str:
    rows = [row for row in sqlite.list_bookings(chat_id, limit=20) if int(row["id"]) == int(booking_id)]
    if not rows:
        draft.pending_action = {}
        return "Не нашла эту бронь. Передала администратору, он поможет проверить вручную."
    row = rows[0]
    booking_draft = BookingDraft.from_dict(__import__('json').loads(row["draft_json"]))
    yclients_error = None
    if booking_draft.yclients_record_id:
        try:
            YClientsClient().delete_record(booking_draft.yclients_record_id)
        except Exception as exc:
            yclients_error = str(exc)
            logger.exception("Failed to delete YCLIENTS record booking_id=%s", booking_id)
    booking_draft.status = "canceled"
    sqlite.update_booking(booking_id, booking_draft.to_dict(), "canceled")
    notify_admin_cancel_refund_required(chat_id=chat_id, booking_id=booking_id, draft=booking_draft, reason=reason or yclients_error)
    draft.pending_action = {}
    if yclients_error:
        return "Заявку на отмену приняла, но автоматически удалить запись в YClients не получилось. Передала администратору — он проверит бронь и возврат предоплаты."
    return "Бронь отменила. Если предоплата уже была внесена, администратор проверит возврат. По правилам возврат должен быть оформлен в течение 7 дней."


def _perform_reschedule_booking(chat_id: str, booking_id: int, new_date: str, new_time: str | None, draft: BookingDraft) -> str:
    rows = [row for row in sqlite.list_bookings(chat_id, limit=20) if int(row["id"]) == int(booking_id)]
    if not rows:
        draft.pending_action = {}
        return "Не нашла эту бронь. Передала администратору, он поможет проверить вручную."
    row = rows[0]
    booking_draft = BookingDraft.from_dict(__import__('json').loads(row["draft_json"]))
    old_date, old_time = booking_draft.date, booking_draft.time
    booking_draft.date = _normalize_date(new_date) or new_date
    if new_time:
        booking_draft.time = _normalize_time(new_time) or new_time
    availability = check_availability(booking_draft, chat_id=chat_id)
    if not availability.ok:
        draft.pending_action = {"type": "await_reschedule_date", "booking_id": booking_id}
        return f"На {booking_draft.date} этот вариант уже занят. Напишите другую дату — проверю."
    yclients_error = None
    if booking_draft.yclients_record_id:
        try:
            YClientsClient().update_record(booking_draft.yclients_record_id, build_yclients_payload(booking_draft))
        except Exception as exc:
            yclients_error = str(exc)
            logger.exception("Failed to update YCLIENTS record booking_id=%s", booking_id)
    booking_draft.status = "rescheduled" if not yclients_error else "reschedule_manual_review"
    sqlite.update_booking(booking_id, booking_draft.to_dict(), booking_draft.status)
    notify_admin_booking_rescheduled(chat_id=chat_id, booking_id=booking_id, draft=booking_draft, old_date=old_date, old_time=old_time)
    draft.pending_action = {}
    if yclients_error:
        return "Перенос проверила, но автоматически изменить запись в YClients не получилось. Передала администратору — он завершит перенос вручную."
    return f"Готово, бронь перенесена на {booking_draft.date} {booking_draft.time or ''}.".strip()


def _looks_positive(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    return bool(is_positive_confirmation(text, BookingDraft()) or any(word in lowered for word in ("да", "подтверж", "верно", "соглас", "включ", "хорошо", "ок")))


def _looks_negative(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    return any(word in lowered for word in ("нет", "не надо", "отмена", "отбой", "не нужно"))


def _object_summary(draft: BookingDraft) -> str:
    return f"{draft.service_variant or service_title(draft.service_type)} на {draft.date or 'дату не указали'} {draft.time or ''}".strip()

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