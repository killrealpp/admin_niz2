"""Live-like context scenarios that verify the bot keeps the thread of a dialog."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import local_regression_suite as reg

from app.ai.ai_orchestrator import AIResponse
from app.core.config import get_settings
from app.db.connection import get_connection
from app.db.repositories import conversations_repo
from app.services import message_handler
from app.services.availability_service import AvailabilityResult


@dataclass
class ContextResult:
    name: str
    ok: bool
    details: str = ""
    transcript: list[tuple[str, str]] = field(default_factory=list)


def _now() -> datetime:
    settings = get_settings()
    return datetime(2026, 5, 28, 15, 30, tzinfo=ZoneInfo(settings.app_timezone))


def _low(text: str) -> str:
    return text.lower().replace("ё", "е")


def _say(suffix: str, text: str, now: datetime, transcript: list[tuple[str, str]], index: int) -> str:
    reply = reg._send(suffix, text, now + timedelta(seconds=index * 10))
    transcript.append((text, reply))
    return reply


def _state(suffix: str) -> dict[str, Any]:
    return reg._latest_state(suffix)


def _set_state(suffix: str, now: datetime, *, status: str, current_step: str, next_step: str | None, form_data: dict[str, Any]) -> None:
    with get_connection() as conn:
        external_id = reg.TEST_PREFIX + suffix
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE u.external_id = %s
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                (external_id,),
            )
            row = cur.fetchone()
        conversations_repo.update_after_message(
            conn,
            row["id"],
            now,
            status=status,
            current_step=current_step,
            next_step=next_step,
            form_data=form_data,
        )


def _draft(suffix: str, now: datetime, *, step: str, **overrides: Any) -> None:
    base = {
        "service_type": "gazebo",
        "service_variant": None,
        "date": None,
        "time": None,
        "duration": None,
        "guests_count": None,
        "event_format": None,
        "phone": "+79990002000",
        "upsell_items": [],
    }
    base.update(overrides)
    form = reg._base_form(**base)
    reg._create_reserved_conversation(suffix, now, form)
    _set_state(suffix, now, status="waiting_user", current_step=step, next_step=step, form_data=form)


def _date_guests_ai(**_: Any) -> AIResponse:
    return AIResponse(
        intent="booking_request",
        action="check_availability",
        current_step="date",
        changed_fields=["date", "guests_count"],
        form_data_patch={"date": "2026-06-30", "guests_count": 20},
    )


def _misclassified_date_only_ai(**_: Any) -> AIResponse:
    return AIResponse(
        intent="company_info",
        action="answer_info",
        current_step="service_variant",
        changed_fields=["date", "guests_count"],
        form_data_patch={"date": "2026-06-30", "guests_count": 30},
        reply_to_user="На 30 июня беседка свободна. Какую беседку выбираете?",
    )


def _semantic_word_guest_ai(**_: Any) -> AIResponse:
    return AIResponse(
        intent="booking_request",
        action="check_availability",
        current_step="date",
        changed_fields=["date", "guests_count"],
        form_data_patch={"date": "2026-06-30", "guests_count": 20},
    )


def _variant_number_poison_ai(**_: Any) -> AIResponse:
    return AIResponse(
        intent="booking_request",
        action="check_availability",
        current_step="date",
        changed_fields=["date", "service_variant", "guests_count"],
        form_data_patch={"date": "2026-05-29", "service_variant": "Беседка №6", "guests_count": 6},
    )


def _patch_common() -> Callable[[], None]:
    original_generate = message_handler.generate_process_reply
    original_missing = message_handler.create_missing_yclients_records
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}

    def restore() -> None:
        message_handler.generate_process_reply = original_generate
        message_handler.create_missing_yclients_records = original_missing

    return restore


def context_date_and_guests_uses_availability(now: datetime) -> ContextResult:
    suffix = "context_date_guests_big"
    transcript: list[tuple[str, str]] = []
    _draft(suffix, now, step="date", phone="+79990002001")
    original_call_ai = message_handler.call_ai
    original_availability = message_handler.check_availability

    def fake_availability(_conn: Any, *, form_data: dict[str, Any], now: datetime) -> AvailabilityResult:
        if form_data.get("date") == "2026-06-30":
            return AvailabilityResult(
                True,
                "ok",
                [
                    "Беседка №1: дата свободна",
                    "Беседка №8: дата свободна",
                    "Беседка №3: дата свободна",
                ],
            )
        return AvailabilityResult(True, "ok", [])

    message_handler.call_ai = _date_guests_ai
    message_handler.check_availability = fake_availability
    try:
        reply = _say(suffix, "на 30 июня нас будет 20", now, transcript, 1)
        state = _state(suffix)
        form = state.get("form_data") or {}
        lowered = _low(reply)
        ok = (
            form.get("date") == "2026-06-30"
            and form.get("guests_count") == 20
            and "30 июня" in lowered
            and "беседка №1" in lowered
            and "беседка №8" in lowered
            and "75 дней" not in lowered
            and "не нашла" not in lowered
            and state.get("current_step") == "service_variant"
        )
        return ContextResult("Дата и гости в одном сообщении идут в availability", ok, f"state={state}", transcript)
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.check_availability = original_availability


def context_small_slots_keep_capacity_and_offer_nearest(now: datetime) -> ContextResult:
    suffix = "context_small_slots"
    transcript: list[tuple[str, str]] = []
    _draft(suffix, now, step="date", phone="+79990002002")
    original_call_ai = message_handler.call_ai
    original_availability = message_handler.check_availability

    def fake_availability(_conn: Any, *, form_data: dict[str, Any], now: datetime) -> AvailabilityResult:
        if form_data.get("date") == "2026-06-30":
            return AvailabilityResult(True, "ok", ["Беседка №2: дата свободна", "Беседка №5: дата свободна"])
        if form_data.get("date") == "2026-06-29":
            return AvailabilityResult(True, "ok", ["Беседка №1: дата свободна", "Беседка №8: дата свободна"])
        return AvailabilityResult(True, "ok", [])

    message_handler.call_ai = _date_guests_ai
    message_handler.check_availability = fake_availability
    try:
        reply = _say(suffix, "на 30 июня нас будет 20", now, transcript, 1)
        state = _state(suffix)
        form = state.get("form_data") or {}
        lowered = _low(reply)
        ok = (
            form.get("guests_count") == 20
            and (form.get("last_unavailable") or {}).get("date") == "2026-06-30"
            and "на 30 июня свободны" in lowered
            and "не подходят" in lowered
            and "29 июня" in lowered
            and "беседка №1" in lowered
            and "75 дней" not in lowered
            and state.get("current_step") == "awaiting_new_date"
        )
        return ContextResult("Маленькие свободные беседки не сбивают контекст 20 гостей", ok, f"state={state}", transcript)
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.check_availability = original_availability


def context_date_only_does_not_become_guests(now: datetime) -> ContextResult:
    suffix = "context_date_only_not_guests"
    transcript: list[tuple[str, str]] = []
    _draft(suffix, now, step="date", phone="+79990002008")
    original_call_ai = message_handler.call_ai
    original_availability = message_handler.check_availability

    def fake_availability(_conn: Any, *, form_data: dict[str, Any], now: datetime) -> AvailabilityResult:
        if form_data.get("guests_count") == 30:
            return AvailabilityResult(True, "ok", ["Беседка №1: дата свободна"])
        return AvailabilityResult(
            True,
            "ok",
            [
                "Беседка №5: дата свободна",
                "Беседка №2: дата свободна",
                "Беседка №4: дата свободна",
                "Беседка №6: дата свободна",
                "Беседка №8: дата свободна",
                "Беседка №3: дата свободна",
                "Крытая беседка: дата свободна",
                "Беседка №1: дата свободна",
            ],
        )

    message_handler.call_ai = _misclassified_date_only_ai
    message_handler.check_availability = fake_availability
    try:
        reply = _say(suffix, "на 30 июня", now, transcript, 1)
        state = _state(suffix)
        form = state.get("form_data") or {}
        lowered = _low(reply)
        ok = (
            form.get("date") == "2026-06-30"
            and not form.get("guests_count")
            and not form.get("service_variant")
            and state.get("current_step") == "guests_count"
            and "30 июня" in lowered
            and "сколько" in lowered
            and "для 30 гостей" not in lowered
            and "беседка №1 рассчитана" not in lowered
        )
        return ContextResult("Чистая дата не превращается в 30 гостей", ok, f"state={state}", transcript)
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.check_availability = original_availability


def context_ai_understands_guest_without_keyword(now: datetime) -> ContextResult:
    suffix = "context_ai_word_guest"
    transcript: list[tuple[str, str]] = []
    _draft(suffix, now, step="date", phone="+79990002011")
    original_call_ai = message_handler.call_ai
    original_availability = message_handler.check_availability
    seen: list[dict[str, Any]] = []

    def fake_availability(_conn: Any, *, form_data: dict[str, Any], now: datetime) -> AvailabilityResult:
        seen.append(dict(form_data))
        return AvailabilityResult(
            True,
            "ok",
            [
                "Беседка №1: дата свободна",
                "Беседка №8: дата свободна",
            ],
        )

    message_handler.call_ai = _semantic_word_guest_ai
    message_handler.check_availability = fake_availability
    try:
        reply = _say(suffix, "на 30 июня двадцать", now, transcript, 1)
        state = _state(suffix)
        form = state.get("form_data") or {}
        lowered = _low(reply)
        ok = (
            seen
            and seen[0].get("guests_count") == 20
            and form.get("date") == "2026-06-30"
            and form.get("guests_count") == 20
            and state.get("current_step") == "service_variant"
            and "беседка №1" in lowered
            and "для 30 гостей" not in lowered
        )
        return ContextResult("AI-смысл без слов-маркеров гостей принимается", ok, f"seen={seen} state={state}", transcript)
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.check_availability = original_availability


def context_gazebo_number_does_not_become_guests(now: datetime) -> ContextResult:
    suffix = "context_variant_number_not_guests"
    transcript: list[tuple[str, str]] = []
    _draft(suffix, now, step="date", phone="+79990002012")
    original_call_ai = message_handler.call_ai
    original_availability = message_handler.check_availability

    def fake_availability(_conn: Any, *, form_data: dict[str, Any], now: datetime) -> AvailabilityResult:
        return AvailabilityResult(True, "ok", ["Беседка №6: дата свободна"])

    message_handler.call_ai = _variant_number_poison_ai
    message_handler.check_availability = fake_availability
    try:
        reply = _say(suffix, "29 мая 6 беседка", now, transcript, 1)
        state = _state(suffix)
        form = state.get("form_data") or {}
        lowered = _low(reply)
        ok = (
            form.get("date") == "2026-05-29"
            and form.get("service_variant") == "Беседка №6"
            and not form.get("guests_count")
            and state.get("current_step") == "guests_count"
            and "сколько" in lowered
            and "для 6 гостей" not in lowered
        )
        return ContextResult("Номер беседки из AI-patch не превращается в гостей", ok, f"state={state}", transcript)
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.check_availability = original_availability


def context_gazebo_choice_question_keeps_date_without_guests(now: datetime) -> ContextResult:
    suffix = "context_choice_keeps_date"
    transcript: list[tuple[str, str]] = []
    _draft(suffix, now, step="guests_count", date="2026-06-30", phone="+79990002009")
    original_call_ai = message_handler.call_ai
    message_handler.call_ai = lambda **_kwargs: AIResponse(
        intent="object_selection_help",
        action="answer_info",
        current_step="guests_count",
        changed_fields=[],
        form_data_patch={},
    )
    try:
        reply = _say(suffix, "а какой у меня выбор есть?", now, transcript, 1)
        state = _state(suffix)
        form = state.get("form_data") or {}
        lowered = _low(reply)
        ok = (
            form.get("date") == "2026-06-30"
            and not form.get("guests_count")
            and state.get("current_step") == "guests_count"
            and "30 июня" in lowered
            and "сколько" in lowered
            and "напишите" not in lowered
        )
        return ContextResult("Вопрос про выбор помнит дату и просит гостей", ok, f"state={state}", transcript)
    finally:
        message_handler.call_ai = original_call_ai


def context_gazebo_guest_count_in_option_question_is_saved(now: datetime) -> ContextResult:
    suffix = "context_guest_options_saved"
    transcript: list[tuple[str, str]] = []
    _draft(suffix, now, step="guests_count", date="2026-07-30", phone="+79990002016")
    state_before = _state(suffix)
    form_before = dict(state_before.get("form_data") or {})
    form_before["last_available_gazebo_variants"] = [
        "Беседка №5",
        "Беседка №2",
        "Беседка №4",
        "Беседка №6",
        "Беседка №8",
        "Беседка №3",
        "Крытая беседка",
        "Беседка №1",
    ]
    _set_state(suffix, now, status="waiting_user", current_step="guests_count", next_step="guests_count", form_data=form_before)
    original_call_ai = message_handler.call_ai
    message_handler.call_ai = lambda **_kwargs: AIResponse(
        intent="object_selection_help",
        action="answer_info",
        current_step="guests_count",
        changed_fields=[],
        form_data_patch={},
    )
    try:
        choice = _say(suffix, "нас будет 30 человек, какая беседка подойдет", now, transcript, 1)
        discount = _say(suffix, "а скидки есть?", now, transcript, 2)
        state = _state(suffix)
        form = state.get("form_data") or {}
        combined = _low(f"{choice}\n{discount}")
        ok = (
            form.get("guests_count") == 30
            and form.get("date") == "2026-07-30"
            and state.get("current_step") == "service_variant"
            and "беседка №1" in combined
            and "для 30 гостей" in combined
            and "скидка 50%" in combined
            and "сколько примерно гостей" not in combined
            and "сколько вас будет" not in combined
        )
        return ContextResult("Гости внутри вопроса про беседку сохраняются и не спрашиваются повторно", ok, f"state={state}", transcript)
    finally:
        message_handler.call_ai = original_call_ai


def context_guest_not_asked_complaint_repairs_state(now: datetime) -> ContextResult:
    suffix = "context_guest_complaint"
    transcript: list[tuple[str, str]] = []
    _draft(
        suffix,
        now,
        step="time",
        service_variant="Беседка №1",
        date="2026-06-30",
        guests_count=30,
        phone="+79990002010",
    )
    state_before = _state(suffix)
    form_before = dict(state_before.get("form_data") or {})
    form_before["last_available_gazebo_variants"] = ["Беседка №1"]
    form_before["single_available_gazebo_variant_auto"] = True
    _set_state(suffix, now, status="waiting_user", current_step="time", next_step="time", form_data=form_before)
    reply = _say(suffix, "а почему первая ты же даже не спросил сколько человек", now, transcript, 1)
    state = _state(suffix)
    form = state.get("form_data") or {}
    lowered = _low(reply)
    ok = (
        not form.get("guests_count")
        and not form.get("service_variant")
        and state.get("current_step") == "guests_count"
        and "вы правы" in lowered
        and "сколько" in lowered
    )
    return ContextResult("Жалоба на неуточненных гостей чинит испорченное состояние", ok, f"state={state}", transcript)


def context_info_question_keeps_selected_object(now: datetime) -> ContextResult:
    suffix = "context_info_keeps_object"
    transcript: list[tuple[str, str]] = []
    _draft(
        suffix,
        now,
        step="time",
        service_variant="Беседка №1",
        date="2026-06-08",
        guests_count=20,
        phone="+79990002003",
    )
    reply = _say(suffix, "а скидка на нее есть?", now, transcript, 1)
    state = _state(suffix)
    form = state.get("form_data") or {}
    lowered = _low(reply)
    ok = (
        form.get("service_variant") == "Беседка №1"
        and form.get("date") == "2026-06-08"
        and form.get("guests_count") == 20
        and state.get("current_step") == "time"
        and "50%" in reply
        and "5 250" in reply
        and "во сколько" in lowered
    )
    return ContextResult("Info-вопрос про скидку держит выбранную беседку и шаг времени", ok, f"state={state}", transcript)


def context_confirmation_summary_then_abort(now: datetime) -> ContextResult:
    suffix = "context_confirm_abort"
    transcript: list[tuple[str, str]] = []
    form = reg._base_form(
        service_type="gazebo",
        service_variant="Беседка №8",
        date="2026-06-08",
        time="18:00",
        duration=5,
        guests_count=20,
        event_format="встреча одноклассников",
        phone="+79990002004",
        upsell_items=["кальян"],
    )
    reg._create_reserved_conversation(suffix, now, form)
    _set_state(
        suffix,
        now,
        status="awaiting_confirmation",
        current_step="awaiting_confirmation",
        next_step="confirmation",
        form_data=form,
    )
    summary = _say(suffix, "а что мы подтверждаем?", now, transcript, 1)
    abort = _say(suffix, "давай отменим эту заявку", now, transcript, 2)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        "черновик" in _low(summary)
        and "Беседка №8" in summary
        and "8 июня" in summary
        and "эту заявку не оформляю" in _low(abort)
        and state.get("current_step") == "service_type"
        and not form.get("service_type")
        and form.get("phone") == "+79990002004"
    )
    return ContextResult("Подтверждение: summary помнит заявку, abort чистит только черновик", ok, f"state={state}", transcript)


def context_two_gazebo_request_starts_sequential_queue(now: datetime) -> ContextResult:
    suffix = "context_two_gazebo_queue"
    transcript: list[tuple[str, str]] = []
    reply = _say(
        suffix,
        "здрасьте мне нужно 2 беседки на 02.06 и 19.06. там есть мангал и угли? хотим мясо пожарить",
        now,
        transcript,
        1,
    )
    state = _state(suffix)
    form = state.get("form_data") or {}
    pending = form.get("pending_additional_bookings") or []
    lowered = _low(reply)
    ok = (
        form.get("service_type") == "gazebo"
        and form.get("date") == "2026-06-02"
        and pending
        and pending[0].get("date") == "2026-06-19"
        and state.get("current_step") == "time"
        and "мангал" in lowered
        and "по очереди" in lowered
        and "2 июня" in lowered
        and "19 июня" in lowered
        and "во сколько" in lowered
    )
    return ContextResult("Две беседки стартуют как последовательная очередь", ok, f"state={state}", transcript)


def context_pending_second_date_does_not_overwrite_first(now: datetime) -> ContextResult:
    suffix = "context_second_date_guard"
    transcript: list[tuple[str, str]] = []
    form = reg._base_form(
        service_type="gazebo",
        service_variant=None,
        date="2026-06-02",
        time="11:00",
        duration=21,
        guests_count=None,
        event_format=None,
        phone="+79990002005",
        upsell_items=[],
    )
    form["pending_additional_bookings"] = [{"service_type": "gazebo", "date": "2026-06-19"}]
    reg._create_reserved_conversation(suffix, now, form)
    _set_state(suffix, now, status="waiting_user", current_step="guests_count", next_step="guests_count", form_data=form)
    reply = _say(suffix, "19.06 на 13", now, transcript, 1)
    state = _state(suffix)
    updated = state.get("form_data") or {}
    lowered = _low(reply)
    ok = (
        updated.get("date") == "2026-06-02"
        and updated.get("time") == "11:00"
        and updated.get("duration") == 21
        and state.get("current_step") == "guests_count"
        and "19 июня" in lowered
        and "следующую отдельную бронь" in lowered
        and "параллельно" in lowered
        and "сколько примерно гостей" in lowered
    )
    return ContextResult("Вторая дата из очереди не перезаписывает первую заявку", ok, f"state={state}", transcript)


def context_weekday_price_question_mentions_discount(now: datetime) -> ContextResult:
    suffix = "context_price_discount"
    transcript: list[tuple[str, str]] = []
    _draft(
        suffix,
        now,
        step="time",
        service_variant="Беседка №1",
        date="2026-06-02",
        guests_count=20,
        phone="+79990002006",
    )
    reply = _say(suffix, "а сколько стоит?", now, transcript, 1)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        form.get("service_type") == "gazebo"
        and form.get("service_variant") == "Беседка №1"
        and form.get("date") == "2026-06-02"
        and state.get("current_step") == "time"
        and "50%" in reply
        and "5 250" in reply
    )
    return ContextResult("Обычный вопрос о цене учитывает буднюю скидку", ok, f"state={state}", transcript)


def context_confirmation_time_change_and_typo_summary(now: datetime) -> ContextResult:
    suffix = "context_confirm_time_change"
    transcript: list[tuple[str, str]] = []
    form = reg._base_form(
        service_type="gazebo",
        service_variant="Беседка №3",
        date="2026-06-02",
        time="11:00",
        duration=21,
        guests_count=10,
        event_format="не указано",
        client_name="Любовь",
        phone="+79990002007",
        upsell_items=["уголь", "лед"],
    )
    reg._create_reserved_conversation(suffix, now, form)
    _set_state(
        suffix,
        now,
        status="awaiting_confirmation",
        current_step="awaiting_confirmation",
        next_step="confirmation",
        form_data=form,
    )
    original_availability = message_handler.check_availability

    def fake_availability(_conn: Any, *, form_data: dict[str, Any], now: datetime) -> AvailabilityResult:
        return AvailabilityResult(True, "ok", ["Беседка №3: 11:00-08:00 следующего дня"])

    message_handler.check_availability = fake_availability
    try:
        changed = _say(suffix, "время тоже поменяй с 11 до 08", now, transcript, 1)
        summary = _say(suffix, "у меня есть активыне заявки?", now, transcript, 2)
    finally:
        message_handler.check_availability = original_availability
    state = _state(suffix)
    updated = state.get("form_data") or {}
    lowered_changed = _low(changed)
    lowered_summary = _low(summary)
    ok = (
        updated.get("time") == "11:00"
        and updated.get("duration") == 21
        and state.get("current_step") == "awaiting_confirmation"
        and "не вижу активной предварительной" not in lowered_changed
        and "до 08:00 следующего дня" in changed
        and "черновике" in lowered_summary
        and "до 08:00 следующего дня" in summary
        and "оформляем вторую" not in lowered_summary
    )
    return ContextResult("Подтверждение: правка времени и summary с опечаткой держат черновик", ok, f"state={state}", transcript)


def context_live_135_paid_gazebo_then_bathhouse_same_number(now: datetime) -> ContextResult:
    suffix = "context_live_135_paid_gazebo_bath"
    transcript: list[tuple[str, str]] = []
    reg._create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201061",
        provider_record_id="local_context_live_135_gazebo",
        phone="+79990002008",
    )
    original_classifier = message_handler.classify_post_booking_message
    original_call_ai = message_handler.call_ai
    original_availability = message_handler.check_availability

    def fake_classifier(**_: Any):
        return reg.PostBookingResponse(
            intent="new_booking_request",
            reply_to_user="Конечно, можно добавить ещё одну бронь.",
        )

    def fake_ai(**kwargs: Any) -> AIResponse:
        text = str(kwargs.get("text") or "").lower()
        if "бан" in text:
            return AIResponse(
                intent="booking_request",
                action="ask_next_question",
                current_step="date",
                changed_fields=["service_type"],
                form_data_patch={"service_type": "bathhouse"},
            )
        return AIResponse(
            intent="company_info",
            action="answer_info",
            reply_to_user="Да, по активной беседке всё нормально.",
        )

    message_handler.classify_post_booking_message = fake_classifier
    message_handler.call_ai = fake_ai
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "Баня свободна.", ["Баня: свободно"])
    try:
        options = _say(suffix, "хоршо\nможно еще что нибудь забронировать?", now, transcript, 1)
        bath = _say(suffix, "давайте еще баню на то же число что и беседка если можно", now, transcript, 2)
        info = _say(suffix, "а вообще норм беседка?", now, transcript, 3)
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.call_ai = original_call_ai
        message_handler.check_availability = original_availability
    state = _state(suffix)
    form = state.get("form_data") or {}
    lowered_options = _low(options)
    lowered_bath = _low(bath)
    lowered_info = _low(info)
    ok = (
        "ожидает подтверждения" not in lowered_options
        and "помимо бани" not in lowered_options
        and ("кроме вашей беседки" in lowered_options or "кроме беседки" in lowered_options)
        and form.get("service_type") == "bathhouse"
        and form.get("date") == "2026-06-30"
        and state.get("current_step") == "time"
        and "на какую дату" not in lowered_bath
        and "во сколько" in lowered_bath
        and "беседка №4" in lowered_info
        and "есть разные варианты" not in lowered_info
        and "по бане продолжим" in lowered_info
    )
    return ContextResult("Live 135: новая баня держит дату беседки и контекст", ok, f"state={state}", transcript)


def context_bathhouse_large_group_blocks_before_format(now: datetime) -> ContextResult:
    suffix = "context_bathhouse_large_group"
    transcript: list[tuple[str, str]] = []
    form = reg._base_form(
        service_type="bathhouse",
        service_variant=None,
        date="2026-06-29",
        time="18:00",
        duration=6,
        guests_count=None,
        event_format=None,
        upsell_items=[],
        phone="+79990002009",
    )
    reg._create_reserved_conversation(suffix, now, form)
    _set_state(suffix, now, status="waiting_user", current_step="guests_count", next_step="guests_count", form_data=form)
    reply = _say(suffix, "40", now, transcript, 1)
    state = _state(suffix)
    updated = state.get("form_data") or {}
    ok = (
        "слишком большая компания" in _low(reply)
        and "бесед" in _low(reply)
        and not updated.get("guests_count")
        and state.get("current_step") in {"guests_count", "service_type"}
    )
    return ContextResult("Баня на 40 гостей блокируется до шага формата", ok, f"state={state}", transcript)


def context_confirmation_no_means_not_confirmed(now: datetime) -> ContextResult:
    suffix = "context_confirmation_no"
    transcript: list[tuple[str, str]] = []
    form = reg._base_form(
        service_type="gazebo",
        service_variant="Беседка №1",
        date="2026-06-29",
        time="18:00",
        duration=6,
        guests_count=40,
        event_format="спокойный отдых",
        phone="+79990002010",
        upsell_items=["не нужны"],
    )
    reg._create_reserved_conversation(suffix, now, form)
    _set_state(suffix, now, status="awaiting_confirmation", current_step="awaiting_confirmation", next_step="confirmation", form_data=form)
    reply = _say(suffix, "нет", now, transcript, 1)
    state = _state(suffix)
    updated = state.get("form_data") or {}
    ok = (
        "что нужно изменить" in _low(reply)
        and "обнов" not in _low(reply)
        and state.get("current_step") == "change_booking"
        and updated.get("upsell_items") == ["не нужны"]
    )
    return ContextResult("Подтверждение: «нет» не меняет допы", ok, f"state={state}", transcript)


def _print_result(result: ContextResult) -> None:
    print(f"\n## {result.name}")
    for user_text, bot_text in result.transcript:
        print(f"USER: {user_text}")
        print(f"BOT: {bot_text}")
    marker = "OK" if result.ok else "FAIL"
    print(f"{marker}: {result.details}")


def main() -> None:
    reg.install_regression_suite_lock("dialog_context_suite")
    now = _now()
    reg._cleanup()
    restore_common = _patch_common()
    try:
        results = [
            context_date_and_guests_uses_availability(now),
            context_small_slots_keep_capacity_and_offer_nearest(now),
            context_date_only_does_not_become_guests(now),
            context_ai_understands_guest_without_keyword(now),
            context_gazebo_number_does_not_become_guests(now),
            context_gazebo_choice_question_keeps_date_without_guests(now),
            context_gazebo_guest_count_in_option_question_is_saved(now),
            context_guest_not_asked_complaint_repairs_state(now),
            context_info_question_keeps_selected_object(now),
            context_confirmation_summary_then_abort(now),
            context_two_gazebo_request_starts_sequential_queue(now),
            context_pending_second_date_does_not_overwrite_first(now),
            context_weekday_price_question_mentions_discount(now),
            context_confirmation_time_change_and_typo_summary(now),
            context_live_135_paid_gazebo_then_bathhouse_same_number(now),
            context_bathhouse_large_group_blocks_before_format(now),
            context_confirmation_no_means_not_confirmed(now),
        ]
    finally:
        restore_common()
        reg._cleanup()
    for result in results:
        _print_result(result)
    print(f"\nSUMMARY: {sum(1 for item in results if item.ok)}/{len(results)} passed")
    if not all(item.ok for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
