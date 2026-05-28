"""Edge dialog scenarios for unusual interruptions inside active flows."""

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

from app.core.config import get_settings
from app.db.connection import get_connection
from app.db.repositories import conversations_repo
from app.services import message_handler


@dataclass
class EdgeResult:
    name: str
    ok: bool
    details: str = ""
    transcript: list[tuple[str, str]] = field(default_factory=list)


def _now() -> datetime:
    settings = get_settings()
    return datetime(2026, 5, 28, 12, 30, tzinfo=ZoneInfo(settings.app_timezone))


def _say(suffix: str, text: str, now: datetime, transcript: list[tuple[str, str]]) -> str:
    reply = reg._send(suffix, text, now)
    transcript.append((text, reply))
    return reply


def _state(suffix: str) -> dict[str, Any]:
    return reg._latest_state(suffix)


def _low(text: str) -> str:
    return text.lower().replace("ё", "е")


def _has(text: str, *needles: str) -> bool:
    lowered = _low(text)
    return all(_low(needle) in lowered for needle in needles)


def _print_result(result: EdgeResult) -> None:
    print(f"\n## {result.name}")
    for user_text, bot_text in result.transcript:
        print(f"USER: {user_text}")
        print(f"BOT: {bot_text}")
    marker = "OK" if result.ok else "FAIL"
    print(f"{marker}: {result.details}")


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


def _draft_conversation(suffix: str, now: datetime, **overrides: Any) -> None:
    base = {
        "service_type": "gazebo",
        "service_variant": "Беседка №4",
        "date": "2026-06-30",
        "time": None,
        "duration": None,
        "guests_count": 10,
        "event_format": None,
        "client_name": "Кирилл",
        "phone": "+79990001001",
        "upsell_items": [],
    }
    base.update(overrides)
    form = reg._base_form(**base)
    reg._create_reserved_conversation(suffix, now, form)
    _set_state(suffix, now, status="waiting_user", current_step="time", next_step="time", form_data=form)


def _confirmation_conversation(suffix: str, now: datetime, **overrides: Any) -> None:
    base = {
        "service_type": "bathhouse",
        "service_variant": None,
        "date": "2026-06-30",
        "time": "18:00",
        "duration": 6,
        "guests_count": 5,
        "event_format": "компания друзей",
        "client_name": "Кирилл",
        "phone": "+79990001002",
        "upsell_items": ["не нужны"],
    }
    base.update(overrides)
    form = reg._base_form(**base)
    reg._create_reserved_conversation(suffix, now, form)
    _set_state(suffix, now, status="awaiting_confirmation", current_step="awaiting_confirmation", next_step="confirmation", form_data=form)


def _patch_confirmation_side_effects() -> Callable[[], None]:
    original_availability = message_handler.check_availability
    original_payment = message_handler.create_payment_link_for_holds
    original_missing = message_handler.create_missing_yclients_records
    message_handler.check_availability = lambda *_args, **_kwargs: reg.AvailabilityResult(True, "Баня свободна.", ["Баня: свободно"])
    message_handler.create_payment_link_for_holds = lambda *_args, **_kwargs: {"payment_url": "https://example.test/edge-pay", "amount": "1.00"}
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}

    def restore() -> None:
        message_handler.check_availability = original_availability
        message_handler.create_payment_link_for_holds = original_payment
        message_handler.create_missing_yclients_records = original_missing

    return restore


def edge_form_summary_question(now: datetime) -> EdgeResult:
    suffix = "edge_form_summary"
    transcript: list[tuple[str, str]] = []
    _draft_conversation(suffix, now)
    reply = _say(suffix, "а что мы вообще сейчас бронируем?", now, transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        _has(reply, "черновик")
        and (_has(reply, "Беседка №4") or _has(reply, "беседка"))
        and state.get("current_step") == "time"
        and form.get("service_variant") == "Беседка №4"
        and not form.get("time")
    )
    return EdgeResult("Анкета: вопрос «что мы сейчас бронируем?» показывает черновик", ok, f"state={state}", transcript)


def edge_form_unrelated_question_keeps_state(now: datetime) -> EdgeResult:
    suffix = "edge_form_unrelated"
    transcript: list[tuple[str, str]] = []
    _draft_conversation(suffix, now)
    reply = _say(suffix, "а кто такой Пушкин вообще?", now, transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        state.get("current_step") == "time"
        and form.get("service_variant") == "Беседка №4"
        and not form.get("time")
        and not form.get("duration")
        and "сразать" not in _low(reply)
        and "предоплат" not in _low(reply)
    )
    return EdgeResult("Анкета: вопрос совсем не по теме не портит состояние", ok, f"reply={reply} | state={state}", transcript)


def edge_form_phone_plus_info(now: datetime) -> EdgeResult:
    suffix = "edge_form_phone_info"
    transcript: list[tuple[str, str]] = []
    _draft_conversation(
        suffix,
        now,
        time="18:00",
        duration=6,
        event_format="день рождения",
        phone=None,
    )
    _set_state(suffix, now, status="waiting_user", current_step="phone", next_step="phone", form_data=(_state(suffix).get("form_data") or {}))
    reply = _say(suffix, "телефон +79991234567, и парковка там есть?", now, transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        form.get("phone") == "+79991234567"
        and "парков" in _low(reply)
        and state.get("current_step") in {"client_name", "upsell_items", "confirmation", "awaiting_confirmation"}
    )
    return EdgeResult("Анкета: телефон + инфо-вопрос в одном сообщении", ok, f"reply={reply} | form={form}", transcript)


def edge_form_abort_during_upsell(now: datetime) -> EdgeResult:
    suffix = "edge_form_abort_upsell"
    transcript: list[tuple[str, str]] = []
    _draft_conversation(
        suffix,
        now,
        time="18:00",
        duration=6,
        event_format="корпоратив",
        upsell_items=[],
    )
    form = _state(suffix).get("form_data") or {}
    _set_state(suffix, now, status="waiting_user", current_step="upsell_items", next_step="upsell_items", form_data=form)
    reply = _say(suffix, "давай откажемся от брони", now, transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        (_has(reply, "заявку не оформляю") or _has(reply, "не оформляю"))
        and "свободно" not in _low(reply)
        and "доп" not in _low(reply)
        and state.get("current_step") == "service_type"
        and form.get("service_type") is None
        and form.get("phone") == "+79990001001"
    )
    return EdgeResult("Анкета: отказ от брони на шаге допов отменяет черновик", ok, f"reply={reply} | state={state}", transcript)


def edge_confirmation_summary_question(now: datetime) -> EdgeResult:
    suffix = "edge_confirmation_summary"
    transcript: list[tuple[str, str]] = []
    _confirmation_conversation(suffix, now)
    reply = _say(suffix, "а какую бронь мы сейчас подтверждаем?", now, transcript)
    state = _state(suffix)
    ok = (
        state.get("current_step") == "awaiting_confirmation"
        and (_has(reply, "Баня") or _has(reply, "заявк"))
        and (_has(reply, "30 июня") or _has(reply, "18:00"))
        and "активных броней" not in _low(reply)
    )
    return EdgeResult("Подтверждение: вопрос «какую бронь подтверждаем?»", ok, f"reply={reply} | state={state}", transcript)


def edge_confirmation_info_then_yes(now: datetime) -> EdgeResult:
    suffix = "edge_confirmation_info_yes"
    transcript: list[tuple[str, str]] = []
    _confirmation_conversation(suffix, now)
    restore = _patch_confirmation_side_effects()
    try:
        info = _say(suffix, "а парковка есть рядом?", now, transcript)
        mid = _state(suffix)
        yes = _say(suffix, "да", now + timedelta(seconds=10), transcript)
        final = _state(suffix)
    finally:
        restore()
    ok = (
        "парков" in _low(info)
        and mid.get("current_step") == "awaiting_confirmation"
        and final.get("status") == "reserved"
        and final.get("current_step") == "reserved"
        and "https://example.test/edge-pay" in yes
    )
    return EdgeResult("Подтверждение: info-вопрос, потом подтверждение", ok, f"mid={mid} | final={final}", transcript)


def edge_confirmation_cancel_immediately(now: datetime) -> EdgeResult:
    suffix = "edge_confirmation_cancel"
    transcript: list[tuple[str, str]] = []
    _confirmation_conversation(suffix, now)
    reply = _say(suffix, "отмени бронь, не будем", now, transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        (_has(reply, "не оформляю") or _has(reply, "отменила заявку") or _has(reply, "заявку не оформляю"))
        and state.get("current_step") == "service_type"
        and form.get("service_type") is None
        and form.get("phone") == "+79990001002"
    )
    return EdgeResult("Подтверждение: сразу отменяем еще не созданную бронь", ok, f"reply={reply} | state={state}", transcript)


def _paid_for_cancel(suffix: str, now: datetime) -> None:
    reg._create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id=f"local_{suffix}_bath",
        phone="+79990001003",
    )


def edge_cancel_info_question(now: datetime) -> EdgeResult:
    suffix = "edge_cancel_info"
    transcript: list[tuple[str, str]] = []
    _paid_for_cancel(suffix, now)
    ask = _say(suffix, "отмени бронь", now, transcript)
    info = _say(suffix, "а аванс вообще возвращается?", now + timedelta(seconds=10), transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        "точно" in _low(ask)
        and ("аванс" in _low(info) or "предоплат" in _low(info))
        and state.get("current_step") == "reserved"
        and (form.get("cancel_flow") or {}).get("stage") == "confirm_cancel"
    )
    return EdgeResult("Cancel-flow: info-вопрос про аванс не сбрасывает отмену", ok, f"info={info} | state={state}", transcript)


def edge_cancel_unrelated_question(now: datetime) -> EdgeResult:
    suffix = "edge_cancel_unrelated"
    transcript: list[tuple[str, str]] = []
    _paid_for_cancel(suffix, now)
    _say(suffix, "отмени бронь", now, transcript)
    reply = _say(suffix, "а кто такой Пушкин?", now + timedelta(seconds=10), transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        (form.get("cancel_flow") or {}).get("stage") == "confirm_cancel"
        and state.get("current_step") == "reserved"
        and ("точно" in _low(reply) or "отмен" in _low(reply))
    )
    return EdgeResult("Cancel-flow: совсем другой вопрос не подтверждает отмену", ok, f"reply={reply} | state={state}", transcript)


def edge_cancel_no_then_reschedule(now: datetime) -> EdgeResult:
    suffix = "edge_cancel_no_reschedule"
    transcript: list[tuple[str, str]] = []
    _paid_for_cancel(suffix, now)
    _say(suffix, "отмени бронь", now, transcript)
    keep = _say(suffix, "нет, оставь", now + timedelta(seconds=10), transcript)
    reschedule = _say(suffix, "лучше перенеси на 26 июня, время то же", now + timedelta(seconds=20), transcript)
    state = _state(suffix)
    flow = (state.get("form_data") or {}).get("reschedule_flow") or {}
    ok = (
        "остав" in _low(keep)
        and flow.get("stage") == "confirm_reschedule"
        and flow.get("date") == "2026-06-26"
        and "перенести" in _low(reschedule)
    )
    return EdgeResult("Cancel-flow: отказ от отмены, затем перенос", ok, f"flow={flow}", transcript)


def edge_reschedule_info_then_continue(now: datetime) -> EdgeResult:
    suffix = "edge_reschedule_info"
    transcript: list[tuple[str, str]] = []
    _paid_for_cancel(suffix, now)
    start = _say(suffix, "перенеси бронь", now, transcript)
    info = _say(suffix, "а парковка там есть?", now + timedelta(seconds=10), transcript)
    target = _say(suffix, "на 26 июня, время то же", now + timedelta(seconds=20), transcript)
    state = _state(suffix)
    flow = (state.get("form_data") or {}).get("reschedule_flow") or {}
    ok = (
        ("какую бронь" in _low(start) or "новую дату" in _low(start) or "перенос" in _low(start))
        and "парков" in _low(info)
        and flow.get("stage") == "confirm_reschedule"
        and flow.get("date") == "2026-06-26"
        and "перенести" in _low(target)
    )
    return EdgeResult("Reschedule-flow: info-вопрос внутри переноса, затем продолжение", ok, f"flow={flow}", transcript)


def edge_reschedule_options_question(now: datetime) -> EdgeResult:
    suffix = "edge_reschedule_options"
    transcript: list[tuple[str, str]] = []
    created = reg._create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_edge_reschedule_options_bath",
        phone="+79990001004",
    )
    reg._add_paid_booking(
        created,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 25),
        provider_record_id="local_edge_reschedule_options_gazebo",
    )
    _say(suffix, "перенести бронь хочу", now, transcript)
    reply = _say(suffix, "а какие варианты переноса вообще?", now + timedelta(seconds=10), transcript)
    state = _state(suffix)
    ok = (
        ("одну бронь" in _low(reply) or "несколько" in _low(reply))
        and ("1." in reply and "2." in reply)
        and state.get("current_step") == "reserved"
    )
    return EdgeResult("Reschedule-flow: вопрос про варианты переноса", ok, f"reply={reply}", transcript)


def edge_post_booking_unrelated_question(now: datetime) -> EdgeResult:
    suffix = "edge_post_booking_unrelated"
    transcript: list[tuple[str, str]] = []
    _paid_for_cancel(suffix, now)
    reply = _say(suffix, "а что там с погодой на выходных?", now, transcript)
    state = _state(suffix)
    ok = (
        state.get("current_step") == "reserved"
        and state.get("status") == "payment_paid"
        and "активных броней" not in _low(reply)
        and "отмен" not in _low(reply)
        and "доп" not in _low(reply)
    )
    return EdgeResult("Post-booking: вопрос на другую тему не меняет бронь", ok, f"reply={reply} | state={state}", transcript)


def main() -> None:
    reg.install_regression_suite_lock("dialog_edge_suite")
    now = _now()
    reg._cleanup()
    original_missing = message_handler.create_missing_yclients_records
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    scenarios = [
        edge_form_summary_question,
        edge_form_unrelated_question_keeps_state,
        edge_form_phone_plus_info,
        edge_form_abort_during_upsell,
        edge_confirmation_summary_question,
        edge_confirmation_info_then_yes,
        edge_confirmation_cancel_immediately,
        edge_cancel_info_question,
        edge_cancel_unrelated_question,
        edge_cancel_no_then_reschedule,
        edge_reschedule_info_then_continue,
        edge_reschedule_options_question,
        edge_post_booking_unrelated_question,
    ]
    results: list[EdgeResult] = []
    try:
        for scenario in scenarios:
            result = scenario(now)
            results.append(result)
            _print_result(result)
    finally:
        message_handler.create_missing_yclients_records = original_missing
        reg._cleanup()
    failed = [result for result in results if not result.ok]
    print(f"\nSUMMARY: {len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:")
        for result in failed:
            print(f"- {result.name}: {result.details}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
