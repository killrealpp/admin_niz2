from __future__ import annotations

import json
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


def _looks_like_upsell_final_refusal(text: str) -> bool:
    """Client explicitly asks not to hear another upsell offer."""
    lowered = (text or "").lower().replace("ё", "е")
    final_markers = (
        "не предлаг", "больше не предлаг", "не надо снова", "не нужно снова",
        "я же сказал", "я же говор", "не спрашивай", "без допов",
        "точно нет", "совсем нет", "ничего не нужно", "ничего не надо"
    )
    return any(marker in lowered for marker in final_markers)


def _text_contains_time(text: str) -> bool:
    lowered = (text or "").lower().replace("ё", "е")
    if re.search(r"\b\d{1,2}[:.]\d{2}\b", lowered):
        return True
    if re.search(r"\b(?:в|к)\s*\d{1,2}(?:\s*(?:утра|дня|вечера|ночи))?\b", lowered):
        return True
    return False


def _text_contains_duration(text: str) -> bool:
    lowered = (text or "").lower().replace("ё", "е")
    if any(word in lowered for word in ("час", "ч.", "ч ", "на сутки", "сутки")):
        return True
    # Short replies like "на 8" during duration collection are valid.
    if re.search(r"\bна\s*\d{1,2}\b", lowered):
        return True
    return False


def _looks_like_slot_explanation_request(text: str) -> bool:
    lowered = (text or "").lower().replace("ё", "е")
    markers = (
        "всмысле", "в смысле", "почему", "как так", "че", "что",
        "не понял", "не поняла", "мне откуда", "все верно", "всё верно",
        "подтвержда", "да", "верно"
    )
    return any(marker in lowered for marker in markers)


def _explicit_watchlist_confirmation(text: str) -> bool:
    """True only when the client clearly asks to be notified.

    A bare «давайте» is too ambiguous after an unavailable-time message: it often
    means «давайте другое время». Do not create watchlists from generic positive
    confirmations.
    """
    lowered = (text or "").lower().replace("ё", "е")
    return any(marker in lowered for marker in (
        "уведом", "сообщ", "напишите если", "напиши если",
        "если освобод", "включи уведом", "да, уведом", "да уведом",
        "поставь уведом", "следи", "отслед"
    ))


def _looks_like_new_time_choice(text: str, draft: BookingDraft | None = None) -> bool:
    lowered = (text or "").lower().replace("ё", "е")
    if _text_contains_time(text):
        return True
    if re.search(r"\bс\s*\d{1,2}\s*(?:до|-|—)\s*\d{1,2}\b", lowered):
        return True
    # During time collection, short phrases like «с 14 до 22», «тогда в 14»
    # should always be treated as a new time, not as agreement to a watchlist.
    if draft and draft.next_step() == "time" and re.search(r"\b(?:в|к|с|на|тогда|давайте)\s*\d{1,2}\b", lowered):
        return True
    return False


def _client_mentions_selected_service(text: str, draft: BookingDraft) -> bool:
    lowered = (text or "").lower().replace("ё", "е")
    if draft.service_type == "bathhouse":
        return "бан" in lowered
    if draft.service_type == "house":
        return "дом" in lowered or "гост" in lowered
    if draft.service_type == "warm_gazebo":
        return "тепл" in lowered or "тёпл" in lowered
    if draft.service_type == "gazebo":
        return "бесед" in lowered
    return False


def _extract_explicit_day_date(text: str) -> str | None:
    """Resolve phrases like «на 16», «на 16 июня», «16 июня» as a date.

    This is deliberately narrow: it is used to protect booking flows from the LLM
    reading «на 16» as 16:00 when the client is actually correcting the date.
    """
    lowered = (text or "").lower().replace("ё", "е")
    if not lowered.strip():
        return None
    # Do not reinterpret explicit times/durations as dates.
    if any(marker in lowered for marker in ("час", "ч.", "вечера", "утра", "дня", "ночи", ":")):
        return None
    m = re.search(r"(?:\bна\s+|\b)(\d{1,2})\s*(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)?\b", lowered)
    if not m:
        return None
    day = int(m.group(1))
    if day < 1 or day > 31:
        return None
    today = now_local().date()
    month = _MONTHS_RU.get(m.group(2) or "") or today.month
    year = today.year
    try:
        candidate = datetime(year, month, day).date()
    except ValueError:
        return None
    if not m.group(2) and candidate < today:
        # Bare day in the past means next month.
        month += 1
        if month > 12:
            month = 1
            year += 1
        try:
            candidate = datetime(year, month, day).date()
        except ValueError:
            return None
    return candidate.isoformat()


def _looks_like_date_change_for_current_service(text: str, draft: BookingDraft) -> bool:
    lowered = (text or "").lower().replace("ё", "е")
    if not draft.service_type:
        return False
    if _extract_explicit_day_date(text):
        # «нет давайте на 16» after a bot asks for duration is commonly a date correction.
        if any(marker in lowered for marker in ("нет", "давайте", "лучше", "всмысле", "имею", "дат", "июн", "июл")):
            return True
    return False


def _derive_time_duration_from_range(text: str) -> tuple[str | None, int | None]:
    lowered = (text or "").lower().replace("ё", "е")
    m = re.search(r"\bс\s*(\d{1,2})(?::(\d{2}))?\s*(?:до|-|—)\s*(\d{1,2})(?::(\d{2}))?\b", lowered)
    if not m:
        return None, None
    start_h = int(m.group(1))
    start_m = int(m.group(2) or 0)
    end_h = int(m.group(3))
    end_m = int(m.group(4) or 0)
    if not (0 <= start_h <= 23 and 0 <= start_m <= 59 and 0 <= end_h <= 23 and 0 <= end_m <= 59):
        return None, None
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    if end_minutes <= start_minutes:
        end_minutes += 24 * 60
    duration_hours = (end_minutes - start_minutes) / 60
    if duration_hours <= 0 or duration_hours > 24:
        return None, None
    duration = int(duration_hours) if float(duration_hours).is_integer() else None
    return f"{start_h:02d}:{start_m:02d}", duration


def _explicitly_asks_for_photo(text: str) -> bool:
    lowered = (text or "").lower().replace("ё", "е")
    return any(marker in lowered for marker in ("фото", "фотк", "покажи", "как выглядит", "выгляд", "посмотреть"))


def _is_broad_availability_reply(reply: str, draft: BookingDraft) -> bool:
    lowered = (reply or "").lower().replace("ё", "е")
    object_markers = ("баня", "беседк", "гостевой", "дом", "теплая", "тёплая", "крытая")
    mentioned = sum(1 for marker in object_markers if marker in lowered)
    list_markers = ("доступны", "свободны", "следующие варианты", "на сегодня", "на завтра")
    return mentioned >= 3 and any(marker in lowered for marker in list_markers)


def _filter_requested_media_for_customer(
    requested_media: list[str] | None,
    *,
    reply: str,
    before: BookingDraft,
    draft: BookingDraft,
    user_text: str,
) -> list[str]:
    media = [str(item) for item in (requested_media or []) if item]
    if not media:
        return []
    if _explicitly_asks_for_photo(user_text):
        return media

    # Broad availability answers become confusing when one random photo is attached.
    # Either the client explicitly asks for photos, or we wait until they choose an object.
    if _is_broad_availability_reply(reply, draft):
        logger.info("MEDIA_SUPPRESSED broad_availability media=%s", media)
        return []

    # During data collection for an already selected object, photos should not repeat
    # unless the client asked for them.
    collecting_steps = {"time", "duration", "guests_count", "event_format", "upsell_items", "client_name", "phone", "confirmation"}
    if draft.service_type and draft.next_step() in collecting_steps and before.service_type == draft.service_type:
        logger.info("MEDIA_SUPPRESSED collecting_flow step=%s media=%s", draft.next_step(), media)
        return []

    return media



def _availability_event_data(draft: BookingDraft, availability_message: str | None = None) -> dict[str, Any]:
    return {
        "service_type": draft.service_type,
        "object_title": draft.service_variant or service_title(draft.service_type) or "выбранный вариант",
        "date": draft.date,
        "human_date": _human_date(draft.date),
        "time": draft.time or draft.blocked_until,
        "available_times": availability_message or "",
        "can_watchlist": bool(draft.service_type and draft.date),
        "next_expected_step": draft.next_step(),
    }


def _available_dates_for_service(service_type: str | None, *, limit: int = 10) -> list[str]:
    """Return dates that are really free for the selected object type from cache.

    This is a state/availability fact, not a client phrase. It prevents the LLM
    from inventing a date like 19 June as free when cache/YClients marked it busy.
    """
    if not service_type:
        return []
    try:
        rows = sqlite.list_availability_rows(service_type=service_type, limit=2000)
    except Exception:
        logger.exception("AVAILABLE_DATES_FROM_CACHE_FAILED service_type=%s", service_type)
        return []
    today = now_local().date().isoformat()
    dates: list[str] = []
    for row in rows:
        date = str(row.get("date") or "")
        status = str(row.get("status") or "")
        time_value = str(row.get("time") or "")
        if not date or date < today:
            continue
        if status == "empty":
            continue
        # For full-day objects the cache uses time=day; for slot services it stores
        # actual times. Any non-empty row means the date has at least one option.
        if not time_value:
            continue
        if date not in dates:
            dates.append(date)
        if len(dates) >= limit:
            break
    return dates


def _should_engine_own_service_date_list(before: BookingDraft, draft: BookingDraft, user_text: str) -> bool:
    lowered = (user_text or "").lower().replace("ё", "е")
    if not draft.service_type or draft.date:
        return False
    if draft.next_step() != "date":
        return False
    # The client selected an object or asks when it is free. Date lists are
    # operational data, so code must provide the list and LLM must only phrase it.
    if before.service_type != draft.service_type:
        return True
    return any(marker in lowered for marker in ("когда", "даты", "дату", "свобод", "есть", "пораньше", "позже"))


def _engine_service_date_list_reply(
    *,
    draft: BookingDraft,
    chat_id: str,
    user_text: str,
    history: list[dict[str, Any]],
    today: str,
) -> str:
    dates = _available_dates_for_service(draft.service_type, limit=10)
    draft.last_offered_dates = dates[:20]
    draft.last_offered_service_type = draft.service_type
    draft.last_offered_object_title = draft.service_variant or _OBJECT_TITLE_BY_SERVICE.get(draft.service_type or "") or service_title(draft.service_type)
    return _llm_reply_from_engine_context(
        draft=draft,
        chat_id=chat_id,
        user_text=user_text,
        history=history,
        today=today,
        event="available_dates_for_service",
        data={
            "service_type": draft.service_type,
            "object_title": draft.last_offered_object_title,
            "available_dates": dates,
            "rule": "Перечисляй только даты из available_dates. Не добавляй другие даты от себя.",
            "next_expected_step": "date",
        },
        fallback=_fallback_question(draft),
    )


def _make_watchlist_candidate_from_draft(draft: BookingDraft) -> WatchlistCandidate | None:
    if not draft.service_type or not draft.date:
        return None
    title = draft.service_variant or _OBJECT_TITLE_BY_SERVICE.get(draft.service_type or "") or service_title(draft.service_type)
    if not title:
        return None
    return WatchlistCandidate(service_type=draft.service_type, object_title=str(title), date=str(draft.date))


def _normalize_event_format_value(value: str | None) -> str | None:
    if not value:
        return value
    text = str(value).strip()
    lowered = text.lower().replace("ё", "е")
    # Do not store the client's literal phrase like "что то другое" as a format.
    # The admin/client summary should use a canonical value.
    if "друг" in lowered or re.search(r"что\s*-?\s*то\s+друг", lowered):
        return "другое"
    casual_rest = ("бух", "пьян", "тус", "посид", "отдох", "отдых", "чил", "шашлык")
    if any(marker in lowered for marker in casual_rest):
        return "отдых"
    birthday = ("день рожд", "др", "днюх", "юбилей")
    if any(marker in lowered for marker in birthday):
        return "день рождения"
    return text



def _llm_reply_from_engine_context(
    *,
    draft: BookingDraft,
    chat_id: str,
    user_text: str,
    history: list[dict[str, Any]],
    today: str,
    event: str,
    data: dict[str, Any] | None = None,
    fallback: str | None = None,
) -> str:
    """Ask the answer model to write client-facing text from a structured engine event.

    The engine owns state and operations. It must not script customer messages.
    This helper passes a compact, non-technical event to the LLM and uses only the
    generated reply. Returned draft/actions from this call are intentionally ignored.
    """
    payload = data or {}
    context = (
        f"{user_text}\n\n"
        "СТРУКТУРНЫЙ РЕЗУЛЬТАТ ОТ КОДА ДЛЯ ОТВЕТА КЛИЕНТУ:\n"
        f"event={event}\n"
        f"data={payload}\n\n"
        "Сформулируй только клиентский ответ от имени Любови. "
        "Не используй технические слова: JSON, API, YClients, слот, Booking ID, payment_id, record_id, backend. "
        "Не меняй смысл события. Если в data есть список available_dates или available_times — используй только эти значения, ничего не придумывай. "
        "Если event про недоступность — предложи другое время/дату и аккуратно предложи уведомление. "
        "Если event про допы — предложи их мягко, как пользу: приехать налегке; не дави. "
        "Если event про контакты — попроси имя/телефон коротко."
    )
    try:
        decision = decide(context, draft, today=today, history=history)
        text = (decision.reply or "").strip()
        if text:
            return text
    except Exception:
        logger.exception("LLM_ENGINE_CONTEXT_REPLY_FAILED event=%s", event)
    return fallback or _fallback_question(draft)


class DialogBlocked(Exception):
    pass


def handle_text(chat_id: str, user_name: str, text: str) -> str:
    logger.info("=== JSON_ENGINE HANDLE_TEXT START === chat_id=%s text=%r", chat_id, text)

    draft = BookingDraft.from_dict(sqlite.load_draft(chat_id))
    logger.info("DRAFT BEFORE: %s", _draft_log_line(draft))

    if _is_hard_reset(text):
        draft = BookingDraft()
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(_llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=text,
            history=[],
            today=now_local().date().isoformat(),
            event="restart_dialog",
            data={},
            fallback=_fallback_question(draft),
        ))

    guard = GuardResult(False)
    if guard.handled:
        if guard.draft_patch:
            _apply_patch(draft, guard.draft_patch, from_user_edit=True)
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        logger.info("DRAFT AFTER GUARD: %s", _draft_log_line(draft))
        return sanitize_reply(guard.text or _fallback_question(draft))

    history = sqlite.list_recent_messages(chat_id, limit=12)
    today = now_local().date().isoformat()

    normalized_text = _normalize_user_text_for_dialog(text)

    if draft.phone and not _is_valid_phone(draft.phone):
        draft.phone = None
        draft.status = "active"
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(_llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=text,
            history=history,
            today=today,
            event="invalid_phone",
            data={"phone_digits_required": 11, "next_step": "phone"},
            fallback=_fallback_question(draft),
        ))

    if draft.phone and _is_valid_phone(draft.phone):
        draft.phone = _format_phone(draft.phone)

    # Booking operations must not depend on the LLM deciding an action.
    # If the client clearly asks to move/cancel an existing paid booking, start the
    # operation state here and keep using the current real booking instead of
    # exposing old/stale rows from PostgreSQL.
    booking_op_reply = _maybe_start_booking_operation(chat_id, text, draft, history=history, today=today)
    if booking_op_reply is not None:
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(booking_op_reply)

    # If a selected time failed live availability, keep the client inside the current
    # new-booking flow. This must run BEFORE pending_action handling: otherwise a
    # phrase like «давайте с 14 до 22» can be mistaken for agreement to watchlist.
    if draft.block_reason == "slot_unavailable":
        if _looks_like_new_time_choice(text, draft):
            draft.block_reason = None
            draft.blocked_until = None
            if (draft.pending_action or {}).get("type") == "watchlist_create":
                draft.pending_action = {}
        elif _explicit_watchlist_confirmation(text):
            # Let pending_action create the watchlist below.
            pass
        elif _looks_like_slot_explanation_request(text):
            sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
            return sanitize_reply(_llm_reply_from_engine_context(
                draft=draft,
                chat_id=chat_id,
                user_text=text,
                history=history,
                today=today,
                event="explain_unavailable_time_continue_booking",
                data={
                    "service_type": draft.service_type,
                    "object_title": draft.service_variant or service_title(draft.service_type),
                    "date": draft.date,
                    "time": draft.blocked_until,
                    "expected_next_step": "time",
                    "watchlist_requires_explicit_request": True,
                },
                fallback=_fallback_question(draft),
            ))

    if (draft.pending_action or {}).get("type") == "watchlist_create" and _looks_like_new_time_choice(text, draft):
        logger.info("WATCHLIST_PENDING_CLEARED_BY_TIME_CHOICE text=%r", text)
        draft.pending_action = {}

    pending_reply = _handle_pending_action(chat_id, text, draft)
    if pending_reply is not None:
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(pending_reply)

    # Upsell is a controlled mini-flow. Client asked to do exactly two soft touches:
    # 1) after event format; 2) after a polite first refusal. A generic "нет спасибо"
    # must NOT immediately close extras, otherwise доп. продажа never happens.
    if draft.next_step() == "upsell_items" and int(draft.upsell_offer_count or 0) >= 1 and _looks_like_upsell_refusal(text):
        current_count = int(draft.upsell_offer_count or 0)
        if current_count <= 1 and not _looks_like_upsell_final_refusal(text):
            draft.upsell_offer_count = 2
            draft.upsell_done = False
            sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
            return sanitize_reply(_llm_reply_from_engine_context(
                draft=draft,
                chat_id=chat_id,
                user_text=text,
                history=history,
                today=today,
                event="upsell_second_offer",
                data={
                    "offer_count": 2,
                    "items_to_offer": ["уголь", "розжиг", "решётки", "посуда", "кальян"],
                    "tone": "very_short_soft_last_attempt",
                    "rule": "Это второе и последнее аккуратное предложение допов. Если клиент снова откажется — сразу переходи к имени/телефону. Не дави и не повторяй тот же текст дословно.",
                    "next_step_if_refused": "contacts",
                },
                fallback=_fallback_question(draft),
            ))
        draft.upsell_offer_count = 2
        draft.upsell_done = True
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(_llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=text,
            history=history,
            today=today,
            event="upsell_final_refusal_go_to_contacts",
            data={"client_name_present": bool(draft.client_name), "phone_present": bool(draft.phone)},
            fallback=_fallback_question(draft),
        ))

    # If the second upsell was already made and the client sends contact details
    # instead of explicitly saying no, treat that as declining extras and proceed.
    if draft.next_step() == "upsell_items" and int(draft.upsell_offer_count or 0) >= 2 and _message_has_contact_data(text):
        draft.upsell_done = True

    if draft.ready_for_confirmation():
        if _is_payment_request(text) or is_positive_confirmation(text, draft):
            return _create_payment_or_admin_handoff(chat_id, draft)

    # If the client asks what the event-format examples mean, do not let the LLM
    # treat words like «например» as the actual format. Keep state and explain.
    if draft.next_step() == "event_format" and _looks_like_event_format_example_request(text):
        return sanitize_reply(_llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=text,
            history=history,
            today=today,
            event="event_format_examples",
            data={
                "examples": ["отдых", "день рождения", "корпоратив", "другое"],
                "rule": "Не записывай 'например' как формат. Объясни коротко и попроси выбрать/описать формат.",
                "next_step": "event_format",
            },
            fallback=_fallback_question(draft),
        ))

    if draft.status == "waiting_payment" and not is_positive_confirmation(text, draft):
        draft.status = "active"
        draft.payment_id = None
        draft.payment_url = None

    llm_text = normalized_text
    explicit_date_override = _extract_explicit_day_date(normalized_text) if _looks_like_date_change_for_current_service(normalized_text, draft) else None
    if explicit_date_override:
        llm_text = (
            f"{text}\n\n"
            f"СТРУКТУРНЫЙ КОНТЕКСТ: клиент уточняет именно дату {explicit_date_override} для уже выбранного объекта. "
            "Это НЕ время 16:00 и НЕ длительность. Сохрани текущий service_type, очисти time/duration если нужно, "
            "верни date равным этой дате и продолжай бронирование этого же объекта."
        )
    elif _looks_like_date_refinement_request(normalized_text, draft):
        llm_text = (
            f"{normalized_text}\n\n"
            "СТРУКТУРНЫЙ КОНТЕКСТ: клиент не отменяет бронь и не меняет объект; "
            "он просит другие даты для уже выбранного объекта. "
            "Сохрани текущий service_type и верни intent=date_refinement."
        )
    elif draft.service_type and any(word in normalized_text.lower() for word in ["не обязательно", "другой вариант", "другие", "не только", "или"]):
        llm_text = f"{normalized_text} (клиент не хочет {draft.service_type}, предложи другие типы объектов: дом, баня, тёплая беседка)"

    decision = decide(llm_text, draft, today=today, history=history)

    action_reply = _handle_decision_action(chat_id, decision, draft, user_text=text)
    if action_reply is not None:
        decision.requested_media = _filter_requested_media_for_customer(
            decision.requested_media,
            reply=action_reply,
            before=draft,
            draft=draft,
            user_text=text,
        )
        _store_requested_media(chat_id, decision.requested_media)
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(action_reply)

    before_patch = BookingDraft.from_dict(draft.to_dict())
    _apply_patch(draft, decision.fields_patch)
    if explicit_date_override:
        logger.info("DATE_OVERRIDE_CURRENT_SERVICE text=%r date=%s service_type=%s", text, explicit_date_override, before_patch.service_type)
        draft.service_type = before_patch.service_type or draft.service_type
        draft.service_variant = before_patch.service_variant or draft.service_variant
        draft.date = explicit_date_override
        draft.time = None
        # The client corrected the date, not duration. Do not keep an implicit/default duration.
        if not _text_contains_duration(text):
            draft.duration = None
        draft.pending_action = {}
        draft.block_reason = None
        draft.blocked_until = None
    range_time, range_duration = _derive_time_duration_from_range(text)
    if range_time:
        logger.info("TIME_RANGE_DERIVED text=%r time=%s duration=%s", text, range_time, range_duration)
        draft.time = range_time
        if range_duration:
            draft.duration = range_duration
    # Do not let the LLM silently default bathhouse duration to 3 hours when
    # the client only said "баню на завтра". Duration must be explicitly chosen.
    if (
        draft.service_type == "bathhouse"
        and before_patch.duration is None
        and draft.duration is not None
        and not _text_contains_duration(normalized_text)
    ):
        logger.info("DROP_IMPLICIT_BATHHOUSE_DURATION text=%r duration=%s", text, draft.duration)
        draft.duration = None

    if _should_engine_own_service_date_list(before_patch, draft, normalized_text):
        logger.info("ENGINE_OWNS_SERVICE_DATE_LIST service_type=%s", draft.service_type)
        reply = _engine_service_date_list_reply(draft=draft, chat_id=chat_id, user_text=normalized_text, history=history, today=today)
        decision.requested_media = _filter_requested_media_for_customer(
            decision.requested_media,
            reply=reply,
            before=before_patch,
            draft=draft,
            user_text=normalized_text,
        )
        _store_requested_media(chat_id, decision.requested_media)
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        logger.info("DRAFT SAVED: %s", _draft_log_line(draft))
        return sanitize_reply(reply, fallback=_fallback_question(draft))

    logger.info("DRAFT PROPOSED: %s", _draft_log_line(draft))

    # Если модель распознала готовность к оплате уже после применения полей,
    # не даём ей увести клиента обратно в допы/разговоры.
    if draft.ready_for_confirmation() and (getattr(decision, "wants_payment", False) or decision.action.type == "create_payment" or _is_payment_request(text)):
        return _create_payment_or_admin_handoff(chat_id, draft)

    invalid_reply = _validate_business_rules(before_patch, draft)
    if invalid_reply:
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(invalid_reply)

    availability_reply = _maybe_check_availability(chat_id, before_patch, draft, user_text=text, history=history, today=today)
    if availability_reply:
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return sanitize_reply(availability_reply)

    # Финальную сводку и переход к оплате формирует LLM.
    # Engine здесь не хардкодит текст заявки, чтобы не терять ответы на вопросы клиента
    # и не подменять цену, рассчитанную/переданную модели.
    reply = decision.reply or _fallback_question(draft)
    reply = _canonicalize_price_in_reply(reply, draft)
    reply = _ensure_next_step(reply, before_patch, draft)
    reply = _client_guard_reply(reply, user_text=text, before=before_patch, draft=draft, chat_id=chat_id, history=history, today=today)
    decision.requested_media = _filter_requested_media_for_customer(
        decision.requested_media,
        reply=reply,
        before=before_patch,
        draft=draft,
        user_text=text,
    )

    reply = sanitize_reply(reply, fallback=_fallback_question(draft))
    _store_requested_media(chat_id, decision.requested_media)
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

    # Диапазоны вида "22–30 июня" / "22-30 июня".
    range_pattern = re.compile(rf"\b(\d{{1,2}})\s*(?:-|–|—)\s*(\d{{1,2}})\s+({month_names})")
    for match in range_pattern.finditer(lowered):
        start_day = int(match.group(1))
        end_day = int(match.group(2))
        month = _MONTHS_RU.get(match.group(3))
        if not month or start_day > end_day or end_day - start_day > 31:
            continue
        for day in range(start_day, end_day + 1):
            year = today.year
            try:
                candidate = datetime(year, month, day).date()
            except ValueError:
                continue
            if candidate < today and (today - candidate).days > 31:
                try:
                    candidate = datetime(year + 1, month, day).date()
                except ValueError:
                    continue
            iso = candidate.isoformat()
            if iso not in found:
                found.append(iso)

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


def _message_has_contact_data(text: str) -> bool:
    if not text:
        return False
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 10:
        return True
    # Typical two-line contact: name + phone may contain the phone in a separate line;
    # if there is a likely name but no full phone, do not close upsells yet.
    return False


def _looks_like_date_refinement_request(text: str, draft: BookingDraft) -> bool:
    if not draft.service_type:
        return False
    if not (draft.last_offered_dates or draft.date):
        return False
    lowered = (text or "").lower().replace("ё", "е").strip()
    if not lowered:
        return False

    # Broad semantic guard for date refinement. It is not tied to one phrase like
    # "попозже": it protects the selected object when the client rejects offered
    # dates or asks for later/other dates.
    date_words = ("дата", "даты", "дату", "число", "когда", "свободн", "июн", "июл", "август", "сент")
    refinement_words = ("друг", "позже", "попозже", "дальше", "след", "не подходит", "не эти", "не на", "когда")

    if any(w in lowered for w in date_words) and any(w in lowered for w in refinement_words):
        return True

    # A short "нет/не" immediately after the bot offered dates usually means
    # "not these dates", not "cancel the selected object".
    if lowered in {"не", "нет", "неа", "не подходит"} and draft.last_offered_dates:
        return True

    return False


def _normalize_user_text_for_dialog(text: str) -> str:
    lowered = (text or "").lower().replace("ё", "е").strip()
    # Cheap typo protection for the very common "че сть" -> "че есть".
    if re.fullmatch(r"ч[ео]?\s*ст[ьъ]?", lowered):
        return "че есть"
    return text


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

    # LLM often returns null for fields it is not focused on. Null must not erase
    # already collected booking details (e.g. duration=8 disappearing during final
    # confirmation). Clear time/duration only when the same patch actually changes
    # date or service, because then old time/duration may no longer apply.
    incoming_date = patch.get("date")
    incoming_service = patch.get("service_type") or patch.get("service")
    try:
        normalized_incoming_date = _normalize_date(str(incoming_date)) if incoming_date else None
    except Exception:
        normalized_incoming_date = None
    try:
        normalized_incoming_service = normalize_service_type(str(incoming_service)) if incoming_service else None
    except Exception:
        normalized_incoming_service = None
    patch_changes_date = bool(normalized_incoming_date and normalized_incoming_date != draft.date)
    patch_changes_service = bool(normalized_incoming_service and normalized_incoming_service != draft.service_type)

    for raw_key, raw_value in patch.items():
        key = aliases.get(raw_key, raw_key)
        if key not in allowed:
            continue
        if key == "upsell_offer_count":
            continue
        value = raw_value
        if value is None:
            if key == "upsell_items":
                draft.upsell_items = []
            elif key == "upsell_done":
                draft.upsell_done = False
            elif key in {"time", "duration"}:
                if from_user_edit or patch_changes_date or patch_changes_service:
                    setattr(draft, key, None)
            elif key in {"service_variant"}:
                if from_user_edit or patch_changes_service:
                    setattr(draft, key, None)
            elif key in {"service_type", "date"}:
                if from_user_edit:
                    setattr(draft, key, None)
            else:
                # Do not erase guests/format/name/phone just because LLM omitted them.
                if from_user_edit:
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
        # The business owner wants two soft upsell touches. Do not let the LLM close
        # extras after the first polite refusal; handle_text() will send the second
        # and final offer explicitly.
        draft.upsell_offer_count = 1
        draft.upsell_done = False


def _validate_business_rules(before: BookingDraft, draft: BookingDraft) -> str | None:
    if draft.service_type == "bathhouse" and draft.guests_count and draft.guests_count > _BATHHOUSE_CAPACITY:
        draft.service_type = None
        draft.service_variant = None
        draft.time = None
        draft.duration = None
        return None
    return None


def _maybe_check_availability(chat_id: str, before: BookingDraft, draft: BookingDraft, *, user_text: str, history: list[dict[str, Any]], today: str) -> str | None:
    changed_keys = []
    for key in ("service_type", "service_variant", "date", "time", "duration", "guests_count"):
        if getattr(before, key) != getattr(draft, key):
            changed_keys.append(key)
    if not changed_keys:
        return None
    if not draft.service_type or not draft.date:
        return None

    # Date-level hold notice must work before duration/time are selected.
    # Otherwise client B hears “date is free” while client A already holds
    # 16:00–00:00 before payment. We still ask for exact duration/time, but with
    # the reservation nuance.
    if not draft.time:
        hold_notice = _date_level_hold_notice(draft, chat_id=chat_id)
        if hold_notice:
            return _llm_reply_from_engine_context(
                draft=draft,
                chat_id=chat_id,
                user_text=user_text,
                history=history,
                today=today,
                event="date_available_but_some_times_held",
                data={
                    "service_type": draft.service_type,
                    "object_title": draft.service_variant or service_title(draft.service_type),
                    "date": draft.date,
                    "held_times": hold_notice.get("held_times", []),
                    "rule": "Не говори, что дата полностью свободна. Скажи, что по дате есть варианты, но часть времени уже предварительно занята; попроси желаемую длительность и время. Не раскрывай чужой chat_id/имя/номер.",
                    "next_step": draft.next_step(),
                },
                fallback=_fallback_question(draft),
            )

    if draft.service_type in {"bathhouse", "house"} and not draft.duration:
        return None
    try:
        availability = check_availability(draft, chat_id=chat_id)
    except Exception as exc:
        logger.warning("Availability check failed: %s", exc)
        return None
    
    if not availability.ok:
        # Date-level unavailability is valid when it comes from records that start on
        # the target date. Previous-day overlaps are filtered in availability.py.
        # So if no time is selected yet, tell the client the chosen date is busy and
        # offer a watchlist instead of collecting contacts for an impossible date.
        draft.available_variants = availability.variants
        # Watchlist is offered only after a real unavailable result. For bathhouse/house
        # this means the concrete time was checked, not just a date-level draft.
        candidate = _make_watchlist_candidate_from_draft(draft)
        if candidate:
            draft.pending_action = {"type": "watchlist_create", "candidate": candidate.__dict__}
        # If exact time was selected, do not let the bot collect contacts first and
        # reveal the problem only at payment. Keep date/duration and ask for a new time.
        if draft.time:
            blocked_time = draft.time
            draft.block_reason = "slot_unavailable"
            draft.blocked_until = blocked_time
            draft.time = None
        return _llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=user_text,
            history=history,
            today=today,
            event="availability_unavailable",
            data=_availability_event_data(draft, availability.message),
            fallback=_fallback_question(draft),
        )
    
    if availability.variants:
        draft.available_variants = availability.variants

    # Date-level truth with holds: a date can still have free times, but if
    # another chat already holds a concrete time before payment, do not simply
    # say “free” without nuance. Ask the client for the desired time and let the
    # next exact-time check block conflicts.
    hold_notice = _date_level_hold_notice(draft, chat_id=chat_id)
    if hold_notice and not draft.time:
        return _llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=user_text,
            history=history,
            today=today,
            event="date_available_but_some_times_held",
            data={
                "service_type": draft.service_type,
                "object_title": draft.service_variant or service_title(draft.service_type),
                "date": draft.date,
                "held_times": hold_notice.get("held_times", []),
                "rule": "Не говори, что дата полностью свободна. Скажи, что есть варианты по времени, но часть времени уже предварительно занята; попроси желаемое время.",
                "next_step": "time",
            },
            fallback=_fallback_question(draft),
        )

    # Reserve the selected object/time as soon as the client has chosen enough
    # concrete booking details. This protects two clients racing for the same
    # object: the first one who reaches date+time+duration keeps a temporary hold,
    # the second one gets an unavailable message before payment.
    if draft.service_type and draft.date and draft.time and draft.duration:
        try:
            sqlite.upsert_hold(chat_id, draft.to_dict())
            logger.info("SLOT_HOLD_UPSERTED chat_id=%s service_type=%s variant=%s date=%s time=%s duration=%s", chat_id, draft.service_type, draft.service_variant, draft.date, draft.time, draft.duration)
        except Exception:
            logger.exception("Failed to upsert slot hold chat_id=%s", chat_id)

    return None


def _ensure_next_step(reply: str, before: BookingDraft, draft: BookingDraft) -> str:
    """Return the LLM reply without appending customer-facing text.

    Engine may protect state, but it must not write dialog lines for the model.
    Previously this function appended hardcoded next-step questions, including the
    second upsell question, which produced contradictory replies like asking for
    a name and then asking about extras in the same message.
    """
    return reply

def _client_guard_reply(reply: str, *, user_text: str, before: BookingDraft, draft: BookingDraft, chat_id: str, history: list[dict[str, Any]], today: str) -> str:
    """Final safety layer for customer-facing wording.

    This does not decide business logic. It prevents admin/developer wording from
    leaking to clients and keeps the upsell flow from contradicting state.
    """
    # The order must be client-friendly: first collect booking essentials, then
    # offer extras, then ask contacts. If the LLM tries to ask name/phone before
    # the upsell step, keep the state-machine order.
    if draft.next_step() == "upsell_items":
        if int(draft.upsell_offer_count or 0) <= 0:
            draft.upsell_offer_count = 1
            draft.upsell_done = False
            return _llm_reply_from_engine_context(
                draft=draft,
                chat_id=chat_id,
                user_text=user_text,
                history=history,
                today=today,
                event="upsell_first_offer",
                data={
                    "offer_count": 1,
                    "items_to_offer": ["уголь", "розжиг", "решётки", "посуда", "кальян"],
                    "tone": "soft_useful_not_pushy",
                    "next_step_if_refused": "upsell_second_offer",
                },
                fallback=reply,
            )

        # Refusals while on upsell_items are handled before LLM in handle_text(),
        # because the state must decide whether to show the second and final offer.
        return reply

    # If the client already refused twice/finally, never let the LLM reopen extras.
    if draft.upsell_done and _reply_mentions_upsell_for_engine(reply) and draft.next_step() in {"client_name", "phone", "confirmation"}:
        return _llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=user_text,
            history=history,
            today=today,
            event="ask_missing_contacts_after_upsell_closed",
            data={"client_name_present": bool(draft.client_name), "phone_present": bool(draft.phone)},
            fallback=reply,
        )

    # The user can send contact details and a side question in one message
    # («Савелий / phone / комары есть?»). The LLM may answer only the side
    # question and forget to move the booking forward. If all fields are now ready,
    # ask for final confirmation in the same customer-facing response.
    if draft.ready_for_confirmation() and not _reply_asks_for_confirmation_or_payment(reply):
        return _llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=user_text,
            history=history,
            today=today,
            event="answer_side_question_and_ask_confirmation",
            data={
                "existing_reply_to_preserve": reply,
                "booking_summary": {
                    "object": draft.service_variant or service_title(draft.service_type),
                    "date": draft.date,
                    "time": draft.time,
                    "duration": draft.duration,
                    "guests": draft.guests_count,
                    "event_format": draft.event_format,
                    "client_name": draft.client_name,
                    "phone_present": bool(draft.phone),
                },
                "rule": "Коротко ответь на вопрос клиента, если он был, и сразу попроси подтвердить данные брони. Не проси заново имя/телефон.",
            },
            fallback=reply,
        )

    return _polish_customer_wording(reply)


def _reply_mentions_upsell_for_engine(reply: str) -> bool:
    lowered = (reply or "").lower().replace("ё", "е")
    return any(marker in lowered for marker in ("доп", "уголь", "розжиг", "решет", "решёт", "посуда", "кальян"))


def _looks_like_event_format_example_request(text: str) -> bool:
    lowered = (text or "").lower().replace("ё", "е").strip(" ?!.…")
    return lowered in {"например", "какие", "какой например", "что например", "типа", "типо"} or any(
        marker in lowered for marker in ("какие форматы", "что за формат", "что можно", "например что")
    )


def _reply_asks_for_confirmation_or_payment(reply: str) -> bool:
    lowered = (reply or "").lower().replace("ё", "е")
    return any(marker in lowered for marker in ("подтверд", "все верно", "всё верно", "перейти к оплат", "ссылк", "оплат"))


def _date_level_hold_notice(draft: BookingDraft, *, chat_id: str) -> dict[str, Any] | None:
    if not draft.service_type or not draft.date or draft.time:
        return None
    try:
        rows = sqlite.active_holds_for_service_date(draft.service_type, draft.date, ignore_chat_id=chat_id)
    except Exception:
        logger.exception("ACTIVE_HOLDS_FOR_SERVICE_DATE_FAILED chat_id=%s", chat_id)
        return None
    if not rows:
        return None
    times = []
    for row in rows[:10]:
        time_value = str(row.get("time") or "")
        duration = row.get("duration")
        if time_value:
            times.append({"time": time_value, "duration": duration})
    return {"held_times": times, "count": len(rows)}

def _polish_customer_wording(reply: str) -> str:
    if not reply:
        return reply
    text = reply
    replacements = {
        "Booking ID": "номер заявки",
        "booking id": "номер заявки",
        "YCLIENTS": "системе бронирования",
        "YClients": "системе бронирования",
        "YClients record_id": "номер записи",
        "payment_id": "номер платежа",
        "record_id": "номер записи",
        "неподтверждённый слот": "неподтверждённое время",
        "неподтвержденный слот": "неподтверждённое время",
        "слот": "время",
        "система записи": "система бронирования",
        "в системе записи": "в системе бронирования",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = text.replace(
        "Хотите, чтобы я предложила дополнительные услуги, такие как уголь, розжиг, решётки или кальян, чтобы вам не пришлось везти всё с собой?",
        "Могу подготовить уголь, розжиг, решётки или кальян, чтобы вам не пришлось везти всё с собой. Что-нибудь добавить?",
    )
    text = text.replace(
        "Хотите, чтобы я предложила дополнительные услуги",
        "Могу подготовить дополнительные услуги",
    )
    return text


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
        draft.block_reason = "slot_unavailable"
        draft.blocked_until = draft.time
        sqlite.save_draft(chat_id, draft.to_dict(), status="active", current_step=draft.next_step())
        return _llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text="подтверждение оплаты",
            history=sqlite.list_recent_messages(chat_id, limit=12),
            today=now_local().date().isoformat(),
            event="payment_blocked_unavailable_time",
            data=_availability_event_data(draft, availability.message),
            fallback=_fallback_question(draft),
        )

    draft.block_reason = None
    draft.blocked_until = None

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
        return _llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text="клиент подтвердил финальную сводку",
            history=sqlite.list_recent_messages(chat_id, limit=12),
            today=now_local().date().isoformat(),
            event="payment_link_failed_admin_notified",
            data={"admin_notified": True},
            fallback=_fallback_question(draft),
        )




def _handle_decision_action(chat_id: str, decision: AdminDecision, draft: BookingDraft, *, user_text: str = "") -> str | None:
    action_type = (decision.action.type or "none").strip()
    params = decision.action.params or {}

    # Booking management actions are allowed only when the client clearly asks
    # to cancel/reschedule or provides a Booking ID. This prevents replies like
    # "в смысле?" from exposing internal booking lists during a new booking flow.
    if action_type in {"request_cancel_confirmation", "request_reschedule_confirmation"}:
        operation = "cancel" if action_type == "request_cancel_confirmation" else "reschedule"
        if not _is_explicit_booking_management_request(user_text, operation=operation, params=params):
            logger.warning("BOOKING_OPERATION_ACTION_IGNORED action=%s text=%r params=%s", action_type, user_text, params)
            return None

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
        return decision.reply or _llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=user_text,
            history=sqlite.list_recent_messages(chat_id, limit=12),
            today=now_local().date().isoformat(),
            event="new_booking_started",
            data={},
            fallback=_fallback_question(draft),
        )

    if action_type == "offer_watchlist":
        candidate = candidate_from_action(params, draft)
        if not candidate:
            return None
        draft.pending_action = {"type": "watchlist_create", "candidate": candidate.__dict__}
        return decision.reply or _llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=user_text,
            history=sqlite.list_recent_messages(chat_id, limit=12),
            today=now_local().date().isoformat(),
            event="offer_watchlist",
            data={"object_title": candidate.object_title, "date": candidate.date},
            fallback=_fallback_question(draft),
        )

    if action_type == "request_cancel_confirmation":
        booking, select_reply = _select_booking_for_operation(chat_id, params, operation="cancel", current_draft=draft)
        if select_reply:
            return select_reply
        if not booking:
            return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text=user_text, history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="cancel_booking_not_found", data={}, fallback=_fallback_question(draft))
        booking_draft = BookingDraft.from_dict(__import__('json').loads(booking["draft_json"]))
        draft.pending_action = {"type": "cancel_booking", "booking_id": int(booking["id"]), "reason": params.get("reason")}
        return decision.reply or f"Правильно понимаю, нужно отменить бронь: {_object_summary(booking_draft)}?"

    if action_type == "request_reschedule_confirmation":
        booking, select_reply = _select_booking_for_operation(chat_id, params, operation="reschedule", current_draft=draft)
        if select_reply:
            return select_reply
        if not booking:
            return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text=user_text, history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="reschedule_booking_not_found", data={}, fallback=_fallback_question(draft))
        booking_draft = BookingDraft.from_dict(__import__('json').loads(booking["draft_json"]))
        new_date = params.get("date") or params.get("date_from") or decision.fields_patch.get("date") or draft.date
        new_time = params.get("time") or decision.fields_patch.get("time") or booking_draft.time
        if not new_date:
            draft.pending_action = {"type": "await_reschedule_date", "booking_id": int(booking["id"])}
            return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text=user_text, history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="ask_reschedule_date", data={}, fallback=_fallback_question(draft))
        probe = BookingDraft.from_dict(booking_draft.to_dict())
        probe.date = _normalize_date(str(new_date)) or str(new_date)
        if new_time:
            probe.time = _normalize_time(str(new_time)) or str(new_time)
        availability = check_availability(probe, chat_id=chat_id)
        if not availability.ok:
            draft.pending_action = {"type": "await_reschedule_date", "booking_id": int(booking["id"])}
            return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text=user_text, history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="reschedule_date_unavailable", data={"date": probe.date, "object_title": probe.service_variant or service_title(probe.service_type)}, fallback=_fallback_question(draft))
        draft.pending_action = {
            "type": "reschedule_booking",
            "booking_id": int(booking["id"]),
            "new_date": probe.date,
            "new_time": probe.time,
        }
        return decision.reply or _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text=user_text, history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="reschedule_needs_confirmation", data={"date": probe.date, "time": probe.time}, fallback=_fallback_question(draft))

    return None


def _is_explicit_booking_management_request(text: str, *, operation: str, params: dict[str, Any] | None = None) -> bool:
    params = params or {}
    if params.get("booking_id") or params.get("id"):
        return True
    lowered = (text or "").lower().replace("ё", "е")
    if operation == "cancel":
        markers = ("отмен", "удал", "снять брон", "отказаться от бро", "вернуть предоплат", "возврат")
    else:
        markers = ("перенес", "перенести", "перенеси", "поменять дату", "изменить дату", "перезапис", "на другую дату")
    return any(marker in lowered for marker in markers)


def _maybe_start_booking_operation(chat_id: str, text: str, draft: BookingDraft, *, history: list[dict[str, Any]], today: str) -> str | None:
    """Start cancel/reschedule from deterministic rules, before asking the LLM.

    This fixes the bug where the LLM says "бронь перенесена/отменена" but the
    operation is never executed in YClients.
    """
    lowered = (text or "").lower().replace("ё", "е")
    if draft.pending_action:
        return None

    if _is_explicit_booking_management_request(text, operation="reschedule", params={}):
        booking, select_reply = _select_booking_for_operation(chat_id, {}, operation="reschedule", current_draft=draft)
        if select_reply:
            return _llm_reply_from_engine_context(
                draft=draft,
                chat_id=chat_id,
                user_text=text,
                history=history,
                today=today,
                event="select_booking_for_reschedule",
                data={"choices_text": select_reply},
                fallback=select_reply,
            )
        if booking:
            draft.pending_action = {"type": "await_reschedule_date", "booking_id": int(booking["id"])}
            return _llm_reply_from_engine_context(
                draft=draft,
                chat_id=chat_id,
                user_text=text,
                history=history,
                today=today,
                event="ask_reschedule_date",
                data={"current_booking": _object_summary(BookingDraft.from_dict(json.loads(booking["draft_json"])))},
                fallback=_fallback_question(draft),
            )

    if _is_explicit_booking_management_request(text, operation="cancel", params={}):
        booking, select_reply = _select_booking_for_operation(chat_id, {}, operation="cancel", current_draft=draft)
        if select_reply:
            return _llm_reply_from_engine_context(
                draft=draft,
                chat_id=chat_id,
                user_text=text,
                history=history,
                today=today,
                event="select_booking_for_cancel",
                data={"choices_text": select_reply},
                fallback=select_reply,
            )
        if booking:
            booking_draft = BookingDraft.from_dict(json.loads(booking["draft_json"]))
            draft.pending_action = {"type": "cancel_booking", "booking_id": int(booking["id"]), "reason": text}
            return _llm_reply_from_engine_context(
                draft=draft,
                chat_id=chat_id,
                user_text=text,
                history=history,
                today=today,
                event="cancel_needs_confirmation",
                data={"booking": _object_summary(booking_draft), "refund_deadline_days": 7},
                fallback=f"Подтвердите отмену брони: {_object_summary(booking_draft)}.",
            )

    return None


def _select_booking_for_operation(chat_id: str, params: dict[str, Any], *, operation: str, current_draft: BookingDraft | None = None) -> tuple[dict | None, str | None]:
    booking_id = params.get("booking_id") or params.get("id")
    rows = _actual_booking_rows(chat_id)

    if booking_id:
        for row in rows:
            if str(row.get("id")) == str(booking_id):
                return row, None
        return None, "Не нашла такую активную бронь. Возможно, её уже отменили или изменили через администратора."

    # Prefer the booking currently loaded in dialog state. This prevents exposing old
    # PostgreSQL rows that may already be deleted manually through support/YClients.
    if current_draft:
        current = _find_row_matching_draft(rows, current_draft)
        if current:
            return current, None

    rows = _filter_existing_yclients_rows(rows)

    if len(rows) == 1:
        return rows[0], None

    if len(rows) > 1:
        lines = ["У вас нашла несколько активных броней. Напишите номер варианта, с которым работаем:"]
        for idx, row in enumerate(rows[:5], start=1):
            bd = BookingDraft.from_dict(json.loads(row["draft_json"]))
            lines.append(f"{idx}) {_object_summary(bd)}")
        return None, "\n".join(lines)

    return None, None


def _actual_booking_rows(chat_id: str) -> list[dict]:
    # Only bookings that should really exist in YClients. Waiting payments and old
    # error/manual rows should not be shown to a client as their real bookings.
    rows = sqlite.list_bookings(chat_id, statuses=["booked", "rescheduled"], limit=20)
    result: list[dict] = []
    for row in rows:
        try:
            bd = BookingDraft.from_dict(json.loads(row["draft_json"]))
        except Exception:
            continue
        if bd.yclients_record_id:
            result.append(row)
    return result


def _find_row_matching_draft(rows: list[dict], draft: BookingDraft) -> dict | None:
    for row in rows:
        try:
            bd = BookingDraft.from_dict(json.loads(row["draft_json"]))
        except Exception:
            continue
        if draft.yclients_record_id and bd.yclients_record_id and str(bd.yclients_record_id) == str(draft.yclients_record_id):
            return row
        if draft.payment_id and bd.payment_id and str(bd.payment_id) == str(draft.payment_id):
            return row
        if draft.service_type == bd.service_type and draft.date == bd.date and draft.time == bd.time and str(draft.duration) == str(bd.duration):
            return row
    return None


def _filter_existing_yclients_rows(rows: list[dict]) -> list[dict]:
    filtered: list[dict] = []
    for row in rows:
        try:
            bd = BookingDraft.from_dict(json.loads(row["draft_json"]))
        except Exception:
            continue
        if _yclients_record_exists_safe(bd):
            filtered.append(row)
    return filtered


def _yclients_record_exists_safe(draft: BookingDraft) -> bool:
    if not draft.yclients_record_id or not draft.date:
        return False
    try:
        records = YClientsClient().get_records(start_date=draft.date, end_date=draft.date, page=1)
        rid = str(draft.yclients_record_id)
        for record in records:
            if str(record.get("id") or "") == rid or str(record.get("record_id") or "") == rid:
                return True
    except Exception:
        # If YClients check fails, keep the row rather than losing the user's booking.
        logger.warning("YCLIENTS_RECORD_EXISTENCE_CHECK_FAILED record_id=%s", draft.yclients_record_id)
        return True
    return False

def _handle_pending_action(chat_id: str, text: str, draft: BookingDraft) -> str | None:
    pending = draft.pending_action or {}
    if not pending:
        return None

    action_type = str(pending.get("type") or "")

    if action_type == "watchlist_create":
        if _looks_negative(text):
            logger.info("WATCHLIST_DECLINED_CONTINUE_FLOW text=%r", text)
            draft.pending_action = {}
            if _client_mentions_selected_service(text, draft):
                return None
            return _llm_reply_from_engine_context(
                draft=draft,
                chat_id=chat_id,
                user_text=text,
                history=sqlite.list_recent_messages(chat_id, limit=12),
                today=now_local().date().isoformat(),
                event="watchlist_declined_continue_booking",
                data={"service_type": draft.service_type, "date": draft.date, "next_step": draft.next_step()},
                fallback=_fallback_question(draft),
            )
        if not _explicit_watchlist_confirmation(text):
            logger.info("WATCHLIST_CONFIRMATION_IGNORED_AMBIGUOUS text=%r", text)
            return None
        raw = pending.get("candidate") or {}
        candidate = WatchlistCandidate(
            service_type=raw.get("service_type"),
            object_title=str(raw.get("object_title") or ""),
            date=str(raw.get("date") or ""),
        )
        watch_id = create_watchlist(chat_id, candidate)
        draft.pending_action = {}
        return _llm_reply_from_engine_context(
            draft=draft,
            chat_id=chat_id,
            user_text=text,
            history=sqlite.list_recent_messages(chat_id, limit=12),
            today=now_local().date().isoformat(),
            event="watchlist_created",
            data={"object_title": candidate.object_title, "date": candidate.date, "watch_id": watch_id},
            fallback=_fallback_question(draft),
        )

    if _looks_negative(text):
        draft.pending_action = {}
        return _llm_reply_from_engine_context(
        draft=draft,
        chat_id=chat_id,
        user_text=text,
        history=sqlite.list_recent_messages(chat_id, limit=12),
        today=now_local().date().isoformat(),
        event="pending_action_declined",
        data={"pending_action_type": action_type},
        fallback=_fallback_question(draft),
    )

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
        booking_id = int(pending.get("booking_id"))
        rows = [row for row in sqlite.list_bookings(chat_id, limit=20) if int(row["id"]) == booking_id]
        if not rows:
            draft.pending_action = {}
            return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text=text, history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="booking_not_found_for_pending_action", data={"action": action_type}, fallback=_fallback_question(draft))
        booking_draft = BookingDraft.from_dict(__import__('json').loads(rows[0]["draft_json"]))
        new_date = _extract_date_from_user_text(text, base_date=booking_draft.date)
        if not new_date:
            return None
        probe = BookingDraft.from_dict(booking_draft.to_dict())
        probe.date = new_date
        availability = check_availability(probe, chat_id=chat_id)
        if not availability.ok:
            draft.pending_action = {"type": "await_reschedule_date", "booking_id": booking_id}
            return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text=text, history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="reschedule_date_unavailable", data={"date": new_date, "object_title": probe.service_variant or service_title(probe.service_type)}, fallback=_fallback_question(draft))
        draft.pending_action = {
            "type": "reschedule_booking",
            "booking_id": booking_id,
            "new_date": new_date,
            "new_time": probe.time,
        }
        return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text=text, history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="reschedule_needs_confirmation", data={"date": new_date, "time": probe.time}, fallback=_fallback_question(draft))

    return None


def _perform_cancel_booking(chat_id: str, booking_id: int, draft: BookingDraft, *, reason: str = "") -> str:
    rows = [row for row in sqlite.list_bookings(chat_id, limit=20) if int(row["id"]) == int(booking_id)]
    if not rows:
        draft.pending_action = {}
        return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text="операция с бронью", history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="booking_not_found_admin_handoff", data={"admin_notified": True}, fallback=_fallback_question(draft))
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
    sqlite.release_holds(chat_id)
    notify_admin_cancel_refund_required(chat_id=chat_id, booking_id=booking_id, draft=booking_draft, reason=reason or yclients_error)
    draft.pending_action = {}
    if yclients_error:
        return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text="отмена брони", history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="cancel_manual_review_refund_required", data={"refund_deadline_days": 7, "admin_notified": True}, fallback=_fallback_question(draft))
    return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text="отмена брони", history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="cancel_completed_refund_required", data={"refund_deadline_days": 7, "admin_notified": True}, fallback=_fallback_question(draft))


def _perform_reschedule_booking(chat_id: str, booking_id: int, new_date: str, new_time: str | None, draft: BookingDraft) -> str:
    rows = [row for row in sqlite.list_bookings(chat_id, limit=20) if int(row["id"]) == int(booking_id)]
    if not rows:
        draft.pending_action = {}
        return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text="операция с бронью", history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="booking_not_found_admin_handoff", data={"admin_notified": True}, fallback=_fallback_question(draft))
    row = rows[0]
    booking_draft = BookingDraft.from_dict(json.loads(row["draft_json"]))
    old_date, old_time, old_record_id = booking_draft.date, booking_draft.time, booking_draft.yclients_record_id
    booking_draft.date = _normalize_date(new_date) or new_date
    if new_time:
        booking_draft.time = _normalize_time(new_time) or new_time

    availability = check_availability(booking_draft, chat_id=chat_id)
    if not availability.ok:
        draft.pending_action = {"type": "await_reschedule_date", "booking_id": booking_id}
        return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text="перенос брони", history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="reschedule_date_unavailable", data={"date": booking_draft.date, "object_title": booking_draft.service_variant or service_title(booking_draft.service_type)}, fallback=_fallback_question(draft))

    yclients_error = None
    try:
        # Safer than PUT /record with a book_record-shaped payload: create the new
        # YClients record first, then delete the old one. If creation fails, the old
        # booking remains untouched.
        response = YClientsClient().create_book_record(build_yclients_payload(booking_draft))
        new_record_id = _extract_yclients_record_id(response)
        if new_record_id:
            booking_draft.yclients_record_id = str(new_record_id)
        if old_record_id:
            YClientsClient().delete_record(str(old_record_id))
    except Exception as exc:
        yclients_error = str(exc)
        logger.exception("Failed to recreate YCLIENTS record for reschedule booking_id=%s", booking_id)

    booking_draft.status = "rescheduled" if not yclients_error else "reschedule_manual_review"
    sqlite.update_booking(booking_id, booking_draft.to_dict(), booking_draft.status)
    sqlite.save_draft(chat_id, booking_draft.to_dict(), status=booking_draft.status, current_step=booking_draft.next_step())
    sqlite.release_holds(chat_id)
    notify_admin_booking_rescheduled(chat_id=chat_id, booking_id=booking_id, draft=booking_draft, old_date=old_date, old_time=old_time)
    draft.pending_action = {}
    if yclients_error:
        return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text="перенос брони", history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="reschedule_manual_review", data={"admin_notified": True}, fallback=_fallback_question(draft))
    return _llm_reply_from_engine_context(draft=draft, chat_id=chat_id, user_text="перенос брони", history=sqlite.list_recent_messages(chat_id, limit=12), today=now_local().date().isoformat(), event="reschedule_completed", data={"date": booking_draft.date, "time": booking_draft.time}, fallback=_fallback_question(draft))


def _extract_yclients_record_id(response: Any) -> str | None:
    if isinstance(response, list) and response:
        for item in response:
            if isinstance(item, dict):
                value = item.get("record_id") or item.get("id")
                if value:
                    return str(value)
    if isinstance(response, dict):
        value = response.get("record_id") or response.get("id")
        if value:
            return str(value)
        data = response.get("data")
        if data is not None:
            return _extract_yclients_record_id(data)
    return None

def _extract_date_from_user_text(text: str, *, base_date: str | None = None) -> str | None:
    lowered = (text or "").lower().replace("ё", "е")
    today = now_local().date()
    base = None
    if base_date:
        try:
            base = datetime.fromisoformat(base_date).date()
        except ValueError:
            base = None

    # Explicit YYYY-MM-DD.
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", lowered)
    if m:
        return m.group(1)

    # Russian month name: «23 июня».
    month_names = "|".join(_MONTHS_RU.keys())
    m = re.search(rf"\b(\d{{1,2}})\s+({month_names})\b", lowered)
    if m:
        day = int(m.group(1))
        month = _MONTHS_RU.get(m.group(2))
        if month:
            year = today.year
            try:
                candidate = datetime(year, month, day).date()
                if candidate < today:
                    candidate = datetime(year + 1, month, day).date()
                return candidate.isoformat()
            except ValueError:
                return None

    # Short follow-up in an active reschedule chain: «тогда на 23».
    m = re.search(r"\b(?:на|к)\s+(\d{1,2})\b", lowered) or re.search(r"^\s*(\d{1,2})\s*$", lowered)
    if m:
        day = int(m.group(1))
        month = (base or today).month
        year = (base or today).year
        try:
            candidate = datetime(year, month, day).date()
            if candidate < today:
                # If the inferred date is already in the past, move one month forward.
                next_month = month + 1
                next_year = year
                if next_month > 12:
                    next_month = 1
                    next_year += 1
                candidate = datetime(next_year, next_month, day).date()
            return candidate.isoformat()
        except ValueError:
            return None

    return None


def _looks_positive(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    return bool(is_positive_confirmation(text, BookingDraft()) or any(word in lowered for word in ("да", "подтверж", "подтаверж", "верно", "соглас", "включ", "хорошо", "ок")))


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