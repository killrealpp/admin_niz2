from __future__ import annotations

from app.services import message_handler as _handler_defaults
from app.services.dialog.date_parsing import (
    explicit_numeric_dates as _explicit_numeric_dates_impl,
    numeric_date_time_patch as _numeric_date_time_patch_impl,
)
from app.services.dialog.new_booking_flow import (
    multi_gazebo_booking_patch as _multi_gazebo_booking_patch_impl,
    multi_gazebo_booking_reply as _multi_gazebo_booking_reply_impl,
)
from app.services.dialog.reference_flow import (
    FreeDatesAfterUnavailableCallbacks as _FreeDatesAfterUnavailableCallbacks,
    ReferencePatchCallbacks as _ReferencePatchCallbacks,
    SameUnavailableDateCallbacks as _SameUnavailableDateCallbacks,
    UnavailableAlternativesCallbacks as _UnavailableAlternativesCallbacks,
    free_dates_after_unavailable_route as _free_dates_after_unavailable_route_impl,
    same_booking_reference_patch as _same_booking_reference_patch_impl,
    same_unavailable_date_route as _same_unavailable_date_route_impl,
    unavailable_alternatives_route as _unavailable_alternatives_route_impl,
)

_INTENT_UNSET = _handler_defaults._INTENT_UNSET

# Transitional extraction layer for the large legacy message handler.
# The implementation refreshes globals from app.services.message_handler on entry
# so existing monkeypatches and compatibility wrappers keep working.
def _refresh_handler_globals() -> None:
    from app.services import message_handler as _handler

    for _name, _value in vars(_handler).items():
        if not _name.startswith("__"):
            globals()[_name] = _value


def _impl_commit_assistant_response(
    conn,
    conversation: dict[str, Any],
    now: datetime,
    reply: str,
    *,
    status: str,
    current_step: str | None,
    next_step: str | None,
    form_data: dict[str, Any],
    intent: Any = _INTENT_UNSET,
    before_update: Any = None,
) -> str:
    _refresh_handler_globals()
    messages_repo.create(
        conn,
        conversation_id=conversation["id"],
        sender=SENDER_ASSISTANT,
        text=reply,
    )
    update_kwargs = {
        "status": status,
        "current_step": current_step,
        "next_step": next_step,
        "form_data": form_data,
    }
    if intent is not _INTENT_UNSET:
        update_kwargs["intent"] = intent
    if before_update is not None:
        before_update()
    conversations_repo.update_after_message(
        conn,
        conversation["id"],
        now,
        **update_kwargs,
    )
    return reply


def _impl_log_ai_provider_unavailable(
    conn,
    *,
    conversation_id: int,
    exc: AIProviderUnavailable,
    text: str,
    form_data: dict[str, Any],
) -> None:
    _refresh_handler_globals()
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


def _impl_log_ai_semantic_degraded(
    conn,
    *,
    conversation_id: int,
    exc: AIProviderUnavailable,
    text: str,
    form_data: dict[str, Any],
) -> None:
    _refresh_handler_globals()
    system_logs_repo.create(
        conn,
        level="warning",
        event_type="ai_semantic_degraded",
        message=str(exc),
        conversation_id=conversation_id,
        payload={
            "status_code": exc.status_code,
            "provider_payload": str(exc.payload or "")[:1000],
            "user_text": text[:500],
            "current_step": next_question(form_data)[0],
        },
    )


def _impl_should_run_semantic_preflight(conversation: dict[str, Any], *, conv_created: bool) -> bool:
    _refresh_handler_globals()
    if conv_created:
        return False
    if conversation.get("status") == "handoff":
        return False
    if conversation.get("current_step") or conversation.get("next_step"):
        return True
    form_data = conversation.get("form_data") or {}
    return any(
        form_data.get(key)
        for key in (
            "service_type",
            "date",
            "time",
            "duration",
            "guests_count",
            "event_format",
            "upsell_items",
            "phone",
            "cancel_flow",
            "reschedule_flow",
        )
    )


def _impl_semantic_ai_pass(
    conn,
    *,
    conversation: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
    now: datetime,
) -> Any:
    _refresh_handler_globals()
    summaries = _context_summaries(
        conn,
        conversation,
        conversation.get("form_data") or {},
        now,
    )
    return call_ai(
        text=text,
        form_data=conversation.get("form_data") or {},
        history=history,
        summaries=summaries,
        current_datetime=now,
        knowledge=_build_semantic_router_knowledge(conversation.get("form_data") or {}),
    )


def _impl_state_text_consistency_reply(
    conn,
    *,
    conversation_id: int,
    reply: str,
    form_data: dict[str, Any],
) -> str:
    _refresh_handler_globals()
    normalized = reply.lower().replace("ё", "е")
    upsells = [str(item).lower().replace("ё", "е") for item in (form_data.get("upsell_items") or [])]
    reason: str | None = None
    if "кальян" in normalized and "добав" in normalized and "кальян" not in upsells:
        reason = "reply_says_hookah_added_without_state"
    if "допы: не нужны" in normalized and upsells != ["не нужны"]:
        reason = reason or "reply_summary_says_no_upsells_without_state"
    if not reason:
        return reply

    if _booking_ready(form_data):
        rebuilt = _confirmation_reply_text(form_data)
    else:
        _next_key, question = next_question(form_data)
        rebuilt = question or _fallback_reply(form_data)[0]

    system_logs_repo.create(
        conn,
        level="warning",
        event_type="state_text_consistency_rebuilt",
        message=reason,
        conversation_id=conversation_id,
        payload={
            "reason": reason,
            "original_reply": reply[:1000],
            "rebuilt_reply": rebuilt[:1000],
            "upsell_items": form_data.get("upsell_items"),
        },
    )
    return rebuilt


def _impl_form_detail_correction_patch(text: str, form_data: dict[str, Any]) -> dict[str, Any]:
    _refresh_handler_globals()
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
    else:
        until_patch = _until_time_duration_patch(text, form_data.get("time"))
        if until_patch:
            patch |= until_patch
    if not period_patch and "time" not in patch and "duration" not in patch and any(marker in normalized for marker in ("время", "час", "с ", "до ", "приед", "заед")):
        time_patch = _single_time_patch(text, "time")
        if time_patch:
            patch |= time_patch

    duration_value = _duration_from_text(text)
    if duration_value is not None and not period_patch and "duration" not in patch:
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


def _impl_confirmation_yes(text: str) -> bool:
    _refresh_handler_globals()
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
    if re.fullmatch(r"(?:ну\s+)?(?:вроде|похоже)\s+да", normalized):
        return True
    if re.fullmatch(r"да\s+(?:вроде|похоже)", normalized):
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


def _impl_wants_abort_confirmation_draft(text: str) -> bool:
    _refresh_handler_globals()
    normalized = text.lower().replace("ё", "е").strip(" .,!?:;")
    compact = re.sub(r"[^\w]+", " ", normalized).strip()
    if compact in {
        "давай нет",
        "давайте нет",
        "нет не будем",
        "не будем",
        "я перехотел",
        "я перехотела",
        "я передумал",
        "я передумала",
    }:
        return True
    return _wants_abort_current_draft(text) or any(
        marker in compact
        for marker in (
            "перехотел",
            "перехотела",
            "не будем оформ",
            "не хочу оформ",
            "не хочу брон",
            "давай не будем",
            "давайте не будем",
        )
    )


def _impl_gazebo_guest_options_shortcut(
    form_data: dict[str, Any],
    text: str,
) -> tuple[str, dict[str, Any], str, str | None] | None:
    _refresh_handler_globals()
    if form_data.get("service_type") != "gazebo" or form_data.get("service_variant"):
        return None
    guest_patch = _capacity_guest_patch(text)
    if not guest_patch:
        return None
    expected_key = next_question(form_data)[0]
    if expected_key != "guests_count" and not (_asks_gazebo_options(text) or _capacity_guest_patch(text)):
        return None
    updated = merge_form_data(form_data, guest_patch)
    if not updated.get("last_available_gazebo_variants"):
        return None
    reply = _gazebo_selection_text(updated)
    suitable_titles = _suitable_available_gazebo_titles(updated)
    if suitable_titles:
        return reply, updated, "service_variant", "service_variant"
    return reply, updated, "awaiting_new_date" if updated.get("date") else "date", "date"


def _impl_explicit_numeric_dates(text: str, now: datetime) -> list[str]:
    return _explicit_numeric_dates_impl(text, now)


def _impl_numeric_date_time_patch(text: str, now: datetime) -> dict[str, Any]:
    return _numeric_date_time_patch_impl(text, now)


def _impl_multi_gazebo_booking_patch(text: str, now: datetime) -> dict[str, Any]:
    _refresh_handler_globals()
    return _multi_gazebo_booking_patch_impl(
        text,
        now,
        service_type_patch=_service_type_patch,
        explicit_numeric_dates=_explicit_numeric_dates,
    )


def _impl_multi_gazebo_booking_reply(text: str, form_data: dict[str, Any]) -> str:
    return _multi_gazebo_booking_reply_impl(text, form_data)


def _impl_late_addon_price_update(
    form_data: dict[str, Any],
    text: str,
) -> tuple[str, str, str | None, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
    if not form_data.get("service_type") or not _looks_like_price_question_text(text):
        return None
    upsell_patch = _upsell_items_patch(text)
    selected_items = upsell_patch.get("upsell_items") or []
    if not selected_items or selected_items == ["не нужны"]:
        return None
    price_reply = _addon_price_reply(" ".join(selected_items)) or _addon_price_reply(text)
    if not price_reply:
        return None
    merged_items = _merge_selected_upsells(form_data.get("upsell_items") or [], selected_items)
    updated_form_data = merge_form_data(
        form_data,
        {
            **upsell_patch,
            "upsell_items": merged_items,
        },
    )
    selected_text = ", ".join(selected_items)
    prefix = f"{price_reply}\n\n{selected_text.capitalize()} добавила в допы ✅"
    next_key, question = next_question(updated_form_data)
    if next_key is None:
        return (
            f"{prefix}\n\n{_confirmation_reply_text(updated_form_data)}",
            "awaiting_confirmation",
            "awaiting_confirmation",
            "confirmation",
            updated_form_data,
        )
    return (
        f"{prefix}\n\n{question or _fallback_question_for_step(next_key, updated_form_data) or ''}".strip(),
        "waiting_user",
        next_key,
        next_key,
        updated_form_data,
    )


def _impl_pending_additional_booking_reply(conversation: dict[str, Any], text: str, now: datetime) -> tuple[str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
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


def _impl_parallel_booking_question_reply(conversation: dict[str, Any], text: str) -> tuple[str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
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


def _impl_continues_current_draft_service_switch(conversation: dict[str, Any], text: str) -> bool:
    _refresh_handler_globals()
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
    if "хочу" in normalized or "нужн" in normalized or re.search(r"\b(?:я\s+)?же\s+хочу\b", normalized):
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


def _impl_ai_should_start_fresh_booking(
    conversation: dict[str, Any],
    ai_result: Any,
    patch: dict[str, Any],
    text: str,
) -> bool:
    _refresh_handler_globals()
    if _continues_current_draft_service_switch(conversation, text):
        return False
    intent = str(getattr(ai_result, "intent", "") or "")
    action = str(getattr(ai_result, "action", "") or "")
    requested_service = _normalize_service_aliases(
        {"service_type": patch.get("service_type")}
    ).get("service_type") or _context_service_for_generic_new_booking(conversation, text)
    starts_new = _starts_new_booking_request(text) or _generic_new_booking_request(text)
    return _ai_should_start_fresh_booking_decision(
        conversation,
        requested_service=requested_service,
        starts_new_request=starts_new,
        wants_additional_booking=_wants_additional_booking(text),
        is_existing_booking_command=(
            _wants_cancel_booking(text) or _wants_reschedule(text) or _wants_swap_bookings(text)
        ),
        ai_intent=intent,
        ai_action=action,
    )


def _impl_asks_booking_summary(text: str) -> bool:
    _refresh_handler_globals()
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


def _impl_draft_summary_reply(form_data: dict[str, Any]) -> str | None:
    _refresh_handler_globals()
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


def _impl_draft_summary_if_no_active_booking(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str | None] | None:
    _refresh_handler_globals()
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


def _impl_asks_available_services(text: str) -> bool:
    _refresh_handler_globals()
    normalized = text.lower().replace("ё", "е")
    if "перенос" in normalized or "перенести" in normalized:
        return False
    return (
        "что" in normalized
        and any(marker in normalized for marker in ("еще", "ещё", "помимо", "кроме", "другое", "другие"))
        and any(marker in normalized for marker in ("забронировать", "забронить", "есть", "можно"))
    ) or any(
        marker in normalized
        for marker in (
            "какие услуги",
            "какие варианты",
            "что можно забронировать",
            "что забронировать",
            "что можно",
            "че можно",
            "чё можно",
            "че у вас можно",
            "чё у вас можно",
            "что у вас есть",
            "какие есть варианты",
        )
    )


def _impl_asks_specific_service_exists(text: str) -> bool:
    _refresh_handler_globals()
    normalized = text.lower().replace("ё", "е")
    if _looks_like_same_date_reference_text(normalized) or _looks_like_same_time_reference_text(normalized):
        return False
    if _has_specific_date_signal(text, _now_local()) or _time_period_patch(text):
        return False
    if any(
        marker in normalized
        for marker in (
            "давайте еще",
            "давайте ещё",
            "давай еще",
            "давай ещё",
            "хочу еще",
            "хочу ещё",
            "нужно еще",
            "нужно ещё",
            "нужна еще",
            "нужна ещё",
            "добав",
            "добв",
        )
    ):
        return False
    return bool(_service_type_patch(normalized)) and (
        any(marker in normalized for marker in ("есть", "бывают", "имеются", "можно"))
        or any(marker in normalized for marker in ("какие", "какой выбор", "какие варианты", "варианты"))
    )


def _impl_available_services_reply(form_data: dict[str, Any] | None = None) -> str:
    _refresh_handler_globals()
    service_type = (form_data or {}).get("service_type")
    if service_type == "gazebo":
        return (
            "Кроме вашей беседки можно отдельной бронью проверить баню, дом, тёплую беседку "
            "или ещё одну беседку.\n\n"
            "Если хотите добавить вторую бронь, напишите услугу и дату, например: "
            "«хочу ещё баню на 30 июня»."
        )
    if service_type == "bathhouse":
        return (
            "Помимо бани можно забронировать беседки, дом, тёплую беседку или формат "
            "«беседка + баня» двумя отдельными бронями.\n\n"
            "Если хотите добавить вторую бронь, напишите услугу и дату, например: "
            "«хочу ещё беседку на 30 июня»."
        )
    if service_type == "house":
        return (
            "Кроме дома можно забронировать беседки, тёплую беседку и баню отдельной бронью.\n\n"
            "Если хотите добавить вторую бронь, напишите услугу и дату."
        )
    return (
        "Можно забронировать: обычные/летние беседки, крытую беседку, тёплую беседку, "
        "баню с бассейном и гостевой дом.\n\n"
        "Какой вариант хотите посмотреть или забронировать?"
    )


def _impl_looks_like_vague_time_answer(text: str) -> bool:
    _refresh_handler_globals()
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


def _impl_wants_abort_current_draft(text: str) -> bool:
    _refresh_handler_globals()
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


def _impl_wants_pause_current_draft(text: str) -> bool:
    _refresh_handler_globals()
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


def _impl_handle_gazebo_browsing_start(
    conn,
    *,
    text: str,
    conversation: dict[str, Any],
    previous_form_data: dict[str, Any],
    history: list[dict[str, Any]],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    _refresh_handler_globals()
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


def _impl_reserved_hold_callbacks() -> _ReservedHoldCallbacks:
    _refresh_handler_globals()
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
        create_hold=_create_hold,
        create_payment_link_for_holds=create_payment_link_for_holds,
        log_payment_link_exception=logger.exception,
    )


def _impl_awaiting_confirmation_callbacks() -> _AwaitingConfirmationCallbacks:
    _refresh_handler_globals()
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


def _impl_new_booking_flow_callbacks() -> _NewBookingFlowCallbacks:
    _refresh_handler_globals()
    return _NewBookingFlowCallbacks(
        new_booking_form_data=_new_booking_form_data,
        wants_new_form_after_stale=_wants_new_form_after_stale,
        service_type_patch=_service_type_patch,
        asks_for_free_slots=_asks_for_free_slots,
        stale_message_starts_new_context=_stale_message_starts_new_context,
        wants_continue_stale_form=_wants_continue_stale_form,
        continue_stale_form_reply=_continue_stale_form_reply,
        should_offer_stale_form_choice=_should_offer_stale_form_choice,
        stale_message_has_new_booking_details=_stale_message_has_new_booking_details,
        stale_form_choice_reply=_stale_form_choice_reply,
        explicit_new_booking_with_details=_explicit_new_booking_with_details,
        fresh_booking_form_data_for_text=_fresh_booking_form_data_for_text,
        should_start_fresh_booking=_should_start_fresh_booking,
        fresh_start_immediate_reply=_fresh_start_immediate_reply,
        ai_should_start_fresh_booking=_ai_should_start_fresh_booking,
        fresh_booking_patch_from_ai=_fresh_booking_patch_from_ai,
        next_question_key=lambda form_data: next_question(form_data)[0],
    )


def _impl_build_reply(ai_reply: str, action: str, form_data: dict[str, Any]) -> tuple[str, str | None]:
    _refresh_handler_globals()
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


def _impl_append_expected_question(reply: str, form_data: dict[str, Any]) -> tuple[str, str | None]:
    _refresh_handler_globals()
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


def _impl_current_gazebo_quality_reply(text: str, form_data: dict[str, Any]) -> str | None:
    _refresh_handler_globals()
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


def _impl_capacity_info_reply(text: str, form_data: dict[str, Any]) -> str | None:
    _refresh_handler_globals()
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
            "если бы нас",
            "нас будет",
            "нас было",
            "человек",
            "гостей",
            "гостя",
        )
    )
    service_type = form_data.get("service_type")
    if (
        service_type == "bathhouse"
        and not has_capacity_signal
        and _last_rejected_guest_count(form_data)
        and _large_group_followup_question(normalized)
    ):
        guests_count = _last_rejected_guest_count(form_data)
        if guests_count and guests_count >= 100:
            return _large_group_manual_reply(guests_count)
    if not has_capacity_signal:
        return None
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
        if guests and int(guests) >= 100:
            return _large_group_manual_reply(int(guests))
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


def _impl_should_append_next_question_after_info(form_data: dict[str, Any], next_key: str | None) -> bool:
    _refresh_handler_globals()
    return _should_append_next_question_after_info_impl(form_data, next_key)
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


def _impl_handle_post_booking_message(
    conn,
    conversation: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
    if conversation.get("current_step") != "reserved" and conversation.get("status") not in {"reserved", "payment_paid"}:
        return None

    form_data = conversation.get("form_data") or {}
    try:
        payments = payments_repo.list_for_conversation(conn, conversation_id=conversation["id"])
        if payments:
            has_local_paid_payment = any(payment.get("status") == "paid" for payment in payments)
            if not has_local_paid_payment:
                sync_payment_statuses(conn)
            create_missing_yclients_records(conn)
            if not has_local_paid_payment:
                payments = payments_repo.list_for_conversation(conn, conversation_id=conversation["id"])
        if any(payment.get("status") == "paid" for payment in payments):
            conversation = {**conversation, "status": "payment_paid"}
    except Exception:
        logger.exception("Post-booking payment refresh failed conversation_id=%s", conversation["id"])

    status = "payment_paid" if conversation.get("status") == "payment_paid" else "reserved"

    if _asks_available_services(text):
        return (
            _available_services_reply_for_active_bookings(conn, conversation, form_data, now),
            status,
            "reserved",
            "payment_status",
            form_data,
        )

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

    if _wants_fake_payment_simulation(text):
        return (
            "Я не могу отметить оплату «будто бы» вручную. "
            "Бронь закрепляется только когда реальный платёж отразится в ЮKassa.\n\n"
            "Если ссылка ещё активна, оплатите по ней — после оплаты я пришлю подтверждение брони ✅",
            status,
            "reserved",
            "payment_status",
            form_data,
        )

    if _mentions_payment_status(text):
        reply, payment_status = _payment_status_reply(conn, conversation, form_data)
        return reply, payment_status, "reserved", "payment_status", form_data

    if _asks_for_free_slots(text):
        lookup_form = form_data | _service_type_patch(text)
        if lookup_form.get("service_type") != "gazebo":
            lookup_form["service_variant"] = None
        reply = _next_free_dates_reply(conn, conversation, lookup_form, now)
        if reply:
            return reply, status, "reserved", "payment_status", form_data

    if _asks_specific_service_exists(text):
        service_type = (_service_type_patch(text) or {}).get("service_type")
        updated = dict(form_data)
        if service_type in load_services_map():
            updated["last_discussed_service_type"] = service_type
        return _specific_service_exists_reply(text), status, "reserved", "payment_status", updated

    if _asks_how_to_book_last_discussed_service(text, form_data):
        service_type = form_data.get("last_discussed_service_type")
        return _specific_service_exists_reply_for_type(str(service_type)), status, "reserved", "payment_status", form_data

    common_info_reply = _policy_or_common_info_reply(text)
    if common_info_reply and _looks_like_info_question(text, now=now):
        return common_info_reply, status, "reserved", "payment_status", form_data

    if _looks_like_weather_question(text):
        return (
            "По погоде точно не подскажу. Лучше проверить прогноз в погодном приложении ближе к дате отдыха.",
            status,
            "reserved",
            "payment_status",
            form_data,
        )

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
            else _specific_service_exists_reply_for_type(str(form_data.get("last_discussed_service_type")))
            if _asks_how_to_book_last_discussed_service(text, form_data)
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
        if _wants_fake_payment_simulation(text):
            return (
                "Я не могу отметить оплату «будто бы» вручную. "
                "Бронь закрепляется только когда реальный платёж отразится в ЮKassa.",
                status,
                "reserved",
                "payment_status",
                form_data,
            )
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
        return summary, status, "reserved", "payment_status", form_data
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


def _impl_handle_booking_reminder_response(
    conn,
    conversation: dict[str, Any],
    user: dict[str, Any],
    text: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
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


def _impl_reply_to_info_during_cancel_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
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


def _impl_reply_to_info_during_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    history: list[dict[str, Any]],
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
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


def _impl_cancel_flow_callbacks() -> _CancelFlowCallbacks:
    _refresh_handler_globals()
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
        record_refund_required=_record_refund_required,
    )


def _impl_record_refund_required(conn, booking: dict[str, Any], now: datetime) -> None:
    _refresh_handler_globals()
    booking_id = int(booking["id"])
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM system_logs
            WHERE event_type = 'refund_required'
              AND payload->>'booking_id' = %s
            LIMIT 1
            """,
            (str(booking_id),),
        )
        if cur.fetchone():
            return
    system_logs_repo.create(
        conn,
        level="warning",
        event_type="refund_required",
        message="paid booking cancelled inside refundable window",
        conversation_id=booking.get("conversation_id"),
        payload={
            "booking_id": booking_id,
            "user_id": booking.get("user_id"),
            "client_name": booking.get("client_name"),
            "phone": booking.get("phone"),
            "booking": _booking_line_short(booking),
            "payment_status": booking.get("payment_status"),
            "cancelled_at": now.isoformat() if hasattr(now, "isoformat") else str(now),
        },
    )


def _impl_same_booking_reference_patch(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    _refresh_handler_globals()
    callbacks = _ReferencePatchCallbacks(
        means_same_date=_means_same_date,
        means_same_time=_means_same_time,
        referenced_service_type_for_same_time=_referenced_service_type_for_same_time,
        looks_like_prior_booking_reference_text=_looks_like_prior_booking_reference_text,
        active_user_bookings=_active_user_bookings,
        hours_from_minutes=_hours_from_minutes,
    )
    return _same_booking_reference_patch_impl(
        conn,
        conversation,
        form_data,
        text,
        now,
        callbacks,
    )


def _impl_start_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    status: str,
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    _refresh_handler_globals()
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


def _impl_handle_reschedule_flow(
    conn,
    conversation: dict[str, Any],
    text: str,
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str, str | None, dict[str, Any]]:
    _refresh_handler_globals()
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


def _impl_reschedule_gazebo_change_options_reply(
    conn,
    conversation: dict[str, Any],
    booking: dict[str, Any],
    form_data: dict[str, Any],
    flow: dict[str, Any],
    text: str,
    now: datetime,
) -> tuple[str, dict[str, Any]] | None:
    _refresh_handler_globals()
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


def _impl_reschedule_execution_callbacks() -> _RescheduleExecutionCallbacks:
    _refresh_handler_globals()
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


def _impl_ai_process_reply(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    required_meaning: str,
) -> str:
    _refresh_handler_globals()
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


def _impl_execute_availability_check(
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
    _refresh_handler_globals()
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


def _impl_direct_free_dates_lookup(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
    *,
    force_new: bool = False,
) -> tuple[str, str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
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


def _impl_free_dates_after_unavailable_route(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
):
    _refresh_handler_globals()
    callbacks = _FreeDatesAfterUnavailableCallbacks(
        asks_for_free_slots=_asks_for_free_slots,
        wants_new_form_after_stale=_wants_new_form_after_stale,
        has_specific_date_signal=_has_specific_date_signal,
        next_free_dates_reply=_next_free_dates_reply,
    )
    return _free_dates_after_unavailable_route_impl(
        conn,
        conversation,
        text,
        now,
        callbacks,
    )


def _impl_unavailable_alternatives_route(
    conn,
    form_data: dict[str, Any],
    text: str,
    now: datetime,
):
    _refresh_handler_globals()
    callbacks = _UnavailableAlternativesCallbacks(
        looks_like_event_context_for_alternatives=_looks_like_event_context_for_alternatives,
        alternative_services_for_unavailable_date=_alternative_services_for_unavailable_date,
        join_preferences=_join_preferences,
    )
    return _unavailable_alternatives_route_impl(
        conn,
        form_data,
        text,
        now,
        callbacks,
    )


def _impl_same_unavailable_date_route(
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    *,
    changed_fields: set[str],
    ai_intent: Any,
    history: list[dict[str, Any]],
):
    _refresh_handler_globals()
    callbacks = _SameUnavailableDateCallbacks(
        asks_for_free_slots=_asks_for_free_slots,
        same_unavailable_date_reply=_same_unavailable_date_reply,
        clear_active_slot_keep_last=_clear_active_slot_keep_last,
        ai_process_reply=_ai_process_reply,
    )
    return _same_unavailable_date_route_impl(
        conversation,
        form_data,
        text,
        changed_fields=changed_fields,
        ai_intent=ai_intent,
        history=history,
        callbacks=callbacks,
    )


def _impl_contextual_upsell_accept_patch(text: str, history: list[dict[str, Any]]) -> dict[str, list[str]]:
    _refresh_handler_globals()
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


def _impl_is_likely_form_answer(
    text: str,
    expected_key: str | None,
    now: datetime,
) -> bool:
    _refresh_handler_globals()
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
            "не",
            "no",
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


def _impl_reply_already_asks(reply: str, next_key: str | None, question: str | None) -> bool:
    _refresh_handler_globals()
    return _reply_already_asks_impl(reply, next_key, question)
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


def _impl_looks_like_info_question(
    text: str,
    *,
    expected_key: str | None = None,
    now: datetime | None = None,
) -> bool:
    _refresh_handler_globals()
    return _looks_like_info_question_impl(
        text,
        expected_key=expected_key,
        now=now,
        callbacks=_info_question_callbacks(),
    )
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


def _impl_answer_info_during_form(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    ai_result: Any,
) -> tuple[str, str | None]:
    _refresh_handler_globals()
    return _answer_info_during_form_impl(
        text=text,
        form_data=form_data,
        history=history,
        ai_result=ai_result,
        callbacks=_info_flow_callbacks(),
    )
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
    elif getattr(ai_result, "intent", "") == "price_question":
        reply = _price_reply_if_known("сколько стоит", form_data)
        if not reply:
            reply = _price_reply_if_known(text, form_data)
        if not reply:
            reply = _ai_process_reply(
                text=text,
                form_data=form_data,
                history=history,
                required_meaning=(
                    "Клиент спрашивает цену. Ответь только по базе знаний и не выдумывай сумму, "
                    "если точной цены нет."
                ),
            )
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


def _impl_gazebo_capacity_mismatch_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
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


def _impl_gazebo_capacity_change_request(
    conn,
    conversation: dict[str, Any],
    text: str,
    now: datetime,
) -> tuple[str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
    form_data = conversation.get("form_data") or {}
    if form_data.get("service_type") != "gazebo" or not form_data.get("service_variant"):
        return None
    normalized = text.lower().replace("ё", "е")
    if not (
        "бесед" in normalized
        or _service_variant_patch(text, allow_bare_ordinal=True)
        or any(marker in normalized for marker in ("не подойд", "не подойдет", "не подходит", "тесн", "маленьк"))
    ):
        return None
    if not any(
        marker in normalized
        for marker in (
            "замен",
            "поменя",
            "измен",
            "не подойд",
            "не подойдет",
            "не подходит",
            "тесн",
            "маленьк",
            "мала",
            "не влез",
            "не вмест",
        )
    ):
        return None
    guests_patch = (
        _capacity_guest_patch(text)
        or _guests_count_patch(text, "guests_count")
        or _expected_guest_count_patch(text)
    )
    if not guests_patch.get("guests_count"):
        return None

    updated = merge_form_data(form_data, guests_patch)
    updated["service_type"] = "gazebo"

    mismatch = _capacity_mismatch_reply(conn, conversation, updated, now)
    if mismatch:
        return mismatch

    updated["service_variant"] = None
    updated.pop("single_available_gazebo_variant_auto", None)
    updated.pop("last_suggested_free_dates", None)
    if not updated.get("date"):
        current_title = form_data.get("service_variant") or "текущую беседку"
        reply = (
            f"Поняла, {current_title} заменим и подберём вариант под {updated.get('guests_count')} гостей.\n\n"
            "Напишите дату отдыха — проверю свободные беседки по журналу и предложу только те, которые подходят по вместимости."
        )
        return reply, "date", "date", updated

    availability = check_availability(conn, form_data={**updated, "service_variant": None}, now=now)
    updated = _remember_available_gazebo_variants(updated, availability.slots)
    reply = _gazebo_selection_text(updated)
    suitable_titles = _suitable_available_gazebo_titles(updated)
    if suitable_titles:
        return reply, "service_variant", "service_variant", updated

    updated["last_unavailable"] = {
        "service_type": "gazebo",
        "date": updated.get("date"),
        "time": updated.get("time"),
        "duration": updated.get("duration"),
        "guests_count": updated.get("guests_count"),
    }
    alternatives = _next_free_dates_reply(conn, conversation, updated, now)
    if alternatives:
        reply = f"{reply}\n\n{alternatives}"
        return reply, "awaiting_new_date", "date", updated
    return (
        f"{reply}\n\nЕсли ни один вариант не подходит, передам запрос администратору для ручного подбора.",
        "service_variant",
        "service_variant",
        updated,
    )


def _impl_bathhouse_capacity_mismatch_reply(
    conn,
    conversation: dict[str, Any],
    form_data: dict[str, Any],
    now: datetime,
) -> tuple[str, str, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
    if form_data.get("service_type") != "bathhouse" or not form_data.get("guests_count"):
        return None
    try:
        guests = int(form_data["guests_count"])
    except (TypeError, ValueError):
        return None
    max_guests = 15
    if guests <= max_guests:
        return None

    updated = dict(form_data)
    updated["guests_count"] = None
    updated["last_rejected_guest_count"] = guests
    updated["last_capacity_rejection"] = {
        "service_type": "bathhouse",
        "guests_count": guests,
        "capacity_max": max_guests,
        "reason": "capacity",
    }
    lines = [
        f"Для бани {guests} гостей — слишком большая компания.",
        f"Баню автоматически оформляю до {max_guests} человек.",
    ]

    lines.append("")
    if guests >= 100:
        lines.append(
            "Для такого количества стандартного авто-варианта нет; крупнейшие обычные варианты сильно меньше. "
            "Такой запрос лучше вручную обсудить с администратором."
        )
        return "\n".join(lines), "service_type", "service_type", updated

    lines.append(
        "Для такой компании можно смотреть стандартные объекты побольше: "
        "Беседку №1 до 50 человек или тёплую беседку до 30 человек, если проходит по вместимости. "
        "Напишите, что выбираем, и дату — проверю свободность."
    )
    return "\n".join(lines), "service_type", "service_type", updated


def _impl_apply_contextual_day_number_patch(
    patch: dict[str, Any],
    form_data: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    _refresh_handler_globals()
    if not patch.get("date") or _has_explicit_month_name(text):
        return patch
    day = _contextual_day_number(text)
    if day is None:
        return patch
    base = _context_date_for_day_number(form_data)
    if not base:
        return patch
    try:
        candidate = base.replace(day=day)
    except ValueError:
        return patch
    if candidate < now.date():
        try:
            candidate = candidate.replace(year=candidate.year + 1)
        except ValueError:
            return patch
    if candidate.isoformat() == patch.get("date"):
        return patch
    updated = dict(patch)
    updated["date"] = candidate.isoformat()
    return updated


def _impl_current_step_patch(text: str, expected_key: str | None, now: datetime | None = None) -> dict[str, Any]:
    _refresh_handler_globals()
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


def _impl_expected_guest_count_patch(text: str) -> dict[str, int]:
    _refresh_handler_globals()
    explicit = _guests_count_patch(text, "guests_count")
    if explicit:
        return explicit
    normalized = text.lower().replace("ё", "е").strip()
    if _explicit_gazebo_variant_reference(text):
        return {}
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
    if guests <= 0 or guests > 999:
        return {}
    return {"guests_count": guests}


def _impl_expected_step_detected_patch(
    detected_patch: dict[str, Any],
    text: str,
    expected_key: str | None,
    now: datetime,
) -> dict[str, Any]:
    _refresh_handler_globals()
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
        if detected_patch.get("duration") and (_has_explicit_duration_signal(text) or _has_explicit_time_period(text)):
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


def _impl_date_numbers_from_context(text: str, patch: dict[str, Any], now: datetime) -> set[int]:
    _refresh_handler_globals()
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


def _impl_ai_guest_count_conflicts_with_date_context(
    text: str,
    patch: dict[str, Any],
    deterministic_patch: dict[str, Any],
    expected_key: str | None,
    now: datetime,
) -> bool:
    _refresh_handler_globals()
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


def _impl_ai_guest_count_conflicts_with_gazebo_variant(
    text: str,
    patch: dict[str, Any],
    deterministic_patch: dict[str, Any],
    expected_key: str | None,
) -> bool:
    _refresh_handler_globals()
    if "guests_count" not in patch:
        return False
    if "guests_count" in deterministic_patch:
        return False
    if expected_key == "guests_count" and not _explicit_gazebo_variant_reference(text):
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


def _impl_ai_first_patch(
    *,
    ai_result: Any,
    detected_patch: dict[str, Any],
    text: str,
    expected_key: str | None,
    now: datetime,
) -> dict[str, Any]:
    _refresh_handler_globals()
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
        if capacity_patch and expected_key == "guests_count":
            return capacity_patch
        return {}
    return ai_patch | detected_patch


def _impl_filter_new_booking_patch_to_current_message(
    patch: dict[str, Any],
    text: str,
    now: datetime,
) -> dict[str, Any]:
    _refresh_handler_globals()
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


def _impl_restore_draft_context_after_service_switch(
    form_data: dict[str, Any],
    previous_form_data: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    _refresh_handler_globals()
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


def _impl_fast_entry_reply(conn, text: str, form_data: dict[str, Any], now: datetime) -> tuple[str, str, str | None, str | None, dict[str, Any]] | None:
    _refresh_handler_globals()
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
        bathhouse_period = _bathhouse_period_options_reply(updated)
        if bathhouse_period:
            reply, next_key = bathhouse_period
            return (
                reply,
                "waiting_user",
                next_key,
                next_key,
                updated,
            )
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


def _impl_handle_incoming(message: IncomingMessage) -> str:
    _refresh_handler_globals()
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

        def commit_reply(
            reply: str,
            *,
            status: str,
            current_step: str | None,
            next_step: str | None,
            form_data: dict[str, Any],
            intent: Any = _INTENT_UNSET,
        ) -> str:
            return _commit_assistant_response(
                conn,
                conversation,
                now,
                reply,
                status=status,
                intent=intent,
                current_step=current_step,
                next_step=next_step,
                form_data=form_data,
            )

        def commit_route_result(route_result) -> str:
            return commit_reply(
                route_result.reply,
                status=route_result.status,
                intent=route_result.intent if route_result.intent is not None else _INTENT_UNSET,
                current_step=route_result.current_step,
                next_step=route_result.next_step,
                form_data=route_result.form_data,
            )

        preflight_capacity_change = _impl_gazebo_capacity_change_request(
            conn,
            conversation,
            message.text,
            now,
        )
        if preflight_capacity_change:
            reply, current_step, next_key, form_data = preflight_capacity_change
            return commit_reply(
                reply,
                status="waiting_user",
                intent="object_selection_help",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )

        semantic_ai_result: Any | None = None
        semantic_ai_error: AIProviderUnavailable | None = None
        if _should_run_semantic_preflight(conversation, conv_created=conv_created):
            try:
                semantic_ai_result = _semantic_ai_pass(
                    conn,
                    conversation=conversation,
                    text=message.text,
                    history=history,
                    now=now,
                )
            except AIProviderUnavailable as exc:
                semantic_ai_error = exc
                logger.warning("AI semantic preflight unavailable conversation_id=%s", conversation["id"])
                _log_ai_semantic_degraded(
                    conn,
                    conversation_id=conversation["id"],
                    exc=exc,
                    text=message.text,
                    form_data=conversation.get("form_data") or {},
                )

        reminder_response = _handle_booking_reminder_response(conn, conversation, user, message.text, now)
        if reminder_response is not None:
            reply, status, current_step, next_key, form_data = reminder_response
            return commit_reply(
                reply,
                status=status,
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )

        current_form_data = conversation.get("form_data") or {}
        stale_result = _handle_stale_new_booking_flow_impl(
            conversation=conversation,
            text=message.text,
            now=now,
            conv_created=conv_created,
            current_form_data=current_form_data,
            callbacks=_new_booking_flow_callbacks(),
        )
        if stale_result is not None:
            if stale_result.reply is not None:
                return commit_reply(
                    stale_result.reply,
                    status=stale_result.status,
                    intent=stale_result.intent if stale_result.intent else _INTENT_UNSET,
                    current_step=stale_result.current_step,
                    next_step=stale_result.next_step,
                    form_data=stale_result.form_data,
                )
            conversation = {
                **conversation,
                "form_data": stale_result.form_data,
                "status": stale_result.status,
                "current_step": stale_result.current_step,
                "next_step": stale_result.next_step,
            }
            if stale_result.persist_context:
                conversations_repo.update_after_message(
                    conn,
                    conversation["id"],
                    now,
                    status=stale_result.status,
                    current_step=stale_result.current_step,
                    next_step=stale_result.next_step,
                    form_data=stale_result.form_data,
                )
            current_form_data = stale_result.form_data

        explicit_photo_reply = _explicit_photo_reply(message.text, conversation.get("form_data") or {})
        if explicit_photo_reply:
            return commit_reply(
                explicit_photo_reply,
                status=conversation.get("status") or "waiting_user",
                intent=conversation.get("intent") or "company_info",
                current_step=conversation.get("current_step"),
                next_step=conversation.get("next_step"),
                form_data=conversation.get("form_data") or {},
            )

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
                return commit_reply(
                    reply,
                    status=status,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )

        if _handoff_active(user, now) and _is_waitlist_decline(message.text):
            waitlist_repo.close_for_user(conn, user_id=int(user["id"]))
            users_repo.clear_handoff(conn, user_id=int(user["id"]))
            reply = "Поняла, запрос на уведомление сняла ✅\n\nЕсли снова понадобится проверить свободные даты, просто напишите услугу и дату."
            return commit_reply(
                reply,
                status="payment_paid" if conversation.get("status") == "payment_paid" else "waiting_user",
                current_step="reserved" if conversation.get("status") == "payment_paid" else conversation.get("current_step"),
                next_step="payment_status" if conversation.get("status") == "payment_paid" else conversation.get("next_step"),
                form_data=conversation.get("form_data") or {},
            )

        if _handoff_active(user, now):
            reply = _handoff_reply()
            return commit_reply(
                reply,
                status="handoff",
                current_step="handoff",
                next_step="handoff",
                form_data=conversation.get("form_data") or {},
            )

        if _looks_like_handoff_needed(message.text):
            _start_user_handoff(
                conn,
                user=user,
                conversation_id=conversation["id"],
                text=message.text,
                now=now,
            )
            reply = _handoff_reply()
            return commit_reply(
                reply,
                status="handoff",
                current_step="handoff",
                next_step="handoff",
                form_data=conversation.get("form_data") or {},
            )

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
                return commit_reply(
                    reply,
                    status="waiting_user",
                    intent=conversation.get("intent") or "booking_request",
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
            if _confirmation_no(message.text):
                form_data = dict(form_data_snapshot)
                form_data.pop("pending_date_confirmation", None)
                reply = "Хорошо, напишите нужную дату."
                return commit_reply(
                    reply,
                    status="waiting_user",
                    current_step="date",
                    next_step="date",
                    form_data=form_data,
                )
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
            return commit_reply(
                weekday_confirmation,
                status="waiting_user",
                current_step="date",
                next_step="date",
                form_data=form_data,
            )

        if conversation.get("current_step") == "awaiting_confirmation" and _asks_booking_summary(message.text):
            form_data = conversation.get("form_data") or {}
            reply = _draft_summary_reply(form_data) or _confirmation_reply_text(form_data)
            return commit_reply(
                reply,
                status="awaiting_confirmation",
                intent="draft_summary",
                current_step="awaiting_confirmation",
                next_step="confirmation",
                form_data=form_data,
            )

        if (
            conversation.get("current_step") == "awaiting_confirmation"
            and (_wants_cancel_booking(message.text) or _wants_abort_confirmation_draft(message.text))
            and not _looks_like_info_question(message.text, now=now)
        ):
            reply, form_data = _abort_current_draft(conversation.get("form_data") or {})
            return commit_reply(
                reply,
                status="waiting_user",
                intent="booking_cancelled",
                current_step="service_type",
                next_step="service_type",
                form_data=form_data,
            )

        hold_command = _handle_reserved_hold_command(conn, conversation, message.text, now, history)
        if hold_command is not None:
            reply, status, current_step, next_key, form_data = hold_command
            return commit_reply(
                reply,
                status=status,
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )

        current_flow_form = conversation.get("form_data") or {}
        has_change_flow = any(
            current_flow_form.get(key)
            for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow")
        )
        parallel_reply = _parallel_booking_question_reply(conversation, message.text)
        if parallel_reply is not None and not has_change_flow:
            reply, current_step, next_key, form_data = parallel_reply
            return commit_reply(
                reply,
                status="waiting_user",
                intent="multi_booking_sequence",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )

        pending_reply = _pending_additional_booking_reply(conversation, message.text, now)
        if pending_reply is not None and not has_change_flow:
            reply, current_step, next_key, form_data = pending_reply
            return commit_reply(
                reply,
                status="waiting_user",
                intent="multi_booking_sequence",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )

        multi_patch = _multi_gazebo_booking_patch(message.text, now)
        if multi_patch and not has_change_flow and conversation.get("current_step") not in {"reserved", "payment_status", "awaiting_confirmation"}:
            form_data = _new_booking_form_data(current_flow_form)
            form_data.update(multi_patch)
            reply = _multi_gazebo_booking_reply(message.text, form_data)
            current_step = "time" if form_data.get("date") else "date"
            next_key = current_step
            return commit_reply(
                reply,
                status="waiting_user",
                intent="multi_booking_sequence",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
        )

        started_new_booking = False
        explicit_new_booking_before_post = (
            not has_change_flow
            and _explicit_new_booking_with_details(message.text)
            and any(
                current_flow_form.get(key)
                for key in ("service_type", "date", "time", "duration", "guests_count", "event_format", "upsell_items")
            )
        )
        can_start_fresh_from_current_state = False
        if not has_change_flow and not explicit_new_booking_before_post:
            can_start_fresh_from_current_state = (
                (
                    conversation.get("current_step") != "awaiting_confirmation"
                    and conversation.get("status") != "awaiting_confirmation"
                )
                or _has_user_bookings(conn, conversation, current_flow_form, now)
            )
        fresh_result = _handle_fresh_start_before_post_booking_impl(
            conversation=conversation,
            text=message.text,
            now=now,
            current_flow_form=current_flow_form,
            has_change_flow=has_change_flow,
            can_start_from_current_state=can_start_fresh_from_current_state,
            callbacks=_new_booking_flow_callbacks(),
        )
        if fresh_result is not None:
            conversation = {
                **conversation,
                "form_data": fresh_result.form_data,
                "current_step": fresh_result.current_step,
                "next_step": fresh_result.next_step,
                "status": fresh_result.status,
            }
            started_new_booking = fresh_result.started_new_booking
            if fresh_result.reply is not None:
                return commit_reply(
                    fresh_result.reply,
                    status=fresh_result.status,
                    intent=fresh_result.intent if fresh_result.intent else _INTENT_UNSET,
                    current_step=fresh_result.current_step,
                    next_step=fresh_result.next_step,
                    form_data=fresh_result.form_data,
                )

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
                return commit_reply(
                    reply,
                    status=status,
                    intent="post_booking",
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )

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
                return commit_reply(
                    reply,
                    status=status,
                    intent="post_booking",
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )

        if _wants_abort_current_draft(message.text) and _current_draft_can_be_aborted(conversation):
            reply, form_data = _abort_current_draft(conversation.get("form_data") or {})
            return commit_reply(
                reply,
                status="waiting_user",
                intent="booking_cancelled",
                current_step="service_type",
                next_step="service_type",
                form_data=form_data,
            )

        if _wants_pause_current_draft(message.text) and _current_draft_can_be_aborted(conversation):
            form_data = conversation.get("form_data") or {}
            next_key = next_question(form_data)[0] or conversation.get("next_step") or conversation.get("current_step")
            reply = _pause_current_draft_reply(form_data)
            return commit_reply(
                reply,
                status="waiting_user",
                intent="booking_paused",
                current_step=next_key,
                next_step=next_key,
                form_data=form_data,
            )

        if conversation.get("intent") == "booking_paused" and _is_post_pause_ack(message.text):
            form_data = conversation.get("form_data") or {}
            reply = "Отлично, буду ждать. Когда будете готовы — просто напишите, продолжим с этого места ✅"
            return commit_reply(
                reply,
                status="waiting_user",
                intent="booking_paused",
                current_step=conversation.get("current_step"),
                next_step=conversation.get("next_step"),
                form_data=form_data,
            )

        if conversation.get("current_step") == "awaiting_confirmation":
            late_addon_price = _late_addon_price_update(conversation.get("form_data") or {}, message.text)
            if late_addon_price is not None:
                reply, status, current_step, next_key, form_data = late_addon_price
                return commit_reply(
                    reply,
                    status=status,
                    intent="booking_request",
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )

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
            return commit_reply(
                result.reply,
                status=result.status,
                intent=result.intent if result.intent else _INTENT_UNSET,
                current_step=result.current_step,
                next_step=result.next_step,
                form_data=result.form_data,
            )

        fresh_after_confirmation = _handle_fresh_start_after_confirmation_impl(
            conversation=conversation,
            text=message.text,
            now=now,
            callbacks=_new_booking_flow_callbacks(),
        )
        if fresh_after_confirmation is not None:
            conversation = {
                **conversation,
                "form_data": fresh_after_confirmation.form_data,
                "current_step": fresh_after_confirmation.current_step,
                "next_step": fresh_after_confirmation.next_step,
                "status": fresh_after_confirmation.status,
            }
            started_new_booking = fresh_after_confirmation.started_new_booking
            if fresh_after_confirmation.reply is not None:
                return commit_reply(
                    fresh_after_confirmation.reply,
                    status=fresh_after_confirmation.status,
                    intent=fresh_after_confirmation.intent if fresh_after_confirmation.intent else _INTENT_UNSET,
                    current_step=fresh_after_confirmation.current_step,
                    next_step=fresh_after_confirmation.next_step,
                    form_data=fresh_after_confirmation.form_data,
                )

        if _starts_gazebo_browsing_after_booking(conversation, message.text):
            reply, status, current_step, next_key, form_data = _handle_gazebo_browsing_start(
                conn,
                text=message.text,
                conversation=conversation,
                previous_form_data=conversation.get("form_data") or {},
                history=history,
                now=now,
            )
            return commit_reply(
                reply,
                status=status,
                intent="gazebo_options",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )

        hold_command = _handle_reserved_hold_command(conn, conversation, message.text, now, history)
        if hold_command is not None:
            reply, status, current_step, next_key, form_data = hold_command
            return commit_reply(
                reply,
                status=status,
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )

        free_dates_route = _impl_free_dates_after_unavailable_route(
            conn,
            conversation,
            message.text,
            now,
        )
        if free_dates_route is not None:
            return commit_route_result(free_dates_route)

        current_form_data = conversation.get("form_data") or {}
        gazebo_capacity_change = _impl_gazebo_capacity_change_request(
            conn,
            conversation,
            message.text,
            now,
        )
        if gazebo_capacity_change:
            reply, current_step, next_key, form_data = gazebo_capacity_change
            return commit_reply(
                reply,
                status="waiting_user",
                intent="object_selection_help",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
        large_group_followup = _bathhouse_large_group_followup_reply(message.text, current_form_data)
        if large_group_followup:
            return commit_reply(
                large_group_followup,
                status="waiting_user",
                intent="company_info",
                current_step=conversation.get("current_step") or "service_type",
                next_step=conversation.get("next_step"),
                form_data=current_form_data,
            )
        if (
            current_form_data.get("service_type") == "bathhouse"
            and _looks_like_info_question(
                message.text,
                expected_key=next_question(current_form_data)[0],
                now=now,
            )
            and not any(current_form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow"))
        ):
            deterministic_info = _deterministic_info_reply(message.text, current_form_data)
            if deterministic_info:
                next_key = next_question(current_form_data)[0]
                return commit_reply(
                    deterministic_info,
                    status="waiting_user",
                    intent="company_info",
                    current_step=next_key or conversation.get("current_step") or "service_type",
                    next_step=next_key,
                    form_data=current_form_data,
                )

        direct_free_dates = _direct_free_dates_lookup(
            conn,
            conversation,
            message.text,
            now,
            force_new=_wants_new_form_after_stale(message.text),
        )
        if direct_free_dates is not None:
            reply, status, current_step, next_key, form_data = direct_free_dates
            return commit_reply(
                reply,
                status=status,
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )

        if (
            current_form_data.get("service_type") == "bathhouse"
            and current_form_data.get("date")
            and _wants_time_change_without_value(message.text)
        ):
            form_data = {**current_form_data, "time": None, "duration": None}
            reply, next_key = _bathhouse_period_options_reply(form_data) or (
                "Поняла, поменяем время. Напишите новый период для бани, например: с 18:00 до 01:00.",
                "time",
            )
            return commit_reply(
                reply,
                status="waiting_user",
                intent="change_booking",
                current_step=next_key,
                next_step=next_key,
                form_data=form_data,
            )
        if _asks_booking_summary(message.text) and not _has_user_bookings(conn, conversation, current_form_data, now):
            draft_reply = _draft_summary_reply(current_form_data)
            if draft_reply:
                next_key, _ = next_question(current_form_data)
                return commit_reply(
                    draft_reply,
                    status="waiting_user",
                    intent="draft_summary",
                    current_step=next_key or conversation.get("current_step"),
                    next_step=next_key,
                    form_data=current_form_data,
                )
        unavailable_alternatives_route = _impl_unavailable_alternatives_route(
            conn,
            current_form_data,
            message.text,
            now,
        )
        if unavailable_alternatives_route is not None:
            return commit_route_result(unavailable_alternatives_route)
        expected_key_before = next_question(current_form_data)[0]
        active_step_hint = conversation.get("next_step") or conversation.get("current_step")
        if active_step_hint in {"guests_count", "upsell_items"}:
            expected_key_before = active_step_hint
        current_upsells = current_form_data.get("upsell_items") or []
        if (
            expected_key_before != "upsell_items"
            and (not current_upsells or current_upsells == ["не нужны"])
            and _last_assistant_asked_upsell(history)
        ):
            expected_key_before = "upsell_items"
        if not current_form_data.get("service_type") and _asks_available_services(message.text):
            reply = _available_services_reply(current_form_data)
            return commit_reply(
                reply,
                status="waiting_user",
                intent="available_services",
                current_step="service_type",
                next_step="service_type",
                form_data=current_form_data,
            )
        if expected_key_before != "upsell_items":
            late_addon_price = _late_addon_price_update(current_form_data, message.text)
            if late_addon_price is not None:
                reply, status, current_step, next_key, form_data = late_addon_price
                return commit_reply(
                    reply,
                    status=status,
                    intent="booking_request",
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
        if (
            expected_key_before == "upsell_items"
            and _looks_like_info_question(message.text, expected_key="upsell_items", now=now)
            and not any(current_form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow"))
        ):
            deterministic_info = _deterministic_info_reply(
                message.text,
                current_form_data,
                append_next_question=False,
            )
            if deterministic_info:
                form_data = merge_form_data(current_form_data, _phone_patch(message.text))
                followup = _upsell_info_followup_reply(current_upsells)
                info_lowered = deterministic_info.lower().replace("ё", "е")
                if "что подготовить" in info_lowered or "если хотите добавить что-то еще" in info_lowered:
                    reply = deterministic_info
                else:
                    reply = f"{deterministic_info}\n\n{followup}"
                return commit_reply(
                    reply,
                    status="waiting_user",
                    intent="company_info",
                    current_step="upsell_items",
                    next_step="upsell_items",
                    form_data=form_data,
                )
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
            return commit_reply(
                reply,
                status="waiting_user",
                intent="object_selection_help",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
        gazebo_guest_options = _gazebo_guest_options_shortcut(current_form_data, message.text)
        if gazebo_guest_options:
            reply, form_data, current_step, next_key = gazebo_guest_options
            return commit_reply(
                reply,
                status="waiting_user",
                intent="object_selection_help",
                current_step=current_step,
                next_step=next_key,
                form_data=form_data,
            )
        if expected_key_before == "upsell_items" and _is_upsell_negative(message.text):
            offer_count = int(current_form_data.get("upsell_offer_count") or 0)
            upsell_reply_kind = _classify_upsell_reply(message.text, history, current_form_data)
            should_push_once = upsell_reply_kind == "negative" and (not current_upsells or current_upsells == ["не нужны"])
            if should_push_once:
                form_data = {
                    **current_form_data,
                    "upsell_items": [],
                    "upsell_offer_count": offer_count + 1,
                }
                reply = _upsell_push_reply(form_data)
                return commit_reply(
                    reply,
                    status="waiting_user",
                    current_step="upsell_items",
                    next_step="upsell_items",
                    form_data=form_data,
                )
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
            return commit_reply(
                reply,
                status=status,
                current_step=current_step,
                next_step=next_step,
                form_data=form_data,
            )
        if expected_key_before == "upsell_items":
            upsell_patch = _upsell_items_patch(message.text)
            if not upsell_patch and (not current_upsells or current_upsells == ["не нужны"]):
                upsell_patch = _contextual_upsell_accept_patch(message.text, history)
            selected_items = upsell_patch.get("upsell_items") or []
            if selected_items and selected_items != ["не нужны"]:
                price_reply = _addon_price_reply(message.text) if _looks_like_price_question_text(message.text) else None
                merged_items = _merge_selected_upsells(current_upsells, selected_items)
                form_data = merge_form_data(
                    current_form_data,
                    {
                        **upsell_patch,
                        "upsell_items": merged_items,
                        "upsell_offer_count": int(current_form_data.get("upsell_offer_count") or 0),
                    },
                )
                reply = _upsell_followup_reply(merged_items, price_reply)
                status = "waiting_user"
                current_step = "upsell_items"
                next_step = "upsell_items"
                return commit_reply(
                    reply,
                    status=status,
                    current_step=current_step,
                    next_step=next_step,
                    form_data=form_data,
                )
        early_patch = _deterministic_patch(message.text, now) | _current_step_patch(
            message.text,
            expected_key_before,
            now,
        )
        early_patch = _apply_contextual_day_number_patch(early_patch, current_form_data, message.text, now)
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
            return commit_reply(
                reply,
                status="waiting_user",
                intent="booking_request",
                current_step="time",
                next_step="time",
                form_data=current_form_data,
            )
        if (
            expected_key_before == "time"
            and _looks_like_vague_time_answer(message.text)
            and not _has_valid_time_signal(message.text, early_patch)
            and not _should_route_existing_booking_command(message.text)
        ):
            reply = next_question(current_form_data)[1] or "Во сколько хотите приехать?"
            return commit_reply(
                reply,
                status="waiting_user",
                intent="booking_request",
                current_step="time",
                next_step="time",
                form_data=current_form_data,
            )
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
            return commit_reply(
                reply,
                status="waiting_user",
                intent="booking_request",
                current_step="guests_count",
                next_step="guests_count",
                form_data=form_data,
            )
        if (
            not current_form_data.get("service_type")
            and _looks_like_info_question(message.text, now=now)
            and not _starts_new_booking_request(message.text)
        ):
            deterministic_info = _deterministic_info_reply(message.text, current_form_data)
            if deterministic_info:
                return commit_reply(
                    deterministic_info,
                    status="waiting_user",
                    intent="company_info",
                    current_step="service_type",
                    next_step="service_type",
                    form_data=current_form_data,
                )
        if (
            current_form_data.get("service_type")
            and _asks_specific_service_exists(message.text)
            and not any(current_form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow"))
        ):
            service_type = (_service_type_patch(message.text) or {}).get("service_type")
            updated_form_data = dict(current_form_data)
            if service_type in load_services_map():
                updated_form_data["last_discussed_service_type"] = service_type
            next_key = next_question(current_form_data)[0]
            if current_form_data.get("service_type") == "bathhouse" and service_type == "bathhouse":
                reply, next_key = _append_current_service_question(
                    "Да, баню уже оформляем; это баня с бассейном.",
                    current_form_data,
                )
                return commit_reply(
                    reply,
                    status="waiting_user",
                    intent="company_info",
                    current_step=next_key or conversation.get("current_step") or "service_type",
                    next_step=next_key,
                    form_data=updated_form_data,
                )
            reply = _specific_service_exists_reply(message.text)
            return commit_reply(
                reply,
                status="waiting_user",
                intent="company_info",
                current_step=next_key or conversation.get("current_step") or "service_type",
                next_step=next_key,
                form_data=updated_form_data,
            )
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
                return commit_reply(
                    reply,
                    status="waiting_user",
                    intent="company_info",
                    current_step=next_key or conversation.get("current_step") or "service_type",
                    next_step=next_key,
                    form_data=current_form_data,
                )
        if (
            current_form_data.get("service_type")
            and _looks_like_info_question(message.text, expected_key=expected_key_before, now=now)
            and not any(current_form_data.get(key) for key in ("cancel_flow", "reschedule_flow", "swap_reschedule_flow"))
        ):
            info_patch = dict(early_patch)
            if (
                expected_key_before != "guests_count"
                and current_form_data.get("service_type") == "bathhouse"
                and _bathhouse_guest_limit_exceeded(info_patch)
            ):
                info_patch.pop("guests_count", None)
            info_form_data = merge_form_data(current_form_data, info_patch)
            deterministic_info = _deterministic_info_reply(message.text, info_form_data)
            if deterministic_info:
                if (
                    info_patch.get("service_variant")
                    and not current_form_data.get("service_variant")
                    and str(info_patch.get("service_variant")) not in deterministic_info
                ):
                    deterministic_info = f"{info_patch['service_variant']} отметила ✅\n\n{deterministic_info}"
                next_key = next_question(info_form_data)[0]
                current_step = next_key or conversation.get("current_step") or "service_type"
                return commit_reply(
                    deterministic_info,
                    status="waiting_user",
                    intent="company_info",
                    current_step=current_step,
                    next_step=next_key,
                    form_data=info_form_data,
                )

        deterministic_patch = early_patch
        try:
            if semantic_ai_result is not None:
                ai_result = semantic_ai_result
            elif semantic_ai_error is not None:
                raise semantic_ai_error
            else:
                ai_result = _semantic_ai_pass(
                    conn,
                    conversation=conversation,
                    text=message.text,
                    history=history,
                    now=now,
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
                return commit_reply(
                    reply,
                    status="waiting_user",
                    intent=ai_result.intent,
                    current_step="clarify_period",
                    next_step=next_key,
                    form_data=form_data,
                )

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
            ai_fresh_result = _handle_ai_fresh_start_impl(
                conversation=conversation,
                ai_result=ai_result,
                patch=patch,
                text=message.text,
                now=now,
                started_new_booking=started_new_booking,
                callbacks=_new_booking_flow_callbacks(),
            )
            if ai_fresh_result is not None:
                conversation = {
                    **conversation,
                    "form_data": ai_fresh_result.form_data,
                    "current_step": ai_fresh_result.current_step,
                    "next_step": ai_fresh_result.next_step,
                    "status": ai_fresh_result.status,
                }
                expected_key_before = ai_fresh_result.expected_key_before
                started_new_booking = ai_fresh_result.started_new_booking
                started_new_booking_from_ai = ai_fresh_result.started_new_booking_from_ai
                patch = ai_fresh_result.patch or patch
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
            if not started_new_booking:
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
                return commit_reply(
                    reply,
                    status="waiting_user",
                    intent=ai_result.intent,
                    current_step="service_type",
                    next_step="service_type",
                    form_data=form_data,
                )
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
            capacity_mismatch = _capacity_mismatch_reply(conn, conversation, form_data, now)
            if capacity_mismatch:
                reply, current_step, next_key, form_data = capacity_mismatch
                return commit_reply(
                    reply,
                    status="waiting_user",
                    intent=ai_result.intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
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
                return commit_reply(
                    reply,
                    status="waiting_user",
                    intent=ai_result.intent,
                    current_step="date",
                    next_step=next_key,
                    form_data=form_data,
                )
            if "phone" in changed_fields and form_data.get("phone") and not _valid_phone(form_data.get("phone")):
                form_data["phone"] = None
                reply = "Телефон получился некорректным. Пришлите, пожалуйста, полный номер телефона для бронирования в формате +7XXXXXXXXXX."
                next_key = "phone"
                return commit_reply(
                    reply,
                    status="waiting_user",
                    intent=ai_result.intent,
                    current_step="phone",
                    next_step=next_key,
                    form_data=form_data,
                )
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
                return commit_reply(
                    reply,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
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
                return commit_reply(
                    reply,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
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
                return commit_reply(
                    reply,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
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
                return commit_reply(
                    reply,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
            same_unavailable_route = _impl_same_unavailable_date_route(
                conversation,
                form_data,
                message.text,
                changed_fields=set(changed_fields),
                ai_intent=ai_result.intent,
                history=history,
            )
            if same_unavailable_route is not None:
                return commit_route_result(same_unavailable_route)
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
            capacity_mismatch = _capacity_mismatch_reply(conn, conversation, form_data, now)
            if capacity_mismatch:
                reply, current_step, next_key, form_data = capacity_mismatch
                status = "waiting_user"
                intent = conversation.get("intent")
                return commit_reply(
                    reply,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
                    form_data=form_data,
                )
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
            capacity_mismatch = _capacity_mismatch_reply(conn, conversation, form_data, now)
            if capacity_mismatch:
                reply, current_step, next_key, form_data = capacity_mismatch
                status = "waiting_user"
                intent = conversation.get("intent")
                return commit_reply(
                    reply,
                    status=status,
                    intent=intent,
                    current_step=current_step,
                    next_step=next_key,
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

        reply = _remove_date_question_when_guest_question_exists(_clean_reply(reply))
        reply = _state_text_consistency_reply(
            conn,
            conversation_id=conversation["id"],
            reply=reply,
            form_data=form_data,
        )
        if next_key and current_step in {None, "service_type"} and form_data.get("service_type"):
            current_step = next_key
        _commit_assistant_response(
            conn,
            conversation,
            now,
            reply,
            status=status,
            intent=intent,
            current_step=current_step,
            next_step=next_key,
            form_data=form_data,
            before_update=lambda: _persist_user_profile(conn, user_id=user["id"], form_data=form_data),
        )

    logger.info(
        "Handled message user_id=%s conversation_id=%s new_user=%s new_conv=%s",
        user["id"],
        conversation["id"],
        user_created,
        conv_created,
    )
    return reply
