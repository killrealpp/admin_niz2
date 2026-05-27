import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.ai.ai_orchestrator import (
    call_ai as _call_ai_impl,
    classify_post_booking_message as _classify_post_booking_message_impl,
    generate_process_reply as _generate_process_reply_impl,
)
from app.ai.errors import AIProviderUnavailable
from app.core.config import get_settings
from app.core.constants import SENDER_ASSISTANT, SENDER_USER
from app.db.connection import get_connection
from app.db.repositories import (
    bookings_repo,
    conversations_repo,
    messages_repo,
    payments_repo,
    slot_holds_repo,
    system_logs_repo,
    users_repo,
    waitlist_repo,
)
from app.services.availability_service import check_availability as _check_availability_impl, load_services_map
from app.services.booking_form_service import merge_form_data, next_question
from app.services.conversation_service import get_or_create_conversation
from app.services.dialog.booking_context import (
    active_user_bookings as _active_user_bookings,
    as_post_booking_conversation as _as_post_booking_conversation,
    context_summaries as _context_summaries,
    conversation_bookings_for_active_flow as _conversation_bookings_for_active_flow,
    has_user_bookings as _has_user_bookings,
)
from app.services.dialog.date_parsing import (
    bare_day_patch as _bare_day_patch,
    bare_weekday_candidate as _bare_weekday_candidate,
    bare_weekday_confirmation as _bare_weekday_confirmation,
    date_patch_after_marker as _date_patch_after_marker,
    date_patch_in_segment as _date_patch_in_segment,
    has_date_signal as _has_date_signal,
    last_explicit_date_patch as _last_explicit_date_patch,
    relative_date_patch as _relative_date_patch,
    reschedule_source_target_day_patch as _reschedule_source_target_day_patch,
)
from app.services.dialog.formatting import (
    duration_minutes_value as _duration_minutes_value,
    format_date_ru as _format_date_ru,
    format_duration as _format_duration,
    format_rub as _format_rub,
    hours_from_minutes as _hours_from_minutes,
)
from app.services.dialog.fresh_start import (
    ai_should_start_fresh_booking as _ai_should_start_fresh_booking_decision,
    should_start_fresh_booking as _should_start_fresh_booking_decision,
)
from app.services.dialog.form_corrections import (
    correction_ack_text as _correction_ack_text,
    extract_corrected_client_name as _extract_corrected_client_name,
    maybe_name_correction_without_value as _maybe_name_correction_without_value,
)
from app.services.dialog.form_patches import (
    client_name_patch as _client_name_patch,
    event_format_patch as _event_format_patch,
    explicit_new_service_request as _explicit_new_service_request,
    guests_count_patch as _guests_count_patch,
    has_upsell_signal as _has_upsell_signal,
    is_upsell_negative as _is_upsell_negative,
    join_preferences as _join_preferences,
    looks_like_name as _looks_like_name,
    looks_like_prior_booking_reference_text as _looks_like_prior_booking_reference_text,
    looks_like_same_date_reference_text as _looks_like_same_date_reference_text,
    looks_like_same_time_reference_text as _looks_like_same_time_reference_text,
    normalize_service_aliases as _normalize_service_aliases,
    phone_patch as _phone_patch,
    service_type_patch as _service_type_patch,
    service_variant_patch as _service_variant_patch,
    upsell_items_patch as _upsell_items_patch,
    upsell_push_reply as _upsell_push_reply,
    valid_phone as _valid_phone,
)
from app.services.dialog.gazebo_options import (
    auto_select_single_available_gazebo as _auto_select_single_available_gazebo,
    available_gazebo_titles as _available_gazebo_titles,
    available_gazebo_variant_configs as _available_gazebo_variant_configs,
    clear_available_gazebo_variants as _clear_available_gazebo_variants,
    format_gazebo_variant_line as _format_gazebo_variant_line,
    gazebo_budget_selection_text as _gazebo_budget_selection_text,
    gazebo_selection_text as _gazebo_selection_text,
    gazebo_title_from_slot as _gazebo_title_from_slot,
    looks_like_gazebo_budget_preference as _looks_like_gazebo_budget_preference,
    normalize_gazebo_title as _normalize_gazebo_title,
    normalize_gazebo_variant as _normalize_gazebo_variant,
    remember_available_gazebo_variants as _remember_available_gazebo_variants,
    selected_gazebo_capacity_issue as _selected_gazebo_capacity_issue,
    selected_variant_config as _selected_variant_config,
    suitable_available_gazebo_titles as _suitable_available_gazebo_titles,
    suitable_gazebo_slots as _suitable_gazebo_slots,
)
from app.services.dialog.booking_texts import (
    booking_line_short as _booking_line_short,
    booking_object_title as _booking_object_title,
    confirmation_reply_text as _confirmation_reply_text,
    format_booking_summary as _format_booking_summary,
    format_hold_summary as _format_hold_summary,
    handoff_reply as _handoff_reply,
    payment_reply_text as _payment_reply_text,
)
from app.services.dialog.cancel_flow import (
    cancel_confirmation_reply as _cancel_confirmation_reply,
    cancel_done_reply as _cancel_done_reply,
    cancel_many_confirmation_reply as _cancel_many_confirmation_reply,
    cancel_many_done_reply as _cancel_many_done_reply,
    cancel_selection_prompt as _cancel_selection_prompt,
    select_cancel_bookings as _select_cancel_bookings,
    wants_cancel_booking as _wants_cancel_booking,
)
from app.services.dialog.handoff import (
    handoff_active as _handoff_active,
    is_location_question as _is_location_question,
    looks_like_handoff_needed as _looks_like_handoff_needed,
    start_user_handoff as _start_user_handoff,
)
from app.services.dialog.price_info import (
    addon_price_reply as _addon_price_reply,
    looks_like_forbidden_broom_request as _looks_like_forbidden_broom_request,
    looks_like_price_question_text as _looks_like_price_question_text,
    policy_or_common_info_reply as _policy_or_common_info_reply,
    price_reply_if_known as _price_reply_if_known_impl,
)
from app.services.dialog.performance import trace_message_handler, trace_span
from app.services.dialog.response_builder import (
    deterministic_process_reply as _deterministic_process_reply,
    fallback_process_reply as _fallback_process_reply,
    looks_like_internal_instruction_text as _looks_like_internal_instruction_text,
)
from app.services.dialog.routing_guards import (
    asks_for_free_slots as _asks_for_free_slots,
    asks_nearest_free_dates as _asks_nearest_free_dates,
)
from app.services.dialog.semantic_router import build_semantic_router_knowledge as _build_semantic_router_knowledge
from app.services.dialog.stale_form import (
    new_booking_form_data as _new_booking_form_data,
    should_offer_stale_form_choice as _should_offer_stale_form_choice,
    stale_form_choice_reply as _stale_form_choice_reply,
)
from app.services.dialog.time_parsing import (
    apply_gazebo_default_duration as _apply_gazebo_default_duration,
    bare_duration_from_text as _bare_duration_from_text,
    duration_from_text as _duration_from_text,
    gazebo_open_ended_duration_requested as _gazebo_open_ended_duration_requested,
    period_conflict as _period_conflict,
    single_time_patch as _single_time_patch,
    time_period_patch as _time_period_patch,
)
from app.services.knowledge_service import load_knowledge
from app.services.media_service import is_explicit_photo_request, media_for_client_message
from app.services.payment_service import (
    create_payment_link_for_bookings as _create_payment_link_for_bookings_impl,
    create_payment_link_for_holds as _create_payment_link_for_holds_impl,
    sync_payment_statuses as _sync_payment_statuses_impl,
)
from app.services.user_service import get_or_create_user
from app.services.waitlist_service import remember_waitlist_request
from app.services.yclients_record_service import (
    create_missing_yclients_records as _create_missing_yclients_records_impl,
    create_yclients_record_for_booking as _create_yclients_record_for_booking_impl,
    delete_yclients_record_for_booking as _delete_yclients_record_for_booking_impl,
    upsert_local_busy_interval_for_booking as _upsert_local_busy_interval_for_booking_impl,
)

logger = logging.getLogger(__name__)


def call_ai(*args: Any, **kwargs: Any) -> Any:
    with trace_span("ai.semantic"):
        return _call_ai_impl(*args, **kwargs)


def generate_process_reply(*args: Any, **kwargs: Any) -> str:
    with trace_span("ai.response"):
        return _generate_process_reply_impl(*args, **kwargs)


def classify_post_booking_message(*args: Any, **kwargs: Any) -> Any:
    with trace_span("ai.post_booking"):
        return _classify_post_booking_message_impl(*args, **kwargs)


def check_availability(*args: Any, **kwargs: Any) -> Any:
    with trace_span("availability"):
        return _check_availability_impl(*args, **kwargs)


def sync_payment_statuses(*args: Any, **kwargs: Any) -> Any:
    with trace_span("payment.sync"):
        return _sync_payment_statuses_impl(*args, **kwargs)


def create_payment_link_for_bookings(*args: Any, **kwargs: Any) -> Any:
    with trace_span("payment.create_link"):
        return _create_payment_link_for_bookings_impl(*args, **kwargs)


def create_payment_link_for_holds(*args: Any, **kwargs: Any) -> Any:
    with trace_span("payment.create_link"):
        return _create_payment_link_for_holds_impl(*args, **kwargs)


def create_missing_yclients_records(*args: Any, **kwargs: Any) -> Any:
    with trace_span("yclients.create_missing_records"):
        return _create_missing_yclients_records_impl(*args, **kwargs)


def create_yclients_record_for_booking(*args: Any, **kwargs: Any) -> Any:
    with trace_span("yclients.create_record"):
        return _create_yclients_record_for_booking_impl(*args, **kwargs)


def delete_yclients_record_for_booking(*args: Any, **kwargs: Any) -> Any:
    with trace_span("yclients.delete_record"):
        return _delete_yclients_record_for_booking_impl(*args, **kwargs)


def upsert_local_busy_interval_for_booking(*args: Any, **kwargs: Any) -> Any:
    with trace_span("yclients.local_busy_upsert"):
        return _upsert_local_busy_interval_for_booking_impl(*args, **kwargs)


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
        "проверяю доступность",
        "проверяю свободность",
        "проверю доступность",
        "проверю свободность",
        "сейчас проверю",
        "сейчас проверяю",
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


def _last_assistant_asked_guest_count(history: list[dict[str, Any]]) -> bool:
    for item in reversed(history):
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        text = str(item.get("text") or "").lower().replace("ё", "е")
        return "сколько вас" in text or "сколько примерно гостей" in text
    return False


def _form_detail_correction_patch(text: str, form_data: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    name = _extract_corrected_client_name(text)
    if name:
        patch["client_name"] = name

    normalized = text.lower().replace("ё", "е")
    date_patch = _relative_date_patch(text, _now_local())
    if date_patch:
        patch |= date_patch

    period_patch = _time_period_patch(text)
    if period_patch:
        patch |= period_patch
    elif any(marker in normalized for marker in ("время", "час", "с ", "до ", "приед", "заед")):
        time_patch = _single_time_patch(text, "time")
        if time_patch:
            patch |= time_patch

    duration_value = _duration_from_text(text)
    if duration_value is not None and not period_patch:
        patch["duration"] = duration_value

    if not _wants_additional_booking(text):
        variant_patch = _service_variant_patch(text, allow_bare_ordinal=True)
        if variant_patch:
            patch |= variant_patch

    if any(marker in normalized for marker in ("телефон", "номер")):
        phone_patch = _phone_patch(text)
        if phone_patch:
            patch |= phone_patch

    if any(marker in normalized for marker in ("гост", "человек")):
        guests_patch = _guests_count_patch(text, "guests_count")
        if guests_patch:
            patch |= guests_patch

    event_patch = _event_format_patch(text)
    if event_patch and any(marker in normalized for marker in ("формат", "отдых", "туса", "день рождения", "корпоратив", "семейн", "компан")):
        patch |= event_patch

    upsell_patch = _upsell_items_patch(text)
    if upsell_patch and _has_upsell_signal(text):
        patch |= upsell_patch

    return {
        key: value
        for key, value in patch.items()
        if key in form_data and value not in (None, "", [])
    }


def _confirmation_yes(text: str) -> bool:
    normalized = re.sub(r"[^\w+]+", " ", text.lower().replace("ё", "е")).strip()
    yes_words = {
        "да",
        "дя",
        "д",
        "+",
        "ага",
        "угу",
        "ок",
        "окей",
        "хорошо",
        "верно",
        "правильно",
        "подтверждаю",
        "подтвердить",
    }
    tokens = normalized.split()
    if tokens and all(token in yes_words for token in tokens):
        return True
    return normalized in {
        "да",
        "дя",
        "д",
        "дада",
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
    if _wants_cancel_booking(text) or _wants_reschedule(text) or _wants_swap_bookings(text):
        return False
    if not any(marker in normalized for marker in ("еще", "ещё", "добав", "также", "тоже", "брон", "заброни", "хочу", "нужн")):
        return False
    if _service_type_patch(normalized):
        return True
    return any(
        marker in normalized
        for marker in (
            "еще одну",
            "еще одна",
            "ещё одну",
            "ещё одна",
            "еще надо",
            "ещё надо",
            "вторую брон",
            "новую брон",
            "добавить брон",
            "добавь брон",
            "еще брон",
            "ещё брон",
        )
    )


def _starts_gazebo_browsing_after_booking(conversation: dict[str, Any], text: str) -> bool:
    if not _asks_gazebo_options(text):
        return False
    if _asks_booking_summary(text):
        return False
    status = str(conversation.get("status") or "")
    current_step = str(conversation.get("current_step") or "")
    return (
        status in {"payment_paid", "reserved"}
        or current_step in {"reserved", "payment_status", "awaiting_new_date"}
        or bool((conversation.get("form_data") or {}).get("last_unavailable"))
    )


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


def _continues_current_draft_service_switch(conversation: dict[str, Any], text: str) -> bool:
    form_data = conversation.get("form_data") or {}
    current_service = _normalize_service_aliases({"service_type": form_data.get("service_type")}).get("service_type")
    requested_service = _normalize_service_aliases(_service_type_patch(text)).get("service_type")
    if not current_service or not requested_service or current_service == requested_service:
        return False
    if conversation.get("status") in {"reserved", "payment_paid"} or conversation.get("current_step") in {"reserved", "payment_status"}:
        return False
    if any(form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow")):
        return False
    normalized = text.lower().replace("ё", "е")
    if any(marker in normalized for marker in ("еще", "ещё", "вторую", "вторая", "добав", "новую брон", "еще одну", "ещё одну")):
        return False
    has_draft_context = any(
        form_data.get(key)
        for key in (
            "date",
            "time",
            "duration",
            "guests_count",
            "event_format",
            "last_unavailable",
            "last_available_gazebo_variants",
        )
    )
    if not has_draft_context:
        return False
    return any(
        marker in normalized
        for marker in (
            "тогда",
            "ладно",
            "лан",
            "давай",
            "давайте",
            "все таки",
            "всё таки",
            "же",
            "вернемся",
            "вернёмся",
            "выбираю",
            "закреп",
            "перв",
            "перу",
            "эту",
            "этот",
        )
    )


def _should_start_fresh_booking(conversation: dict[str, Any], text: str) -> bool:
    if _continues_current_draft_service_switch(conversation, text):
        return False
    wants_additional = _wants_additional_booking(text)
    starts_new = _starts_new_booking_request(text)
    requested_service = (_service_type_patch(text) or {}).get("service_type")
    return _should_start_fresh_booking_decision(
        conversation,
        requested_service=requested_service,
        starts_new_request=starts_new,
        wants_additional_booking=wants_additional,
        is_existing_booking_command=(
            _wants_cancel_booking(text) or _wants_reschedule(text) or _wants_swap_bookings(text)
        ),
    )


def _ai_should_start_fresh_booking(
    conversation: dict[str, Any],
    ai_result: Any,
    patch: dict[str, Any],
    text: str,
) -> bool:
    if _continues_current_draft_service_switch(conversation, text):
        return False
    intent = str(getattr(ai_result, "intent", "") or "")
    action = str(getattr(ai_result, "action", "") or "")
    requested_service = _normalize_service_aliases(
        {"service_type": patch.get("service_type")}
    ).get("service_type")
    return _ai_should_start_fresh_booking_decision(
        conversation,
        requested_service=requested_service,
        starts_new_request=_starts_new_booking_request(text),
        wants_additional_booking=_wants_additional_booking(text),
        is_existing_booking_command=(
            _wants_cancel_booking(text) or _wants_reschedule(text) or _wants_swap_bookings(text)
        ),
        ai_intent=intent,
        ai_action=action,
    )


def _fresh_booking_patch_from_ai(
    *,
    ai_result: Any,
    patch: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    fresh_patch = _filter_new_booking_patch_to_current_message(patch, text, now)
    ai_patch = dict(getattr(ai_result, "form_data_patch", None) or {})
    changed_fields = set(getattr(ai_result, "changed_fields", None) or [])
    for key in ("service_type", "service_variant", "preferences"):
        if key in ai_patch:
            fresh_patch[key] = ai_patch[key]
    for key in ("date", "time", "duration", "guests_count", "event_format", "upsell_items", "phone"):
        if key in ai_patch and key in changed_fields:
            fresh_patch[key] = ai_patch[key]
    return fresh_patch


def _is_plain_greeting(text: str) -> bool:
    normalized = re.sub(r"[^\w\s]+", " ", text.lower().replace("ё", "е")).strip()
    words = set(normalized.split())
    return bool(words & {"привет", "здравствуйте", "добрый", "день", "вечер"}) and not _service_type_patch(normalized)


def _asks_booking_summary(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if _asks_available_services(text):
        return False
    if any(marker in normalized for marker in ("цена", "стоим", "сколько стоит", "почем", "прайс", "оплат")):
        return False
    if "брон" in normalized and any(marker in normalized for marker in ("какие", "есть", "мои", "у меня", "теперь")):
        return True
    if "брон" in normalized and any(marker in normalized for marker in ("первая", "первую", "какая", "какую", "что выбрал", "что выбрали")):
        return True
    if "запис" in normalized and any(marker in normalized for marker in ("на мне", "у меня", "висит", "висят", "что там", "забыл", "напомни")):
        return True
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
            )
        )
    )


def _draft_summary_reply(form_data: dict[str, Any]) -> str | None:
    if not form_data or not any(
        form_data.get(key)
        for key in ("service_type", "service_variant", "date", "time", "duration", "guests_count", "event_format", "last_unavailable")
    ):
        return None
    title = (load_services_map().get(form_data.get("service_type")) or {}).get("title") or form_data.get("service_type") or "услуга"
    if form_data.get("service_variant"):
        title = f"{form_data.get('service_variant')} ({title})"
    lines = ["Оформленной брони пока нет — мы ещё собираем заявку ✅", "", "Сейчас в черновике:"]
    lines.append(f"- Услуга: {title}")
    date_value = form_data.get("date") or (form_data.get("last_unavailable") or {}).get("date")
    if date_value:
        lines.append(f"- Дата: {_format_date_ru(date_value)}")
    if form_data.get("time"):
        duration = f" на {_format_duration(form_data.get('duration'))}" if form_data.get("duration") else ""
        lines.append(f"- Время: с {form_data.get('time')}{duration}")
    guests = form_data.get("guests_count") or (form_data.get("last_unavailable") or {}).get("guests_count")
    if guests:
        lines.append(f"- Гостей: {guests}")
    if form_data.get("event_format"):
        lines.append(f"- Формат: {form_data.get('event_format')}")
    next_key, question = next_question(form_data)
    if question:
        lines.append("")
        lines.append(question)
    return "\n".join(lines)


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
    if _is_non_slot_detail_change(text):
        return False
    return any(marker in normalized for marker in ("отмен", "убер", "помен", "замен", "вместо", "перенес"))


def _is_non_slot_detail_change(text: str) -> bool:
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
        marker in normalized for marker in ("имя", "зовут", "телефон", "номер", "гост", "человек", "доп", "кальян", "уголь", "розжиг", "решет", "шампур", "посуд", "лед", "вода", "формат")
    ):
        return False
    return True


def _wants_continue_stale_form(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip()
    return _confirmation_yes(text) or any(marker in normalized for marker in ("продолж", "стар", "с этой", "эту заявку", "давай", "давайте"))


def _wants_new_form_after_stale(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip()
    return _confirmation_no(text) or any(marker in normalized for marker in ("нов", "сначала", "заново", "другую заявку", "другая заявка"))


def _stale_message_starts_new_context(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if _wants_cancel_booking(text) or _wants_reschedule(text) or _wants_swap_bookings(text):
        return False
    if _wants_new_form_after_stale(text):
        return True
    service_patch = _service_type_patch(text)
    if not service_patch:
        return False
    if _asks_for_free_slots(text) or _starts_new_booking_request(text):
        return True
    return any(marker in normalized for marker in ("какие", "когда", "свобод", "хочу", "нужн", "заброн", "брон"))


def _continue_stale_form_reply(form_data: dict[str, Any]) -> tuple[str, str | None]:
    cleaned = dict(form_data)
    cleaned.pop("stale_form_flow", None)
    next_key, question = next_question(cleaned)
    if next_key is None:
        return _confirmation_reply_text(cleaned), "confirmation"
    return f"Хорошо, продолжаем эту заявку ✅\n\n{question}", next_key


def _wants_abort_current_draft(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    return any(
        marker in normalized
        for marker in (
            "не хочу бронировать",
            "не хочу ее бронировать",
            "не хочу её бронировать",
            "не хочу его бронировать",
            "не хочу это бронировать",
            "не надо бронировать",
            "не нужно бронировать",
            "не оформляй",
            "не оформляем",
            "не нужно оформлять",
            "не будем оформлять",
            "отмена заявки",
            "отмени заявку",
            "передумал",
            "передумала",
            "забей",
            "отбой",
        )
    )


def _wants_pause_current_draft(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    if _wants_abort_current_draft(text) or _wants_cancel_booking(text) or _wants_reschedule(text):
        return False
    pause_markers = (
        "позже напиш",
        "напишу позже",
        "потом напиш",
        "попозже напиш",
        "позже реш",
        "потом реш",
        "вернусь позже",
        "я подумаю",
        "надо подумать",
        "нужно подумать",
        "пока не знаю",
        "не знаю пока",
        "пока хз",
    )
    if any(marker in normalized for marker in pause_markers):
        return True
    return "хз" in normalized and any(marker in normalized for marker in ("позже", "потом", "напиш"))


def _service_title(service_type: Any) -> str | None:
    if not service_type:
        return None
    return (load_services_map().get(str(service_type)) or {}).get("title") or str(service_type)


def _current_draft_can_be_aborted(conversation: dict[str, Any]) -> bool:
    form_data = conversation.get("form_data") or {}
    if any(form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow")):
        return False
    if conversation.get("status") in {"reserved", "payment_paid", "handoff"}:
        return False
    if conversation.get("current_step") in {"reserved", "payment_status", "handoff"}:
        return False
    return bool(form_data.get("service_type") or form_data.get("date") or form_data.get("time"))


def _abort_current_draft(form_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    cleaned = _new_booking_form_data(form_data)
    reply = (
        "Хорошо, эту заявку не оформляю ✅\n\n"
        "Имя и телефон оставила, чтобы не спрашивать повторно. "
        "Если хотите выбрать другую услугу или дату, напишите, что бронируем."
    )
    return reply, cleaned


def _pause_current_draft_reply(form_data: dict[str, Any]) -> str:
    service_title = _service_title(form_data.get("service_type"))
    filled: list[str] = []
    if service_title:
        filled.append(service_title)
    if form_data.get("date"):
        filled.append(_format_date_ru(str(form_data["date"])))
    if form_data.get("time"):
        filled.append(f"с {form_data['time']}")
    if form_data.get("guests_count"):
        filled.append(f"{form_data['guests_count']} гостей")
    summary = f"\n\nСейчас в черновике: {', '.join(filled)}." if filled else ""
    return (
        "Хорошо, напишите, когда определитесь — продолжим с этого места ✅"
        f"{summary}"
    )


def _new_gazebo_browsing_form_data(previous: dict[str, Any], text: str, now: datetime) -> dict[str, Any]:
    fresh = _new_booking_form_data(previous)
    patch = _deterministic_patch(text, now)
    fresh["service_type"] = "gazebo"
    for key in ("date", "guests_count", "preferences"):
        if patch.get(key):
            fresh[key] = patch[key]
    return fresh


def _handle_gazebo_browsing_start(
    conn,
    *,
    text: str,
    conversation: dict[str, Any],
    previous_form_data: dict[str, Any],
    history: list[dict[str, Any]],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    form_data = _new_gazebo_browsing_form_data(previous_form_data, text, now)
    if form_data.get("date"):
        availability = check_availability(conn, form_data=form_data, now=now)
        if availability.ok and not availability.slots:
            required, next_key = _no_availability_reply(form_data)
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
            current_step = next_key or "service_variant"
    else:
        required = (
            "Клиент спрашивает, какие беседки есть. Ответь коротко: есть разные беседки по вместимости и удобствам. "
            "Скажи, что свободные варианты нужно показывать только после проверки даты в журнале. "
            "Попроси дату отдыха одним вопросом. Не используй параметры прошлой брони."
        )
        next_key = "date"
        current_step = "date"
    reply = _ai_process_reply(
        text=text,
        form_data=form_data,
        history=history,
        required_meaning=required,
    )
    return reply, "waiting_user", current_step, next_key, form_data


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


def _hold_object_title(hold: dict[str, Any]) -> str:
    service_type = hold.get("service_type")
    config = load_services_map().get(service_type) or {}
    title = config.get("title") or service_type or "бронь"
    service_id = str(hold.get("yclients_service_id") or "").strip()
    for variant in config.get("variants") or []:
        if service_id and str(variant.get("yclients_service_id") or "").strip() == service_id:
            return str(variant.get("title") or title)
    return str(title)


def _expired_hold_inline_reply(holds: list[dict[str, Any]]) -> str:
    if not holds:
        return "Резерв истёк: предоплата не поступила в течение 10 минут.\n\nСлот снова доступен. Если всё ещё актуально, напишите — проверю свободность заново ✅"
    lines = ["Резерв истёк: предоплата не поступила в течение 10 минут."]
    for hold in holds[:3]:
        date_text = _format_date_ru(hold.get("slot_date"))
        time_text = str(hold.get("slot_time") or "")[:5]
        duration = _format_duration(hold.get("duration_minutes"))
        lines.append(f"- {_hold_object_title(hold)}: {date_text}, с {time_text} на {duration}")
    lines.append("")
    lines.append("Слот снова доступен. Если всё ещё актуально, напишите — проверю свободность заново ✅")
    return "\n".join(lines)


def _pending_payment_for_holds(conn, conversation_id: int, hold_ids: list[int]) -> dict[str, Any] | None:
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


def _handle_reserved_hold_command(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    form_data = conversation.get("form_data") or {}
    asks_summary = _asks_booking_summary(text)
    wants_cancel_or_change = _wants_cancel_or_change_hold(text)
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
        expired_holds = slot_holds_repo.list_expired_for_conversation(
            conn,
            conversation_id=conversation["id"],
            limit=5,
        )
        unnotified_expired = [hold for hold in expired_holds if not hold.get("expired_notified_at")]
        if hold_context and unnotified_expired and not _has_user_bookings(conn, conversation, form_data, now):
            for hold in unnotified_expired:
                slot_holds_repo.mark_expired_notified(conn, hold_id=hold["id"], now=now)
            cleaned = _new_booking_form_data(form_data)
            return (
                _expired_hold_inline_reply(unnotified_expired),
                "waiting_user",
                "service_type",
                "service_type",
                cleaned,
            )
        if form_data.get("reschedule_flow") or form_data.get("swap_reschedule_flow"):
            return None
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
            has_bookings = _has_user_bookings(conn, conversation, form_data, now)
            if has_bookings:
                if _wants_cancel_booking(text):
                    return _start_cancel_booking_flow(
                        conn,
                        conversation,
                        text,
                        form_data,
                        "payment_paid",
                        now,
                    )
                if _wants_reschedule(text):
                    return _start_reschedule_flow(
                        conn,
                        conversation,
                        text,
                        form_data,
                        "payment_paid",
                        now,
                    )
                return None
            return (
                "Сейчас не вижу активной предварительной заявки, которую можно отменить или поменять. Можем оформить новую бронь.",
                "waiting_user",
                conversation.get("current_step") or "waiting_user",
                next_question(form_data)[0],
                form_data,
            )
        return None

    if (
        not hold_context
        and not asks_summary
        and not wants_cancel_or_change
        and not _confirmation_yes(text)
        and not _mentions_payment_status(text)
    ):
        return None

    if asks_summary:
        reply = _reply_with_hold_summary(conn, conversation, form_data, now)
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        return reply, status, "reserved", "payment_status", form_data

    correction_patch = _form_detail_correction_patch(text, form_data)
    if not correction_patch and history and _last_assistant_asked_name_correction(history) and _looks_like_name(text):
        correction_patch = {"client_name": text.strip().title()}
    if correction_patch:
        form_data = merge_form_data(form_data, correction_patch)
        reply = (
            f"{_correction_ack_text(correction_patch)}\n\n"
            "Резерв оставила активным. Можно оплатить по ссылке, которую отправляла выше.\n\n"
            "После оплаты пришлю подтверждение брони ✅"
        )
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        return reply, status, "reserved", "payment_status", form_data
    if _maybe_name_correction_without_value(text):
        status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"
        return (
            "Поняла, поправим имя ✅\n\nКакое имя указать в брони?",
            status,
            "reserved",
            "payment_status",
            form_data,
        )

    if _confirmation_yes(text):
        hold_ids = [int(hold["id"]) for hold in active_holds]
        existing_payment = _pending_payment_for_holds(conn, conversation["id"], hold_ids)
        if existing_payment:
            return (
                "Ссылка на предоплату уже создана ✅\n\n"
                f"{_payment_reply_text(existing_payment)}",
                "reserved",
                "reserved",
                "payment_status",
                form_data,
            )
        try:
            payment = create_payment_link_for_holds(
                conn,
                conversation_id=conversation["id"],
                user_id=conversation["user_id"],
                hold_ids=hold_ids,
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


def _price_reply_if_known(text: str, form_data: dict[str, Any]) -> str | None:
    return _price_reply_if_known_impl(
        text,
        form_data,
        selected_variant_config=_selected_variant_config,
    )


def _explicit_photo_reply(text: str, form_data: dict[str, Any]) -> str | None:
    if not is_explicit_photo_request(text):
        return None
    variant_patch = _service_variant_patch(text, allow_bare_ordinal=True)
    if variant_patch.get("service_variant"):
        title = variant_patch["service_variant"]
        reply = f"Конечно, сейчас отправлю фото: {title} 📸"
        if media_for_client_message(text, reply):
            return reply
        return f"Фото для {title} пока не добавлено в базу."
    service_patch = _service_type_patch(text)
    service_type = service_patch.get("service_type")
    if service_type:
        normalized_service = _normalize_service_aliases({"service_type": service_type}).get("service_type")
        service_title = None
        if normalized_service in {"bathhouse", "house", "warm_gazebo"}:
            service_title = (load_services_map().get(normalized_service) or {}).get("title")
        if service_title:
            reply = f"Конечно, сейчас отправлю фото: {service_title} 📸"
            if media_for_client_message(text, reply):
                return reply
            return f"Фото для {service_title} пока не добавлено в базу."
    title = form_data.get("service_variant")
    if title:
        reply = f"Конечно, сейчас отправлю фото: {title} 📸"
        if media_for_client_message(text, reply):
            return reply
        return f"Фото для {title} пока не добавлено в базу."

    available_titles = _suitable_available_gazebo_titles(form_data) or _available_gazebo_titles(form_data)
    if available_titles:
        names = ", ".join(available_titles[:8])
        reply = f"Конечно, сейчас отправлю фото вариантов: {names} 📸"
        if media_for_client_message(text, reply):
            return reply

    if "бесед" in text.lower().replace("ё", "е") or form_data.get("service_type") == "gazebo":
        return (
            "Конечно, покажу фото. Напишите номер беседки, например «фото беседки №2», "
            "или выберите дату и количество гостей — отправлю подходящие варианты."
        )
    return None


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
    next_key, question = next_question(form_data)
    photo_reply = _explicit_photo_reply(text, form_data)
    if photo_reply:
        return photo_reply
    price_reply = _price_reply_if_known(text, form_data)
    if price_reply:
        return price_reply
    capacity_reply = _capacity_info_reply(text, form_data)
    if capacity_reply:
        reply = capacity_reply
        if (
            form_data.get("service_type") == "gazebo"
            and form_data.get("service_variant")
            and not form_data.get("guests_count")
            and not _capacity_guest_patch(text)
        ):
            return reply
        if (
            question
            and _should_append_next_question_after_info(form_data, next_key)
            and not _reply_already_asks(reply, next_key, question)
        ):
            reply = f"{reply}\n\n{question}"
        return reply
    policy_reply = _policy_or_common_info_reply(text)
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
    if (
        question
        and _should_append_next_question_after_info(form_data, next_key)
        and not _reply_already_asks(reply, next_key, question)
    ):
        reply = f"{reply}\n\n{question}"
    return reply


def _capacity_info_reply(text: str, form_data: dict[str, Any]) -> str | None:
    normalized = text.lower().replace("ё", "е")
    guests_patch = _guests_count_patch(text, "guests_count")
    guests = guests_patch.get("guests_count")
    has_capacity_signal = any(
        marker in normalized
        for marker in (
            "вмест",
            "помест",
            "рассчит",
            "если нас",
            "нас будет",
            "человек",
            "гостей",
            "гостя",
        )
    )
    if not has_capacity_signal:
        return None
    service_type = form_data.get("service_type")
    if service_type == "gazebo" and not form_data.get("service_variant"):
        if not guests:
            return None
        guests_count = int(guests)
        available = _available_gazebo_variant_configs(form_data)
        variants = available or (load_services_map().get("gazebo") or {}).get("variants") or []
        suitable = [
            variant
            for variant in variants
            if int(variant.get("capacity_max") or 0) >= guests_count
        ]
        if guests_count >= 20:
            suitable = sorted(
                suitable,
                key=lambda item: (
                    0 if "№1" in str(item.get("title") or "") else 1,
                    int(item.get("price") or 999999),
                    int(item.get("capacity_max") or 9999),
                ),
            )
        else:
            suitable = sorted(
                suitable,
                key=lambda item: (
                    int(item.get("capacity_max") or 9999),
                    int(item.get("price") or 999999),
                ),
            )
        if suitable:
            lines = [f"Для {guests_count} гостей лучше смотреть такие варианты:"]
            for variant in suitable[:5]:
                lines.append(f"- {_format_gazebo_variant_line(variant)}")
            if guests_count >= 20 and any("№1" in str(item.get("title") or "") for item in suitable):
                lines.append("")
                lines.append("Беседка №1 идёт первой, потому что для большой компании там комфортнее по месту ✅")
            if form_data.get("date") and available:
                lines.append("")
                lines.append("Перечислила только свободные на выбранную дату варианты.")
            elif not form_data.get("date"):
                lines.append("")
                lines.append("Назовите дату — проверю, какие из них свободны в журнале.")
            return "\n".join(lines)
        if form_data.get("date") and available is not None:
            return f"На выбранную дату среди свободных беседок не вижу варианта, который комфортно подходит для {guests_count} гостей."
        return f"Для {guests_count} гостей нужна беседка побольше. Обычно в первую очередь смотрим Беседку №1 до 50 человек."
    if service_type == "gazebo" and form_data.get("service_variant"):
        title = str(form_data.get("service_variant"))
        capacity = _gazebo_capacity_by_title(title)
        if not capacity:
            return None
        if guests:
            guests_count = int(guests)
            if guests_count <= int(capacity):
                return (
                    f"{title} рассчитана до {capacity} человек, для {guests_count} гостей подходит ✅\n\n"
                    "Во сколько хотите приехать? Можно сразу написать период, например: с 18:00 до 00:00."
                )
            return (
                f"{title} рассчитана до {capacity} человек, для {guests_count} гостей будет тесно.\n\n"
                "Подберу другой свободный вариант по вместимости, чтобы всем было комфортно ✅"
            )
        return (
            f"{title} рассчитана до {capacity} человек ✅\n\n"
            "Сколько вас будет человек? Проверю, подходит ли она по вместимости."
        )
    if service_type == "bathhouse":
        if guests and int(guests) >= 20:
            return (
                f"Для {guests} человек баня с бассейном не лучший основной формат: "
                "она больше подходит для небольшой компании и отдыха в бане.\n\n"
                "Для такой компании лучше смотреть Беседку №1 до 50 человек или тёплую беседку до 30 человек. "
                "Если хотите совместить, можно оформить баню и беседку двумя отдельными услугами.\n\n"
                "Если всё же оставляем баню, во сколько хотите приехать? Можно сразу написать период, например: с 18:00 до 00:00."
            )
        return (
            "Баня с бассейном больше подходит для небольшой компании и отдыха в бане. "
            "Если компания большая и нужен стол/застолье, лучше добавить беседку отдельной бронью."
        )
    if service_type == "warm_gazebo":
        capacity = (load_services_map().get("warm_gazebo") or {}).get("capacity_max")
        if guests and capacity:
            if int(guests) <= int(capacity):
                return f"Тёплая беседка рассчитана до {capacity} человек, для {guests} гостей подходит."
            return (
                f"Тёплая беседка рассчитана до {capacity} человек, для {guests} гостей будет тесно. "
                "Для такой компании лучше смотреть Беседку №1 до 50 человек."
            )
    if service_type == "house" and guests and int(guests) >= 20:
        return (
            f"Для {guests} человек гостевой дом как основной объект может быть не лучшим вариантом. "
            "Для большой компании лучше смотреть Беседку №1 до 50 человек или тёплую беседку до 30 человек."
        )
    return None


def _should_append_next_question_after_info(form_data: dict[str, Any], next_key: str | None) -> bool:
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


def _should_route_existing_booking_command(text: str) -> bool:
    return (
        _asks_booking_summary(text)
        or _wants_cancel_booking(text)
        or _wants_reschedule(text)
        or _wants_swap_bookings(text)
        or _wants_multi_booking_reschedule(text)
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
        bookings = _active_user_bookings(conn, conversation, form_data, _now_local())
        if not bookings:
            return (
                "Оплата получена ✅\n\n"
                "Но резерв по этой ссылке уже истёк, поэтому бронь не закрепилась автоматически. "
                "Напишите, если слот всё ещё актуален — я заново проверю свободность.",
                "waiting_user",
            )
        journal_ready = bool(bookings) and all(booking.get("yclients_record_id") for booking in bookings)
        if journal_ready and not paid_payment.get("payment_notified_at"):
            payments_repo.mark_payment_notified(conn, payment_id=paid_payment["id"])
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
    return "Пока не вижу активных броней по вашему номеру.\n\nЕсли хотите оформить бронь, напишите услугу и дату — проверю свободные варианты."


def _plain_ack_after_closed_booking(text: str) -> bool:
    normalized = re.sub(r"[^\w+]+", " ", text.lower().replace("ё", "е")).strip()
    if _confirmation_yes(text):
        return True
    return normalized in {"спасибо", "спс", "понял", "поняла", "ладно", "ясно", "ок спасибо", "хорошо спасибо"}


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
        payments = payments_repo.list_for_conversation(conn, conversation_id=conversation["id"])
        if payments:
            sync_payment_statuses(conn)
            create_missing_yclients_records(conn)
            payments = payments_repo.list_for_conversation(conn, conversation_id=conversation["id"])
        if any(payment.get("status") == "paid" for payment in payments):
            conversation = {**conversation, "status": "payment_paid"}
    except Exception:
        logger.exception("Post-booking payment refresh failed conversation_id=%s", conversation["id"])

    status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"

    if _asks_booking_summary(text) or _continues_booking_summary_question(text, history):
        cleared = {**form_data, "cancel_flow": None, "reschedule_flow": None, "swap_reschedule_flow": None}
        return _post_booking_summary(conn, conversation, cleared, now), status, "reserved", "payment_status", cleared

    if (
        conversation.get("status") == "payment_paid"
        and _plain_ack_after_closed_booking(text)
        and not _active_user_bookings(conn, conversation, form_data, now)
    ):
        cleared = _new_booking_form_data(form_data)
        return (
            "Хорошо ✅ Если понадобится новая бронь, напишите услугу и дату — проверю свободные варианты.",
            "waiting_user",
            "service_type",
            "service_type",
            cleared,
        )

    if form_data.get("cancel_flow"):
        return _handle_cancel_booking_flow(conn, conversation, text, form_data, now)

    flow_info_reply = _reply_to_info_during_reschedule_flow(
        conn,
        conversation,
        text,
        history,
        form_data,
        status,
        now,
    )
    if flow_info_reply:
        return flow_info_reply

    if form_data.get("swap_reschedule_flow"):
        return _handle_swap_reschedule_flow(conn, conversation, text, form_data, now)

    if form_data.get("reschedule_flow"):
        return _handle_reschedule_flow(conn, conversation, text, form_data, now)

    if _wants_cancel_booking(text):
        return _start_cancel_booking_flow(conn, conversation, text, form_data, status, now)

    if _wants_multi_booking_reschedule(text):
        return _start_swap_reschedule_flow(conn, conversation, text, form_data, status, now)

    if _wants_reschedule(text):
        if _wants_swap_bookings(text):
            return _start_swap_reschedule_flow(conn, conversation, text, form_data, status, now)
        return _start_reschedule_flow(conn, conversation, text, form_data, status, now)

    if _is_waitlist_decline(text):
        waitlist_repo.close_for_user(conn, user_id=int(conversation["user_id"]))
        return (
            "Поняла, больше не будем держать этот запрос в ожидании ✅\n\nЕсли снова понадобится проверить дату или оформить бронь, просто напишите услугу и дату.",
            status,
            "reserved",
            "payment_status",
            form_data,
        )

    if _asks_for_free_slots(text):
        lookup_form = form_data | _service_type_patch(text)
        if lookup_form.get("service_type") != "gazebo":
            lookup_form["service_variant"] = None
        reply = _next_free_dates_reply(conn, conversation, lookup_form, now)
        if reply:
            return reply, status, "reserved", "payment_status", form_data

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
    if getattr(classified, "handoff_to_human", False) and not (
        _wants_cancel_booking(text) or _wants_reschedule(text) or _wants_swap_bookings(text)
    ):
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
        change_type = getattr(classified, "change_type", "unknown") or "unknown"
        if change_type == "cancel" or _wants_cancel_booking(text):
            return _start_cancel_booking_flow(conn, conversation, text, form_data, status, now)
        if change_type == "reschedule" or _wants_reschedule(text):
            if _wants_swap_bookings(text) or _wants_multi_booking_reschedule(text):
                return _start_swap_reschedule_flow(conn, conversation, text, form_data, status, now)
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


def _handle_booking_reminder_response(
    conn,
    conversation: dict[str, Any],
    user: dict[str, Any],
    text: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    bookings = bookings_repo.list_waiting_reminder_response_for_user(
        conn,
        user_id=int(user["id"]),
        phone=user.get("phone"),
        now=now,
    )
    if not bookings:
        return None
    form_data = conversation.get("form_data") or {}
    booking_ids = [int(booking["id"]) for booking in bookings]
    if _confirmation_yes(text):
        bookings_repo.mark_reminder_response(conn, booking_ids=booking_ids, response="yes", now=now)
        return (
            "Спасибо, ждём вас завтра ✅\n\nБронь оставляю активной.",
            "payment_paid",
            "reserved",
            "payment_status",
            {**form_data, "reschedule_flow": None, "cancel_flow": None, "swap_reschedule_flow": None},
        )
    normalized = text.lower().replace("ё", "е")
    if _confirmation_no(text) or _wants_cancel_booking(text) or any(marker in normalized for marker in ("не придем", "не приедем", "не получится", "не сможем")):
        bookings_repo.mark_reminder_response(conn, booking_ids=booking_ids, response="no", now=now)
        cancelled_lines: list[str] = []
        failed_lines: list[str] = []
        for booking in bookings:
            if delete_yclients_record_for_booking(conn, booking=booking):
                bookings_repo.cancel_by_id(conn, booking_id=int(booking["id"]), now=now)
                cancelled_lines.append(f"- {_booking_line_short(booking)}")
            else:
                failed_lines.append(f"- {_booking_line_short(booking)}")
        if failed_lines:
            return (
                "Не получилось автоматически снять запись в журнале по этим броням:\n"
                + "\n".join(failed_lines)
                + "\n\nПередала ситуацию команде, с вами свяжутся по сохранённому номеру.",
                "handoff",
                "handoff",
                "handoff",
                form_data,
            )
        return (
            "Поняла, отменила бронь:\n"
            + "\n".join(cancelled_lines)
            + "\n\nЕсли отмена меньше чем за 7 дней до даты брони, аванс по правилам не возвращается.",
            "payment_paid",
            "reserved",
            "payment_status",
            {**form_data, "reschedule_flow": None, "cancel_flow": None, "swap_reschedule_flow": None},
        )
    return None


def _wants_reschedule(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "перенес",
            "перенеси",
            "перенести",
            "перенесешь",
            "перенесёшь",
            "пернести",
            "перенос",
            "сдвин",
            "поменять дату",
            "изменить дату",
            "другую дату",
            "поменять время",
            "изменить время",
            "поменять местами",
            "местами",
            "поменять брони",
        )
    )


def _wants_swap_bookings(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return (
        "местами" in normalized
        and any(marker in normalized for marker in ("брон", "дат", "бесед", "бан", "помен", "обмен"))
    ) or (
        "поменять даты" in normalized
        and any(marker in normalized for marker in ("две", "2", "обе", "брон"))
    )


def _wants_multi_booking_reschedule(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("обе", "оба", "все брони", "все брон", "две брони", "2 брони")) or (
        "обе" in normalized and any(marker in normalized for marker in ("бесед", "бан", "услуг"))
    )


def _asks_reschedule_options(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return (
        "как" in normalized
        and any(marker in normalized for marker in ("перенест", "перенес", "пернос", "поменять"))
    ) or (
        "вариант" in normalized
        and any(marker in normalized for marker in ("перенос", "перенест", "поменять"))
    )


def _reply_to_info_during_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    if not (form_data.get("reschedule_flow") or form_data.get("swap_reschedule_flow")):
        return None
    if _asks_reschedule_options(text):
        bookings = _active_user_bookings(conn, conversation, form_data, now)
        if not bookings:
            bookings = _conversation_bookings_for_active_flow(conn, conversation)
        updated = {
            **form_data,
            "reschedule_flow": None,
            "swap_reschedule_flow": {"stage": "collect_swap"} if len(bookings) > 1 else form_data.get("swap_reschedule_flow"),
        }
        return _reschedule_options_reply(bookings), status, "reserved", "payment_status", updated
    if _wants_cancel_booking(text) or _wants_reschedule(text) or _wants_multi_booking_reschedule(text):
        return None
    if not _looks_like_info_question(text, now=now):
        return None

    info_form = {**form_data, "reschedule_flow": None, "swap_reschedule_flow": None}
    reply = _deterministic_info_reply(text, info_form)
    if not reply:
        reply = _ai_process_reply(
            text=text,
            form_data=info_form,
            history=history,
            required_meaning=(
                "Клиент задал информационный вопрос во время сценария переноса брони. "
                "Коротко ответь по базе знаний, без выдумок. "
                "Не передавай администратору, если вопрос обычный информационный."
            ),
        )
    reply = reply.strip()
    if form_data.get("reschedule_flow") or form_data.get("swap_reschedule_flow"):
        reply += "\n\nЕсли продолжаем перенос, напишите новую дату и нужную бронь."
    return reply, status, "reserved", "payment_status", form_data


def _reschedule_options_reply(bookings: list[dict[str, Any]]) -> str:
    lines = [
        "Можно перенести одну бронь или несколько сразу ✅",
        "",
        "Напишите в свободной форме, например:",
        "- «первую бронь на 27 июня»",
        "- «обе брони на 29 июня»",
        "- «Беседку №4 на 27 июня, Беседку №1 на 29 июня»",
        "",
        "Я проверю журнал и скажу, получится ли так перенести.",
    ]
    if bookings:
        lines.extend(["", "Сейчас вижу такие брони:"])
        for index, booking in enumerate(bookings, start=1):
            lines.append(f"{index}. {_booking_line_short(booking)}")
    return "\n".join(lines)


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
    selected = _select_cancel_bookings(bookings, None, text)
    booking = selected[0] if len(selected) == 1 else None
    flow = {"stage": "confirm_cancel"}
    if len(selected) > 1:
        flow["booking_ids"] = [booking["id"] for booking in selected]
    elif booking:
        flow["booking_id"] = booking.get("id")
    else:
        flow["booking_id"] = None
    updated = {**form_data, "cancel_flow": flow}
    if len(selected) > 1:
        return _cancel_many_confirmation_reply(selected, now), status, "reserved", "payment_status", updated
    if not booking:
        return _cancel_selection_prompt(bookings), status, "reserved", "payment_status", updated
    return _cancel_confirmation_reply(booking, now), status, "reserved", "payment_status", updated


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
    selected = _select_cancel_bookings(bookings, flow, text)
    booking = selected[0] if len(selected) == 1 else None
    if not selected:
        flow = flow | {"stage": "confirm_cancel"}
        return _cancel_selection_prompt(bookings), status, "reserved", "payment_status", {**form_data, "cancel_flow": flow}

    if not flow.get("booking_id") and not flow.get("booking_ids"):
        if len(selected) > 1:
            flow = flow | {"booking_ids": [item["id"] for item in selected], "stage": "confirm_cancel"}
            return _cancel_many_confirmation_reply(selected, now), status, "reserved", "payment_status", {**form_data, "cancel_flow": flow}
        flow = flow | {"booking_id": booking["id"], "stage": "confirm_cancel"}
        return _cancel_confirmation_reply(booking, now), status, "reserved", "payment_status", {**form_data, "cancel_flow": flow}

    if _confirmation_no(text):
        cleared = {**form_data, "cancel_flow": None}
        return "Хорошо, бронь оставила без изменений ✅", status, "reserved", "payment_status", cleared

    if not _confirmation_yes(text):
        if len(selected) > 1:
            return _cancel_many_confirmation_reply(selected, now), status, "reserved", "payment_status", {**form_data, "cancel_flow": flow}
        return _cancel_confirmation_reply(booking, now), status, "reserved", "payment_status", {**form_data, "cancel_flow": flow}

    if len(selected) > 1:
        for item in selected:
            old_booking = bookings_repo.get_by_id(conn, booking_id=int(item["id"])) or item
            if not delete_yclients_record_for_booking(conn, booking=old_booking):
                user = users_repo.get_by_id(conn, int(conversation["user_id"]))
                if user:
                    _start_user_handoff(
                        conn,
                        user=user,
                        conversation_id=conversation["id"],
                        text=text,
                        now=now,
                        reason="техническая ошибка: не удалось удалить несколько записей в журнале",
                    )
                return _handoff_reply(), "handoff", "handoff", "handoff", form_data
        for item in selected:
            bookings_repo.cancel_by_id(conn, booking_id=int(item["id"]), now=now)
        cleared = {**form_data, "cancel_flow": None}
        return _cancel_many_done_reply(selected, now), "payment_paid", "reserved", "payment_status", cleared

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
        _cancel_done_reply(booking, now),
        "payment_paid",
        "reserved",
        "payment_status",
        cleared,
    )


def _start_swap_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    if len(bookings) < 2:
        fallback_bookings = _conversation_bookings_for_active_flow(conn, conversation)
        if len(fallback_bookings) >= 2:
            bookings = fallback_bookings
    if len(bookings) < 2:
        return _start_reschedule_flow(conn, conversation, text, form_data, status, now)
    status = "payment_paid" if any(booking.get("payment_status") == "paid" for booking in bookings) else status
    same_target_assignments = _same_target_assignments_for_bookings(text, bookings, now)
    if len(same_target_assignments) >= 2:
        updated = {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}, "reschedule_flow": None}
        return _prepare_swap_reschedule(conn, conversation, bookings, same_target_assignments, updated, status, now)
    assignments = _parse_swap_assignments(text, bookings, now)
    updated = {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}, "reschedule_flow": None}
    if len(assignments) >= 2:
        return _prepare_swap_reschedule(conn, conversation, bookings, assignments, updated, status, now)
    return _swap_collect_reply(bookings), status, "reserved", "payment_status", updated


def _handle_swap_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    if not bookings:
        bookings = _conversation_bookings_for_active_flow(conn, conversation)
    status = (
        "payment_paid"
        if conversation.get("status") == "payment_paid" or any(booking.get("payment_status") == "paid" for booking in bookings)
        else "reserved"
    )
    flow = dict(form_data.get("swap_reschedule_flow") or {})
    if flow.get("stage") == "confirm_swap":
        if _confirmation_no(text):
            return "Хорошо, оставила брони без изменений ✅", status, "reserved", "payment_status", {**form_data, "swap_reschedule_flow": None}
        if _confirmation_yes(text):
            return _execute_swap_reschedule(conn, conversation, bookings, form_data, flow)
        return _swap_confirmation_reply(bookings, flow.get("assignments") or []), status, "reserved", "payment_status", form_data

    assignments = _same_target_assignments_for_bookings(text, bookings, now) or _parse_swap_assignments(text, bookings, now)
    if len(assignments) < 2:
        return _swap_collect_reply(bookings), status, "reserved", "payment_status", form_data
    return _prepare_swap_reschedule(conn, conversation, bookings, assignments, form_data, status, now)


def _prepare_swap_reschedule(
    conn,
    conversation: dict[str, Any],
    bookings: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    by_id = {int(booking["id"]): booking for booking in bookings}
    normalized_assignments: list[dict[str, Any]] = []
    unavailable: list[str] = []
    ignore_source_record_ids = [
        str(booking.get("yclients_record_id"))
        for booking in bookings
        if booking.get("yclients_record_id")
    ]
    for assignment in assignments:
        booking = by_id.get(int(assignment["booking_id"]))
        if not booking:
            continue
        flow = {
            "booking_id": booking["id"],
            "date": assignment["date"],
            "time": assignment.get("time") or str(booking.get("booking_time"))[:5],
            "duration": assignment.get("duration") or _hours_from_minutes(booking.get("duration_minutes")),
        }
        check_form = _form_data_for_booking_reschedule(
            {**form_data, "ignore_source_record_ids": ignore_source_record_ids},
            booking,
            flow,
        )
        availability = check_availability(conn, form_data=check_form, now=now)
        if availability.ok and not availability.slots:
            unavailable.append(f"{_booking_object_title(booking)} на {_format_date_ru(flow['date'])}, с {flow['time']}")
            continue
        normalized_assignments.append(flow)
    if unavailable:
        return (
            "Так перенести не получится: по журналу не свободно:\n"
            + "\n".join(f"- {item}" for item in unavailable)
            + "\n\nНапишите другой вариант переноса — проверю заново.",
            status,
            "reserved",
            "payment_status",
            {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}},
        )
    if len(normalized_assignments) < 2:
        return _swap_collect_reply(bookings), status, "reserved", "payment_status", {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}}
    flow = {"stage": "confirm_swap", "assignments": normalized_assignments}
    return (
        _swap_confirmation_reply(bookings, normalized_assignments),
        status,
        "reserved",
        "payment_status",
        {**form_data, "swap_reschedule_flow": flow, "reschedule_flow": None},
    )


def _execute_swap_reschedule(
    conn,
    conversation: dict[str, Any],
    bookings: list[dict[str, Any]],
    form_data: dict[str, Any],
    flow: dict[str, Any],
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    by_id = {int(booking["id"]): booking for booking in bookings}
    assignments = list(flow.get("assignments") or [])
    old_bookings: list[dict[str, Any]] = []
    for assignment in assignments:
        booking = bookings_repo.get_by_id(conn, booking_id=int(assignment["booking_id"])) or by_id.get(int(assignment["booking_id"]))
        if booking:
            old_bookings.append(booking)
    if len(old_bookings) < len(assignments):
        return (
            "Не смогла найти одну из броней для переноса. Напишите, пожалуйста, какие брони переносим — проверю заново.",
            "payment_paid",
            "reserved",
            "payment_status",
            {**form_data, "swap_reschedule_flow": None, "reschedule_flow": None},
        )

    deleted_old: list[dict[str, Any]] = []
    for booking in old_bookings:
        if not delete_yclients_record_for_booking(conn, booking=booking):
            for deleted in deleted_old:
                _restore_booking_after_failed_reschedule(conn, deleted)
            return (
                "Сейчас не получилось изменить одну из записей в журнале.\n\n"
                "Старые брони оставила без изменений. Напишите другой вариант переноса — проверю ещё раз.",
                "payment_paid",
                "reserved",
                "payment_status",
                {**form_data, "swap_reschedule_flow": None, "reschedule_flow": None},
            )
        deleted_old.append(booking)

    updated_bookings: list[dict[str, Any]] = []
    try:
        for assignment, old_booking in zip(assignments, old_bookings, strict=False):
            new_date = datetime.fromisoformat(str(assignment["date"])).date()
            new_time = datetime.strptime(str(assignment["time"])[:5], "%H:%M").time()
            new_duration = _duration_minutes_value(assignment.get("duration"))
            updated = bookings_repo.update_schedule(
                conn,
                booking_id=int(old_booking["id"]),
                booking_date=new_date,
                booking_time=new_time,
                duration_minutes=new_duration,
            )
            if not updated:
                raise RuntimeError(f"booking #{old_booking.get('id')} was not updated")
            updated = bookings_repo.get_by_id(conn, booking_id=int(updated["id"])) or updated
            updated_bookings.append(updated)
        for updated in updated_bookings:
            create_yclients_record_for_booking(conn, booking=updated)
    except Exception:
        logger.exception("Failed to execute grouped reschedule")
        restored_lines: list[str] = []
        for old_booking in old_bookings:
            restored = _restore_booking_after_failed_reschedule(conn, old_booking)
            if restored:
                restored_lines.append(_booking_line_short(restored))
        restored_text = "\n".join(f"- {line}" for line in restored_lines) if restored_lines else "старые брони оставила в базе, но журнал нужно проверить вручную"
        return (
            "Новое время не получилось закрепить в журнале: похоже, один из слотов уже занят или недоступен.\n\n"
            f"Старые брони восстановила:\n{restored_text}\n\n"
            "Напишите другой вариант переноса — проверю ещё раз.",
            "payment_paid",
            "reserved",
            "payment_status",
            {**form_data, "swap_reschedule_flow": None, "reschedule_flow": None},
        )

    done = [
        f"{_booking_object_title(booking)} → {_format_date_ru(str(booking.get('booking_date')))}, с {str(booking.get('booking_time'))[:5]}"
        for booking in updated_bookings
    ]
    cleared = {**form_data, "swap_reschedule_flow": None, "reschedule_flow": None}
    return (
        "Готово ✅\n\nОбновила брони по вашему варианту:\n"
        + "\n".join(f"- {item}" for item in done)
        + "\n\nАвансы сохраняются, разницу при необходимости можно будет доплатить на месте.",
        "payment_paid",
        "reserved",
        "payment_status",
        cleared,
    )


def _swap_collect_reply(bookings: list[dict[str, Any]]) -> str:
    lines = [
        "Поняла, хотите изменить несколько броней ✅",
        "",
        "Напишите, пожалуйста, конкретно что куда переносим. Например:",
        "«Беседка №4 на 26 июня, Беседка №1 на 29 мая»",
        "или «обе брони на 27 июня».",
        "",
        "Сейчас вижу такие брони:",
    ]
    for index, booking in enumerate(bookings, start=1):
        lines.append(f"{index}. {_booking_line_short(booking)}")
    return "\n".join(lines)


def _swap_confirmation_reply(bookings: list[dict[str, Any]], assignments: list[dict[str, Any]]) -> str:
    by_id = {int(booking["id"]): booking for booking in bookings}
    lines = ["Проверила по журналу, такой перенос возможен ✅", "", "Подтвердите, пожалуйста:"]
    for assignment in assignments:
        booking = by_id.get(int(assignment["booking_id"]))
        if not booking:
            continue
        lines.append(
            f"- {_booking_line_short(booking)} → {_format_date_ru(assignment['date'])}, с {assignment['time']} на {_format_duration(assignment.get('duration'))}"
        )
    lines.extend(["", "Авансы сохраняются. Подтверждаете перенос? Напишите «да» или «нет»."])
    return "\n".join(lines)


def _parse_swap_assignments(text: str, bookings: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    normalized = text.lower().replace("ё", "е")
    positions: list[tuple[int, int, dict[str, Any]]] = []
    used: set[int] = set()
    for booking in bookings:
        booking_id = int(booking["id"])
        for pattern in _booking_reference_patterns(booking, bookings):
            match = re.search(pattern, normalized)
            if match and booking_id not in used:
                positions.append((match.start(), match.end(), booking))
                used.add(booking_id)
                break
    positions.sort(key=lambda item: item[0])
    assignments: list[dict[str, Any]] = []
    last_target: dict[str, Any] | None = None
    for index, (_start, end, booking) in enumerate(positions):
        next_start = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        segment = text[end:next_start]
        base_date = booking.get("booking_date") if isinstance(booking.get("booking_date"), date) else None
        date_patch = _date_patch_in_segment(segment, now, base_date=base_date)
        if not date_patch.get("date") and last_target and _means_same_target(segment):
            date_patch = {"date": last_target["date"]}
        if not date_patch.get("date"):
            continue
        time_patch = _time_period_patch(segment)
        target = {
            "booking_id": booking["id"],
            "date": date_patch["date"],
            "time": time_patch.get("time") or str(booking.get("booking_time"))[:5],
            "duration": time_patch.get("duration") or _hours_from_minutes(booking.get("duration_minutes")),
        }
        assignments.append(
            target
        )
        last_target = target
    return assignments


def _same_target_assignments_for_bookings(text: str, bookings: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    if len(bookings) < 2 or not _wants_multi_booking_reschedule(text):
        return []
    first_booking_date = bookings[0].get("booking_date") if isinstance(bookings[0].get("booking_date"), date) else None
    date_patch = _date_patch_in_segment(text, now, base_date=first_booking_date)
    if not date_patch.get("date"):
        return []
    time_patch = _time_period_patch(text)
    assignments: list[dict[str, Any]] = []
    for booking in bookings:
        assignments.append(
            {
                "booking_id": booking["id"],
                "date": date_patch["date"],
                "time": time_patch.get("time") or str(booking.get("booking_time"))[:5],
                "duration": time_patch.get("duration") or _hours_from_minutes(booking.get("duration_minutes")),
            }
        )
    return assignments


def _means_same_target(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("тоже", "также", "туда же", "на эту же", "на тот же", "то же"))


def _means_same_time(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if any(
        marker in normalized
        for marker in (
            "то же время",
            "тоже время",
            "такое же время",
            "в то же",
            "на то же",
            "в это же время",
            "время то же",
            "время такое же",
        )
    ):
        return True
    if any(marker in normalized for marker in ("час", "время")) and any(
        marker in normalized
        for marker in (
            "те же",
            "так же",
            "также",
            "как там",
            "как было",
            "без изменений",
        )
    ):
        return True
    return False


def _means_same_date(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
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


def _referenced_service_type_for_same_time(text: str) -> str | None:
    normalized = text.lower().replace("ё", "е")
    if "бесед" in normalized:
        return "gazebo"
    if "бан" in normalized:
        return "bathhouse"
    if "дом" in normalized or "домик" in normalized or "коттедж" in normalized:
        return "house"
    return None


def _same_booking_reference_patch(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    wants_same_time = _means_same_time(text)
    wants_same_date = _means_same_date(text)
    if not (wants_same_time or wants_same_date):
        return {}
    if (
        (not wants_same_date or form_data.get("date"))
        and (not wants_same_time or (form_data.get("time") and form_data.get("duration")))
    ):
        return {}
    bookings = _active_user_bookings(conn, conversation, form_data, now)
    if not bookings:
        return {}
    referenced_service = _referenced_service_type_for_same_time(text)
    explicit_reference = bool(referenced_service or _looks_like_prior_booking_reference_text(text))
    candidates = [
        booking for booking in bookings
        if not referenced_service or booking.get("service_type") == referenced_service
    ]
    if not candidates:
        return {}
    current_date = str(form_data.get("date") or "")
    if current_date:
        same_date = [booking for booking in candidates if str(booking.get("booking_date")) == current_date]
        if same_date:
            candidates = same_date
    booking = candidates[0]
    patch: dict[str, Any] = {}
    if wants_same_date and booking.get("booking_date") and (explicit_reference or not form_data.get("date")):
        patch["date"] = str(booking.get("booking_date"))
    if wants_same_time and booking.get("booking_time") and (explicit_reference or not form_data.get("time")):
        patch["time"] = str(booking.get("booking_time"))[:5]
    if wants_same_time and booking.get("duration_minutes") and (explicit_reference or not form_data.get("duration")):
        patch["duration"] = _hours_from_minutes(booking.get("duration_minutes"))
    return patch


def _same_time_reference_patch(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    return _same_booking_reference_patch(conn, conversation, form_data, text, now)


def _preserve_current_service_for_reference(
    patch: dict[str, Any],
    current_form_data: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    current_service = current_form_data.get("service_type")
    requested_service = patch.get("service_type")
    if (
        current_service
        and requested_service
        and requested_service != current_service
        and _looks_like_prior_booking_reference_text(text)
    ):
        cleaned = dict(patch)
        cleaned.pop("service_type", None)
        cleaned.pop("preferences", None)
        return cleaned
    return patch


def _means_same_object(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "та же бесед",
            "ту же бесед",
            "эта же бесед",
            "эту же бесед",
            "тот же объект",
            "тот же вариант",
            "оставляем",
            "оставить",
        )
    )


def _means_change_object(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "другую бесед",
            "другая бесед",
            "поменять бесед",
            "сменить бесед",
            "заменить бесед",
            "замен",
            "замеить",
            "на другую",
            "не эту",
            "поменьше",
            "меньше",
            "не такая большая",
            "не большая",
            "подешевле",
            "дешевле",
            "за 5800",
            "со светом",
            "светом",
            "розет",
        )
    )


def _booking_reference_patterns(booking: dict[str, Any], bookings: list[dict[str, Any]]) -> list[str]:
    title = _booking_object_title(booking).lower().replace("ё", "е")
    patterns: list[str] = []
    number_match = re.search(r"№\s*(\d+)", title)
    if number_match:
        number = number_match.group(1)
        patterns.extend(
            [
                rf"беседк[а-я\s]*(?:номер|№)?\s*{number}\b",
                rf"(?:номер|№)\s*{number}\b",
            ]
        )
        ordinal = {
            "1": "перв",
            "2": "втор",
            "3": "трет",
            "4": "четверт",
            "5": "пят",
            "6": "шест",
            "8": "восьм",
        }.get(number)
        if ordinal:
            patterns.append(rf"{ordinal}[а-я]*\s+беседк[а-я]*")
    if booking.get("service_type") == "bathhouse":
        patterns.append(r"бан[а-я]*")
    if booking.get("service_type") == "house":
        patterns.append(r"дом[а-я]*")
    try:
        index = bookings.index(booking) + 1
    except ValueError:
        index = 0
    ordinal_by_index = {1: "перв", 2: "втор", 3: "трет", 4: "четверт"}.get(index)
    if ordinal_by_index:
        patterns.append(rf"{ordinal_by_index}[а-я]*\s+(?:брон[а-я]*|беседк[а-я]*|бан[а-я]*|услуг[а-я]*)")
    ordinal_forms = {
        1: ("первую", "первая", "первой", "первую"),
        2: ("вторую", "вторая", "второй", "второе"),
        3: ("третью", "третья", "третьей", "третье"),
        4: ("четвертую", "четвертая", "четвертой", "четвертое"),
    }.get(index, ())
    patterns.extend(rf"\b{form}\b" for form in ordinal_forms)
    return patterns


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
    if len(bookings) > 1:
        same_target_assignments = _same_target_assignments_for_bookings(text, bookings, now)
        if len(same_target_assignments) >= 2:
            updated = {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}, "reschedule_flow": None}
            return _prepare_swap_reschedule(conn, conversation, bookings, same_target_assignments, updated, status, now)
    flow = {"stage": "reschedule", "booking_id": None} | _initial_reschedule_flow_patch(text, now)
    updated = {**form_data, "reschedule_flow": flow}
    if len(bookings) == 1:
        flow["booking_id"] = bookings[0]["id"]
        updated["reschedule_flow"] = flow
        return _handle_reschedule_flow(conn, conversation, text, updated, now)
    selected = _select_reschedule_booking(bookings, None, text)
    if selected:
        flow["booking_id"] = selected["id"]
        updated["reschedule_flow"] = flow
        return _handle_reschedule_flow(conn, conversation, text, updated, now)

    lines = ["Конечно, перенос возможен: аванс сохраняется, остаток можно будет внести на месте.", "", "Какую бронь переносим?"]
    for index, booking in enumerate(bookings, start=1):
        lines.append(f"{index}. {_booking_line_short(booking)}")
    return "\n".join(lines), status, "reserved", "payment_status", updated


def _initial_reschedule_flow_patch(text: str, now: datetime) -> dict[str, Any]:
    patch = _deterministic_patch(text, now)
    flow_patch: dict[str, Any] = {}
    if patch.get("date"):
        flow_patch["date"] = patch["date"]
    if patch.get("time"):
        flow_patch["time"] = patch["time"]
    if patch.get("duration"):
        flow_patch["duration"] = patch["duration"]
    if _means_same_time(text):
        flow_patch["same_time"] = True
    if _means_same_object(text):
        flow_patch["same_object"] = True
    if _means_change_object(text):
        flow_patch["same_object"] = False
        flow_patch["change_object"] = True
    variant = (_reschedule_service_variant_patch(text) or {}).get("service_variant")
    if variant:
        flow_patch["service_variant"] = variant
        flow_patch["same_object"] = False
        flow_patch["change_object"] = True
    return flow_patch


def _reschedule_service_variant_patch(text: str, *, allow_bare: bool = False) -> dict[str, str]:
    normalized = text.lower().replace("ё", "е")
    variants: list[tuple[int, str]] = []
    patterns = (
        r"\bбеседк[а-яё]*\s*(?:на\s*)?(?:№|номер\s*)?([1-8])\b",
        r"(?:№|номер)\s*([1-8])\b",
        r"\b([1-8])\s*(?:-?\s*)?(?:ю|ую|ая|я)?\s*беседк",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            variants.append((match.start(), f"Беседка №{match.group(1)}"))
    if "крыт" in normalized and "бесед" in normalized:
        variants.append((normalized.find("крыт"), "Крытая беседка"))
    if variants:
        variants.sort(key=lambda item: item[0])
        return {"service_variant": variants[-1][1]}
    if "бесед" in normalized:
        ordinal_patch = _service_variant_patch(text, allow_bare_ordinal=True)
        if ordinal_patch.get("service_variant"):
            return {"service_variant": ordinal_patch["service_variant"]}
    if allow_bare:
        return _service_variant_patch(text, allow_bare_ordinal=True)
    return {}


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
    if not bookings and flow.get("booking_id"):
        direct_booking = bookings_repo.get_by_id(conn, booking_id=int(flow["booking_id"]))
        if direct_booking and direct_booking.get("status") != "cancelled":
            bookings = [direct_booking]
            status = "payment_paid" if direct_booking.get("payment_status") == "paid" else status
    if len(bookings) > 1:
        same_target_assignments = _same_target_assignments_for_bookings(text, bookings, now)
        if len(same_target_assignments) >= 2:
            updated = {**form_data, "swap_reschedule_flow": {"stage": "collect_swap"}, "reschedule_flow": None}
            return _prepare_swap_reschedule(conn, conversation, bookings, same_target_assignments, updated, status, now)
    booking = _select_reschedule_booking(bookings, flow.get("booking_id"), text)
    if not booking:
        lines = ["Какую бронь переносим?"]
        for index, item in enumerate(bookings, start=1):
            lines.append(f"{index}. {_booking_line_short(item)}")
        return "\n".join(lines), status, "reserved", "payment_status", {**form_data, "reschedule_flow": flow}

    if flow.get("stage") == "choose_reschedule_variant":
        candidate = flow.get("candidate_variant")
        variant_patch = _reschedule_service_variant_patch(text, allow_bare=True)
        if _confirmation_yes(text) and candidate:
            flow = flow | {
                "stage": "reschedule",
                "service_variant": candidate,
                "same_object": False,
                "change_object": True,
            }
            form_data = {**form_data, "reschedule_flow": flow}
        elif variant_patch.get("service_variant"):
            flow = flow | {
                "stage": "reschedule",
                "service_variant": variant_patch["service_variant"],
                "same_object": False,
                "change_object": True,
            }
            form_data = {**form_data, "reschedule_flow": flow}
        else:
            preference_patch = _guests_count_patch(text, "guests_count")
            if preference_patch or _means_change_object(text):
                flow = flow | {"stage": "reschedule"}
                if preference_patch:
                    flow["guests_count"] = preference_patch["guests_count"]
                form_data = {**form_data, "reschedule_flow": flow}
            else:
                return (
                    "Какую беседку ставим вместо текущей? Можно написать номер или «да», если подходит предложенный вариант.",
                    status,
                    "reserved",
                    "payment_status",
                    {**form_data, "reschedule_flow": flow},
                )

    if flow.get("stage") == "confirm_reschedule":
        if _confirmation_no(text):
            return "Хорошо, оставила бронь без изменений ✅", status, "reserved", "payment_status", {**form_data, "reschedule_flow": None}
        if not _confirmation_yes(text):
            return _reschedule_confirmation_reply(booking, flow), status, "reserved", "payment_status", {**form_data, "reschedule_flow": flow}
        return _execute_reschedule(conn, conversation, booking, form_data, flow)

    patch = _deterministic_patch(text, now)
    guests_patch = _guests_count_patch(text, "guests_count")
    if guests_patch:
        patch |= guests_patch
    patch.pop("service_variant", None)
    variant_patch = _reschedule_service_variant_patch(
        text,
        allow_bare=bool(flow.get("change_object") and not flow.get("service_variant")),
    )
    if variant_patch:
        patch |= variant_patch
    target_from_marker = _reschedule_target_date_patch(text, now, booking)
    if target_from_marker:
        patch["date"] = target_from_marker["date"]
    if patch.get("time") and not patch.get("duration"):
        patch["duration"] = _hours_from_minutes(booking.get("duration_minutes"))
    same_time = bool(flow.get("same_time")) or _means_same_time(text)
    same_object = bool(flow.get("same_object")) or _means_same_object(text)
    change_object = bool(flow.get("change_object")) or _means_change_object(text)
    normalized_preferences = text.lower().replace("ё", "е")
    wants_smaller = any(
        marker in normalized_preferences
        for marker in (
            "поменьше",
            "меньше",
            "не большая",
            "не такая большая",
            "подешевле",
            "дешевле",
        )
    )
    wants_light = "свет" in normalized_preferences or "розет" in normalized_preferences
    price_limit = _price_limit_from_text(text)
    current_variant = _booking_object_title(booking)
    requested_variant = patch.get("service_variant") or flow.get("service_variant")
    target_variant = None
    if booking.get("service_type") == "gazebo":
        if requested_variant:
            target_variant = _canonical_reschedule_gazebo_variant(str(requested_variant))
            if _normalize_gazebo_title(target_variant) == _normalize_gazebo_title(current_variant):
                same_object = True
                change_object = False
            else:
                same_object = False
                change_object = True
        elif change_object:
            target_variant = None
            same_object = False
        else:
            target_variant = current_variant
            same_object = True
    if _bare_weekday_confirmation(text, now) and not patch.get("date"):
        return _bare_weekday_confirmation(text, now) or "", status, "reserved", "payment_status", {**form_data, "reschedule_flow": flow | {"booking_id": booking["id"]}}

    target_date = patch.get("date") or flow.get("date")
    target_time = patch.get("time") or flow.get("time")
    if change_object and not target_date and booking.get("booking_date"):
        target_date = str(booking.get("booking_date"))
    if change_object and not target_time and booking.get("booking_time"):
        target_time = str(booking.get("booking_time"))[:5]
        same_time = True
    if not target_time and same_time:
        target_time = str(booking.get("booking_time"))[:5]
    target_duration = patch.get("duration") or flow.get("duration")
    if target_time and not target_duration:
        target_duration = _hours_from_minutes(booking.get("duration_minutes"))
    flow = flow | {
        "booking_id": booking["id"],
        "date": target_date,
        "time": target_time,
        "duration": target_duration,
        "same_time": same_time,
        "same_object": same_object,
        "change_object": change_object,
        "service_variant": target_variant,
    }
    if patch.get("guests_count"):
        flow["guests_count"] = patch["guests_count"]
    if wants_smaller:
        flow["wants_smaller"] = True
    if wants_light:
        flow["wants_light"] = True
    if price_limit:
        flow["price_limit"] = price_limit
    updated = {**form_data, "reschedule_flow": flow}
    option_reply = _reschedule_gazebo_change_options_reply(
        conn,
        conversation,
        booking,
        form_data,
        flow,
        text,
        now,
    )
    if option_reply:
        reply, option_flow = option_reply
        return reply, status, "reserved", "payment_status", {**form_data, "reschedule_flow": option_flow}
    if not target_date:
        return (
            f"Переносим {_booking_line_short(booking)}.\n\nНа какую новую дату?",
            status,
            "reserved",
            "payment_status",
            updated,
        )
    if not target_time:
        if booking.get("service_type") == "gazebo":
            if target_variant and _normalize_gazebo_title(target_variant) != _normalize_gazebo_title(current_variant):
                variant_line = f"Меняем беседку на: {target_variant}."
            elif target_variant:
                variant_line = f"Беседку оставляем ту же: {target_variant}."
            else:
                variant_line = f"Беседку можем поменять. Какую ставим вместо {current_variant}?"
        else:
            variant_line = f"Услугу оставляем ту же: {current_variant}."
        return (
            f"Поняла дату: {_format_date_ru(target_date)}.\n\n"
            f"{variant_line}\n\n"
            "Во сколько хотите приехать? Можно написать «в то же время» или указать новый период, например: с 18:00 до 00:00.",
            status,
            "reserved",
            "payment_status",
            updated,
        )
    if booking.get("service_type") == "gazebo" and change_object and not target_variant:
        return (
            f"Дату и время поняла: {_format_date_ru(target_date)}, с {target_time}.\n\n"
            f"Какую беседку ставим вместо {current_variant}? Можно написать номер беседки или «оставить ту же».",
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
                f"На {_format_date_ru(target_date)} с {target_time} свободного варианта для переноса не нашла. Напишите другую дату или время — проверю ещё раз.",
                check_form,
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


def _reschedule_gazebo_change_options_reply(
    conn,
    conversation: dict[str, Any],
    booking: dict[str, Any],
    form_data: dict[str, Any],
    flow: dict[str, Any],
    text: str,
    now: datetime,
) -> tuple[str, dict[str, Any]] | None:
    if booking.get("service_type") != "gazebo" or not flow.get("change_object") or flow.get("service_variant"):
        return None
    target_date = flow.get("date")
    if not target_date:
        return None
    target_time = flow.get("time") or str(booking.get("booking_time") or "")[:5]
    target_duration = flow.get("duration") or _hours_from_minutes(booking.get("duration_minutes"))
    lookup_flow = flow | {
        "time": target_time,
        "duration": target_duration,
        "same_time": True,
    }
    check_form = _form_data_for_booking_reschedule(form_data, booking, lookup_flow)
    check_form["service_variant"] = None
    availability = check_availability(conn, form_data=check_form, now=now)
    if availability.ok and not availability.slots:
        return (
            _append_waitlist_offer(
                f"На {_format_date_ru(target_date)} свободных беседок для замены не нашла. Напишите другую дату или время — проверю ещё раз.",
                check_form,
            ),
            lookup_flow,
        )
    options_form = _remember_available_gazebo_variants(check_form, availability.slots)
    variants = _available_gazebo_variant_configs(options_form) or []
    variants = _filter_reschedule_gazebo_options(variants, booking, flow, text)
    if not variants:
        return (
            "На эту дату вижу свободные беседки, но подходящих под ваши пожелания не нашла.\n\n"
            "Можно написать другое количество гостей, бюджет или конкретный номер беседки — проверю ещё раз.",
            lookup_flow,
        )
    if len(variants) == 1:
        variant = variants[0]
        title = str(variant.get("title") or "беседка")
        confirm_flow = lookup_flow | {
            "stage": "confirm_reschedule",
            "service_variant": title,
            "same_object": False,
            "change_object": True,
        }
        return (
            f"Подходит {_format_gazebo_variant_line(variant)} ✅\n\n"
            f"{_reschedule_confirmation_reply(booking, confirm_flow)}",
            confirm_flow,
        )
    lines = ["Из свободных вариантов под ваши пожелания подходят:"]
    for variant in variants:
        lines.append(f"- {_format_gazebo_variant_line(variant)}")
    lines.append("")
    lines.append("Какую беседку ставим вместо текущей?")
    return "\n".join(lines), lookup_flow | {"stage": "choose_reschedule_variant"}


def _filter_reschedule_gazebo_options(
    variants: list[dict[str, Any]],
    booking: dict[str, Any],
    flow: dict[str, Any],
    text: str,
) -> list[dict[str, Any]]:
    normalized = text.lower().replace("ё", "е")
    current_title = _normalize_gazebo_title(_booking_object_title(booking))
    current_capacity = _gazebo_capacity_by_title(_booking_object_title(booking))
    guests = flow.get("guests_count")
    wants_smaller = bool(flow.get("wants_smaller")) or any(marker in normalized for marker in ("поменьше", "меньше", "не большая", "не такая большая", "подешевле", "дешевле"))
    wants_light = bool(flow.get("wants_light")) or "свет" in normalized or "розет" in normalized
    price_limit = flow.get("price_limit") or _price_limit_from_text(text)
    result: list[dict[str, Any]] = []
    for variant in variants:
        title = str(variant.get("title") or "")
        if _normalize_gazebo_title(title) == current_title:
            continue
        capacity = int(variant.get("capacity_max") or 0)
        if guests and capacity and capacity < int(guests):
            continue
        if wants_smaller and current_capacity and capacity and capacity > current_capacity:
            continue
        if wants_light and not _gazebo_variant_has_light(title):
            continue
        price = int(variant.get("price") or 0)
        if price_limit and price and price > price_limit:
            continue
        result.append(variant)
    return sorted(result, key=lambda item: (int(item.get("capacity_max") or 9999), int(item.get("price") or 999999)))


def _gazebo_capacity_by_title(title: str) -> int | None:
    normalized = _normalize_gazebo_title(title)
    for variant in (load_services_map().get("gazebo") or {}).get("variants") or []:
        if _normalize_gazebo_title(variant.get("title")) == normalized:
            return int(variant.get("capacity_max") or 0)
    return None


def _gazebo_variant_has_light(title: str) -> bool:
    normalized = _normalize_gazebo_title(title)
    return any(marker in normalized for marker in ("№1", "№3", "№8", "крыт"))


def _price_limit_from_text(text: str) -> int | None:
    normalized = text.lower().replace(" ", "")
    match = re.search(r"(?:за|до)?(\d{4,5})(?:р|руб|₽)?", normalized)
    if not match:
        return None
    value = int(match.group(1))
    return value if value >= 1000 else None


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
        return (
            "Сейчас не получилось изменить запись в журнале.\n\n"
            "Старую бронь оставила без изменений. Напишите другую дату или время — проверю ещё раз.",
            "payment_paid",
            "reserved",
            "payment_status",
            {**form_data, "reschedule_flow": None},
        )

    new_date = datetime.fromisoformat(str(target_date)).date()
    new_time = datetime.strptime(str(target_time)[:5], "%H:%M").time()
    new_duration = _duration_minutes_value(target_duration)
    target_form = _form_data_for_booking_reschedule(form_data, old_booking, flow)
    target_variant_config = _selected_variant_config(target_form)
    target_yclients_service_id = str(
        target_variant_config.get("yclients_service_id")
        or old_booking.get("hold_yclients_service_id")
        or ""
    )
    updated_booking = bookings_repo.update_schedule(
        conn,
        booking_id=int(booking["id"]),
        booking_date=new_date,
        booking_time=new_time,
        duration_minutes=new_duration,
    )
    if updated_booking and flow.get("guests_count"):
        updated_booking = bookings_repo.update_details(
            conn,
            booking_id=int(booking["id"]),
            guests_count=int(flow["guests_count"]),
        ) or updated_booking
    if updated_booking:
        if updated_booking.get("slot_hold_id"):
            updated_hold = slot_holds_repo.update_slot(
                conn,
                hold_id=int(updated_booking["slot_hold_id"]),
                yclients_service_id=target_yclients_service_id,
                slot_date=new_date,
                slot_time=new_time,
                duration_minutes=new_duration,
                now=_now_local(),
            )
            if updated_hold:
                target_yclients_service_id = str(updated_hold.get("yclients_service_id") or target_yclients_service_id)
        updated_booking = {
            **updated_booking,
            "hold_yclients_service_id": target_yclients_service_id,
        }
        upsert_local_busy_interval_for_booking(conn, booking=updated_booking)
        try:
            create_yclients_record_for_booking(conn, booking=updated_booking)
        except Exception as exc:
            logger.exception("Failed to create YCLIENTS record after reschedule booking_id=%s", booking.get("id"))
            restored = _restore_booking_after_failed_reschedule(conn, old_booking)
            if restored:
                return (
                    "Новое время не получилось закрепить в журнале: похоже, слот уже занят или недоступен.\n\n"
                    f"Старую бронь восстановила: {_booking_line_short(restored)}.\n\n"
                    "Напишите другую дату или время — проверю ещё раз.",
                    "payment_paid",
                    "reserved",
                    "payment_status",
                    {**form_data, "reschedule_flow": None},
                )
            user = users_repo.get_by_id(conn, int(conversation["user_id"]))
            if user:
                _start_user_handoff(
                    conn,
                    user=user,
                    conversation_id=conversation["id"],
                    text=f"перенос брони #{booking.get('id')}",
                    now=_now_local(),
                    reason="не удалось восстановить старую запись после ошибки переноса",
                )
            return _handoff_reply(), "handoff", "handoff", "handoff", form_data
    cleared = {**form_data, "date": target_date, "time": target_time, "duration": target_duration, "reschedule_flow": None}
    if flow.get("guests_count"):
        cleared["guests_count"] = flow.get("guests_count")
    variant_line = ""
    if booking.get("service_type") == "gazebo" and flow.get("service_variant"):
        cleared["service_variant"] = flow.get("service_variant")
        variant_line = f"\nБеседка: {flow.get('service_variant')}."
    return (
        f"Готово ✅\n\nПеренесла бронь на {_format_date_ru(target_date)}, с {target_time} на {_format_duration(target_duration)}.{variant_line}\n\nАванс сохраняется, остаток можно будет внести на месте.",
        "payment_paid",
        "reserved",
        "payment_status",
        cleared,
    )


def _restore_booking_after_failed_reschedule(conn, old_booking: dict[str, Any]) -> dict[str, Any] | None:
    old_date = old_booking.get("booking_date")
    old_time = old_booking.get("booking_time")
    old_duration = old_booking.get("duration_minutes")
    if not old_date or not old_time:
        return None
    restored = bookings_repo.update_schedule(
        conn,
        booking_id=int(old_booking["id"]),
        booking_date=old_date,
        booking_time=old_time,
        duration_minutes=old_duration,
    )
    if not restored:
        return None
    if restored.get("slot_hold_id"):
        slot_holds_repo.update_slot(
            conn,
            hold_id=int(restored["slot_hold_id"]),
            yclients_service_id=str(old_booking.get("hold_yclients_service_id") or ""),
            slot_date=old_date,
            slot_time=old_time,
            duration_minutes=old_duration,
            now=_now_local(),
        )
    restored = {
        **restored,
        "hold_yclients_service_id": old_booking.get("hold_yclients_service_id"),
    }
    try:
        create_yclients_record_for_booking(conn, booking=restored)
    except Exception:
        logger.exception("Failed to restore old YCLIENTS record booking_id=%s", old_booking.get("id"))
        upsert_local_busy_interval_for_booking(conn, booking=restored)
        return restored
    return bookings_repo.get_by_id(conn, booking_id=int(old_booking["id"])) or restored


def _reschedule_target_date_patch(text: str, now: datetime, booking: dict[str, Any]) -> dict[str, str]:
    booking_date = booking.get("booking_date")
    base_date = booking_date if isinstance(booking_date, date) else None
    normalized = text.lower().replace("ё", "е")
    if base_date and any(marker in normalized for marker in ("на денек позже", "на денёк позже", "день позже", "на день позже", "следующий день", "на следующий день")):
        return {"date": (base_date + timedelta(days=1)).isoformat()}
    if base_date and any(marker in normalized for marker in ("на денек раньше", "на денёк раньше", "день раньше", "на день раньше", "предыдущий день", "на предыдущий день")):
        return {"date": (base_date - timedelta(days=1)).isoformat()}
    for marker in (
        "перенести на",
        "перенеси на",
        "перенесите на",
        "перенесем на",
        "перенесём на",
        "пернести на",
        "пернести на",
        "поменять на",
        "изменить на",
    ):
        patch = _date_patch_after_marker(text, now, marker, base_date=base_date)
        if patch:
            return patch
    patch = _reschedule_source_target_day_patch(text, now, base_date)
    if patch:
        return patch
    patch = _last_explicit_date_patch(text, now, exclude_date=base_date)
    if patch:
        return patch
    return {}


def _reschedule_confirmation_reply(booking: dict[str, Any], flow: dict[str, Any]) -> str:
    target_date = flow.get("date")
    target_time = flow.get("time")
    target_duration = flow.get("duration")
    current_variant = _booking_object_title(booking)
    target_variant = flow.get("service_variant")
    variant_line = ""
    if (
        booking.get("service_type") == "gazebo"
        and target_variant
        and _normalize_gazebo_title(target_variant) != _normalize_gazebo_title(current_variant)
    ):
        variant_line = f"Новая беседка: {target_variant}.\n\n"
    return (
        "Проверила, на новое время свободно ✅\n\n"
        f"Перенести бронь «{_booking_line_short(booking)}» "
        f"на {_format_date_ru(target_date)}, с {target_time} на {_format_duration(target_duration)}?\n\n"
        f"{variant_line}"
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
    ordinal_index = _ordinal_index(normalized)
    if ordinal_index is not None and 0 <= ordinal_index < len(bookings):
        return bookings[ordinal_index]
    service_patch = _service_type_patch(text)
    service_type = service_patch.get("service_type")
    if service_type:
        matches = [booking for booking in bookings if booking.get("service_type") == service_type]
        variant = (_service_variant_patch(text) or {}).get("service_variant")
        if variant:
            variant_lower = str(variant).lower().replace("ё", "е")
            variant_matches = [
                booking
                for booking in matches
                if str(_booking_object_title(booking)).lower().replace("ё", "е") == variant_lower
            ]
            if variant_matches:
                matches = variant_matches
        date_patch = _relative_date_patch(text, _now_local())
        if date_patch.get("date"):
            dated = [booking for booking in matches if str(booking.get("booking_date")) == date_patch["date"]]
            if len(dated) == 1:
                return dated[0]
        if len(matches) == 1:
            return matches[0]
    return bookings[0] if len(bookings) == 1 else None


def _ordinal_index(text: str) -> int | None:
    words = {
        "первую": 0,
        "первая": 0,
        "первый": 0,
        "первое": 0,
        "вторую": 1,
        "вторая": 1,
        "второй": 1,
        "второе": 1,
        "третью": 2,
        "третья": 2,
        "третий": 2,
        "третье": 2,
        "четвертую": 3,
        "четвертая": 3,
        "четвертый": 3,
        "четвертое": 3,
        "пятую": 4,
        "пятая": 4,
        "пятый": 4,
        "пятое": 4,
    }
    for word, index in words.items():
        if re.search(rf"\b{word}\b", text):
            return index
    return None


def _form_data_for_booking_reschedule(form_data: dict[str, Any], booking: dict[str, Any], flow: dict[str, Any]) -> dict[str, Any]:
    service_type = booking.get("service_type")
    ignore_source_record_ids = {
        str(item)
        for item in (form_data.get("ignore_source_record_ids") or [])
        if item
    }
    if booking.get("yclients_record_id"):
        ignore_source_record_ids.add(str(booking.get("yclients_record_id")))
    updated = {
        **form_data,
        "service_type": service_type,
        "date": flow.get("date"),
        "time": flow.get("time"),
        "duration": flow.get("duration"),
        "guests_count": flow.get("guests_count") or booking.get("guests_count") or form_data.get("guests_count"),
        "ignore_source_record_ids": sorted(ignore_source_record_ids),
    }
    if service_type == "gazebo":
        updated["service_variant"] = flow.get("service_variant") or _booking_object_title(booking)
    return updated


def _canonical_reschedule_gazebo_variant(value: str) -> str:
    normalized = _normalize_gazebo_title(value)
    variants = (load_services_map().get("gazebo") or {}).get("variants") or []
    for variant in variants:
        title = str(variant.get("title") or "")
        if _normalize_gazebo_title(title) == normalized:
            return title
    return value


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
    deterministic_reply = _deterministic_process_reply(required_meaning)
    if deterministic_reply:
        return _clean_reply(deterministic_reply)
    try:
        reply = _clean_reply(generate_process_reply(
            text=text,
            form_data=form_data,
            history=history,
            required_meaning=required_meaning,
            knowledge=load_knowledge(),
        ))
        if _looks_like_internal_instruction_text(reply):
            logger.warning("AI process reply looked like internal instruction, using fallback")
            return _clean_reply(_fallback_process_reply(required_meaning, form_data))
        return reply
    except AIProviderUnavailable:
        raise
    except Exception:
        logger.exception("AI process reply generation failed")
        return _clean_reply(_fallback_process_reply(required_meaning, form_data))


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
            and not form_data.get("guests_count")
        ):
            prefix = "свободна" if form_data.get("single_available_gazebo_variant_auto") else "свободна"
            return (
                f"На {date_text} {prefix}: {form_data['service_variant']} ✅\n\n"
                "Сколько вас будет человек? Проверю, подходит ли она по вместимости.",
                "guests_count",
            )
        if (
            form_data.get("service_type") == "gazebo"
            and form_data.get("service_variant")
            and form_data.get("guests_count")
            and not form_data.get("time")
        ):
            capacity = _gazebo_capacity_by_title(str(form_data.get("service_variant")))
            capacity_note = (
                f"{form_data['service_variant']} рассчитана до {capacity} человек, "
                f"для {form_data.get('guests_count')} гостей подходит ✅"
                if capacity
                else f"{form_data.get('guests_count')} гостей для {form_data['service_variant']} подходит ✅"
            )
            return (
                f"{capacity_note}\n\n"
                "Во сколько хотите приехать? Можно сразу написать период, например: с 18:00 до 00:00.",
                "time",
            )
        if form_data.get("service_type") == "gazebo" and not form_data.get("service_variant"):
            options = ", ".join(slot.split(":", 1)[0] for slot in slots[:8])
            if not form_data.get("guests_count"):
                return (
                    f"На {date_text} свободны: {options} ✅\n\n"
                    "Сколько вас будет человек? Подскажу подходящие свободные варианты.",
                    "guests_count",
                )
            return _gazebo_selection_text(form_data), "service_variant"
        if form_data.get("time") and form_data.get("duration"):
            if "свобод" in shown.lower():
                text = shown.rstrip(".") + "."
            else:
                text = f"{shown} свободно."
        else:
            selected_title = form_data.get("service_variant") if form_data.get("service_type") == "gazebo" else None
            if selected_title:
                text = f"На {date_text} {selected_title} свободна ✅."
            else:
                availability_word = "свободен" if form_data.get("service_type") == "house" else "свободна"
                text = f"На {date_text} {title.lower()} {availability_word} ✅."
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


def _alternative_services_for_unavailable_date(
    conn,
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str] | None:
    service_type = form_data.get("service_type")
    if service_type not in {"house", "bathhouse", "warm_gazebo"}:
        return None
    date_value = form_data.get("date") or (form_data.get("last_unavailable") or {}).get("date")
    if not date_value:
        return None
    guests_count = form_data.get("guests_count") or (form_data.get("last_unavailable") or {}).get("guests_count")
    source_title = "гостевой дом" if service_type == "house" else (load_services_map().get(service_type) or {}).get("title") or "выбранный объект"
    date_text = _format_date_ru(date_value)
    alternatives: list[str] = []

    gazebo_form = {
        **form_data,
        "service_type": "gazebo",
        "service_variant": None,
        "date": date_value,
        "guests_count": guests_count,
        "time": form_data.get("time"),
        "duration": form_data.get("duration"),
    }
    gazebo_availability = check_availability(conn, form_data=gazebo_form, now=now)
    gazebo_slots = _suitable_gazebo_slots(gazebo_availability.slots, guests_count)
    if gazebo_availability.ok and gazebo_slots:
        gazebo_form = _remember_available_gazebo_variants(gazebo_form, gazebo_slots)
        variants = _available_gazebo_variant_configs(gazebo_form) or []
        if guests_count:
            variants = [
                variant for variant in variants
                if int(variant.get("capacity_max") or 0) >= int(guests_count)
            ]
        if variants:
            if int(guests_count or 0) >= 20:
                variants = sorted(
                    variants,
                    key=lambda item: (
                        0 if "№1" in str(item.get("title") or "") else 1,
                        int(item.get("price") or 999999),
                    ),
                )
            shown = "\n".join(f"- {_format_gazebo_variant_line(variant)}" for variant in variants[:5])
            alternatives.append(f"Свободные беседки:\n{shown}")

    for alt_service in ("warm_gazebo", "bathhouse"):
        if alt_service == service_type:
            continue
        alt_config = load_services_map().get(alt_service) or {}
        if not alt_config:
            continue
        alt_form = {
            **form_data,
            "service_type": alt_service,
            "service_variant": None,
            "date": date_value,
        }
        availability = check_availability(conn, form_data=alt_form, now=now)
        if availability.ok and availability.slots:
            alternatives.append(f"{alt_config.get('title') or alt_service}: свободно")

    if not alternatives:
        return None

    reply = (
        f"На {date_text} свободных вариантов для «{source_title}» не нашла.\n\n"
        "Но на эту дату можно рассмотреть другие варианты 👇\n\n"
        + "\n\n".join(alternatives)
        + "\n\nЕсли хотите, можем переключиться на подходящую беседку или другую услугу на эту же дату."
    )
    return reply, "service_type"


def _looks_like_event_context_for_alternatives(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(
        marker in normalized
        for marker in (
            "праздник",
            "отметить",
            "отмечать",
            "мероприят",
            "день рождения",
            "др",
            "корпоратив",
            "компания",
            "гости",
        )
    )


def _waitlist_request_text(form_data: dict[str, Any] | None) -> str:
    if not form_data:
        return "этот запрос"
    service_type = form_data.get("service_type")
    title = (load_services_map().get(service_type) or {}).get("title") or "услугу"
    parts = [title.lower()]
    if form_data.get("guests_count"):
        parts.append(f"для {form_data.get('guests_count')} гостей")
    if form_data.get("date"):
        parts.append(f"на {_format_date_ru(form_data.get('date'))}")
    if form_data.get("time"):
        parts.append(f"с {form_data.get('time')}")
    if form_data.get("service_variant"):
        parts.append(str(form_data.get("service_variant")))
    return " ".join(parts)


def _append_waitlist_offer(reply: str, form_data: dict[str, Any] | None = None) -> str:
    request_text = _waitlist_request_text(form_data)
    return (
        f"{reply}\n\n"
        f"Я запомнила запрос: {request_text}. Если место освободится из-за отмены, мы сможем вас уведомить."
    )


def _next_free_dates_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
    *,
    limit: int = 5,
    days_ahead: int = 75,
) -> str | None:
    last_unavailable = form_data.get("last_unavailable") or {}
    service_type = form_data.get("service_type") or last_unavailable.get("service_type")
    if not service_type:
        return None

    service_config = load_services_map().get(service_type) or {}
    title = service_config.get("title") or service_type
    booked_dates = {
        str(booking.get("booking_date"))
        for booking in _active_user_bookings(conn, conversation, form_data, now)
        if booking.get("service_type") == service_type
    }
    previously_suggested_dates = {
        str(item)
        for item in (form_data.get("last_suggested_free_dates") or [])
        if item
    }

    start = now.date()
    unavailable_date = last_unavailable.get("date") or form_data.get("date")
    if unavailable_date:
        try:
            start = max(start, datetime.fromisoformat(str(unavailable_date)).date() + timedelta(days=1))
        except ValueError:
            pass

    time_value = form_data.get("time") or last_unavailable.get("time")
    duration_value = form_data.get("duration") or last_unavailable.get("duration")
    guests_count = form_data.get("guests_count") or last_unavailable.get("guests_count")
    service_variant = form_data.get("service_variant") or last_unavailable.get("service_variant")

    found: list[tuple[date, list[str]]] = []
    for offset in range(days_ahead):
        candidate = start + timedelta(days=offset)
        if candidate.isoformat() in booked_dates:
            continue
        if candidate.isoformat() in previously_suggested_dates:
            continue
        check_form = {
            **form_data,
            "service_type": service_type,
            "service_variant": service_variant,
            "date": candidate.isoformat(),
            "time": time_value,
            "duration": duration_value,
            "guests_count": guests_count,
        }
        availability = check_availability(conn, form_data=check_form, now=now)
        slots = _suitable_gazebo_slots(availability.slots, guests_count) if service_type == "gazebo" else availability.slots
        if availability.ok and slots:
            found.append((candidate, slots))
            if len(found) >= limit:
                break

    if not found:
        return (
            f"На ближайшие {days_ahead} дней свободных дат для «{title}» не нашла.\n\n"
            "Можно написать другой период или выбрать другую услугу — проверю по журналу."
        )

    if service_type == "gazebo" and guests_count:
        lines = [f"Ближайшие даты, где есть беседки для {guests_count} гостей:"]
    else:
        lines = [f"Ближайшие свободные даты для «{title}»:"]
    for candidate, slots in found:
        if service_type == "gazebo":
            variants = ", ".join(_gazebo_title_from_slot(slot) for slot in slots[:5])
            lines.append(f"- {_format_date_ru(candidate)}: {variants}")
        else:
            first_slot = slots[0].split(":", 1)[1].strip() if ":" in slots[0] else slots[0]
            lines.append(f"- {_format_date_ru(candidate)}: {first_slot}")
    lines.append("")
    lines.append("Какую дату выбираете?")
    form_data["last_suggested_free_dates"] = sorted(
        previously_suggested_dates | {candidate.isoformat() for candidate, _ in found}
    )[-20:]
    return "\n".join(lines)


def _reset_unavailable_slot(form_data: dict[str, Any]) -> dict[str, Any]:
    updated = form_data.copy()
    updated["last_unavailable"] = {
        "service_type": form_data.get("service_type"),
        "date": form_data.get("date"),
        "time": form_data.get("time"),
        "duration": form_data.get("duration"),
        "guests_count": form_data.get("guests_count"),
        "service_variant": form_data.get("service_variant"),
    }
    updated["date"] = None
    updated["time"] = None
    updated["duration"] = None
    if form_data.get("last_suggested_free_dates"):
        updated["last_suggested_free_dates"] = form_data.get("last_suggested_free_dates")
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


def _direct_free_dates_lookup(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    *,
    force_new: bool = False,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    if not _asks_for_free_slots(text):
        return None
    current_form_data = conversation.get("form_data") or {}
    patch = (
        _deterministic_patch(text, now)
        | _guests_count_patch(text, "guests_count")
    )
    service_patch = _normalize_service_aliases({"service_type": patch.get("service_type")})
    requested_service = service_patch.get("service_type")
    current_service = _normalize_service_aliases({"service_type": current_form_data.get("service_type")}).get("service_type")
    service_type = requested_service or current_service or (current_form_data.get("last_unavailable") or {}).get("service_type")
    if not service_type:
        return None

    if force_new or (requested_service and requested_service != current_service):
        form_data = _new_booking_form_data(current_form_data)
    else:
        form_data = dict(current_form_data)
    form_data.pop("stale_form_flow", None)
    form_data["service_type"] = service_type
    form_data = merge_form_data(form_data, patch)
    form_data = _normalize_service_aliases(form_data)
    if form_data.get("service_type") != "gazebo":
        form_data["service_variant"] = None

    if _asks_nearest_free_dates(text):
        if not patch.get("date"):
            form_data["date"] = None
        if not patch.get("time"):
            form_data["time"] = None
        if not patch.get("duration"):
            form_data["duration"] = None

    if form_data.get("date") and not _asks_nearest_free_dates(text):
        availability = check_availability(conn, form_data=form_data, now=now)
        if availability.ok and availability.slots:
            form_data = _remember_available_gazebo_variants(form_data, availability.slots)
            form_data = _auto_select_single_available_gazebo(form_data)
            reply, next_key = _availability_reply(availability.message, availability.slots, form_data)
            return reply, "waiting_user", next_key or "date", next_key, form_data
        alternative = _alternative_services_for_unavailable_date(conn, form_data, now)
        if alternative:
            reply, next_key = alternative
            return reply, "waiting_user", "service_type", next_key, _reset_unavailable_slot(form_data)

    reply = _next_free_dates_reply(conn, conversation, form_data, now)
    if not reply:
        return None
    return reply, "waiting_user", "awaiting_new_date", "date", form_data


def _continues_booking_summary_question(text: str, history: list[dict[str, Any]]) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    if normalized not in {"и это все", "и это всё", "это все", "это всё", "только одна", "только одну"}:
        return False
    for item in reversed(history[:-1]):
        if item.get("sender") == SENDER_USER:
            continue
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        previous = str(item.get("text") or "").lower().replace("ё", "е")
        return "брон" in previous
    return False


def _last_assistant_asked_upsell(history: list[dict[str, Any]]) -> bool:
    for item in reversed(history):
        if item.get("sender") == SENDER_USER:
            continue
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        text = str(item.get("text") or "").lower().replace("ё", "е")
        return (
            "что подготовить" in text
            and any(marker in text for marker in ("доп", "уголь", "розжиг", "решет", "шампур", "кальян", "воду"))
        )
    return False


def _last_assistant_asked_name_correction(history: list[dict[str, Any]]) -> bool:
    for item in reversed(history):
        if item.get("sender") == SENDER_USER:
            continue
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        text = str(item.get("text") or "").lower().replace("ё", "е")
        return "какое имя указать" in text or "как имя указать" in text
    return False


def _is_waitlist_decline(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    return any(
        marker in normalized
        for marker in (
            "не актуально",
            "уже не актуально",
            "больше не актуально",
            "не нужно уведомлять",
            "не надо уведомлять",
            "снял запрос",
            "снять запрос",
        )
    )


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
    photo_reply = _explicit_photo_reply(text, form_data)
    if photo_reply:
        return photo_reply, next_key
    deterministic = _deterministic_info_reply(text, form_data)
    if deterministic:
        reply = deterministic
        if (
            form_data.get("service_type") == "gazebo"
            and form_data.get("service_variant")
            and not form_data.get("guests_count")
            and not _capacity_guest_patch(text)
        ):
            return reply, "guests_count"
    elif form_data.get("service_type") == "gazebo" and _asks_gazebo_options(text):
        reply = _gazebo_selection_text(form_data)
        if not form_data.get("guests_count"):
            return reply, "guests_count"
    elif getattr(ai_result, "action", "") == "answer_info" and ai_reply:
        reply = ai_reply
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

    if (
        question
        and _should_append_next_question_after_info(form_data, next_key)
        and not _reply_already_asks(reply, next_key, question)
    ):
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


def _gazebo_capacity_mismatch_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str | None, dict[str, Any]] | None:
    issue = _selected_gazebo_capacity_issue(form_data)
    if not issue:
        return None
    selected, guests, capacity = issue
    selected_title = str(selected.get("title") or form_data.get("service_variant") or "Выбранная беседка")
    updated = dict(form_data)
    updated["service_variant"] = None
    updated.pop("single_available_gazebo_variant_auto", None)

    available_variants = _available_gazebo_variant_configs(updated)
    if available_variants is None and updated.get("date"):
        availability_form = {**updated, "service_variant": None}
        availability = check_availability(conn, form_data=availability_form, now=now)
        updated = _remember_available_gazebo_variants(updated, availability.slots)
        available_variants = _available_gazebo_variant_configs(updated)

    lines = [
        f"{selected_title} рассчитана до {capacity} человек, а вас будет {guests}.",
        "Чтобы не было тесно, эту беседку не закрепляю.",
    ]
    if available_variants:
        suitable = [
            variant for variant in available_variants
            if int(variant.get("capacity_max") or 0) >= guests
        ]
        if suitable:
            lines.append("")
            lines.append("Из реально свободных на выбранную дату подходят:")
            for variant in suitable:
                lines.append(f"- {_format_gazebo_variant_line(variant)}")
            lines.append("")
            lines.append("Какую из них закрепляем?")
            return "\n".join(lines), "service_variant", "service_variant", updated

        date_text = _format_date_ru(updated.get("date"))
        lines.append("")
        lines.append(f"Из свободных на {date_text} вариантов нет беседки, которая подойдёт для {guests} гостей.")
        lines.append("Не буду предлагать занятые или слишком маленькие варианты.")
    else:
        lines.append("")
        lines.append("Сейчас не вижу подходящих свободных вариантов для такого количества гостей на выбранную дату.")

    updated["last_unavailable"] = {
        "service_type": "gazebo",
        "date": updated.get("date"),
        "time": updated.get("time"),
        "duration": updated.get("duration"),
        "guests_count": guests,
    }
    alternatives = _next_free_dates_reply(conn, conversation, updated, now)
    if alternatives:
        lines.append("")
        lines.append(alternatives)
    else:
        lines.append("")
        lines.append("Напишите другую дату — проверю подходящие свободные беседки.")
    return "\n".join(lines), "awaiting_new_date", "date", updated


def _booking_ready(form_data: dict[str, Any]) -> bool:
    next_key, _ = next_question(form_data)
    if next_key is not None:
        return False
    return _valid_phone(form_data.get("phone"))


def _awaiting_confirmation_side_reply(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
) -> str:
    if _looks_like_info_question(text):
        deterministic = _deterministic_info_reply(text, form_data)
        if deterministic:
            return deterministic
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
        | _guests_count_patch(text, "guests_count")
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
        patch |= _service_variant_patch(text, allow_bare_ordinal=True)
        patch |= _guests_count_patch(text, "guests_count")
    if expected_key == "client_name":
        patch |= _client_name_patch(text, expected_key)
    if expected_key == "time":
        if not _service_variant_patch(text, allow_bare_ordinal=True):
            patch |= _single_time_patch(text, expected_key)
    if expected_key == "duration" and "duration" not in patch:
        duration = _duration_from_text(text)
        if duration is None:
            duration = _bare_duration_from_text(text)
        if duration is not None:
            patch["duration"] = duration
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
        if _looks_like_booking_request_with_date(text, detected_patch):
            return ai_patch | detected_patch
        capacity_patch = _capacity_guest_patch(text)
        if capacity_patch:
            return capacity_patch
        return {}
    return ai_patch | detected_patch


def _capacity_guest_patch(text: str) -> dict[str, int]:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("если нас", "нас будет", "человек", "гостей", "гостя")):
        return {}
    return _guests_count_patch(text, "guests_count")


def _selects_gazebo_variant_without_time(text: str) -> bool:
    if not _service_variant_patch(text, allow_bare_ordinal=True):
        return False
    if _time_period_patch(text):
        return False
    normalized = text.lower().replace("ё", "е")
    if re.search(r"\b(?:с|до|в)\s*\d{1,2}(?::\d{2})?\b", normalized):
        return False
    if re.search(r"\b\d{1,2}\s*(?:час|часа|часов|ч)\b", normalized):
        return False
    return True


def _guest_count_answer_without_time(text: str, expected_key: str | None) -> bool:
    if expected_key != "guests_count":
        return False
    if not _guests_count_patch(text, "guests_count"):
        return False
    if _time_period_patch(text):
        return False
    normalized = text.lower().replace("ё", "е")
    if re.search(r"\b(?:с|до|в)\s*\d{1,2}(?::\d{2})?\b", normalized):
        return False
    return True


def _selects_gazebo_variant_without_guest_count(text: str) -> bool:
    if not _service_variant_patch(text, allow_bare_ordinal=True):
        return False
    normalized = text.lower().replace("ё", "е")
    return not any(marker in normalized for marker in ("гост", "человек", "чел", "нас "))


def _looks_like_booking_request_with_date(text: str, detected_patch: dict[str, Any]) -> bool:
    if not detected_patch.get("service_type") or not detected_patch.get("date"):
        return False
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("заброн", "брон", "нужн", "хочу", "давай", "можно", "бесед", "бан", "дом"))


def _filter_new_booking_patch_to_current_message(
    patch: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    allowed: set[str] = set()
    if _service_type_patch(text):
        allowed.update({"service_type", "preferences"})
    variant_patch = _service_variant_patch(text)
    if variant_patch:
        allowed.update(key for key in ("service_variant", "preferences") if key in variant_patch)
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


def _restore_draft_context_after_service_switch(
    form_data: dict[str, Any],
    previous_form_data: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    if not _continues_current_draft_service_switch({"form_data": previous_form_data}, text):
        return form_data
    updated = dict(form_data)
    last_unavailable = previous_form_data.get("last_unavailable") or {}
    for key in ("date", "time", "duration", "guests_count", "event_format"):
        if updated.get(key):
            continue
        if previous_form_data.get(key):
            updated[key] = previous_form_data[key]
        elif last_unavailable.get(key):
            updated[key] = last_unavailable[key]
    if updated.get("service_type") == "gazebo":
        if previous_form_data.get("last_available_gazebo_variants"):
            updated["last_available_gazebo_variants"] = previous_form_data["last_available_gazebo_variants"]
        if not updated.get("service_variant"):
            variant_patch = _service_variant_patch(text, allow_bare_ordinal=True)
            if variant_patch.get("service_variant"):
                updated["service_variant"] = variant_patch["service_variant"]
    return updated


def _fast_entry_reply(conn, text: str, form_data: dict[str, Any], now: datetime) -> tuple[str, str, str | None, str | None, dict[str, Any]] | None:
    patch = _deterministic_patch(text, now)
    updated = merge_form_data(form_data, patch)
    if updated.get("service_type") != "gazebo":
        updated["service_variant"] = None
    updated = _apply_gazebo_default_duration(
        updated,
        force=_gazebo_open_ended_duration_requested(text),
    )

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
            alternative = _alternative_services_for_unavailable_date(conn, updated, now)
            if alternative:
                reply, next_key = alternative
                return reply, "waiting_user", "service_type", next_key, _reset_unavailable_slot(updated)
            reply, next_key = _no_availability_reply(updated)
            return reply, "waiting_user", "awaiting_new_date", next_key, _reset_unavailable_slot(updated)
        updated = _remember_available_gazebo_variants(updated, availability.slots)
        updated = _auto_select_single_available_gazebo(updated)
        reply, next_key = _availability_reply(availability.message, availability.slots, updated)
        return reply, "waiting_user", next_key, next_key, updated

    return None


@trace_message_handler(logger)
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

        reminder_response = _handle_booking_reminder_response(conn, conversation, user, message.text, now)
        if reminder_response is not None:
            reply, status, current_step, next_key, form_data = reminder_response
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

        current_form_data = conversation.get("form_data") or {}
        if current_form_data.get("stale_form_flow"):
            if _wants_new_form_after_stale(message.text) and not _service_type_patch(message.text) and not _asks_for_free_slots(message.text):
                form_data = _new_booking_form_data(current_form_data)
                reply = "Хорошо, начнём новую анкету ✅\n\nЧто хотите забронировать?"
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
                    current_step="service_type",
                    next_step="service_type",
                    form_data=form_data,
                )
                return reply
            if _stale_message_starts_new_context(message.text):
                form_data = _new_booking_form_data(current_form_data)
                conversation = {
                    **conversation,
                    "form_data": form_data,
                    "status": "waiting_user",
                    "current_step": None,
                    "next_step": None,
                }
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    current_step=None,
                    next_step=None,
                    form_data=form_data,
                )
                current_form_data = form_data
            if current_form_data.get("stale_form_flow") and _wants_continue_stale_form(message.text):
                reply, next_key = _continue_stale_form_reply(current_form_data)
                form_data = dict(current_form_data)
                form_data.pop("stale_form_flow", None)
                status = "awaiting_confirmation" if next_key == "confirmation" else "waiting_user"
                current_step = "awaiting_confirmation" if next_key == "confirmation" else next_key
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
            if current_form_data.get("stale_form_flow"):
                reply = "Уточните, пожалуйста: продолжаем старую заявку или начинаем новую?"
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
                    current_step="stale_form_choice",
                    next_step="stale_form_choice",
                    form_data=current_form_data,
                )
                return reply

        if not conv_created and _should_offer_stale_form_choice(conversation, now):
            form_data = {
                **current_form_data,
                "stale_form_flow": {
                    "started_at": now.isoformat(),
                    "previous_step": conversation.get("current_step"),
                },
            }
            reply = _stale_form_choice_reply(current_form_data)
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
                current_step="stale_form_choice",
                next_step="stale_form_choice",
                form_data=form_data,
            )
            return reply

        explicit_photo_reply = _explicit_photo_reply(message.text, conversation.get("form_data") or {})
        if explicit_photo_reply:
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=explicit_photo_reply,
            )
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                status=conversation.get("status") or "waiting_user",
                intent=conversation.get("intent") or "company_info",
                current_step=conversation.get("current_step"),
                next_step=conversation.get("next_step"),
                form_data=conversation.get("form_data") or {},
            )
            return explicit_photo_reply

        if _should_route_existing_booking_command(message.text) and _has_user_bookings(
            conn,
            conversation,
            conversation.get("form_data") or {},
            now,
        ):
            if _handoff_active(user, now):
                users_repo.clear_handoff(conn, user_id=int(user["id"]))
            routed_conversation = _as_post_booking_conversation(conversation)
            routed = _handle_post_booking_message(conn, routed_conversation, message.text, history, now)
            if routed is not None:
                reply, status, current_step, next_key, form_data = routed
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

        if _handoff_active(user, now) and _is_waitlist_decline(message.text):
            waitlist_repo.close_for_user(conn, user_id=int(user["id"]))
            users_repo.clear_handoff(conn, user_id=int(user["id"]))
            reply = "Поняла, запрос на уведомление сняла ✅\n\nЕсли снова понадобится проверить свободные даты, просто напишите услугу и дату."
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
                status="payment_paid" if conversation.get("status") == "payment_paid" else "waiting_user",
                current_step="reserved" if conversation.get("status") == "payment_paid" else conversation.get("current_step"),
                next_step="payment_status" if conversation.get("status") == "payment_paid" else conversation.get("next_step"),
                form_data=conversation.get("form_data") or {},
            )
            return reply

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
                    required = _append_waitlist_offer(required, form_data)
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

        hold_command = _handle_reserved_hold_command(conn, conversation, message.text, now, history)
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

        post_booking_checked = False
        if (
            conversation.get("current_step") != "awaiting_confirmation"
            and conversation.get("status") != "awaiting_confirmation"
        ):
            post_booking_checked = True
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

        started_new_booking = False
        current_flow_form = conversation.get("form_data") or {}
        has_change_flow = any(
            current_flow_form.get(key)
            for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow")
        )
        if (
            not has_change_flow
            and _should_start_fresh_booking(conversation, message.text)
        ):
            conversation = {
                **conversation,
                "form_data": _new_booking_form_data(current_flow_form),
                "current_step": None,
                "next_step": None,
                "status": "waiting_user",
            }
            started_new_booking = True

        if (
            not started_new_booking
            and not post_booking_checked
            and conversation.get("current_step") != "awaiting_confirmation"
            and conversation.get("status") != "awaiting_confirmation"
        ):
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

        if _wants_abort_current_draft(message.text) and _current_draft_can_be_aborted(conversation):
            reply, form_data = _abort_current_draft(conversation.get("form_data") or {})
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
                intent="booking_cancelled",
                current_step="service_type",
                next_step="service_type",
                form_data=form_data,
            )
            return reply

        if _wants_pause_current_draft(message.text) and _current_draft_can_be_aborted(conversation):
            form_data = conversation.get("form_data") or {}
            next_key = next_question(form_data)[0] or conversation.get("next_step") or conversation.get("current_step")
            reply = _pause_current_draft_reply(form_data)
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
                intent="booking_paused",
                current_step=next_key,
                next_step=next_key,
                form_data=form_data,
            )
            return reply

        if conversation.get("current_step") == "awaiting_confirmation":
            form_data = conversation.get("form_data") or {}
            correction_patch = _form_detail_correction_patch(message.text, form_data)
            if not correction_patch and _last_assistant_asked_name_correction(history) and _looks_like_name(message.text):
                correction_patch = {"client_name": message.text.strip().title()}
            if correction_patch:
                form_data = merge_form_data(form_data, correction_patch)
                form_data = _normalize_service_aliases(form_data)
                if form_data.get("service_type") != "gazebo":
                    form_data["service_variant"] = None
                form_data = _normalize_gazebo_variant(form_data)
                form_data = _apply_gazebo_default_duration(
                    form_data,
                    force=_gazebo_open_ended_duration_requested(message.text),
                )
                if {"service_type", "service_variant", "date", "time", "duration"} & set(correction_patch):
                    availability = check_availability(conn, form_data=form_data, now=now)
                    if availability.ok and not availability.slots:
                        required, next_key = _no_availability_reply(form_data)
                        remember_waitlist_request(
                            conn,
                            conversation_id=conversation["id"],
                            user_id=user["id"],
                            form_data=form_data,
                        )
                        reply = _append_waitlist_offer(required, form_data)
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
                            status="waiting_user",
                            intent="change_booking",
                            current_step="awaiting_new_date",
                            next_step=next_key,
                            form_data=form_data,
                        )
                        return reply
                    form_data = _remember_available_gazebo_variants(form_data, availability.slots)
                    form_data = _auto_select_single_available_gazebo(form_data)
                reply = f"{_correction_ack_text(correction_patch)}\n\n{_confirmation_reply_text(form_data)}"
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
                    intent="change_booking",
                    current_step="awaiting_confirmation",
                    next_step="confirmation",
                    form_data=form_data,
                )
                return reply
            if _maybe_name_correction_without_value(message.text):
                reply = "Поняла, поправим имя ✅\n\nКакое имя указать в брони?"
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
                    intent="change_booking",
                    current_step="awaiting_confirmation",
                    next_step="confirmation",
                    form_data=form_data,
                )
                return reply
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

        if (
            not any((conversation.get("form_data") or {}).get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow"))
            and _should_start_fresh_booking(conversation, message.text)
        ):
            conversation = {
                **conversation,
                "form_data": _new_booking_form_data(conversation.get("form_data") or {}),
                "current_step": None,
                "next_step": None,
                "status": "waiting_user",
            }
            started_new_booking = True

        if _starts_gazebo_browsing_after_booking(conversation, message.text):
            reply, status, current_step, next_key, form_data = _handle_gazebo_browsing_start(
                conn,
                text=message.text,
                conversation=conversation,
                previous_form_data=conversation.get("form_data") or {},
                history=history,
                now=now,
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
                status=status,
                intent="gazebo_options",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
            return reply

        hold_command = _handle_reserved_hold_command(conn, conversation, message.text, now, history)
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
            _asks_for_free_slots(message.text)
            and (
                conversation.get("current_step") == "awaiting_new_date"
                or (conversation.get("form_data") or {}).get("last_unavailable")
            )
        ):
            form_data = conversation.get("form_data") or {}
            reply = _next_free_dates_reply(conn, conversation, form_data, now)
            if reply:
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
                    next_step="date",
                    form_data=form_data,
                )
                return reply

        direct_free_dates = _direct_free_dates_lookup(conn, conversation, message.text, now)
        if direct_free_dates is not None:
            reply, status, current_step, next_key, form_data = direct_free_dates
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

        current_form_data = conversation.get("form_data") or {}
        if _asks_booking_summary(message.text) and not _has_user_bookings(conn, conversation, current_form_data, now):
            draft_reply = _draft_summary_reply(current_form_data)
            if draft_reply:
                next_key, _ = next_question(current_form_data)
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=draft_reply,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    intent="draft_summary",
                    current_step=next_key or conversation.get("current_step"),
                    next_step=next_key,
                    form_data=current_form_data,
                )
                return draft_reply
        if current_form_data.get("last_unavailable") and _looks_like_event_context_for_alternatives(message.text):
            alternative = _alternative_services_for_unavailable_date(conn, current_form_data, now)
            if alternative:
                reply, next_key = alternative
                form_data = dict(current_form_data)
                form_data["preferences"] = _join_preferences(form_data.get("preferences"), message.text.strip())
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
                    intent="alternative_services",
                    current_step="service_type",
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
        expected_key_before = next_question(current_form_data)[0]
        current_upsells = current_form_data.get("upsell_items") or []
        if (
            expected_key_before != "upsell_items"
            and (not current_upsells or current_upsells == ["не нужны"])
            and _last_assistant_asked_upsell(history)
        ):
            expected_key_before = "upsell_items"
        if (
            current_form_data.get("service_type") == "gazebo"
            and current_form_data.get("date")
            and not current_form_data.get("service_variant")
            and current_form_data.get("last_available_gazebo_variants")
            and _looks_like_gazebo_budget_preference(message.text)
        ):
            reply = _gazebo_budget_selection_text(current_form_data) or _gazebo_selection_text(current_form_data)
            form_data = {
                **current_form_data,
                "preferences": _join_preferences(current_form_data.get("preferences"), "подешевле"),
            }
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
                intent="object_selection_help",
                current_step="service_variant",
                next_step="service_variant",
                form_data=form_data,
            )
            return reply
        if expected_key_before == "upsell_items" and _is_upsell_negative(message.text):
            offer_count = int(current_form_data.get("upsell_offer_count") or 0)
            should_push_once = offer_count < 1 and (not current_upsells or current_upsells == ["не нужны"])
            if should_push_once:
                form_data = {
                    **current_form_data,
                    "upsell_items": [],
                    "upsell_offer_count": offer_count + 1,
                }
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
            accepted_items = current_upsells if current_upsells and current_upsells != ["не нужны"] else ["не нужны"]
            form_data = merge_form_data(
                current_form_data,
                {
                    "upsell_items": accepted_items,
                    "upsell_offer_count": offer_count,
                },
            )
            next_key, question = next_question(form_data)
            if next_key is None:
                reply = _confirmation_reply_text(form_data)
                status = "awaiting_confirmation"
                current_step = "awaiting_confirmation"
                next_step = "confirmation"
            else:
                if accepted_items == ["не нужны"]:
                    prefix = "Поняла, без допов ✅"
                else:
                    prefix = f"Хорошо, оставим допы: {', '.join(accepted_items)} ✅"
                reply = f"{prefix}\n\n{question}"
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
        if expected_key_before == "upsell_items":
            upsell_patch = _upsell_items_patch(message.text)
            selected_items = upsell_patch.get("upsell_items") or []
            if selected_items and selected_items != ["не нужны"]:
                price_reply = _addon_price_reply(message.text) if _looks_like_price_question_text(message.text) else None
                form_data = merge_form_data(
                    current_form_data,
                    upsell_patch | {"upsell_offer_count": int(current_form_data.get("upsell_offer_count") or 0)},
                )
                next_key, question = next_question(form_data)
                items_text = ", ".join(selected_items)
                prefix = f"Хорошо, {items_text} добавим ✅"
                if price_reply:
                    prefix = f"{price_reply}\n\n{prefix}"
                if next_key is None:
                    reply = f"{price_reply}\n\n{_confirmation_reply_text(form_data)}" if price_reply else _confirmation_reply_text(form_data)
                    status = "awaiting_confirmation"
                    current_step = "awaiting_confirmation"
                    next_step = "confirmation"
                else:
                    reply = f"{prefix}\n\n{question}"
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
        early_patch |= _same_time_reference_patch(
            conn,
            conversation,
            current_form_data,
            message.text,
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
                knowledge=_build_semantic_router_knowledge(conversation.get("form_data") or {}),
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
            patch = _preserve_current_service_for_reference(
                patch,
                conversation.get("form_data") or {},
                message.text,
            )
            started_new_booking_from_ai = False
            if (
                not started_new_booking
                and _ai_should_start_fresh_booking(conversation, ai_result, patch, message.text)
            ):
                conversation = {
                    **conversation,
                    "form_data": _new_booking_form_data(conversation.get("form_data") or {}),
                    "current_step": None,
                    "next_step": None,
                    "status": "waiting_user",
                }
                expected_key_before = next_question(conversation.get("form_data") or {})[0]
                started_new_booking = True
                started_new_booking_from_ai = True
                patch = _fresh_booking_patch_from_ai(
                    ai_result=ai_result,
                    patch=patch,
                    text=message.text,
                    now=now,
                )
            if started_new_booking and not started_new_booking_from_ai:
                patch = _filter_new_booking_patch_to_current_message(patch, message.text, now)
            active_expected_step_before = conversation.get("next_step") or conversation.get("current_step") or expected_key_before
            if _selects_gazebo_variant_without_time(message.text) or _guest_count_answer_without_time(message.text, active_expected_step_before):
                patch.pop("time", None)
                patch.pop("duration", None)
            if _selects_gazebo_variant_without_guest_count(message.text):
                patch.pop("guests_count", None)
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
                "event_format" in patch
                and "event_format" not in deterministic_patch
                and not _event_format_patch(message.text)
                and not (
                    expected_key_before == "event_format"
                    and active_expected_step_before == "event_format"
                    and not _looks_like_info_question(
                        message.text,
                        expected_key=expected_key_before,
                        now=now,
                    )
                )
            ):
                patch.pop("event_format", None)
            previous_event_format = (conversation.get("form_data") or {}).get("event_format")
            if (
                expected_key_before == "upsell_items"
                and "client_name" not in patch
                and not (conversation.get("form_data") or {}).get("client_name")
                and _looks_like_name(message.text)
                and not _looks_like_price_question_text(message.text)
                and not _looks_like_info_question(
                    message.text,
                    expected_key=expected_key_before,
                    now=now,
                )
            ):
                patch["client_name"] = message.text.strip().title()
            changed_fields = set(ai_result.changed_fields) | set(patch.keys())
            if _selects_gazebo_variant_without_time(message.text) or _guest_count_answer_without_time(message.text, active_expected_step_before):
                changed_fields.discard("time")
                changed_fields.discard("duration")
            if _selects_gazebo_variant_without_guest_count(message.text):
                changed_fields.discard("guests_count")
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
            form_data = _restore_draft_context_after_service_switch(
                form_data,
                conversation.get("form_data") or {},
                message.text,
            )
            if form_data.get("date") and not (conversation.get("form_data") or {}).get("date"):
                changed_fields.add("date")
            if form_data.get("guests_count") and not (conversation.get("form_data") or {}).get("guests_count"):
                changed_fields.add("guests_count")
            if (
                not previous_event_format
                and active_expected_step_before != "event_format"
                and not _event_format_patch(message.text)
                and "event_format" in getattr(ai_result, "changed_fields", [])
            ):
                form_data["event_format"] = None
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
            if {"service_type", "date", "time", "duration"} & changed_fields:
                form_data.pop("last_available_gazebo_variants", None)
                form_data.pop("single_available_gazebo_variant_auto", None)
            form_data = _normalize_gazebo_variant(form_data)
            form_data = _apply_gazebo_default_duration(
                form_data,
                force=_gazebo_open_ended_duration_requested(message.text),
            )
            capacity_mismatch = _gazebo_capacity_mismatch_reply(conn, conversation, form_data, now)
            if capacity_mismatch:
                reply, current_step, next_key, form_data = capacity_mismatch
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
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
                return reply
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
                reply = "Телефон получился некорректным. Пришлите, пожалуйста, полный номер телефона для бронирования в формате +7XXXXXXXXXX."
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
                and form_data.get("date")
                and not form_data.get("service_variant")
                and "guests_count" in changed_fields
            ):
                reply = _gazebo_selection_text(form_data)
                suitable_titles = _suitable_available_gazebo_titles(form_data)
                if _asks_for_free_slots(message.text) or not suitable_titles:
                    alternatives = _next_free_dates_reply(conn, conversation, form_data, now)
                    if alternatives:
                        reply = f"{reply}\n\n{alternatives}"
                    next_key = "date"
                    current_step = "awaiting_new_date"
                else:
                    next_key = "service_variant"
                    current_step = "service_variant"
                status = "waiting_user"
                intent = ai_result.intent
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
                and form_data.get("service_variant")
                and form_data.get("guests_count")
                and ("guests_count" in changed_fields or active_expected_step_before == "guests_count")
                and not form_data.get("time")
            ):
                title = str(form_data.get("service_variant"))
                capacity = _gazebo_capacity_by_title(title)
                capacity_note = (
                    f"{title} рассчитана до {capacity} человек, для {form_data.get('guests_count')} гостей подходит ✅"
                    if capacity
                    else f"{form_data.get('guests_count')} гостей для {title} подходит ✅"
                )
                reply = (
                    f"{capacity_note}\n\n"
                    "Во сколько хотите приехать? Можно сразу написать период, например: с 18:00 до 00:00."
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
                and not form_data.get("date")
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
            effective_action = (
                "check_availability"
                if _looks_like_booking_request_with_date(
                    message.text,
                    {
                        "service_type": form_data.get("service_type"),
                        "date": form_data.get("date"),
                    },
                )
                else ai_result.action
            )
            if (
                effective_action == "answer_info"
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
                current_step = next_key or expected_key_now or conversation.get("current_step") or ai_result.current_step
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
                effective_action,
                list(changed_fields),
                form_data,
            ):
                availability = check_availability(conn, form_data=form_data, now=now)
                if availability.ok and not availability.slots:
                    alternative = _alternative_services_for_unavailable_date(conn, form_data, now)
                    if alternative:
                        required, next_key = alternative
                    elif _asks_for_free_slots(message.text):
                        required = _next_free_dates_reply(conn, conversation, form_data, now) or _no_availability_reply(form_data)[0]
                        next_key = "date"
                    else:
                        required, next_key = _no_availability_reply(form_data)
                        remember_waitlist_request(
                            conn,
                            conversation_id=conversation["id"],
                            user_id=user["id"],
                            form_data=form_data,
                        )
                        required = _append_waitlist_offer(required, form_data)
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
                    effective_action,
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
                current_step = next_key
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
            form_data = _apply_gazebo_default_duration(
                form_data,
                force=_gazebo_open_ended_duration_requested(message.text),
            )
            capacity_mismatch = _gazebo_capacity_mismatch_reply(conn, conversation, form_data, now)
            if capacity_mismatch:
                reply, current_step, next_key, form_data = capacity_mismatch
                status = "waiting_user"
                intent = conversation.get("intent")
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
                    alternative = _alternative_services_for_unavailable_date(conn, form_data, now)
                    if alternative:
                        reply, next_key = alternative
                    else:
                        reply, next_key = _no_availability_reply(form_data)
                        remember_waitlist_request(
                            conn,
                            conversation_id=conversation["id"],
                            user_id=user["id"],
                            form_data=form_data,
                        )
                        reply = _append_waitlist_offer(reply, form_data)
                    form_data = _reset_unavailable_slot(form_data)
                    current_step = "service_type" if alternative else "awaiting_new_date"
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
            form_data = _normalize_service_aliases(form_data)
            if form_data.get("service_type") != "gazebo":
                form_data["service_variant"] = None
                form_data.pop("single_available_gazebo_variant_auto", None)
            form_data = _normalize_gazebo_variant(form_data)
            form_data = _apply_gazebo_default_duration(
                form_data,
                force=_gazebo_open_ended_duration_requested(message.text),
            )
            capacity_mismatch = _gazebo_capacity_mismatch_reply(conn, conversation, form_data, now)
            if capacity_mismatch:
                reply, current_step, next_key, form_data = capacity_mismatch
                status = "waiting_user"
                intent = conversation.get("intent")
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
            changed_fields = set(deterministic_patch.keys())
            if _should_check_availability("ask_next_question", list(changed_fields), form_data):
                availability = check_availability(conn, form_data=form_data, now=now)
                if availability.ok and not availability.slots:
                    alternative = _alternative_services_for_unavailable_date(conn, form_data, now)
                    if alternative:
                        required, next_key = alternative
                    else:
                        required, next_key = _no_availability_reply(form_data)
                        remember_waitlist_request(
                            conn,
                            conversation_id=conversation["id"],
                            user_id=user["id"],
                            form_data=form_data,
                        )
                        required = _append_waitlist_offer(required, form_data)
                    form_data = _reset_unavailable_slot(form_data)
                    reply = required
                    current_step = "service_type" if alternative else "awaiting_new_date"
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
