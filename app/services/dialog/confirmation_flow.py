from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from app.ai.errors import AIProviderUnavailable
from app.core.config import get_settings
from app.db.repositories import bookings_repo, payments_repo, slot_holds_repo
from app.services.availability_service import load_services_map
from app.services.booking_form_service import next_question
from app.services.dialog.booking_texts import (
    confirmation_reply_text,
    format_booking_summary,
    format_hold_summary,
    payment_reply_text,
)
from app.services.dialog.formatting import format_date_ru, format_duration


def mentions_payment_status(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if wants_fake_payment_simulation(text):
        return False
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
            "вносил предоплату",
            "вносила предоплату",
            "вносил оплат",
            "вносила оплат",
            "предоплата поступила",
            "предоплату поступила",
            "бронь оплачена",
            "бронь активна",
        )
    ) or ("предоплат" in normalized and any(marker in normalized for marker in ("внос", "поступ", "прош", "актив")))


def wants_fake_payment_simulation(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("оплат", "предоплат")):
        return False
    return any(
        marker in normalized
        for marker in (
            "будто",
            "как будто",
            "типа оплат",
            "сделай оплат",
            "сделать оплат",
            "можешь сделать",
            "можете сделать",
            "засчитай",
            "зачти",
            "нарисуй",
            "имитир",
            "тестово",
            "тестом",
        )
    )


def wants_payment_delay_or_hold_extension(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "оплачу позже",
            "позже оплачу",
            "оплачу через",
            "через пол час",
            "через час",
            "денег нет",
            "сейчас денег нет",
            "щас денег нет",
            "соберу с людей",
            "подождете",
            "подождите",
            "можете подождать",
            "резерв продл",
        )
    ) and any(marker in normalized for marker in ("оплат", "денег", "соберу", "подожд", "резерв"))


def wants_decline_unpaid_hold(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip(" .,!?:;")
    if not any(marker in normalized for marker in ("оплач", "оплат", "предоплат", "плат")):
        return False
    return any(
        marker in normalized
        for marker in (
            "не хочу оплач",
            "не буду оплач",
            "не хочу платить",
            "не буду платить",
            "платить не буду",
            "оплачивать не буду",
            "оплату не буду",
            "предоплату не буду",
            "не надо оплач",
            "не нужно оплач",
            "не стану оплач",
            "отказываюсь оплач",
            "передумал оплач",
            "передумала оплач",
            "без оплаты",
            "без предоплаты",
        )
    )


def wants_resume_expired_hold(text: str) -> bool:
    normalized = re.sub(r"[^\w]+", " ", text.lower().replace("ё", "е")).strip()
    if normalized in {"давайте", "давай", "актуально", "еще актуально", "ещё актуально", "оформляем", "оформим"}:
        return True
    return any(
        marker in normalized
        for marker in (
            "давай ее же",
            "давайте ее же",
            "ее же оформ",
            "эту же оформ",
            "тот же слот",
            "ту же брон",
            "та же брон",
            "все еще актуально",
            "всё еще актуально",
            "все еще хочу",
            "всё еще хочу",
        )
    )


def restore_form_from_expired_hold(form_data: dict[str, Any], hold: dict[str, Any]) -> dict[str, Any]:
    restored = dict(form_data)
    restored["service_type"] = hold.get("service_type") or restored.get("service_type")
    if hold.get("slot_date"):
        restored["date"] = hold["slot_date"].isoformat()
    if hold.get("slot_time"):
        restored["time"] = str(hold["slot_time"])[:5]
    duration = hold.get("duration_minutes")
    if duration:
        restored["duration"] = int(duration) // 60
    restored["payment_status"] = "not_required_yet"
    restored.pop("cancel_flow", None)
    restored.pop("reschedule_flow", None)
    restored.pop("swap_reschedule_flow", None)
    return restored


def is_non_slot_detail_change(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    detail_markers = (
        "имя",
        "зовут",
        "телефон",
        "номер",
        "гост",
        "человек",
        "доп",
        "кальян",
        "уголь",
        "розжиг",
        "решет",
        "шампур",
        "посуд",
        "лед",
        "вода",
        "формат",
    )
    if not any(marker in normalized for marker in detail_markers):
        return False
    slot_markers = (
        "дат",
        "сегодня",
        "завтра",
        "послезавтра",
        "суббот",
        "воскрес",
        "понедель",
        "вторник",
        "сред",
        "четверг",
        "пятниц",
        "время",
        "час",
        "беседк",
        "бан",
        "дом",
        "перенес",
        "перенест",
    )
    if any(marker in normalized for marker in slot_markers) and not any(
        marker in normalized
        for marker in (
            "имя",
            "зовут",
            "телефон",
            "номер",
            "гост",
            "человек",
            "доп",
            "кальян",
            "уголь",
            "розжиг",
            "решет",
            "шампур",
            "посуд",
            "лед",
            "вода",
            "формат",
        )
    ):
        return False
    return True


def wants_cancel_or_change_hold(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if is_non_slot_detail_change(text):
        return False
    return any(marker in normalized for marker in ("отмен", "убер", "помен", "замен", "вместо", "перенес"))


def _wants_time_change_without_value(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return (
        any(marker in normalized for marker in ("помен", "измени", "изменить", "исправ", "замен"))
        and any(marker in normalized for marker in ("время", "час", "период", "слот"))
    )


def hold_object_title(hold: dict[str, Any]) -> str:
    service_type = hold.get("service_type")
    config = load_services_map().get(service_type) or {}
    title = config.get("title") or service_type or "бронь"
    service_id = str(hold.get("yclients_service_id") or "").strip()
    for variant in config.get("variants") or []:
        if service_id and str(variant.get("yclients_service_id") or "").strip() == service_id:
            return str(variant.get("title") or title)
    return str(title)


def expired_hold_inline_reply(holds: list[dict[str, Any]]) -> str:
    hold_ttl_minutes = get_settings().hold_ttl_minutes
    if not holds:
        return (
            f"Резерв истёк: предоплата не поступила в течение {hold_ttl_minutes} минут.\n\n"
            "Слот снова доступен. Если всё ещё актуально, напишите — проверю свободность заново ✅"
        )
    lines = [f"Резерв истёк: предоплата не поступила в течение {hold_ttl_minutes} минут."]
    for hold in holds[:3]:
        date_text = format_date_ru(hold.get("slot_date"))
        time_text = str(hold.get("slot_time") or "")[:5]
        duration = format_duration(hold.get("duration_minutes"))
        lines.append(f"- {hold_object_title(hold)}: {date_text}, с {time_text} на {duration}")
    lines.append("")
    lines.append("Слот снова доступен. Если всё ещё актуально, напишите — проверю свободность заново ✅")
    return "\n".join(lines)


def pending_payment_for_holds(conn, conversation_id: int, hold_ids: list[int]) -> dict[str, Any] | None:
    wanted = {int(item) for item in hold_ids}
    if not wanted:
        return None
    for payment in payments_repo.list_for_conversation(conn, conversation_id=conversation_id):
        if payment.get("status") not in {"pending", "waiting_for_capture"}:
            continue
        raw_payload = payment.get("raw_payload") or {}
        if not isinstance(raw_payload, dict):
            continue
        payment_hold_ids = {
            int(item)
            for item in raw_payload.get("hold_ids") or []
            if str(item).isdigit()
        }
        if payment_hold_ids == wanted and payment.get("payment_url"):
            return payment
    return None


def pending_payments_for_holds(conn, conversation_id: int, hold_ids: list[int]) -> list[dict[str, Any]]:
    wanted = {int(item) for item in hold_ids}
    if not wanted:
        return []
    result: list[dict[str, Any]] = []
    for payment in payments_repo.list_for_conversation(conn, conversation_id=conversation_id):
        if payment.get("status") not in {"pending", "waiting_for_capture"}:
            continue
        raw_payload = payment.get("raw_payload") or {}
        if not isinstance(raw_payload, dict):
            continue
        payment_hold_ids = {
            int(item)
            for item in raw_payload.get("hold_ids") or []
            if str(item).isdigit()
        }
        if payment_hold_ids and payment_hold_ids <= wanted:
            result.append(payment)
    return result


def _unpaid_hold_cancel_prompt() -> str:
    return (
        "Поняла, без предоплаты бронь не закрепляется.\n\n"
        "Снять предварительную заявку и освободить слот? Если хотите подобрать другой вариант, "
        "напишите «да» — после этого начнём новую заявку."
    )


def _start_unpaid_hold_cancel_flow(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    active_holds: list[dict[str, Any]],
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    hold_ids = [int(hold["id"]) for hold in active_holds]
    pending_payments = pending_payments_for_holds(conn, int(conversation["id"]), hold_ids)
    updated = {
        **form_data,
        "unpaid_hold_cancel_flow": {
            "stage": "confirm_cancel",
            "hold_ids": hold_ids,
            "payment_ids": [int(payment["id"]) for payment in pending_payments],
        },
        "cancel_flow": None,
        "reschedule_flow": None,
        "swap_reschedule_flow": None,
    }
    return _unpaid_hold_cancel_prompt(), "reserved", "reserved", "payment_status", updated


def _handle_unpaid_hold_cancel_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    active_holds: list[dict[str, Any]],
    now: datetime,
    callbacks: ReservedHoldCallbacks,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    flow = dict(form_data.get("unpaid_hold_cancel_flow") or {})
    hold_ids = [int(item) for item in flow.get("hold_ids") or [] if str(item).isdigit()]
    if not hold_ids:
        hold_ids = [int(hold["id"]) for hold in active_holds]
    active_hold_ids = {int(hold["id"]) for hold in active_holds}
    cancellable_hold_ids = [hold_id for hold_id in hold_ids if hold_id in active_hold_ids]

    if callbacks.confirmation_no(text):
        updated = {**form_data, "unpaid_hold_cancel_flow": None}
        return (
            "Хорошо, предварительную заявку оставила без изменений ✅\n\n"
            "Если решите закрепить бронь, оплатите по ссылке выше до окончания резерва.",
            "reserved",
            "reserved",
            "payment_status",
            updated,
        )

    normalized = text.lower().replace("ё", "е")
    if not (
        callbacks.confirmation_yes(text)
        or wants_decline_unpaid_hold(text)
        or any(marker in normalized for marker in ("снять заявку", "сними заявку", "освободить слот", "подобрать другой", "другой вариант"))
    ):
        updated = {**form_data, "unpaid_hold_cancel_flow": flow | {"stage": "confirm_cancel", "hold_ids": hold_ids}}
        return _unpaid_hold_cancel_prompt(), "reserved", "reserved", "payment_status", updated

    if cancellable_hold_ids:
        slot_holds_repo.cancel_ids(conn, hold_ids=cancellable_hold_ids, now=now)
    pending_payments = pending_payments_for_holds(conn, int(conversation["id"]), cancellable_hold_ids or hold_ids)
    for payment in pending_payments:
        raw_payload = payment.get("raw_payload") or {}
        if not isinstance(raw_payload, dict):
            raw_payload = {}
        payments_repo.mark_superseded(
            conn,
            payment_id=int(payment["id"]),
            raw_payload=raw_payload | {
                "state": "superseded_by_client_declined_prepayment",
                "cancelled_hold_ids": cancellable_hold_ids,
            },
        )

    cleaned = callbacks.new_booking_form_data(form_data)
    return (
        "Сняла предварительную заявку ✅\n\n"
        "Без предоплаты бронь не закрепляется. Если хотите подобрать другой вариант, напишите услугу и дату.",
        "waiting_user",
        "service_type",
        "service_type",
        cleaned,
    )


def reply_with_hold_summary(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
    *,
    active_user_bookings: Callable[[Any, dict[str, Any], dict[str, Any], datetime], list[dict[str, Any]]],
    prefix: str | None = None,
) -> str:
    slot_holds_repo.expire_old(conn, now)
    holds = slot_holds_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation["id"],
        now=now,
    )
    bookings = active_user_bookings(conn, conversation, form_data, now)
    if not holds:
        message = (
            format_booking_summary(bookings)
            if bookings
            else "Сейчас активных предварительных заявок не осталось. Можем оформить новую бронь."
        )
        return f"{prefix}\n\n{message}" if prefix else message
    summary = format_hold_summary(holds, form_data)
    if bookings:
        summary = f"{format_booking_summary(bookings)}\n\nСейчас дополнительно в резерве:\n{summary}"
    return f"{prefix}\n\n{summary}" if prefix else summary


@dataclass(frozen=True)
class ReservedHoldCallbacks:
    active_user_bookings: Callable[[Any, dict[str, Any], dict[str, Any], datetime], list[dict[str, Any]]]
    asks_booking_summary: Callable[[str], bool]
    has_user_bookings: Callable[[Any, dict[str, Any], dict[str, Any], datetime], bool]
    post_booking_summary: Callable[[Any, dict[str, Any], dict[str, Any], datetime], str]
    new_booking_form_data: Callable[[dict[str, Any]], dict[str, Any]]
    wants_cancel_booking: Callable[[str], bool]
    wants_reschedule: Callable[[str], bool]
    start_cancel_booking_flow: Callable[..., tuple[str, str, str, str | None, dict[str, Any]]]
    start_reschedule_flow: Callable[..., tuple[str, str, str, str | None, dict[str, Any]]]
    form_detail_correction_patch: Callable[[str, dict[str, Any]], dict[str, Any]]
    last_assistant_asked_name_correction: Callable[[list[dict[str, Any]]], bool]
    looks_like_name: Callable[[str], bool]
    merge_form_data: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    correction_ack_text: Callable[[dict[str, Any]], str]
    maybe_name_correction_without_value: Callable[[str], bool]
    confirmation_yes: Callable[[str], bool]
    confirmation_no: Callable[[str], bool]
    service_type_patch: Callable[[str], dict[str, Any]]
    date_patch_after_marker: Callable[[str, datetime, str], dict[str, Any]]
    relative_date_patch: Callable[[str, datetime], dict[str, Any]]
    check_availability: Callable[..., Any]
    reset_unavailable_slot: Callable[[dict[str, Any]], dict[str, Any]]
    create_hold: Callable[[Any, dict[str, Any], dict[str, Any], dict[str, Any], datetime], dict[str, Any]]
    create_payment_link_for_holds: Callable[..., Any]
    log_payment_link_exception: Callable[[str, Any], None]


@dataclass(frozen=True)
class FlowResult:
    reply: str
    status: str
    current_step: str
    next_step: str | None
    form_data: dict[str, Any]
    intent: str | None = None


@dataclass(frozen=True)
class AwaitingConfirmationCallbacks:
    form_detail_correction_patch: Callable[[str, dict[str, Any]], dict[str, Any]]
    last_assistant_asked_name_correction: Callable[[list[dict[str, Any]]], bool]
    looks_like_name: Callable[[str], bool]
    merge_form_data: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    normalize_service_aliases: Callable[[dict[str, Any]], dict[str, Any]]
    normalize_gazebo_variant: Callable[[dict[str, Any]], dict[str, Any]]
    apply_gazebo_default_duration: Callable[..., dict[str, Any]]
    gazebo_open_ended_duration_requested: Callable[[str], bool]
    check_availability: Callable[..., Any]
    no_availability_reply: Callable[[dict[str, Any]], tuple[str, str | None]]
    remember_waitlist_request: Callable[..., Any]
    append_waitlist_offer: Callable[[str, dict[str, Any]], str]
    reset_unavailable_slot: Callable[[dict[str, Any]], dict[str, Any]]
    remember_available_gazebo_variants: Callable[[dict[str, Any], list[Any]], dict[str, Any]]
    auto_select_single_available_gazebo: Callable[[dict[str, Any]], dict[str, Any]]
    correction_ack_text: Callable[[dict[str, Any]], str]
    maybe_name_correction_without_value: Callable[[str], bool]
    confirmation_yes: Callable[[str], bool]
    confirmation_no: Callable[[str], bool]
    create_hold: Callable[[Any, dict[str, Any], dict[str, Any], dict[str, Any], datetime], dict[str, Any]]
    create_payment_link_for_holds: Callable[..., Any]
    hold_ttl_minutes: int
    side_reply: Callable[..., str]
    log_ai_provider_unavailable: Callable[..., None]
    log_payment_link_exception: Callable[[str, Any], None]


def handle_reserved_hold_command(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    history: list[dict[str, Any]] | None,
    callbacks: ReservedHoldCallbacks,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    form_data = conversation.get("form_data") or {}
    asks_summary = callbacks.asks_booking_summary(text)
    wants_cancel_or_change = wants_cancel_or_change_hold(text)
    hold_context = (
        conversation.get("current_step") in {"reserved", "payment_status"}
        or conversation.get("status") in {"reserved", "payment_paid"}
    )
    slot_holds_repo.expire_old(conn, now)
    active_holds = slot_holds_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation["id"],
        now=now,
    )
    if not active_holds:
        if hold_context and form_data.get("unpaid_hold_cancel_flow"):
            flow = dict(form_data.get("unpaid_hold_cancel_flow") or {})
            hold_ids = [int(item) for item in flow.get("hold_ids") or [] if str(item).isdigit()]
            normalized = text.lower().replace("ё", "е")
            if (
                callbacks.confirmation_yes(text)
                or wants_decline_unpaid_hold(text)
                or any(marker in normalized for marker in ("снять заявку", "сними заявку", "освободить слот", "подобрать другой", "другой вариант"))
            ):
                for payment in pending_payments_for_holds(conn, int(conversation["id"]), hold_ids):
                    raw_payload = payment.get("raw_payload") or {}
                    if not isinstance(raw_payload, dict):
                        raw_payload = {}
                    payments_repo.mark_superseded(
                        conn,
                        payment_id=int(payment["id"]),
                        raw_payload=raw_payload | {
                            "state": "superseded_by_client_declined_expired_prepayment",
                            "cancelled_hold_ids": [],
                            "expired_hold_ids": hold_ids,
                        },
                    )
                cleaned = callbacks.new_booking_form_data(form_data)
                return (
                    "Предварительная заявка уже не активна, ссылку на предоплату закрыла в этой заявке.\n\n"
                    "Если хотите подобрать другой вариант, напишите услугу и дату.",
                    "waiting_user",
                    "service_type",
                    "service_type",
                    cleaned,
                )
            cleaned = callbacks.new_booking_form_data(form_data)
            return (
                "Предварительная заявка уже не активна: резерв не найден или истёк.\n\n"
                "Если хотите подобрать другой вариант, напишите услугу и дату.",
                "waiting_user",
                "service_type",
                "service_type",
                cleaned,
            )
        expired_holds = slot_holds_repo.list_expired_for_conversation(
            conn,
            conversation_id=conversation["id"],
            limit=5,
        )
        unnotified_expired = [hold for hold in expired_holds if not hold.get("expired_notified_at")]
        if hold_context and unnotified_expired and not callbacks.has_user_bookings(conn, conversation, form_data, now):
            for hold in unnotified_expired:
                slot_holds_repo.mark_expired_notified(conn, hold_id=hold["id"], now=now)
            cleaned = callbacks.new_booking_form_data(form_data)
            return (
                expired_hold_inline_reply(unnotified_expired),
                "waiting_user",
                "service_type",
                "service_type",
                cleaned,
            )
        if form_data.get("reschedule_flow") or form_data.get("swap_reschedule_flow"):
            return None
        if hold_context and expired_holds and wants_resume_expired_hold(text):
            restored = restore_form_from_expired_hold(form_data, expired_holds[0])
            availability = callbacks.check_availability(conn, form_data=restored, now=now)
            next_key = next_question(restored)[0]
            if availability.ok and availability.slots and not next_key:
                return (
                    confirmation_reply_text(restored),
                    "awaiting_confirmation",
                    "awaiting_confirmation",
                    "confirmation",
                    restored,
                )
            next_key = next_key or "guests_count"
            service_title = "Баня" if restored.get("service_type") == "bathhouse" else "Бронь"
            return (
                f"{service_title}: прежний слот снова проверила. Продолжим ту же заявку.\n\n{next_question(restored)[1]}",
                "waiting_user",
                next_key,
                next_key,
                restored,
            )
        if asks_summary:
            summary = callbacks.post_booking_summary(conn, conversation, form_data, now)
            next_key = next_question(form_data)[0]
            return (
                summary,
                "waiting_user",
                next_key or conversation.get("current_step") or "waiting_user",
                next_key,
                form_data,
            )
        if wants_cancel_or_change:
            has_bookings = callbacks.has_user_bookings(conn, conversation, form_data, now)
            if has_bookings:
                if callbacks.wants_cancel_booking(text):
                    return callbacks.start_cancel_booking_flow(
                        conn,
                        conversation,
                        text,
                        form_data,
                        "payment_paid",
                        now,
                    )
                if callbacks.wants_reschedule(text):
                    return callbacks.start_reschedule_flow(
                        conn,
                        conversation,
                        text,
                        form_data,
                        "payment_paid",
                        now,
                    )
                return None
            if not hold_context:
                return None
            return (
                "Сейчас не вижу активной предварительной заявки, которую можно отменить или поменять. Можем оформить новую бронь.",
                "waiting_user",
                conversation.get("current_step") or "waiting_user",
                next_question(form_data)[0],
                form_data,
        )
        return None

    if form_data.get("unpaid_hold_cancel_flow"):
        return _handle_unpaid_hold_cancel_flow(
            conn,
            conversation,
            text,
            form_data,
            active_holds,
            now,
            callbacks,
        )

    if hold_context and wants_decline_unpaid_hold(text):
        return _start_unpaid_hold_cancel_flow(conn, conversation, form_data, active_holds)

    if wants_fake_payment_simulation(text):
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        return (
            "Я не могу отметить оплату «будто бы» вручную. "
            "Бронь закрепляется только когда реальный платёж отразится в ЮKassa.\n\n"
            "Резерв пока активен: оплатите по ссылке выше, и после оплаты я пришлю подтверждение брони ✅",
            status,
            "reserved",
            "payment_status",
            form_data,
        )

    if wants_payment_delay_or_hold_extension(text):
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        hold_ttl_minutes = get_settings().hold_ttl_minutes
        return (
            f"Понимаю. Резерв держится {hold_ttl_minutes} минут, поэтому надолго удержать слот без предоплаты не получится.\n\n"
            "Если успеете оплатить по ссылке — бронь закрепится автоматически. "
            "Если резерв истечёт, напишите «давайте» или «оформим эту же» — я заново проверю тот же слот.",
            status,
            "reserved",
            "payment_status",
            form_data,
        )

    if (
        not hold_context
        and not asks_summary
        and not wants_cancel_or_change
        and not callbacks.confirmation_yes(text)
        and not mentions_payment_status(text)
    ):
        return None

    if asks_summary:
        reply = reply_with_hold_summary(
            conn,
            conversation,
            form_data,
            now,
            active_user_bookings=callbacks.active_user_bookings,
        )
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        return reply, status, "reserved", "payment_status", form_data

    correction_patch = callbacks.form_detail_correction_patch(text, form_data)
    if not correction_patch and history and callbacks.last_assistant_asked_name_correction(history) and callbacks.looks_like_name(text):
        correction_patch = {"client_name": text.strip().title()}
    if correction_patch:
        old_hold_ids = [int(hold["id"]) for hold in active_holds]
        old_payment = pending_payment_for_holds(conn, conversation["id"], old_hold_ids)
        form_data = callbacks.merge_form_data(form_data, correction_patch)
        should_recreate_unpaid_hold = (
            len(active_holds) == 1
            and conversation.get("status") != "payment_paid"
            and bool({"service_type", "service_variant", "date", "time", "duration"} & set(correction_patch))
        )
        if should_recreate_unpaid_hold:
            availability = callbacks.check_availability(conn, form_data=form_data, now=now)
            if not availability.ok or not availability.slots:
                updated = callbacks.reset_unavailable_slot(form_data)
                return (
                    availability.message or "На новое время свободных вариантов не нашла. Напишите другую дату или время.",
                    "waiting_user",
                    "awaiting_new_slot",
                    next_question(updated)[0],
                    updated,
                )
            slot_holds_repo.cancel_ids(conn, hold_ids=old_hold_ids, now=now)
            try:
                new_hold = callbacks.create_hold(
                    conn,
                    conversation,
                    {"id": conversation["user_id"]},
                    form_data,
                    now,
                )
                payment = callbacks.create_payment_link_for_holds(
                    conn,
                    conversation_id=conversation["id"],
                    user_id=conversation["user_id"],
                    hold_ids=[int(new_hold["id"])],
                    client_name=str(form_data.get("client_name") or "Клиент"),
                    phone=str(form_data.get("phone") or ""),
                    force_new=True,
                    raw_payload_extra={
                        "replaces_payment_id": int(old_payment["id"]) if old_payment else None,
                        "state": "payment_link_recreated_after_hold_correction",
                    },
                )
            except Exception:
                callbacks.log_payment_link_exception("Payment link recreation failed conversation_id=%s", conversation["id"])
                payment = None
            if old_payment:
                raw_payload = old_payment.get("raw_payload") or {}
                if not isinstance(raw_payload, dict):
                    raw_payload = {}
                payments_repo.mark_superseded(
                    conn,
                    payment_id=int(old_payment["id"]),
                    raw_payload=raw_payload | {
                        "state": "superseded_by_hold_correction",
                        "superseded_by_payment_id": int(payment["id"]) if payment else None,
                    },
                )
            reply = (
                f"{callbacks.correction_ack_text(correction_patch)}\n\n"
                "Старый резерв отменила и поставила новый на обновлённые данные.\n\n"
                f"{payment_reply_text(payment)}"
            )
            return reply, "reserved", "reserved", "payment_status", form_data
        reply = (
            f"{callbacks.correction_ack_text(correction_patch)}\n\n"
            "Резерв оставила активным. Можно оплатить по ссылке, которую отправляла выше.\n\n"
            "После оплаты пришлю подтверждение брони ✅"
        )
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        return reply, status, "reserved", "payment_status", form_data
    if callbacks.maybe_name_correction_without_value(text):
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        return (
            "Поняла, поправим имя ✅\n\nКакое имя указать в брони?",
            status,
            "reserved",
            "payment_status",
            form_data,
        )

    if callbacks.confirmation_yes(text):
        hold_ids = [int(hold["id"]) for hold in active_holds]
        existing_payment = pending_payment_for_holds(conn, conversation["id"], hold_ids)
        if existing_payment:
            return (
                "Ссылка на предоплату уже создана ✅\n\n"
                f"{payment_reply_text(existing_payment)}",
                "reserved",
                "reserved",
                "payment_status",
                form_data,
            )
        try:
            payment = callbacks.create_payment_link_for_holds(
                conn,
                conversation_id=conversation["id"],
                user_id=conversation["user_id"],
                hold_ids=hold_ids,
                client_name=str(form_data.get("client_name") or "Клиент"),
                phone=str(form_data.get("phone") or ""),
            )
        except Exception:
            callbacks.log_payment_link_exception("Payment link creation failed conversation_id=%s", conversation["id"])
            payment = None
        return payment_reply_text(payment), "reserved", "reserved", "payment_status", form_data

    if not wants_cancel_or_change:
        normalized = text.lower().replace("ё", "е")
        if any(marker in normalized for marker in ("зачем", "не понял", "не понимаю")):
            reply = reply_with_hold_summary(
                conn,
                conversation,
                form_data,
                now,
                active_user_bookings=callbacks.active_user_bookings,
                prefix="Извините, я сбился с контекста. Новую дату писать не нужно.",
            )
            status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
            return reply, status, "reserved", "payment_status", form_data
        return None

    service_type = (callbacks.service_type_patch(text) or {}).get("service_type")
    cancel_date = callbacks.date_patch_after_marker(text, now, "вместо").get("date")
    explicit_date = callbacks.relative_date_patch(text, now).get("date")
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
        availability = callbacks.check_availability(conn, form_data=new_form, now=now)
        if availability.ok and availability.slots:
            reply = confirmation_reply_text(new_form)
            return reply, "awaiting_confirmation", "awaiting_confirmation", "confirmation", new_form
        prefix = "Старую дату убрал." if cancelled else "Понял, проверил новую дату."
        return (
            f"{prefix} На {format_date_ru(replacement_date)} свободных вариантов не нашёл. Напишите другую дату.",
            "waiting_user",
            "awaiting_new_date",
            "date",
            callbacks.reset_unavailable_slot(new_form),
        )

    prefix = "Отменил выбранную позицию." if cancelled else "Не нашёл такую активную позицию для отмены."
    reply = reply_with_hold_summary(
        conn,
        conversation,
        form_data,
        now,
        active_user_bookings=callbacks.active_user_bookings,
        prefix=prefix,
    )
    status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
    return reply, status, "reserved", "payment_status", form_data


def handle_awaiting_confirmation(
    conn,
    conversation: dict[str, Any],
    user: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
    now: datetime,
    callbacks: AwaitingConfirmationCallbacks,
) -> FlowResult:
    form_data = conversation.get("form_data") or {}
    if callbacks.confirmation_no(text) and not _looks_like_explicit_upsell_correction(text):
        return FlowResult(
            reply="Хорошо, что нужно изменить: дату, время, объект, гостей, допы или отменить заявку?",
            status="waiting_user",
            current_step="change_booking",
            next_step=None,
            form_data=form_data,
        )

    correction_patch = callbacks.form_detail_correction_patch(text, form_data)
    if not correction_patch and callbacks.last_assistant_asked_name_correction(history) and callbacks.looks_like_name(text):
        correction_patch = {"client_name": text.strip().title()}
    if correction_patch:
        form_data = callbacks.merge_form_data(form_data, correction_patch)
        form_data = callbacks.normalize_service_aliases(form_data)
        if form_data.get("service_type") != "gazebo":
            form_data["service_variant"] = None
        form_data = callbacks.normalize_gazebo_variant(form_data)
        form_data = callbacks.apply_gazebo_default_duration(
            form_data,
            force=callbacks.gazebo_open_ended_duration_requested(text),
        )
        if {"service_type", "service_variant", "date", "time", "duration"} & set(correction_patch):
            availability = callbacks.check_availability(conn, form_data=form_data, now=now)
            if availability.ok and not availability.slots:
                required, next_key = callbacks.no_availability_reply(form_data)
                callbacks.remember_waitlist_request(
                    conn,
                    conversation_id=conversation["id"],
                    user_id=user["id"],
                    form_data=form_data,
                )
                reply = callbacks.append_waitlist_offer(required, form_data)
                return FlowResult(
                    reply=reply,
                    status="waiting_user",
                    current_step="awaiting_new_date",
                    next_step=next_key,
                    form_data=callbacks.reset_unavailable_slot(form_data),
                    intent="change_booking",
                )
            form_data = callbacks.remember_available_gazebo_variants(form_data, availability.slots)
            form_data = callbacks.auto_select_single_available_gazebo(form_data)
        reply = f"{callbacks.correction_ack_text(correction_patch)}\n\n{confirmation_reply_text(form_data)}"
        return FlowResult(
            reply=reply,
            status="awaiting_confirmation",
            current_step="awaiting_confirmation",
            next_step="confirmation",
            form_data=form_data,
            intent="change_booking",
        )

    if callbacks.maybe_name_correction_without_value(text):
        return FlowResult(
            reply="Поняла, поправим имя ✅\n\nКакое имя указать в брони?",
            status="awaiting_confirmation",
            current_step="awaiting_confirmation",
            next_step="confirmation",
            form_data=form_data,
            intent="change_booking",
        )

    if _wants_time_change_without_value(text):
        return FlowResult(
            reply=(
                "Поняла, поменяем время.\n\n"
                "Напишите новый период, например: с 18:00 до 00:00. "
                "Если нужно до утра, можно написать: с 11:00 до 08:00 следующего дня."
            ),
            status="awaiting_confirmation",
            current_step="awaiting_confirmation",
            next_step="confirmation",
            form_data=form_data,
            intent="change_booking",
        )

    if callbacks.confirmation_yes(text):
        availability = callbacks.check_availability(conn, form_data=form_data, now=now)
        if availability.ok and availability.slots:
            try:
                hold = callbacks.create_hold(conn, conversation, user, form_data, now)
            except slot_holds_repo.SlotHoldConflict:
                callbacks.remember_waitlist_request(
                    conn,
                    conversation_id=conversation["id"],
                    user_id=user["id"],
                    form_data=form_data,
                )
                reply = (
                    "Этот слот только что заняли, поэтому я не буду отправлять ссылку на оплату для уже занятого времени.\n\n"
                    "Напишите, пожалуйста, другое время или дату — сразу проверю свободные варианты ✅"
                )
                return FlowResult(
                    reply=reply,
                    status="waiting_user",
                    current_step="awaiting_new_slot",
                    next_step="date",
                    form_data=callbacks.reset_unavailable_slot(form_data),
                )
            active_holds = slot_holds_repo.list_active_for_conversation(
                conn,
                conversation_id=conversation["id"],
                now=now,
            )
            reply = (
                f"Отлично, предварительно зарезервировал выбранный вариант на "
                f"{callbacks.hold_ttl_minutes} минут.\n\n"
                f"{format_hold_summary(active_holds, form_data)}"
            )
            try:
                payment = callbacks.create_payment_link_for_holds(
                    conn,
                    conversation_id=conversation["id"],
                    user_id=user["id"],
                    hold_ids=[hold["id"]],
                    client_name=str(form_data.get("client_name") or user.get("name") or "Клиент"),
                    phone=str(form_data.get("phone") or user.get("phone") or ""),
                )
            except Exception:
                callbacks.log_payment_link_exception("Payment link creation failed conversation_id=%s", conversation["id"])
                payment = None
            return FlowResult(
                reply=f"{reply}\n\n{payment_reply_text(payment)}",
                status="reserved",
                current_step="reserved",
                next_step="payment_status",
                form_data=form_data,
            )

        if _duration_validation_message(availability.message):
            updated = dict(form_data)
            updated["duration"] = None
            updated.pop("last_unavailable", None)
            return FlowResult(
                reply=availability.message,
                status="waiting_user",
                current_step="duration",
                next_step="duration",
                form_data=updated,
            )

        if _capacity_validation_message(availability.message):
            updated = dict(form_data)
            updated["guests_count"] = None
            updated.pop("last_unavailable", None)
            return FlowResult(
                reply=availability.message,
                status="waiting_user",
                current_step="guests_count",
                next_step="guests_count",
                form_data=updated,
            )

        callbacks.remember_waitlist_request(
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
        return FlowResult(
            reply=reply,
            status="waiting_user",
            current_step="awaiting_new_date",
            next_step="date",
            form_data=callbacks.reset_unavailable_slot(form_data),
        )

    if callbacks.confirmation_no(text):
        return FlowResult(
            reply="Хорошо, что нужно изменить: дату, время, объект, гостей, допы или отменить заявку?",
            status="waiting_user",
            current_step="change_booking",
            next_step=None,
            form_data=form_data,
        )

    try:
        reply = callbacks.side_reply(
            text=text,
            form_data=form_data,
            history=history,
        )
    except AIProviderUnavailable as exc:
        callbacks.log_ai_provider_unavailable(
            conn,
            conversation_id=conversation["id"],
            exc=exc,
            text=text,
            form_data=form_data,
        )
        reply = (
            "Заявка пока ожидает подтверждения. "
            "Если всё верно, напишите «да». Если нужно что-то поменять — напишите, что именно изменить."
        )
    return FlowResult(
        reply=reply,
        status="awaiting_confirmation",
        current_step="awaiting_confirmation",
        next_step="confirmation",
        form_data=form_data,
        intent="confirmation_side_question",
    )


def _duration_validation_message(message: str) -> bool:
    lowered = message.lower().replace("ё", "е")
    return message.startswith("Для «") and ("длительность" in lowered or "фиксирован" in lowered)


def _capacity_validation_message(message: str) -> bool:
    lowered = message.lower().replace("ё", "е")
    return "слишком большая компания" in lowered or "не оформляю больше чем" in lowered


def _looks_like_explicit_upsell_correction(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "доп",
            "уголь",
            "розжиг",
            "решет",
            "решот",
            "шампур",
            "лед",
            "лёд",
            "посуд",
            "кальян",
            "вода",
            "уберите",
            "убрать",
            "не готовьте",
            "ниче не готовьте",
            "ничего не готовьте",
            "все с собой",
            "всё с собой",
        )
    )


def create_hold(
    conn,
    conversation: dict[str, Any],
    user: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
    *,
    selected_variant_config: Callable[[dict[str, Any]], dict[str, Any]],
    duration_minutes_value: Callable[[Any], int],
    hold_ttl_minutes: int,
) -> dict[str, Any]:
    slot_date = datetime.fromisoformat(str(form_data["date"])).date()
    slot_time = datetime.strptime(str(form_data["time"])[:5], "%H:%M").time()
    variant = selected_variant_config(form_data)
    return slot_holds_repo.create(
        conn,
        conversation_id=conversation["id"],
        user_id=user["id"],
        service_type=form_data["service_type"],
        yclients_service_id=str(variant.get("yclients_service_id") or ""),
        yclients_staff_id=str(variant.get("yclients_staff_id") or ""),
        slot_date=slot_date,
        slot_time=slot_time,
        duration_minutes=duration_minutes_value(form_data.get("duration")),
        expires_at=now + timedelta(minutes=hold_ttl_minutes),
    )


def create_booking_from_hold(
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


def awaiting_confirmation_side_reply(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    looks_like_info_question: Callable[..., bool],
    deterministic_info_reply: Callable[[str, dict[str, Any]], str | None],
    ai_process_reply: Callable[..., str],
) -> str:
    if looks_like_info_question(text):
        deterministic = deterministic_info_reply(text, form_data)
        if deterministic:
            return deterministic
        required = (
            "Клиент задал вопрос, пока заявка ожидает финального подтверждения. "
            "Ответь на вопрос по базе знаний честно и кратко. "
            "Не повторяй всю анкету. В конце мягко напомни: если по заявке всё верно, "
            "можно подтвердить бронь словом «да», а если нужно что-то изменить — пусть напишет, что именно."
        )
        return ai_process_reply(
            text=text,
            form_data=form_data,
            history=history,
            required_meaning=required,
        )
    return (
        "Понял. Заявка пока ожидает подтверждения. "
        "Если всё верно, напишите «да». Если нужно что-то поменять — напишите, что именно изменить."
    )
