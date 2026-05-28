import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
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
from app.services.dialog.availability_flow import (
    AvailabilityExecutionCallbacks as _AvailabilityExecutionCallbacks,
    DirectFreeDatesLookupCallbacks as _DirectFreeDatesLookupCallbacks,
    alternative_services_for_unavailable_date as _alternative_services_for_unavailable_date_impl,
    append_waitlist_offer as _append_waitlist_offer,
    apply_previous_period_for_new_date as _apply_previous_period_for_new_date,
    availability_reply as _availability_reply,
    clear_active_slot_keep_last as _clear_active_slot_keep_last,
    direct_free_dates_lookup as _direct_free_dates_lookup_impl,
    execute_availability_check as _execute_availability_check_impl,
    no_availability_reply as _no_availability_reply,
    next_free_dates_reply as _next_free_dates_reply_impl,
    reset_unavailable_slot as _reset_unavailable_slot,
    same_unavailable_date_reply as _same_unavailable_date_reply,
    should_check_availability as _should_check_availability,
)
from app.services.dialog.date_parsing import (
    MONTH_NUMBERS_RU,
    MONTH_PATTERN,
    bare_day_patch as _bare_day_patch,
    bare_weekday_candidate as _bare_weekday_candidate,
    bare_weekday_confirmation as _bare_weekday_confirmation,
    date_patch_after_marker as _date_patch_after_marker,
    has_date_signal as _has_date_signal,
    relative_date_patch as _relative_date_patch,
)
from app.services.dialog.formatting import (
    duration_minutes_value as _duration_minutes_value,
    format_date_ru as _format_date_ru,
    format_duration as _format_duration,
    format_rub as _format_rub,
    format_time_duration_range as _format_time_duration_range,
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
    CancelFlowCallbacks as _CancelFlowCallbacks,
    cancel_confirmation_reply as _cancel_confirmation_reply,
    cancel_done_reply as _cancel_done_reply,
    cancel_many_confirmation_reply as _cancel_many_confirmation_reply,
    cancel_many_done_reply as _cancel_many_done_reply,
    cancel_selection_prompt as _cancel_selection_prompt,
    handle_cancel_booking_flow as _handle_cancel_booking_flow_impl,
    select_cancel_bookings as _select_cancel_bookings,
    start_cancel_booking_flow as _start_cancel_booking_flow_impl,
    wants_cancel_booking as _wants_cancel_booking,
)
from app.services.dialog.confirmation_flow import (
    AwaitingConfirmationCallbacks as _AwaitingConfirmationCallbacks,
    ReservedHoldCallbacks as _ReservedHoldCallbacks,
    awaiting_confirmation_side_reply as _awaiting_confirmation_side_reply_impl,
    create_booking_from_hold as _create_booking_from_hold_impl,
    create_hold as _create_hold_impl,
    expired_hold_inline_reply as _expired_hold_inline_reply,
    handle_awaiting_confirmation as _handle_awaiting_confirmation_impl,
    handle_reserved_hold_command as _handle_reserved_hold_command_impl,
    mentions_payment_status as _mentions_payment_status,
    pending_payment_for_holds as _pending_payment_for_holds,
    reply_with_hold_summary as _reply_with_hold_summary_impl,
    wants_cancel_or_change_hold as _wants_cancel_or_change_hold,
)
from app.services.dialog.handoff import (
    handoff_active as _handoff_active,
    is_location_question as _is_location_question,
    looks_like_handoff_needed as _looks_like_handoff_needed,
    start_user_handoff as _start_user_handoff,
)
from app.services.dialog.price_info import (
    addon_price_reply as _addon_price_reply,
    discount_reply_if_known as _discount_reply_if_known_impl,
    looks_like_forbidden_broom_request as _looks_like_forbidden_broom_request,
    looks_like_price_question_text as _looks_like_price_question_text,
    policy_or_common_info_reply as _policy_or_common_info_reply,
    price_reply_if_known as _price_reply_if_known_impl,
)
from app.services.dialog.media_flow import (
    ExplicitPhotoCallbacks as _ExplicitPhotoCallbacks,
    explicit_photo_reply as _explicit_photo_reply_impl,
)
from app.services.dialog.performance import trace_message_handler, trace_span
from app.services.dialog.post_booking_flow import (
    classify_post_booking_safely as _classify_post_booking_safely,
    continues_booking_summary_question as _continues_booking_summary_question,
    is_waitlist_decline as _is_waitlist_decline,
    payment_status_reply as _payment_status_reply_impl,
    plain_ack_after_closed_booking as _plain_ack_after_closed_booking,
    post_booking_summary as _post_booking_summary,
)
from app.services.dialog.response_builder import (
    deterministic_process_reply as _deterministic_process_reply,
    fallback_process_reply as _fallback_process_reply,
    looks_like_internal_instruction_text as _looks_like_internal_instruction_text,
)
from app.services.dialog.reschedule_flow import (
    RescheduleExecutionCallbacks as _RescheduleExecutionCallbacks,
    SwapRescheduleCallbacks as _SwapRescheduleCallbacks,
    asks_reschedule_options as _asks_reschedule_options,
    canonical_reschedule_gazebo_variant as _canonical_reschedule_gazebo_variant,
    execute_reschedule as _execute_reschedule_impl,
    execute_swap_reschedule as _execute_swap_reschedule_impl,
    form_data_for_booking_reschedule as _form_data_for_booking_reschedule,
    gazebo_capacity_by_title as _gazebo_capacity_by_title,
    initial_reschedule_flow_patch as _initial_reschedule_flow_patch_impl,
    means_change_object as _means_change_object,
    means_same_date as _means_same_date,
    means_same_object as _means_same_object,
    means_same_time as _means_same_time,
    prepare_swap_reschedule as _prepare_swap_reschedule_impl,
    preserve_current_service_for_reference as _preserve_current_service_for_reference,
    price_limit_from_text as _price_limit_from_text,
    referenced_service_type_for_same_time as _referenced_service_type_for_same_time,
    reschedule_confirmation_reply as _reschedule_confirmation_reply,
    reschedule_gazebo_change_options_reply as _reschedule_gazebo_change_options_reply_impl,
    handle_swap_reschedule_flow as _handle_swap_reschedule_flow_impl,
    reschedule_options_reply as _reschedule_options_reply,
    reschedule_service_variant_patch as _reschedule_service_variant_patch,
    reschedule_target_date_patch as _reschedule_target_date_patch,
    restore_booking_after_failed_reschedule as _restore_booking_after_failed_reschedule_impl,
    same_target_assignments_for_bookings as _same_target_assignments_for_bookings,
    select_reschedule_booking as _select_reschedule_booking_impl,
    start_swap_reschedule_flow as _start_swap_reschedule_flow_impl,
    wants_multi_booking_reschedule as _wants_multi_booking_reschedule,
    wants_reschedule as _wants_reschedule,
    wants_swap_bookings as _wants_swap_bookings,
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
from app.services.knowledge_service import load_knowledge, retrieve_client_knowledge
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
    cleaned = cleaned.replace("сразать", "сразу")
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
    return bool(form_data.get("time")) and not form_data.get("duration")


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
    normalized = text.lower().replace("ё", "е").strip()
    compact = re.sub(r"[^\w]+", " ", normalized).strip()
    if compact in {"нет", "не", "не подтверждаю"} or "измен" in compact:
        return True
    return any(
        marker in compact
        for marker in (
            "нет остав",
            "не отмен",
            "не надо отмен",
            "не нужно отмен",
        )
    )


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
    has_booking_signal = any(
        marker in normalized
        for marker in (
            "нужн",
            "хочу",
            "давай",
            "заброни",
            "брон",
            "заказ",
            "оформ",
            "можно",
            "еще",
            "ещё",
            "добав",
        )
    )
    if not has_booking_signal:
        return False
    if _looks_like_info_question(text):
        return any(
            marker in normalized
            for marker in ("нужн", "хочу", "заброни", "брон", "заказ", "оформ")
        ) or bool(_explicit_numeric_dates(text, _now_local()))
    return True


def _explicit_numeric_dates(text: str, now: datetime) -> list[str]:
    normalized = text.lower().replace("ё", "е")
    dates: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", normalized):
        day = int(match.group(1))
        month = int(match.group(2))
        raw_year = match.group(3)
        year = int(raw_year) if raw_year else now.date().year
        if raw_year and year < 100:
            year += 2000
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if not raw_year and candidate < now.date():
            try:
                candidate = candidate.replace(year=candidate.year + 1)
            except ValueError:
                continue
        value = candidate.isoformat()
        if value not in seen:
            dates.append(value)
            seen.add(value)
    return dates


def _numeric_date_time_patch(text: str, now: datetime) -> dict[str, Any]:
    normalized = text.lower().replace("ё", "е")
    match = re.search(
        r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\s*(?:на|в|к)?\s*(\d{1,2})(?:[:.](\d{2}))?",
        normalized,
    )
    if not match:
        return {}
    after = normalized[match.end() : match.end() + 24]
    if any(marker in after for marker in ("человек", "чел", "гостей", "гостя", "гость")):
        return {}
    day = int(match.group(1))
    month = int(match.group(2))
    raw_year = match.group(3)
    year = int(raw_year) if raw_year else now.date().year
    if raw_year and year < 100:
        year += 2000
    hour = int(match.group(4))
    minute = int(match.group(5) or 0)
    if hour > 23 or minute > 59:
        return {}
    try:
        candidate = date(year, month, day)
    except ValueError:
        return {}
    if not raw_year and candidate < now.date():
        try:
            candidate = candidate.replace(year=candidate.year + 1)
        except ValueError:
            return {}
    return {"date": candidate.isoformat(), "time": f"{hour:02d}:{minute:02d}"}


def _multi_gazebo_booking_patch(text: str, now: datetime) -> dict[str, Any]:
    normalized = text.lower().replace("ё", "е")
    if (_service_type_patch(normalized) or {}).get("service_type") != "gazebo":
        return {}
    if not (
        re.search(r"\b2\s*(?:бесед|брон|заяв)", normalized)
        or re.search(r"\bдве\s+(?:бесед|брон|заяв)", normalized)
        or re.search(r"\bдва\s+(?:бесед|брон|заяв)", normalized)
    ):
        return {}
    dates = _explicit_numeric_dates(text, now)
    patch: dict[str, Any] = {
        "service_type": "gazebo",
        "pending_additional_bookings": [
            {"service_type": "gazebo", "date": value}
            for value in dates[1:]
        ],
        "multi_booking_mode": "sequential",
    }
    if dates:
        patch["date"] = dates[0]
    return patch


def _multi_gazebo_booking_reply(text: str, form_data: dict[str, Any]) -> str:
    lines: list[str] = []
    normalized = text.lower().replace("ё", "е")
    if "мангал" in normalized or "угл" in normalized:
        lines.append("Мангал у беседок есть. Уголь можно добавить к заявке, чтобы не везти с собой.")
        lines.append("")
    pending = form_data.get("pending_additional_bookings") or []
    if form_data.get("date"):
        first = _format_date_ru(form_data.get("date"))
        if pending:
            second_dates = ", ".join(_format_date_ru(item.get("date")) for item in pending if item.get("date"))
            lines.append(
                f"Две беседки можно оформить, но заявки заполняем по очереди: начинаем с {first}, "
                f"а {second_dates} держу как следующую отдельную бронь."
            )
        else:
            lines.append("Две беседки можно оформить, но заявки заполняем по очереди, чтобы не смешать даты и время.")
        lines.append("")
        lines.append(f"По первой беседке на {first}: во сколько хотите приехать?")
    else:
        lines.append("Две беседки можно оформить, но заявки заполняем по очереди, чтобы не смешать даты и время.")
        lines.append("")
        lines.append("Начнём с первой беседки. На какую дату её поставить?")
    return "\n".join(lines)


def _question_text_for_key(key: str | None, form_data: dict[str, Any]) -> str | None:
    if key == "time":
        return "Во сколько хотите приехать? Можно сразу написать период, например: с 18:00 до 00:00."
    if key == "duration":
        return "На сколько часов хотите забронировать?"
    if key == "guests_count":
        return "Сколько примерно гостей?"
    if key == "service_variant":
        return "Какую беседку выбираете? Могу предложить варианты по количеству гостей и удобствам."
    if key == "event_format":
        return "Какой формат отдыха: день рождения, корпоратив, семейный отдых, компания друзей или спокойный вечер?"
    if key == "upsell_items":
        return next_question(form_data)[1]
    if key == "client_name":
        return "На какое имя записать бронь?"
    if key == "phone":
        return "Телефон для бронирования?"
    return None


def _pending_additional_booking_reply(conversation: dict[str, Any], text: str, now: datetime) -> tuple[str, str, str | None, dict[str, Any]] | None:
    form_data = conversation.get("form_data") or {}
    pending = form_data.get("pending_additional_bookings") or []
    if not pending:
        return None
    dates = set(_explicit_numeric_dates(text, now))
    pending_dates = {str(item.get("date")) for item in pending if item.get("date")}
    if not dates or not (dates & pending_dates):
        return None
    if conversation.get("current_step") in {"reserved", "payment_status"} or conversation.get("status") in {"reserved", "payment_paid"}:
        return None
    current_date = form_data.get("date")
    second_date = next(iter(dates & pending_dates))
    calculated_key, calculated_question = next_question(form_data)
    next_key = conversation.get("next_step") or conversation.get("current_step") or calculated_key
    question = calculated_question if next_key == calculated_key else _question_text_for_key(next_key, form_data) or calculated_question
    current_text = f"Сейчас заканчиваем первую заявку"
    if current_date:
        current_text += f" на {_format_date_ru(current_date)}"
    reply = (
        f"{_format_date_ru(second_date)} я помню как следующую отдельную бронь.\n\n"
        f"{current_text}. Параллельно две анкеты не заполняем, чтобы не смешать время, гостей и допы.\n\n"
        f"{question or 'Если по первой заявке всё верно, напишите «да».'}"
    )
    return reply, next_key or conversation.get("current_step") or "service_type", next_key, form_data


def _parallel_booking_question_reply(conversation: dict[str, Any], text: str) -> tuple[str, str, str | None, dict[str, Any]] | None:
    normalized = text.lower().replace("ё", "е")
    if "параллел" not in normalized:
        return None
    if not any(marker in normalized for marker in ("брон", "заявк", "анкет")):
        return None
    form_data = conversation.get("form_data") or {}
    calculated_key, calculated_question = next_question(form_data)
    next_key = conversation.get("next_step") or conversation.get("current_step") or calculated_key
    question = calculated_question if next_key == calculated_key else _question_text_for_key(next_key, form_data) or calculated_question
    pending = form_data.get("pending_additional_bookings") or []
    pending_text = ""
    if pending:
        dates = ", ".join(_format_date_ru(item.get("date")) for item in pending if item.get("date"))
        if dates:
            pending_text = f" Следующую отдельную бронь на {dates} я помню."
    reply = (
        "Параллельно две анкеты не заполняем: брони оформляются по очереди, "
        "чтобы не смешать даты, время, гостей и допы."
        f"{pending_text}\n\n"
        f"{question or 'Сейчас закончим текущую заявку, потом перейдем ко второй.'}"
    )
    return reply, next_key or conversation.get("current_step") or "service_type", next_key, form_data


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
    if any(
        marker in normalized
        for marker in (
            "что мы подтверждаем",
            "что сейчас подтверждаем",
            "что подтверждаем",
            "какую подтверждаем",
            "какая заявка на подтверждении",
        )
    ):
        return True
    if "брон" in normalized and any(marker in normalized for marker in ("какие", "есть", "мои", "у меня", "теперь")):
        return True
    if "брон" in normalized and any(marker in normalized for marker in ("первая", "первую", "какая", "какую", "что выбрал", "что выбрали")):
        return True
    if "брон" in normalized and any(
        marker in normalized
        for marker in (
            "что мы",
            "что сейчас",
            "что вообще",
            "что делаем",
            "что оформ",
            "что подтверждаем",
            "какую подтверждаем",
        )
    ):
        return True
    if "заявк" in normalized and any(
        marker in normalized
        for marker in ("что", "какую", "какая", "текущ", "сейчас", "оформ", "подтвержд")
    ):
        return True
    if "заявк" in normalized and any(
        marker in normalized
        for marker in ("актив", "актуальн", "есть", "мои", "у меня", "висят", "висит")
    ):
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
        if form_data.get("duration"):
            lines.append(f"- Время: {_format_time_duration_range(form_data.get('time'), form_data.get('duration'))}")
        else:
            lines.append(f"- Время: с {form_data.get('time')}")
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


def _draft_summary_if_no_active_booking(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str | None] | None:
    if _active_user_bookings(conn, conversation, form_data, now):
        return None
    active_holds = slot_holds_repo.list_active_for_conversation(
        conn,
        conversation_id=conversation["id"],
        now=now,
    )
    if active_holds:
        return None
    draft_reply = _draft_summary_reply(form_data)
    if not draft_reply:
        return None
    next_key, _ = next_question(form_data)
    return draft_reply, next_key


def _current_request_summary(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> str:
    draft_summary = _draft_summary_if_no_active_booking(conn, conversation, form_data, now)
    if draft_summary:
        return draft_summary[0]
    return _post_booking_summary(conn, conversation, form_data, now)


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


def _is_closing_ack(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip()
    normalized = re.sub(r"[^\w\s]+", " ", normalized)
    words = set(normalized.split())
    return bool(words & {"спасибо", "благодарю", "хорошо", "ок", "окей", "понял", "поняла"})


def _is_post_pause_ack(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip()
    normalized = re.sub(r"[^\w\s]+", " ", normalized)
    if not normalized:
        return False
    if _is_closing_ack(normalized):
        return True
    return normalized in {"кайф", "класс", "супер", "отлично", "лады", "ладно"}


def _references_existing_guest_count(text: str, form_data: dict[str, Any]) -> bool:
    guests = form_data.get("guests_count")
    if not guests:
        return False
    normalized = text.lower().replace("ё", "е").strip()
    if not any(marker in normalized for marker in ("говорил", "говорила", "сказал", "сказала", "писал", "писала", "уже")):
        return False
    if str(guests) not in re.findall(r"\b\d{1,3}\b", normalized):
        return False
    if _time_period_patch(text):
        return False
    if re.search(r"\b(?:с|до|в|к)\s*\d{1,2}(?::\d{2})?\b", normalized):
        return False
    if re.search(r"\b\d{1,2}:\d{2}\b", normalized):
        return False
    return True


def _has_explicit_time_signal(text: str) -> bool:
    return bool(_time_period_patch(text) or _single_time_patch(text))


def _has_valid_time_signal(text: str, deterministic_patch: dict[str, Any]) -> bool:
    if _has_explicit_time_signal(text):
        return True
    if any(key in deterministic_patch for key in ("time", "duration")):
        return True
    return _means_same_time(text) and any(key in deterministic_patch for key in ("time", "duration"))


def _looks_like_vague_time_answer(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized in {
        "ну че нибудь",
        "ну что нибудь",
        "что нибудь",
        "че нибудь",
        "чего нибудь",
        "как нибудь",
        "любое",
        "любой",
        "без разницы",
        "не важно",
        "не принципиально",
        "на ваше усмотрение",
    } or any(
        marker in normalized
        for marker in (
            "что-нибудь",
            "че-нибудь",
            "чего-нибудь",
            "как-нибудь",
            "без разницы",
            "не принципиально",
        )
    )


def _has_explicit_duration_signal(text: str) -> bool:
    return _duration_from_text(text) is not None


def _has_specific_date_signal(text: str, now: datetime) -> bool:
    return bool(
        _relative_date_patch(text, now)
        or _bare_day_patch(text, now, "date")
        or _has_date_signal(text)
    )


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
    if (
        any(marker in normalized for marker in ("откаж", "отказ"))
        and any(marker in normalized for marker in ("брон", "заявк", "запис", "оформ"))
    ):
        return True
    if (
        any(marker in normalized for marker in ("бронь не нужна", "бронь больше не нужна", "заявка не нужна"))
        or "не будем бронировать" in normalized
    ):
        return True
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
    if _asks_nearest_free_dates(text):
        reply = _next_free_dates_reply(conn, conversation, form_data, now)
        if reply:
            return reply, "waiting_user", "awaiting_new_date", "date", form_data

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
    return _reply_with_hold_summary_impl(
        conn,
        conversation,
        form_data,
        now,
        active_user_bookings=_active_user_bookings,
        prefix=prefix,
    )


def _reserved_hold_callbacks() -> _ReservedHoldCallbacks:
    return _ReservedHoldCallbacks(
        active_user_bookings=_active_user_bookings,
        asks_booking_summary=_asks_booking_summary,
        has_user_bookings=_has_user_bookings,
        post_booking_summary=_current_request_summary,
        new_booking_form_data=_new_booking_form_data,
        wants_cancel_booking=_wants_cancel_booking,
        wants_reschedule=_wants_reschedule,
        start_cancel_booking_flow=_start_cancel_booking_flow,
        start_reschedule_flow=_start_reschedule_flow,
        form_detail_correction_patch=_form_detail_correction_patch,
        last_assistant_asked_name_correction=_last_assistant_asked_name_correction,
        looks_like_name=_looks_like_name,
        merge_form_data=merge_form_data,
        correction_ack_text=_correction_ack_text,
        maybe_name_correction_without_value=_maybe_name_correction_without_value,
        confirmation_yes=_confirmation_yes,
        service_type_patch=_service_type_patch,
        date_patch_after_marker=_date_patch_after_marker,
        relative_date_patch=_relative_date_patch,
        check_availability=check_availability,
        reset_unavailable_slot=_reset_unavailable_slot,
        create_payment_link_for_holds=create_payment_link_for_holds,
        log_payment_link_exception=logger.exception,
    )


def _awaiting_confirmation_callbacks() -> _AwaitingConfirmationCallbacks:
    return _AwaitingConfirmationCallbacks(
        form_detail_correction_patch=_form_detail_correction_patch,
        last_assistant_asked_name_correction=_last_assistant_asked_name_correction,
        looks_like_name=_looks_like_name,
        merge_form_data=merge_form_data,
        normalize_service_aliases=_normalize_service_aliases,
        normalize_gazebo_variant=_normalize_gazebo_variant,
        apply_gazebo_default_duration=_apply_gazebo_default_duration,
        gazebo_open_ended_duration_requested=_gazebo_open_ended_duration_requested,
        check_availability=check_availability,
        no_availability_reply=_no_availability_reply,
        remember_waitlist_request=remember_waitlist_request,
        append_waitlist_offer=_append_waitlist_offer,
        reset_unavailable_slot=_reset_unavailable_slot,
        remember_available_gazebo_variants=_remember_available_gazebo_variants,
        auto_select_single_available_gazebo=_auto_select_single_available_gazebo,
        correction_ack_text=_correction_ack_text,
        maybe_name_correction_without_value=_maybe_name_correction_without_value,
        confirmation_yes=_confirmation_yes,
        confirmation_no=_confirmation_no,
        create_hold=_create_hold,
        create_payment_link_for_holds=create_payment_link_for_holds,
        hold_ttl_minutes=get_settings().hold_ttl_minutes,
        side_reply=_awaiting_confirmation_side_reply,
        log_ai_provider_unavailable=_log_ai_provider_unavailable,
        log_payment_link_exception=logger.exception,
    )


def _staff_id_for_service_id(service_type: str | None, service_id: str | None) -> str:
    service_id = str(service_id or "").strip()
    if not service_type or not service_id:
        return ""
    config = load_services_map().get(service_type) or {}
    for variant in list(config.get("variants") or []) or [config]:
        if str(variant.get("yclients_service_id") or "").strip() == service_id:
            return str(variant.get("yclients_staff_id") or "")
    return ""


def _handle_reserved_hold_command(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    return _handle_reserved_hold_command_impl(
        conn,
        conversation,
        text,
        now,
        history,
        _reserved_hold_callbacks(),
    )


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


def _discount_reply_if_known(text: str, form_data: dict[str, Any]) -> str | None:
    return _discount_reply_if_known_impl(
        text,
        form_data,
        selected_variant_config=_selected_variant_config,
    )


def _explicit_photo_reply(text: str, form_data: dict[str, Any]) -> str | None:
    return _explicit_photo_reply_impl(
        text,
        form_data,
        _ExplicitPhotoCallbacks(
            service_variant_patch=_service_variant_patch,
            service_type_patch=_service_type_patch,
            normalize_service_aliases=_normalize_service_aliases,
            load_services_map=load_services_map,
            suitable_available_gazebo_titles=_suitable_available_gazebo_titles,
            available_gazebo_titles=_available_gazebo_titles,
        ),
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
    next_key, question = next_question(form_data)
    photo_reply = _explicit_photo_reply(text, form_data)
    if photo_reply:
        return photo_reply
    discount_reply = _discount_reply_if_known(text, form_data)
    if discount_reply:
        return discount_reply
    price_reply = _price_reply_if_known(text, form_data)
    if price_reply:
        return price_reply
    if form_data.get("service_type") == "gazebo" and _looks_like_gazebo_budget_preference(text):
        budget_reply = _gazebo_budget_selection_text(form_data)
        if budget_reply:
            return budget_reply
    gazebo_quality_reply = _current_gazebo_quality_reply(text, form_data)
    if gazebo_quality_reply:
        return gazebo_quality_reply
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


def _current_gazebo_quality_reply(text: str, form_data: dict[str, Any]) -> str | None:
    if form_data.get("service_type") != "gazebo" or not form_data.get("service_variant"):
        return None
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("хорош", "норм", "подойдет", "подойдёт", "что за", "какая", "как она", "как бесед")):
        return None
    if not any(marker in normalized for marker in ("бесед", "она", "это", "вариант")):
        return None
    variant = _selected_variant_config(form_data)
    title = str(variant.get("title") or form_data.get("service_variant") or "Беседка").strip()
    line = _format_gazebo_variant_line(variant, date_value=form_data.get("date"))
    normalized_title = title.lower().replace("ё", "е")
    if "№4" in title or " 4" in normalized_title:
        verdict = (
            f"Да, {title} нормальный бюджетный вариант для небольшой компании: "
            "мангал есть, но света и розеток нет."
        )
    elif "№2" in title or " 2" in normalized_title:
        verdict = (
            f"Да, {title} хороший простой вариант, если нужен недорогой отдых с мангалом. "
            "Важно: без света и розеток."
        )
    else:
        verdict = f"Да, {title} подходит. По ней ориентир такой: {line}."
    if next_question(form_data)[0] is None:
        return f"{verdict}\n\nЕсли по заявке всё верно, подтвердите бронь словом «да»."
    return verdict


def _active_booking_reference_info_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    now: datetime,
) -> str | None:
    referenced_service = _referenced_service_type_for_same_time(text)
    current_service = form_data.get("service_type")
    if not referenced_service or referenced_service == current_service:
        return None
    bookings = [
        booking
        for booking in _active_user_bookings(conn, conversation, form_data, now)
        if booking.get("service_type") == referenced_service
    ]
    if not bookings:
        return None
    booking = bookings[0]
    line = _booking_line_short(booking)
    title = _booking_object_title(booking)
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


def _append_current_service_question(reply: str, form_data: dict[str, Any]) -> tuple[str, str | None]:
    next_key, question = next_question(form_data)
    if not question or _reply_already_asks(reply, next_key, question):
        return reply, next_key
    service_cases = {
        "bathhouse": "бане",
        "gazebo": "беседке",
        "warm_gazebo": "тёплой беседке",
        "house": "дому",
    }
    title = service_cases.get(str(form_data.get("service_type") or ""), "этой заявке")
    return f"{reply}\n\nПо {title} продолжим: {question}", next_key


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
                lines.append(f"- {_format_gazebo_variant_line(variant, date_value=form_data.get('date'))}")
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
    return _payment_status_reply_impl(
        conn,
        conversation,
        form_data,
        now=_now_local(),
        sync_payment_statuses=sync_payment_statuses,
        create_missing_yclients_records=create_missing_yclients_records,
        log_exception=logger.exception,
    )


def _classify_post_booking(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    now: datetime,
) -> Any:
    return _classify_post_booking_safely(
        text=text,
        form_data=form_data,
        history=history,
        now=now,
        classify_post_booking_message=classify_post_booking_message,
        load_knowledge=load_knowledge,
        log_exception=logger.exception,
    )


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

    if _asks_available_services(text):
        return _available_services_reply(), status, "reserved", "payment_status", form_data

    if _asks_booking_summary(text) or _continues_booking_summary_question(text, history):
        cleared = {**form_data, "cancel_flow": None, "reschedule_flow": None, "swap_reschedule_flow": None}
        draft_summary = _draft_summary_if_no_active_booking(conn, conversation, cleared, now)
        if draft_summary:
            draft_reply, next_key = draft_summary
            return (
                draft_reply,
                "waiting_user",
                next_key or conversation.get("current_step") or "service_type",
                next_key,
                cleared,
            )
        return _post_booking_summary(conn, conversation, cleared, now), status, "reserved", "payment_status", cleared

    if (
        conversation.get("status") == "payment_paid"
        and _plain_ack_after_closed_booking(text, _confirmation_yes)
        and not any(form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow"))
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

    cancel_info_reply = _reply_to_info_during_cancel_flow(
        conn,
        conversation,
        text,
        history,
        form_data,
        status,
        now,
    )
    if cancel_info_reply:
        return cancel_info_reply

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
            _current_request_summary(conn, conversation, form_data, now)
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
        draft_summary = _draft_summary_if_no_active_booking(conn, conversation, form_data, now)
        if draft_summary:
            draft_reply, next_key = draft_summary
            return (
                draft_reply,
                "waiting_user",
                next_key or conversation.get("current_step") or "service_type",
                next_key,
                form_data,
            )
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


def _reply_to_info_during_cancel_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    _ = history
    if not form_data.get("cancel_flow"):
        return None
    if _confirmation_yes(text) or _confirmation_no(text):
        return None
    if _wants_reschedule(text) or _wants_multi_booking_reschedule(text):
        return None
    if not _looks_like_info_question(text, now=now):
        return None

    normalized = text.lower().replace("ё", "е")
    if any(marker in normalized for marker in ("аванс", "предоплат", "возврат", "вернут", "возвращ")):
        bookings = _active_user_bookings(conn, conversation, form_data, now)
        selected = _select_cancel_bookings(bookings, form_data.get("cancel_flow"), text)
        if len(selected) > 1:
            return _cancel_many_confirmation_reply(selected, now), status, "reserved", "payment_status", form_data
        if len(selected) == 1:
            return _cancel_confirmation_reply(selected[0], now), status, "reserved", "payment_status", form_data

    info_form = {**form_data, "cancel_flow": None}
    reply = _deterministic_info_reply(text, info_form)
    if not reply:
        return None
    reply = reply.strip()
    reply += "\n\nЕсли отменяем эту бронь, напишите «да». Если оставляем — «нет»."
    return reply, status, "reserved", "payment_status", form_data


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

def _start_cancel_booking_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    return _start_cancel_booking_flow_impl(
        conn,
        conversation,
        text,
        form_data,
        status,
        now,
        _cancel_flow_callbacks(),
    )


def _handle_cancel_booking_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    return _handle_cancel_booking_flow_impl(
        conn,
        conversation,
        text,
        form_data,
        now,
        _cancel_flow_callbacks(),
    )


def _cancel_flow_callbacks() -> _CancelFlowCallbacks:
    return _CancelFlowCallbacks(
        active_user_bookings=_active_user_bookings,
        get_booking_by_id=lambda conn, booking_id: bookings_repo.get_by_id(conn, booking_id=booking_id),
        cancel_booking_by_id=lambda conn, booking_id, now: bookings_repo.cancel_by_id(
            conn,
            booking_id=booking_id,
            now=now,
        ),
        delete_yclients_record_for_booking=lambda conn, booking: delete_yclients_record_for_booking(
            conn,
            booking=booking,
        ),
        get_user_by_id=lambda conn, user_id: users_repo.get_by_id(conn, user_id),
        start_user_handoff=_start_user_handoff,
        handoff_reply=_handoff_reply,
        confirmation_yes=_confirmation_yes,
        confirmation_no=_confirmation_no,
    )


def _start_swap_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    return _start_swap_reschedule_flow_impl(
        conn,
        conversation,
        text,
        form_data,
        status,
        now,
        _swap_reschedule_callbacks(),
    )


def _handle_swap_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    return _handle_swap_reschedule_flow_impl(
        conn,
        conversation,
        text,
        form_data,
        now,
        _swap_reschedule_callbacks(),
    )


def _prepare_swap_reschedule(
    conn,
    conversation: dict[str, Any],
    bookings: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    return _prepare_swap_reschedule_impl(
        conn,
        conversation,
        bookings,
        assignments,
        form_data,
        status,
        now,
        _swap_reschedule_callbacks(),
    )


def _execute_swap_reschedule(
    conn,
    conversation: dict[str, Any],
    bookings: list[dict[str, Any]],
    form_data: dict[str, Any],
    flow: dict[str, Any],
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    return _execute_swap_reschedule_impl(
        conn,
        conversation,
        bookings,
        form_data,
        flow,
        _reschedule_execution_callbacks(),
    )


def _swap_reschedule_callbacks() -> _SwapRescheduleCallbacks:
    return _SwapRescheduleCallbacks(
        active_user_bookings=_active_user_bookings,
        conversation_bookings_for_active_flow=_conversation_bookings_for_active_flow,
        confirmation_yes=_confirmation_yes,
        confirmation_no=_confirmation_no,
        check_availability=check_availability,
        append_waitlist_offer=_append_waitlist_offer,
        start_reschedule_flow=_start_reschedule_flow,
        execute_swap_reschedule=_execute_swap_reschedule,
    )


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
    return _initial_reschedule_flow_patch_impl(text, _deterministic_patch(text, now))


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
    return _reschedule_gazebo_change_options_reply_impl(
        conn,
        conversation,
        booking,
        form_data,
        flow,
        text,
        now,
        check_availability=check_availability,
        append_waitlist_offer=_append_waitlist_offer,
    )


def _execute_reschedule(
    conn,
    conversation: dict[str, Any],
    booking: dict[str, Any],
    form_data: dict[str, Any],
    flow: dict[str, Any],
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    return _execute_reschedule_impl(
        conn,
        conversation,
        booking,
        form_data,
        flow,
        _reschedule_execution_callbacks(),
    )


def _restore_booking_after_failed_reschedule(conn, old_booking: dict[str, Any]) -> dict[str, Any] | None:
    return _restore_booking_after_failed_reschedule_impl(conn, old_booking, _reschedule_execution_callbacks())


def _reschedule_execution_callbacks() -> _RescheduleExecutionCallbacks:
    return _RescheduleExecutionCallbacks(
        get_booking_by_id=lambda conn, booking_id: bookings_repo.get_by_id(conn, booking_id=booking_id),
        delete_yclients_record_for_booking=lambda conn, booking: delete_yclients_record_for_booking(
            conn,
            booking=booking,
        ),
        duration_minutes_value=_duration_minutes_value,
        update_booking_schedule=lambda conn, booking_id, booking_date, booking_time, duration_minutes: bookings_repo.update_schedule(
            conn,
            booking_id=booking_id,
            booking_date=booking_date,
            booking_time=booking_time,
            duration_minutes=duration_minutes,
        ),
        update_booking_details=lambda conn, booking_id, guests_count: bookings_repo.update_details(
            conn,
            booking_id=booking_id,
            guests_count=guests_count,
        ),
        update_slot=lambda conn, hold_id, yclients_service_id, yclients_staff_id, slot_date, slot_time, duration_minutes, now: slot_holds_repo.update_slot(
            conn,
            hold_id=hold_id,
            yclients_service_id=yclients_service_id,
            yclients_staff_id=yclients_staff_id,
            slot_date=slot_date,
            slot_time=slot_time,
            duration_minutes=duration_minutes,
            now=now,
        ),
        now_local=_now_local,
        upsert_local_busy_interval_for_booking=lambda conn, booking: upsert_local_busy_interval_for_booking(
            conn,
            booking=booking,
        ),
        create_yclients_record_for_booking=lambda conn, booking: create_yclients_record_for_booking(
            conn,
            booking=booking,
        ),
        staff_id_for_service_id=_staff_id_for_service_id,
        get_user_by_id=lambda conn, user_id: users_repo.get_by_id(conn, user_id),
        start_user_handoff=_start_user_handoff,
        handoff_reply=_handoff_reply,
        log_exception=logger.exception,
    )


def _select_reschedule_booking(bookings: list[dict[str, Any]], booking_id: Any, text: str) -> dict[str, Any] | None:
    return _select_reschedule_booking_impl(bookings, booking_id, text, _now_local())


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
            knowledge=retrieve_client_knowledge(text, form_data),
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


def _alternative_services_for_unavailable_date(
    conn,
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str] | None:
    return _alternative_services_for_unavailable_date_impl(
        conn,
        form_data,
        now,
        check_availability=check_availability,
    )


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


def _next_free_dates_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
    *,
    limit: int = 5,
    days_ahead: int = 75,
) -> str | None:
    return _next_free_dates_reply_impl(
        conn,
        conversation,
        form_data,
        now,
        check_availability=check_availability,
        active_user_bookings=_active_user_bookings,
        limit=limit,
        days_ahead=days_ahead,
    )


def _availability_execution_callbacks() -> _AvailabilityExecutionCallbacks:
    return _AvailabilityExecutionCallbacks(
        check_availability=check_availability,
        alternative_services_for_unavailable_date=_alternative_services_for_unavailable_date,
        next_free_dates_reply=_next_free_dates_reply,
        remember_waitlist_request=remember_waitlist_request,
        asks_for_free_slots=_asks_for_free_slots,
    )


def _execute_availability_check(
    conn,
    conversation: dict[str, Any],
    *,
    user_id: Any,
    form_data: dict[str, Any],
    text: str,
    now: datetime,
    offer_next_free_dates: bool = True,
    remember_waitlist: bool = True,
    alternative_current_step: str = "awaiting_new_date",
):
    return _execute_availability_check_impl(
        conn,
        conversation,
        user_id=user_id,
        form_data=form_data,
        text=text,
        now=now,
        callbacks=_availability_execution_callbacks(),
        offer_next_free_dates=offer_next_free_dates,
        remember_waitlist=remember_waitlist,
        alternative_current_step=alternative_current_step,
    )


def _direct_free_dates_lookup(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    *,
    force_new: bool = False,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    callbacks = _DirectFreeDatesLookupCallbacks(
        asks_for_free_slots=_asks_for_free_slots,
        asks_nearest_free_dates=_asks_nearest_free_dates,
        deterministic_patch=_deterministic_patch,
        guests_count_patch=_guests_count_patch,
        normalize_service_aliases=_normalize_service_aliases,
        new_booking_form_data=_new_booking_form_data,
        merge_form_data=merge_form_data,
        check_availability=check_availability,
        alternative_services_for_unavailable_date=_alternative_services_for_unavailable_date,
        next_free_dates_reply=_next_free_dates_reply,
    )
    return _direct_free_dates_lookup_impl(
        conn,
        conversation,
        text,
        now,
        callbacks,
        force_new=force_new,
    )


def _last_assistant_asked_upsell(history: list[dict[str, Any]]) -> bool:
    return bool(_last_assistant_upsell_text(history))


def _last_assistant_upsell_text(history: list[dict[str, Any]]) -> str:
    for item in reversed(history):
        if item.get("sender") == SENDER_USER:
            continue
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        text = str(item.get("text") or "").lower().replace("ё", "е")
        if any(
            marker in text
            for marker in (
                "что подготовить",
                "что добавим",
                "добавим только",
                "добавим самый",
                "могу добавить",
            )
        ) and any(marker in text for marker in ("доп", "уголь", "розжиг", "решет", "шампур", "кальян", "воду", "посуд", "мангальн")):
            return text
    return ""


def _contextual_upsell_accept_patch(text: str, history: list[dict[str, Any]]) -> dict[str, list[str]]:
    normalized = re.sub(r"[^\w+]+", " ", text.lower().replace("ё", "е")).strip()
    accepts = {
        "давай",
        "давайте",
        "ну давай",
        "ну давайте",
        "ок давайте",
        "хорошо давайте",
        "ладно давайте",
    }
    if not (_confirmation_yes(text) or normalized in accepts):
        return {}
    prompt = _last_assistant_upsell_text(history)
    if not prompt:
        return {}
    if "мангальн" in prompt or "уголь" in prompt or "розжиг" in prompt or "шампур" in prompt or "решет" in prompt:
        return {"upsell_items": ["базовый мангальный набор"]}
    if "вода" in prompt and "посуд" in prompt:
        return {"upsell_items": ["вода", "посуда"]}
    if "вода" in prompt:
        return {"upsell_items": ["вода"]}
    if "кальян" in prompt:
        return {"upsell_items": ["кальян"]}
    return {}


def _last_assistant_asked_name_correction(history: list[dict[str, Any]]) -> bool:
    for item in reversed(history):
        if item.get("sender") == SENDER_USER:
            continue
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        text = str(item.get("text") or "").lower().replace("ё", "е")
        return "какое имя указать" in text or "как имя указать" in text
    return False


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
                lines.append(f"- {_format_gazebo_variant_line(variant, date_value=updated.get('date'))}")
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
    return _awaiting_confirmation_side_reply_impl(
        text=text,
        form_data=form_data,
        history=history,
        looks_like_info_question=_looks_like_info_question,
        deterministic_info_reply=_deterministic_info_reply,
        ai_process_reply=_ai_process_reply,
    )


def _create_hold(conn, conversation: dict[str, Any], user: dict[str, Any], form_data: dict[str, Any], now: datetime) -> dict[str, Any]:
    settings = get_settings()
    return _create_hold_impl(
        conn,
        conversation,
        user,
        form_data,
        now,
        selected_variant_config=_selected_variant_config,
        duration_minutes_value=_duration_minutes_value,
        hold_ttl_minutes=settings.hold_ttl_minutes,
    )


def _create_booking_from_hold(
    conn,
    conversation: dict[str, Any],
    user: dict[str, Any],
    form_data: dict[str, Any],
    hold: dict[str, Any],
) -> dict[str, Any]:
    return _create_booking_from_hold_impl(
        conn,
        conversation,
        user,
        form_data,
        hold,
    )


def _deterministic_patch(text: str, now: datetime) -> dict[str, Any]:
    return (
        _service_type_patch(text)
        | _service_variant_patch(text)
        | _phone_patch(text)
        | _event_format_patch(text)
        | _guests_count_patch(text, "guests_count")
        | _upsell_items_patch(text)
        | _numeric_date_time_patch(text, now)
        | _relative_date_patch(text, now)
        | _time_period_patch(text)
    )


def _current_step_patch(text: str, expected_key: str | None, now: datetime | None = None) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if expected_key == "date":
        patch |= _bare_day_patch(text, now or _now_local(), expected_key)
    if expected_key == "guests_count":
        patch |= _guests_count_patch(text, expected_key)
        patch |= _expected_guest_count_patch(text)
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


def _expected_guest_count_patch(text: str) -> dict[str, int]:
    explicit = _guests_count_patch(text, "guests_count")
    if explicit:
        return explicit
    normalized = text.lower().replace("ё", "е").strip()
    if _time_period_patch(text):
        return {}
    if re.search(r"\b(?:с|до|в|к)\s*\d{1,2}(?::\d{2})?\b", normalized):
        return {}
    if re.search(r"\b\d{1,2}:\d{2}\b", normalized):
        return {}
    if any(marker in normalized for marker in ("утра", "вечера", "дня", "ночи", "час", "часа", "часов", " ч")):
        return {}
    numbers = re.findall(r"\b\d{1,3}\b", normalized)
    if len(numbers) != 1:
        return {}
    guests = int(numbers[0])
    if guests <= 0 or guests > 300:
        return {}
    return {"guests_count": guests}


def _expected_step_detected_patch(
    detected_patch: dict[str, Any],
    text: str,
    expected_key: str | None,
    now: datetime,
) -> dict[str, Any]:
    if not expected_key:
        return {}
    if expected_key == "date" and detected_patch.get("date"):
        return {"date": detected_patch["date"]}
    if expected_key == "guests_count":
        patch = _current_step_patch(text, expected_key, now)
        if patch.get("guests_count"):
            return {"guests_count": patch["guests_count"]}
    if expected_key == "service_variant" and detected_patch.get("service_variant"):
        return {"service_variant": detected_patch["service_variant"]}
    if expected_key == "time":
        result: dict[str, Any] = {}
        if detected_patch.get("time"):
            result["time"] = detected_patch["time"]
        if detected_patch.get("duration") and _has_explicit_duration_signal(text):
            result["duration"] = detected_patch["duration"]
        return result
    if expected_key == "duration" and detected_patch.get("duration"):
        return {"duration": detected_patch["duration"]}
    if expected_key == "event_format" and detected_patch.get("event_format"):
        return {"event_format": detected_patch["event_format"]}
    if expected_key == "upsell_items" and detected_patch.get("upsell_items") and _has_upsell_signal(text):
        return {"upsell_items": detected_patch["upsell_items"]}
    if expected_key in {"client_name", "phone"} and detected_patch.get(expected_key):
        return {expected_key: detected_patch[expected_key]}
    return {}


def _date_numbers_from_context(text: str, patch: dict[str, Any], now: datetime) -> set[int]:
    normalized = text.lower().replace("ё", "е")
    values: set[int] = set()
    date_value = patch.get("date") or _relative_date_patch(text, now).get("date")
    if date_value:
        try:
            parsed = date.fromisoformat(str(date_value))
        except ValueError:
            parsed = None
        if parsed:
            values.add(parsed.day)
    for match in re.finditer(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./]\d{2,4})?", normalized):
        day = int(match.group(1))
        month = int(match.group(2))
        if 1 <= day <= 31:
            values.add(day)
        if 1 <= month <= 12:
            values.add(month)
    for match in re.finditer(rf"\b(\d{{1,2}})\s+({MONTH_PATTERN})\b", normalized):
        day = int(match.group(1))
        month = MONTH_NUMBERS_RU.get(match.group(2))
        if 1 <= day <= 31:
            values.add(day)
        if month and 1 <= month <= 12 and "." in normalized:
            values.add(month)
    return values


def _ai_guest_count_conflicts_with_date_context(
    text: str,
    patch: dict[str, Any],
    deterministic_patch: dict[str, Any],
    expected_key: str | None,
    now: datetime,
) -> bool:
    if "guests_count" not in patch:
        return False
    if "guests_count" in deterministic_patch:
        return False
    if expected_key == "guests_count":
        return False
    if not (
        patch.get("date")
        or deterministic_patch.get("date")
        or _relative_date_patch(text, now)
        or _has_date_signal(text)
    ):
        return False
    try:
        guests = int(patch["guests_count"])
    except (TypeError, ValueError):
        return False
    return guests in _date_numbers_from_context(text, patch | deterministic_patch, now)


def _ai_guest_count_conflicts_with_gazebo_variant(
    text: str,
    patch: dict[str, Any],
    deterministic_patch: dict[str, Any],
    expected_key: str | None,
) -> bool:
    if "guests_count" not in patch:
        return False
    if "guests_count" in deterministic_patch:
        return False
    if expected_key == "guests_count":
        return False
    variant_patch = _service_variant_patch(text, allow_bare_ordinal=True)
    variant = str(variant_patch.get("service_variant") or "")
    match = re.search(r"№\s*(\d+)", variant)
    if not match:
        return False
    try:
        guests = int(patch["guests_count"])
        variant_number = int(match.group(1))
    except (TypeError, ValueError):
        return False
    return guests == variant_number


def _complains_guest_count_not_asked(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return (
        any(marker in normalized for marker in ("не спросил", "не спросили", "не спрашивал", "не спрашивали"))
        and any(marker in normalized for marker in ("сколько человек", "сколько гостей", "сколько нас", "количество гостей"))
    )


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
        expected_patch = _expected_step_detected_patch(ai_patch | detected_patch, text, expected_key, now)
        if expected_patch:
            return expected_patch
        if _looks_like_booking_request_with_date(text, detected_patch):
            return ai_patch | detected_patch
        capacity_patch = _capacity_guest_patch(text)
        if capacity_patch:
            return capacity_patch
        return {}
    return ai_patch | detected_patch


def _capacity_guest_patch(text: str) -> dict[str, int]:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("если нас", "нас будет", "человек", "чел", "гостей", "гостя")):
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
    if not _expected_guest_count_patch(text):
        return False
    if _time_period_patch(text):
        return False
    normalized = text.lower().replace("ё", "е")
    if re.search(r"\b(?:с|до|в)\s*\d{1,2}(?::\d{2})?\b", normalized):
        return False
    return True


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
    if (
        _relative_date_patch(text, now)
        or _bare_day_patch(text, now, "date")
        or _has_date_signal(text)
        or _looks_like_same_date_reference_text(text)
    ):
        allowed.add("date")
    if _time_period_patch(text) or _looks_like_same_time_reference_text(text):
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
        availability_result = _execute_availability_check(
            conn,
            {"id": None},
            user_id=None,
            form_data=updated,
            text=text,
            now=now,
            offer_next_free_dates=False,
            remember_waitlist=False,
            alternative_current_step="service_type",
        )
        return (
            availability_result.reply,
            "waiting_user",
            availability_result.current_step,
            availability_result.next_key,
            availability_result.form_data,
        )

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

        if (
            not conv_created
            and _should_offer_stale_form_choice(conversation, now)
            and not (_wants_new_form_after_stale(message.text) and _asks_for_free_slots(message.text))
        ):
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

        if conversation.get("current_step") == "awaiting_confirmation" and _asks_booking_summary(message.text):
            form_data = conversation.get("form_data") or {}
            reply = _draft_summary_reply(form_data) or _confirmation_reply_text(form_data)
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
                intent="draft_summary",
                current_step="awaiting_confirmation",
                next_step="confirmation",
                form_data=form_data,
            )
            return reply

        if (
            conversation.get("current_step") == "awaiting_confirmation"
            and _wants_cancel_booking(message.text)
            and not _looks_like_info_question(message.text, now=now)
        ):
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

        current_flow_form = conversation.get("form_data") or {}
        has_change_flow = any(
            current_flow_form.get(key)
            for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow")
        )
        parallel_reply = _parallel_booking_question_reply(conversation, message.text)
        if parallel_reply is not None and not has_change_flow:
            reply, current_step, next_key, form_data = parallel_reply
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
                intent="multi_booking_sequence",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
            return reply

        pending_reply = _pending_additional_booking_reply(conversation, message.text, now)
        if pending_reply is not None and not has_change_flow:
            reply, current_step, next_key, form_data = pending_reply
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
                intent="multi_booking_sequence",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
            return reply

        multi_patch = _multi_gazebo_booking_patch(message.text, now)
        if multi_patch and not has_change_flow and conversation.get("current_step") not in {"reserved", "payment_status", "awaiting_confirmation"}:
            form_data = _new_booking_form_data(current_flow_form)
            form_data.update(multi_patch)
            reply = _multi_gazebo_booking_reply(message.text, form_data)
            current_step = "time" if form_data.get("date") else "date"
            next_key = current_step
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
                intent="multi_booking_sequence",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
            return reply

        started_new_booking = False
        if (
            not has_change_flow
            and (
                (
                    conversation.get("current_step") != "awaiting_confirmation"
                    and conversation.get("status") != "awaiting_confirmation"
                )
                or _has_user_bookings(conn, conversation, current_flow_form, now)
            )
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

        post_booking_checked = False
        if (
            not started_new_booking
            and conversation.get("current_step") != "awaiting_confirmation"
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

        if conversation.get("intent") == "booking_paused" and _is_post_pause_ack(message.text):
            form_data = conversation.get("form_data") or {}
            reply = "Отлично, буду ждать. Когда будете готовы — просто напишите, продолжим с этого места ✅"
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
                current_step=conversation.get("current_step"),
                next_step=conversation.get("next_step"),
                form_data=form_data,
            )
            return reply

        if conversation.get("current_step") == "awaiting_confirmation":
            result = _handle_awaiting_confirmation_impl(
                conn,
                conversation,
                user,
                message.text,
                history,
                now,
                _awaiting_confirmation_callbacks(),
            )
            messages_repo.create(
                conn,
                conversation_id=conversation["id"],
                sender=SENDER_ASSISTANT,
                text=result.reply,
            )
            update_kwargs = {
                "status": result.status,
                "current_step": result.current_step,
                "next_step": result.next_step,
                "form_data": result.form_data,
            }
            if result.intent:
                update_kwargs["intent"] = result.intent
            conversations_repo.update_after_message(
                conn,
                conversation["id"],
                now,
                **update_kwargs,
            )
            return result.reply

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
            and not _wants_new_form_after_stale(message.text)
            and not _has_specific_date_signal(message.text, now)
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

        direct_free_dates = _direct_free_dates_lookup(
            conn,
            conversation,
            message.text,
            now,
            force_new=_wants_new_form_after_stale(message.text),
        )
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
        active_step_hint = conversation.get("next_step") or conversation.get("current_step")
        if active_step_hint == "guests_count":
            expected_key_before = "guests_count"
        current_upsells = current_form_data.get("upsell_items") or []
        if (
            expected_key_before != "upsell_items"
            and (not current_upsells or current_upsells == ["не нужны"])
            and _last_assistant_asked_upsell(history)
        ):
            expected_key_before = "upsell_items"
        if (
            current_form_data.get("service_type") == "gazebo"
            and not current_form_data.get("service_variant")
            and _looks_like_gazebo_budget_preference(message.text)
        ):
            form_data = merge_form_data(
                current_form_data,
                _guests_count_patch(message.text, "guests_count"),
            )
            reply = _gazebo_budget_selection_text(form_data) or _gazebo_selection_text(form_data)
            form_data = {
                **form_data,
                "preferences": _join_preferences(form_data.get("preferences"), "подешевле"),
            }
            next_key = "service_variant" if form_data.get("date") and form_data.get("last_available_gazebo_variants") else "date"
            current_step = next_key
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
                current_step=current_step,
                next_step=next_key,
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
            if not upsell_patch and (not current_upsells or current_upsells == ["не нужны"]):
                upsell_patch = _contextual_upsell_accept_patch(message.text, history)
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
        if (
            expected_key_before in {"event_format", "upsell_items"}
            and current_form_data.get("time")
            and current_form_data.get("duration")
            and not _relative_date_patch(message.text, now)
            and not re.search(
                r"\b\d{1,2}\s*(?:мая|июня|июля|августа|сентября|октября|ноября|декабря|января|февраля|марта|апреля)\b",
                message.text.lower().replace("ё", "е"),
            )
        ):
            late_duration = _bare_duration_from_text(message.text)
            if late_duration is not None:
                early_patch["duration"] = late_duration
        if (
            current_form_data.get("service_type") == "gazebo"
            and not current_form_data.get("service_variant")
            and expected_key_before in {"date", "service_variant"}
        ):
            early_patch |= _service_variant_patch(message.text, allow_bare_ordinal=True)
        early_patch |= _same_time_reference_patch(
            conn,
            conversation,
            current_form_data,
            message.text,
            now,
        )
        if expected_key_before == "time" and _references_existing_guest_count(message.text, current_form_data):
            question = next_question(current_form_data)[1] or "Во сколько хотите приехать?"
            reply = f"Да, {current_form_data['guests_count']} гостей записала ✅\n\n{question}"
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
                intent="booking_request",
                current_step="time",
                next_step="time",
                form_data=current_form_data,
            )
            return reply
        if (
            expected_key_before == "time"
            and _looks_like_vague_time_answer(message.text)
            and not _has_valid_time_signal(message.text, early_patch)
            and not _should_route_existing_booking_command(message.text)
        ):
            reply = next_question(current_form_data)[1] or "Во сколько хотите приехать?"
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
                intent="booking_request",
                current_step="time",
                next_step="time",
                form_data=current_form_data,
            )
            return reply
        if (
            current_form_data.get("service_type") == "gazebo"
            and _complains_guest_count_not_asked(message.text)
        ):
            form_data = dict(current_form_data)
            form_data["guests_count"] = None
            form_data["service_variant"] = None
            form_data.pop("last_available_gazebo_variants", None)
            form_data.pop("single_available_gazebo_variant_auto", None)
            form_data.pop("last_suggested_free_dates", None)
            reply = (
                "Вы правы, количество гостей ещё не уточнили. "
                "Чтобы подобрать беседку по вместимости, сколько вас будет человек?"
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
                intent="booking_request",
                current_step="guests_count",
                next_step="guests_count",
                form_data=form_data,
            )
            return reply
        if (
            not current_form_data.get("service_type")
            and _looks_like_info_question(message.text, now=now)
            and not _starts_new_booking_request(message.text)
        ):
            deterministic_info = _deterministic_info_reply(message.text, current_form_data)
            if deterministic_info:
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=deterministic_info,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    intent="company_info",
                    current_step="service_type",
                    next_step="service_type",
                    form_data=current_form_data,
                )
                return deterministic_info
        if (
            current_form_data.get("service_type")
            and _looks_like_info_question(message.text, expected_key=expected_key_before, now=now)
            and not any(current_form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow"))
        ):
            active_reference_info = _active_booking_reference_info_reply(
                conn,
                conversation,
                current_form_data,
                message.text,
                now,
            )
            if active_reference_info:
                reply, next_key = _append_current_service_question(active_reference_info, current_form_data)
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
                    intent="company_info",
                    current_step=next_key or conversation.get("current_step") or "service_type",
                    next_step=next_key,
                    form_data=current_form_data,
                )
                return reply
        if (
            current_form_data.get("service_type")
            and _looks_like_info_question(message.text, expected_key=expected_key_before, now=now)
            and not any(current_form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow"))
        ):
            info_form_data = merge_form_data(current_form_data, early_patch)
            deterministic_info = _deterministic_info_reply(message.text, info_form_data)
            if deterministic_info:
                if (
                    early_patch.get("service_variant")
                    and not current_form_data.get("service_variant")
                    and str(early_patch.get("service_variant")) not in deterministic_info
                ):
                    deterministic_info = f"{early_patch['service_variant']} отметила ✅\n\n{deterministic_info}"
                next_key = next_question(info_form_data)[0]
                current_step = next_key or conversation.get("current_step") or "service_type"
                messages_repo.create(
                    conn,
                    conversation_id=conversation["id"],
                    sender=SENDER_ASSISTANT,
                    text=deterministic_info,
                )
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status="waiting_user",
                    intent="company_info",
                    current_step=current_step,
                    next_step=next_key,
                    form_data=info_form_data,
                )
                return deterministic_info

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
            blocked_guest_count_from_date = _ai_guest_count_conflicts_with_date_context(
                message.text,
                patch,
                deterministic_patch,
                active_expected_step_before,
                now,
            )
            blocked_guest_count_from_variant = _ai_guest_count_conflicts_with_gazebo_variant(
                message.text,
                patch,
                deterministic_patch,
                active_expected_step_before,
            )
            if blocked_guest_count_from_date or blocked_guest_count_from_variant:
                patch.pop("guests_count", None)
            if active_expected_step_before == "time" and not _has_valid_time_signal(message.text, deterministic_patch):
                patch.pop("time", None)
                if not _has_explicit_duration_signal(message.text):
                    patch.pop("duration", None)
            if _selects_gazebo_variant_without_time(message.text) or _guest_count_answer_without_time(message.text, active_expected_step_before):
                patch.pop("time", None)
                patch.pop("duration", None)
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
            if active_expected_step_before == "time" and not _has_valid_time_signal(message.text, deterministic_patch):
                changed_fields.discard("time")
                if not _has_explicit_duration_signal(message.text):
                    changed_fields.discard("duration")
            if _selects_gazebo_variant_without_time(message.text) or _guest_count_answer_without_time(message.text, active_expected_step_before):
                changed_fields.discard("time")
                changed_fields.discard("duration")
            if blocked_guest_count_from_date or blocked_guest_count_from_variant:
                changed_fields.discard("guests_count")
            if "guests_count" not in patch and "guests_count" not in deterministic_patch:
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
            if {"service_type", "date", "time", "duration", "guests_count"} & changed_fields:
                form_data.pop("last_suggested_free_dates", None)
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
                and form_data.get("last_available_gazebo_variants")
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
            accepted_state_changes = {
                "service_type",
                "service_variant",
                "date",
                "time",
                "duration",
                "guests_count",
                "event_format",
                "upsell_items",
                "client_name",
                "phone",
            } & changed_fields
            if (
                (effective_action == "answer_info" and not accepted_state_changes)
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
                availability_result = _execute_availability_check(
                    conn,
                    conversation,
                    user_id=user["id"],
                    form_data=form_data,
                    text=message.text,
                    now=now,
                    alternative_current_step="awaiting_new_date",
                )
                form_data = availability_result.form_data
                next_key = availability_result.next_key
                reply = _ai_process_reply(
                    text=message.text,
                    form_data=form_data,
                    history=history,
                    required_meaning=availability_result.reply,
                )
                current_step = availability_result.current_step
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
                availability_result = _execute_availability_check(
                    conn,
                    conversation,
                    user_id=user["id"],
                    form_data=form_data,
                    text=message.text,
                    now=now,
                    offer_next_free_dates=False,
                    alternative_current_step="service_type",
                )
                reply = availability_result.reply
                next_key = availability_result.next_key
                current_step = availability_result.current_step
                form_data = availability_result.form_data
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
                availability_result = _execute_availability_check(
                    conn,
                    conversation,
                    user_id=user["id"],
                    form_data=form_data,
                    text=message.text,
                    now=now,
                    offer_next_free_dates=False,
                    alternative_current_step="service_type",
                )
                reply = availability_result.reply
                next_key = availability_result.next_key
                current_step = availability_result.current_step
                form_data = availability_result.form_data
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
