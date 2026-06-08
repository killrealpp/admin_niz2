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
from app.services.dialog.bathhouse_flow import bathhouse_period_options_reply as _bathhouse_period_options_reply
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
    explicit_numeric_dates as _explicit_numeric_dates_impl,
    has_date_signal as _has_date_signal,
    numeric_date_time_patch as _numeric_date_time_patch_impl,
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
    classify_upsell_reply as _classify_upsell_reply,
    client_name_patch as _client_name_patch,
    event_format_patch as _event_format_patch,
    explicit_new_service_request as _explicit_new_service_request,
    guests_count_patch as _guests_count_patch,
    has_upsell_signal as _has_upsell_signal,
    is_upsell_final_negative as _is_upsell_final_negative,
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
    wants_fake_payment_simulation as _wants_fake_payment_simulation,
)
from app.services.dialog.handoff import (
    handoff_active as _handoff_active,
    is_location_question as _is_location_question,
    looks_like_handoff_needed as _looks_like_handoff_needed,
    start_user_handoff as _start_user_handoff,
)
from app.services.dialog.info_flow import (
    ActiveBookingInfoCallbacks as _ActiveBookingInfoCallbacks,
    InfoFlowCallbacks as _InfoFlowCallbacks,
    InfoQuestionCallbacks as _InfoQuestionCallbacks,
    active_booking_reference_info_reply as _active_booking_reference_info_reply_impl,
    answer_info_during_form as _answer_info_during_form_impl,
    append_current_service_question as _append_current_service_question_impl,
    contextual_photo_reply as _contextual_photo_reply_impl,
    deterministic_info_reply as _deterministic_info_reply_impl,
    looks_like_info_question as _looks_like_info_question_impl,
    reply_already_asks as _reply_already_asks_impl,
    should_append_next_question_after_info as _should_append_next_question_after_info_impl,
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
from app.services.dialog.new_booking_flow import (
    NewBookingFlowCallbacks as _NewBookingFlowCallbacks,
    context_service_for_generic_new_booking as _context_service_for_generic_new_booking_impl,
    fresh_booking_form_data_for_text as _fresh_booking_form_data_for_text_impl,
    fresh_booking_patch_from_ai as _fresh_booking_patch_from_ai_impl,
    fresh_start_immediate_reply as _fresh_start_immediate_reply_impl,
    generic_new_booking_request as _generic_new_booking_request_impl,
    handle_ai_fresh_start as _handle_ai_fresh_start_impl,
    handle_fresh_start_after_confirmation as _handle_fresh_start_after_confirmation_impl,
    handle_fresh_start_before_post_booking as _handle_fresh_start_before_post_booking_impl,
    handle_stale_new_booking_flow as _handle_stale_new_booking_flow_impl,
    multi_gazebo_booking_patch as _multi_gazebo_booking_patch_impl,
    multi_gazebo_booking_reply as _multi_gazebo_booking_reply_impl,
    starts_new_booking_request as _starts_new_booking_request_impl,
    wants_additional_booking as _wants_additional_booking_impl,
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
from app.services.dialog.reference_flow import (
    preserve_current_service_for_reference as _preserve_current_service_for_reference,
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
    StaleFormTextCallbacks as _StaleFormTextCallbacks,
    continue_stale_form_reply as _continue_stale_form_reply_impl,
    explicit_new_booking_with_details as _explicit_new_booking_with_details_impl,
    new_booking_form_data as _new_booking_form_data,
    should_offer_stale_form_choice as _should_offer_stale_form_choice,
    stale_form_choice_reply as _stale_form_choice_reply,
    stale_message_has_new_booking_details as _stale_message_has_new_booking_details_impl,
    stale_message_starts_new_context as _stale_message_starts_new_context_impl,
    wants_continue_stale_form as _wants_continue_stale_form_impl,
    wants_new_form_after_stale as _wants_new_form_after_stale_impl,
)
from app.services.dialog.time_parsing import (
    apply_gazebo_default_duration as _apply_gazebo_default_duration,
    bare_duration_from_text as _bare_duration_from_text,
    duration_from_text as _duration_from_text,
    gazebo_open_ended_duration_requested as _gazebo_open_ended_duration_requested,
    has_explicit_time_period as _has_explicit_time_period,
    period_conflict as _period_conflict,
    single_time_patch as _single_time_patch,
    time_period_patch as _time_period_patch,
    until_time_duration_patch as _until_time_duration_patch,
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
_INTENT_UNSET = object()


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


def _commit_assistant_response(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_commit_assistant_response

    return _impl_commit_assistant_response(*args, **kwargs)


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


def _log_ai_provider_unavailable(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_log_ai_provider_unavailable

    return _impl_log_ai_provider_unavailable(*args, **kwargs)


def _log_ai_semantic_degraded(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_log_ai_semantic_degraded

    return _impl_log_ai_semantic_degraded(*args, **kwargs)


def _should_run_semantic_preflight(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_should_run_semantic_preflight

    return _impl_should_run_semantic_preflight(*args, **kwargs)


def _semantic_ai_pass(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_semantic_ai_pass

    return _impl_semantic_ai_pass(*args, **kwargs)


def _state_text_consistency_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_state_text_consistency_reply

    return _impl_state_text_consistency_reply(*args, **kwargs)


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


def _wants_time_change_without_value(text: str) -> bool:
    if _time_period_patch(text) or _single_time_patch(text, "time") or _duration_from_text(text) is not None:
        return False
    normalized = text.lower().replace("ё", "е")
    return (
        any(marker in normalized for marker in ("помен", "измени", "изменить", "исправ", "замен"))
        and any(marker in normalized for marker in ("время", "час", "период", "слот"))
    )


def _last_assistant_asked_guest_count(history: list[dict[str, Any]]) -> bool:
    for item in reversed(history):
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        text = str(item.get("text") or "").lower().replace("ё", "е")
        return "сколько вас" in text or "сколько примерно гостей" in text
    return False


def _form_detail_correction_patch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_form_detail_correction_patch

    return _impl_form_detail_correction_patch(*args, **kwargs)


def _confirmation_yes(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_confirmation_yes

    return _impl_confirmation_yes(*args, **kwargs)


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


def _wants_abort_confirmation_draft(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_wants_abort_confirmation_draft

    return _impl_wants_abort_confirmation_draft(*args, **kwargs)


def _wants_additional_booking(text: str) -> bool:
    return _wants_additional_booking_impl(
        text,
        wants_cancel_booking=_wants_cancel_booking,
        wants_reschedule=_wants_reschedule,
        wants_swap_bookings=_wants_swap_bookings,
        service_type_patch=_service_type_patch,
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
    return _starts_new_booking_request_impl(
        text,
        asks_available_services=_asks_available_services,
        service_type_patch=_service_type_patch,
        looks_like_info_question=_looks_like_info_question,
        explicit_numeric_dates=_explicit_numeric_dates,
        now_local=_now_local,
    )


def _generic_new_booking_request(text: str) -> bool:
    return _generic_new_booking_request_impl(
        text,
        wants_cancel_booking=_wants_cancel_booking,
        wants_reschedule=_wants_reschedule,
        wants_swap_bookings=_wants_swap_bookings,
    )


def _context_service_for_generic_new_booking(conversation: dict[str, Any], text: str) -> str | None:
    return _context_service_for_generic_new_booking_impl(
        conversation,
        text,
        generic_new_booking_request=_generic_new_booking_request,
        service_exists=lambda service_type: service_type in load_services_map(),
    )


def _fresh_booking_form_data_for_text(previous: dict[str, Any], text: str) -> dict[str, Any]:
    return _fresh_booking_form_data_for_text_impl(
        previous,
        text,
        new_booking_form_data=_new_booking_form_data,
        service_type_patch=_service_type_patch,
        generic_new_booking_request=_generic_new_booking_request,
        normalize_service_aliases=_normalize_service_aliases,
        service_exists=lambda service_type: service_type in load_services_map(),
    )


def _fresh_start_immediate_reply(form_data: dict[str, Any], text: str, now: datetime) -> tuple[str, str, str | None] | None:
    return _fresh_start_immediate_reply_impl(
        form_data,
        text,
        now,
        generic_new_booking_request=_generic_new_booking_request,
        asks_for_free_slots=_asks_for_free_slots,
        asks_nearest_free_dates=_asks_nearest_free_dates,
        has_specific_date_signal=_has_specific_date_signal,
        looks_like_same_date_reference_text=_looks_like_same_date_reference_text,
        time_period_patch=_time_period_patch,
        looks_like_same_time_reference_text=_looks_like_same_time_reference_text,
        service_title=lambda service_type: (load_services_map().get(service_type) or {}).get("title"),
    )


def _gazebo_guest_options_shortcut(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_gazebo_guest_options_shortcut

    return _impl_gazebo_guest_options_shortcut(*args, **kwargs)


def _explicit_numeric_dates(*args: Any, **kwargs: Any) -> Any:
    return _explicit_numeric_dates_impl(*args, **kwargs)


def _numeric_date_time_patch(*args: Any, **kwargs: Any) -> Any:
    return _numeric_date_time_patch_impl(*args, **kwargs)


def _multi_gazebo_booking_patch(*args: Any, **kwargs: Any) -> Any:
    return _multi_gazebo_booking_patch_impl(
        *args,
        **kwargs,
        service_type_patch=_service_type_patch,
        explicit_numeric_dates=_explicit_numeric_dates,
    )


def _multi_gazebo_booking_reply(*args: Any, **kwargs: Any) -> Any:
    return _multi_gazebo_booking_reply_impl(*args, **kwargs)


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


def _merge_selected_upsells(current_items: Any, selected_items: list[str]) -> list[str]:
    merged: list[str] = []
    for item in list(current_items or []) + list(selected_items or []):
        text = str(item).strip()
        if not text or text == "не нужны":
            continue
        if text not in merged:
            merged.append(text)
    return merged


def _upsell_followup_reply(items: list[str], price_reply: str | None = None) -> str:
    items_text = ", ".join(items)
    prefix = f"Хорошо, {items_text} добавим ✅"
    if price_reply:
        prefix = f"{price_reply}\n\n{prefix}"
    return (
        f"{prefix}\n\n"
        "Если хотите добавить что-то ещё, напишите. "
        "Если больше ничего не нужно, напишите «нет», и продолжим по анкете."
    )


def _upsell_info_followup_reply(items: Any) -> str:
    selected = [str(item).strip() for item in list(items or []) if str(item).strip() and str(item).strip() != "не нужны"]
    if selected:
        return "Если хотите добавить что-то ещё, напишите. Если больше ничего не нужно, напишите «нет»."
    return "Что подготовить для вас? Если ничего не нужно, напишите «нет»."


def _late_addon_price_update(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_late_addon_price_update

    return _impl_late_addon_price_update(*args, **kwargs)


def _pending_additional_booking_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_pending_additional_booking_reply

    return _impl_pending_additional_booking_reply(*args, **kwargs)


def _parallel_booking_question_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_parallel_booking_question_reply

    return _impl_parallel_booking_question_reply(*args, **kwargs)


def _continues_current_draft_service_switch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_continues_current_draft_service_switch

    return _impl_continues_current_draft_service_switch(*args, **kwargs)


def _should_start_fresh_booking(conversation: dict[str, Any], text: str) -> bool:
    if _continues_current_draft_service_switch(conversation, text):
        return False
    wants_additional = _wants_additional_booking(text)
    requested_service = (_service_type_patch(text) or {}).get("service_type") or _context_service_for_generic_new_booking(conversation, text)
    starts_new = _starts_new_booking_request(text) or _generic_new_booking_request(text)
    return _should_start_fresh_booking_decision(
        conversation,
        requested_service=requested_service,
        starts_new_request=starts_new,
        wants_additional_booking=wants_additional,
        is_existing_booking_command=(
            _wants_cancel_booking(text) or _wants_reschedule(text) or _wants_swap_bookings(text)
        ),
    )


def _ai_should_start_fresh_booking(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_ai_should_start_fresh_booking

    return _impl_ai_should_start_fresh_booking(*args, **kwargs)


def _fresh_booking_patch_from_ai(
    *,
    ai_result: Any,
    patch: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    return _fresh_booking_patch_from_ai_impl(
        ai_result=ai_result,
        patch=patch,
        text=text,
        now=now,
        filter_new_booking_patch_to_current_message=_filter_new_booking_patch_to_current_message,
    )


def _is_plain_greeting(text: str) -> bool:
    normalized = re.sub(r"[^\w\s]+", " ", text.lower().replace("ё", "е")).strip()
    words = set(normalized.split())
    return bool(words & {"привет", "здравствуйте", "добрый", "день", "вечер"}) and not _service_type_patch(normalized)


def _asks_booking_summary(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_asks_booking_summary

    return _impl_asks_booking_summary(*args, **kwargs)


def _draft_summary_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_draft_summary_reply

    return _impl_draft_summary_reply(*args, **kwargs)


def _draft_summary_if_no_active_booking(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_draft_summary_if_no_active_booking

    return _impl_draft_summary_if_no_active_booking(*args, **kwargs)


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


def _asks_available_services(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_asks_available_services

    return _impl_asks_available_services(*args, **kwargs)


def _asks_specific_service_exists(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_asks_specific_service_exists

    return _impl_asks_specific_service_exists(*args, **kwargs)


def _specific_service_exists_reply(text: str) -> str:
    service_type = (_service_type_patch(text) or {}).get("service_type")
    return _specific_service_exists_reply_for_type(service_type)


def _specific_service_exists_reply_for_type(service_type: str | None) -> str:
    title = (load_services_map().get(service_type) or {}).get("title") or "эта услуга"
    if service_type == "bathhouse":
        return (
            "Да, есть баня с бассейном. Она оформляется отдельной бронью, "
            "не добавляется к беседке как доп.\n\n"
            "Если хотите забронировать баню, напишите дату, время и длительность — проверю свободность."
        )
    if service_type == "gazebo":
        return (
            "Есть несколько беседок: №1 до 50 гостей, №2/№4/№6 до 15, №5 до 10, "
            "№3/№8 и Крытая беседка до 20 гостей.\n\n"
            "Беседка оформляется отдельной бронью. Если хотите добавить её, напишите дату — проверю свободность."
        )
    return (
        f"Да, {title.lower()} есть. Если хотите добавить её отдельной бронью, "
        "напишите дату — проверю свободность."
    )


def _asks_how_to_book_last_discussed_service(text: str, form_data: dict[str, Any]) -> bool:
    service_type = form_data.get("last_discussed_service_type")
    if service_type not in load_services_map():
        return False
    normalized = text.lower().replace("ё", "е")
    return (
        any(marker in normalized for marker in ("как бронир", "как заброни", "как оформ", "как ее", "как её", "ее как", "её как"))
        and any(marker in normalized for marker in ("?", "нужно", "надо", "можно", "брони", "оформ"))
    )


def _looks_like_weather_question(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(marker in normalized for marker in ("погод", "дожд", "ливень", "гроза", "ветер", "холод", "жара"))


def _available_services_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_available_services_reply

    return _impl_available_services_reply(*args, **kwargs)


def _primary_service_type_from_bookings(bookings: list[dict[str, Any]]) -> str | None:
    service_types: list[str] = []
    for booking in bookings:
        service_type = str(booking.get("service_type") or "").strip()
        if service_type and service_type not in service_types:
            service_types.append(service_type)
    if len(service_types) == 1:
        return service_types[0]
    return None


def _available_services_reply_for_active_bookings(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> str:
    active_service_type = _primary_service_type_from_bookings(
        _active_user_bookings(conn, conversation, form_data, now)
    )
    if active_service_type:
        return _available_services_reply({**form_data, "service_type": active_service_type})
    return _available_services_reply(form_data)


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


def _looks_like_vague_time_answer(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_looks_like_vague_time_answer

    return _impl_looks_like_vague_time_answer(*args, **kwargs)


def _has_explicit_duration_signal(text: str) -> bool:
    return _duration_from_text(text) is not None


def _has_specific_date_signal(text: str, now: datetime) -> bool:
    return bool(
        _relative_date_patch(text, now)
        or _bare_day_patch(text, now, "date")
        or _has_date_signal(text)
    )


def _stale_form_text_callbacks() -> _StaleFormTextCallbacks:
    return _StaleFormTextCallbacks(
        confirmation_yes=_confirmation_yes,
        confirmation_no=_confirmation_no,
        service_type_patch=_service_type_patch,
        now_local=_now_local,
        has_specific_date_signal=_has_specific_date_signal,
        relative_date_patch=_relative_date_patch,
        time_period_patch=_time_period_patch,
        has_explicit_duration_signal=_has_explicit_duration_signal,
        guests_count_patch=_guests_count_patch,
        wants_cancel_booking=_wants_cancel_booking,
        wants_reschedule=_wants_reschedule,
        wants_swap_bookings=_wants_swap_bookings,
        asks_for_free_slots=_asks_for_free_slots,
        starts_new_booking_request=_starts_new_booking_request,
    )


def _wants_continue_stale_form(text: str) -> bool:
    return _wants_continue_stale_form_impl(text, _stale_form_text_callbacks())


def _wants_new_form_after_stale(text: str) -> bool:
    return _wants_new_form_after_stale_impl(text, _stale_form_text_callbacks())


def _stale_message_starts_new_context(text: str) -> bool:
    return _stale_message_starts_new_context_impl(text, _stale_form_text_callbacks())


def _stale_message_has_new_booking_details(text: str) -> bool:
    return _stale_message_has_new_booking_details_impl(text, _stale_form_text_callbacks())


def _explicit_new_booking_with_details(text: str) -> bool:
    return _explicit_new_booking_with_details_impl(text, _stale_form_text_callbacks())


def _continue_stale_form_reply(form_data: dict[str, Any]) -> tuple[str, str | None]:
    return _continue_stale_form_reply_impl(form_data, _confirmation_reply_text)


def _wants_abort_current_draft(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_wants_abort_current_draft

    return _impl_wants_abort_current_draft(*args, **kwargs)


def _wants_pause_current_draft(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_wants_pause_current_draft

    return _impl_wants_pause_current_draft(*args, **kwargs)


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
        "Если захотите забронировать позже, просто напишите, что бронируем."
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


def _handle_gazebo_browsing_start(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_handle_gazebo_browsing_start

    return _impl_handle_gazebo_browsing_start(*args, **kwargs)


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


def _reserved_hold_callbacks(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_reserved_hold_callbacks

    return _impl_reserved_hold_callbacks(*args, **kwargs)


def _awaiting_confirmation_callbacks(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_awaiting_confirmation_callbacks

    return _impl_awaiting_confirmation_callbacks(*args, **kwargs)


def _new_booking_flow_callbacks(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_new_booking_flow_callbacks

    return _impl_new_booking_flow_callbacks(*args, **kwargs)


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


def _build_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_build_reply

    return _impl_build_reply(*args, **kwargs)


def _append_expected_question(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_append_expected_question

    return _impl_append_expected_question(*args, **kwargs)


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


def _info_question_callbacks() -> _InfoQuestionCallbacks:
    return _InfoQuestionCallbacks(
        is_likely_form_answer=_is_likely_form_answer,
        now_local=_now_local,
        confirmation_yes=_confirmation_yes,
        confirmation_no=_confirmation_no,
    )


def _info_flow_callbacks() -> _InfoFlowCallbacks:
    return _InfoFlowCallbacks(
        next_question=next_question,
        reply_already_asks=_reply_already_asks,
        explicit_photo_reply=_explicit_photo_reply,
        discount_reply_if_known=_discount_reply_if_known,
        price_reply_if_known=_price_reply_if_known,
        looks_like_gazebo_budget_preference=_looks_like_gazebo_budget_preference,
        gazebo_budget_selection_text=_gazebo_budget_selection_text,
        current_gazebo_quality_reply=_current_gazebo_quality_reply,
        capacity_info_reply=_capacity_info_reply,
        policy_or_common_info_reply=_policy_or_common_info_reply,
        should_append_next_question_after_info=_should_append_next_question_after_info,
        capacity_guest_patch=_capacity_guest_patch,
        clean_reply=_clean_reply,
        ai_process_reply=_ai_process_reply,
        asks_gazebo_options=_asks_gazebo_options,
        gazebo_selection_text=_gazebo_selection_text,
    )


def _active_booking_info_callbacks() -> _ActiveBookingInfoCallbacks:
    return _ActiveBookingInfoCallbacks(
        means_same_date=_means_same_date,
        means_same_time=_means_same_time,
        referenced_service_type_for_same_time=_referenced_service_type_for_same_time,
        active_user_bookings=_active_user_bookings,
        booking_line_short=_booking_line_short,
        booking_object_title=_booking_object_title,
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


def _deterministic_info_reply(text: str, form_data: dict[str, Any], *, append_next_question: bool = True) -> str | None:
    return _deterministic_info_reply_impl(
        text,
        form_data,
        callbacks=_info_flow_callbacks(),
        append_next_question=append_next_question,
    )


def _current_gazebo_quality_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_current_gazebo_quality_reply

    return _impl_current_gazebo_quality_reply(*args, **kwargs)


def _active_booking_reference_info_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    now: datetime,
) -> str | None:
    return _active_booking_reference_info_reply_impl(
        conn,
        conversation,
        form_data,
        text,
        now,
        callbacks=_active_booking_info_callbacks(),
    )


def _append_current_service_question(reply: str, form_data: dict[str, Any]) -> tuple[str, str | None]:
    return _append_current_service_question_impl(
        reply,
        form_data,
        callbacks=_info_flow_callbacks(),
    )


def _last_rejected_guest_count(form_data: dict[str, Any]) -> int | None:
    values = [
        form_data.get("last_rejected_guest_count"),
        (form_data.get("last_capacity_rejection") or {}).get("guests_count"),
    ]
    for value in values:
        try:
            guests = int(value)
        except (TypeError, ValueError):
            continue
        if guests > 0:
            return guests
    return None


def _large_group_manual_reply(guests_count: int) -> str:
    return (
        f"На {guests_count} человек стандартные объекты не рассчитаны.\n\n"
        "Для такого количества стандартного авто-варианта нет; крупнейшие обычные варианты сильно меньше. "
        "Такой запрос лучше вручную обсудить с администратором."
    )


def _large_group_followup_question(normalized: str) -> bool:
    return any(
        marker in normalized
        for marker in (
            "что подход",
            "что тогда",
            "вариант",
            "куда",
            "можно",
            "порекоменду",
            "посовет",
        )
    )


def _bathhouse_large_group_followup_reply(text: str, form_data: dict[str, Any]) -> str | None:
    if form_data.get("service_type") != "bathhouse":
        return None
    normalized = text.lower().replace("ё", "е")
    if not _large_group_followup_question(normalized):
        return None
    guests = (_guests_count_patch(text, "guests_count") or {}).get("guests_count")
    if not guests:
        guests = _last_rejected_guest_count(form_data)
    if not guests:
        return None
    guests_count = int(guests)
    if guests_count < 100:
        return None
    return _large_group_manual_reply(guests_count)


def _capacity_info_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_capacity_info_reply

    return _impl_capacity_info_reply(*args, **kwargs)


def _should_append_next_question_after_info(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_should_append_next_question_after_info

    return _impl_should_append_next_question_after_info(*args, **kwargs)


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


def _handle_post_booking_message(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_handle_post_booking_message

    return _impl_handle_post_booking_message(*args, **kwargs)


def _handle_booking_reminder_response(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_handle_booking_reminder_response

    return _impl_handle_booking_reminder_response(*args, **kwargs)


def _reply_to_info_during_cancel_flow(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_reply_to_info_during_cancel_flow

    return _impl_reply_to_info_during_cancel_flow(*args, **kwargs)


def _reply_to_info_during_reschedule_flow(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_reply_to_info_during_reschedule_flow

    return _impl_reply_to_info_during_reschedule_flow(*args, **kwargs)

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


def _cancel_flow_callbacks(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_cancel_flow_callbacks

    return _impl_cancel_flow_callbacks(*args, **kwargs)


def _record_refund_required(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_record_refund_required

    return _impl_record_refund_required(*args, **kwargs)


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


def _same_booking_reference_patch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_same_booking_reference_patch

    return _impl_same_booking_reference_patch(*args, **kwargs)


def _same_time_reference_patch(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    return _same_booking_reference_patch(conn, conversation, form_data, text, now)


def _start_reschedule_flow(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_start_reschedule_flow

    return _impl_start_reschedule_flow(*args, **kwargs)


def _initial_reschedule_flow_patch(text: str, now: datetime) -> dict[str, Any]:
    return _initial_reschedule_flow_patch_impl(text, _deterministic_patch(text, now))


def _handle_reschedule_flow(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_handle_reschedule_flow

    return _impl_handle_reschedule_flow(*args, **kwargs)


def _reschedule_gazebo_change_options_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_reschedule_gazebo_change_options_reply

    return _impl_reschedule_gazebo_change_options_reply(*args, **kwargs)


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


def _reschedule_execution_callbacks(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_reschedule_execution_callbacks

    return _impl_reschedule_execution_callbacks(*args, **kwargs)


def _select_reschedule_booking(bookings: list[dict[str, Any]], booking_id: Any, text: str) -> dict[str, Any] | None:
    return _select_reschedule_booking_impl(bookings, booking_id, text, _now_local())


def _ai_process_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_ai_process_reply

    return _impl_ai_process_reply(*args, **kwargs)


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


def _execute_availability_check(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_execute_availability_check

    return _impl_execute_availability_check(*args, **kwargs)


def _direct_free_dates_lookup(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_direct_free_dates_lookup

    return _impl_direct_free_dates_lookup(*args, **kwargs)


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


def _contextual_upsell_accept_patch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_contextual_upsell_accept_patch

    return _impl_contextual_upsell_accept_patch(*args, **kwargs)


def _last_assistant_asked_name_correction(history: list[dict[str, Any]]) -> bool:
    for item in reversed(history):
        if item.get("sender") == SENDER_USER:
            continue
        if item.get("sender") != SENDER_ASSISTANT:
            continue
        text = str(item.get("text") or "").lower().replace("ё", "е")
        return "какое имя указать" in text or "как имя указать" in text
    return False


def _is_likely_form_answer(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_is_likely_form_answer

    return _impl_is_likely_form_answer(*args, **kwargs)


def _reply_already_asks(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_reply_already_asks

    return _impl_reply_already_asks(*args, **kwargs)


def _looks_like_info_question(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_looks_like_info_question

    return _impl_looks_like_info_question(*args, **kwargs)


def _answer_info_during_form(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_answer_info_during_form

    return _impl_answer_info_during_form(*args, **kwargs)


def _safe_reply_without_availability_claim(
    reply: str,
    form_data: dict[str, Any],
) -> tuple[str, str | None]:
    next_key, question = next_question(form_data)
    bathhouse_period = _bathhouse_period_options_reply(form_data)
    if bathhouse_period:
        return bathhouse_period
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


def _gazebo_capacity_mismatch_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_gazebo_capacity_mismatch_reply

    return _impl_gazebo_capacity_mismatch_reply(*args, **kwargs)


def _bathhouse_capacity_mismatch_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_bathhouse_capacity_mismatch_reply

    return _impl_bathhouse_capacity_mismatch_reply(*args, **kwargs)


def _bathhouse_guest_limit_exceeded(form_data: dict[str, Any]) -> bool:
    if not form_data.get("guests_count"):
        return False
    try:
        return int(form_data["guests_count"]) > 15
    except (TypeError, ValueError):
        return False


def _capacity_mismatch_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str | None, dict[str, Any]] | None:
    return _gazebo_capacity_mismatch_reply(
        conn,
        conversation,
        form_data,
        now,
    ) or _bathhouse_capacity_mismatch_reply(
        conn,
        conversation,
        form_data,
        now,
    )


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
    contextual_photo = _contextual_photo_reply_impl(
        text,
        form_data,
        history,
        callbacks=_info_flow_callbacks(),
    )
    if contextual_photo:
        return contextual_photo
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


def _apply_contextual_day_number_patch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_apply_contextual_day_number_patch

    return _impl_apply_contextual_day_number_patch(*args, **kwargs)


def _context_date_for_day_number(form_data: dict[str, Any]) -> date | None:
    candidates = [
        form_data.get("date"),
        (form_data.get("last_unavailable") or {}).get("date"),
    ]
    for value in candidates:
        if not value:
            continue
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            continue
    return None


def _contextual_day_number(text: str) -> int | None:
    normalized = text.lower().replace("ё", "е")
    patterns = (
        r"\b(?:на|к|ко)\s+(\d{1,2})(?:\s*[-е]*\s*(?:числа|число))?\b",
        r"\b(\d{1,2})\s*(?:числа|число)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        tail = normalized[match.end() : match.end() + 16]
        if any(marker in tail for marker in ("час", "чел", "гост", "мин")):
            continue
        day = int(match.group(1))
        if 1 <= day <= 31:
            return day
    return None


def _has_explicit_month_name(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return any(month in normalized for month in MONTH_NUMBERS_RU)


def _current_step_patch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_current_step_patch

    return _impl_current_step_patch(*args, **kwargs)


def _expected_guest_count_patch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_expected_guest_count_patch

    return _impl_expected_guest_count_patch(*args, **kwargs)


def _expected_step_detected_patch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_expected_step_detected_patch

    return _impl_expected_step_detected_patch(*args, **kwargs)


def _date_numbers_from_context(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_date_numbers_from_context

    return _impl_date_numbers_from_context(*args, **kwargs)


def _ai_guest_count_conflicts_with_date_context(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_ai_guest_count_conflicts_with_date_context

    return _impl_ai_guest_count_conflicts_with_date_context(*args, **kwargs)


def _ai_guest_count_conflicts_with_gazebo_variant(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_ai_guest_count_conflicts_with_gazebo_variant

    return _impl_ai_guest_count_conflicts_with_gazebo_variant(*args, **kwargs)


def _explicit_gazebo_variant_reference(text: str) -> bool:
    if not _service_variant_patch(text, allow_bare_ordinal=True):
        return False
    normalized = text.lower().replace("ё", "е")
    return bool(
        "бесед" in normalized
        or "№" in normalized
        or re.search(r"\bномер(?:\s+\d|\s+од|\s+дв|\s+тр|\s+чет|\s+пят|\s+шест|\s+вос)", normalized)
    )


def _complains_guest_count_not_asked(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    return (
        any(marker in normalized for marker in ("не спросил", "не спросили", "не спрашивал", "не спрашивали"))
        and any(marker in normalized for marker in ("сколько человек", "сколько гостей", "сколько нас", "количество гостей"))
    )


def _ai_first_patch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_ai_first_patch

    return _impl_ai_first_patch(*args, **kwargs)


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


def _filter_new_booking_patch_to_current_message(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_filter_new_booking_patch_to_current_message

    return _impl_filter_new_booking_patch_to_current_message(*args, **kwargs)


def _restore_draft_context_after_service_switch(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_restore_draft_context_after_service_switch

    return _impl_restore_draft_context_after_service_switch(*args, **kwargs)


def _fast_entry_reply(*args: Any, **kwargs: Any) -> Any:
    from app.services.dialog.message_handler_flow_glue import _impl_fast_entry_reply

    return _impl_fast_entry_reply(*args, **kwargs)


@trace_message_handler(logger)
def handle_incoming(message: IncomingMessage) -> str:
    from app.services.dialog.message_handler_flow_glue import _impl_handle_incoming

    return _impl_handle_incoming(message)
