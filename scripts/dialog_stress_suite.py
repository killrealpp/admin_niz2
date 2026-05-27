"""Stress scenarios with unusual client phrasing.

This suite is intentionally closer to live Telegram dialogs than unit tests:
it prints every user message and bot reply, then checks the most important
state invariant for each scenario.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
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
class StressResult:
    name: str
    ok: bool
    details: str = ""
    transcript: list[tuple[str, str]] = field(default_factory=list)


def _now() -> datetime:
    settings = get_settings()
    return datetime(2026, 5, 27, 12, 0, tzinfo=ZoneInfo(settings.app_timezone))


def _say(suffix: str, text: str, now: datetime, transcript: list[tuple[str, str]]) -> str:
    reply = reg._send(suffix, text, now)
    transcript.append((text, reply))
    return reply


def _contains_all(text: str, *needles: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    return all(needle.lower().replace("ё", "е") in lowered for needle in needles)


def _state(suffix: str) -> dict:
    return reg._latest_state(suffix)


def _print_result(result: StressResult) -> None:
    print(f"\n## {result.name}")
    for user_text, bot_text in result.transcript:
        print(f"USER: {user_text}")
        print(f"BOT: {bot_text}")
    marker = "OK" if result.ok else "FAIL"
    print(f"{marker}: {result.details}")


def stress_budget_selection(now: datetime) -> StressResult:
    suffix = "stress_budget_typo"
    transcript: list[tuple[str, str]] = []
    created = reg._create_reserved_conversation(
        suffix,
        now,
        reg._base_form(
            service_type="gazebo",
            service_variant=None,
            date="2026-06-30",
            time=None,
            duration=None,
            guests_count=15,
            event_format="компания друзей",
            upsell_items=[],
            last_available_gazebo_variants=[
                "Беседка №1",
                "Беседка №2",
                "Беседка №3",
                "Беседка №4",
                "Беседка №8",
                "Крытая беседка",
            ],
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="service_variant",
            next_step="service_variant",
            form_data=created["conversation"]["form_data"],
        )
    reply = _say(suffix, "а есть ченить подешелве, но чтоб мы влезли?", now, transcript)
    ok = (
        _contains_all(reply, "беседка №2", "беседка №4")
        and "Беседка №1" not in reply
        and "Беседка №3" not in reply
        and _state(suffix).get("current_step") == "service_variant"
    )
    return StressResult(
        "Опечатка и бюджетный подбор беседки",
        ok,
        "ожидаю только самые дешевые подходящие свободные варианты",
        transcript,
    )


def stress_upsell_informal_refusals(now: datetime) -> StressResult:
    suffix = "stress_upsell_refusals"
    transcript: list[tuple[str, str]] = []
    created = reg._create_reserved_conversation(
        suffix,
        now,
        reg._base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="18:00",
            duration=6,
            guests_count=10,
            event_format="просто посидеть",
            client_name=None,
            phone=None,
            upsell_items=[],
            upsell_offer_count=0,
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
            form_data=created["conversation"]["form_data"],
        )
    first = _say(suffix, "неа, ниче не надо наверное", now, transcript)
    mid = _state(suffix)
    second = _say(suffix, "да нет же говорю, без всего", now + timedelta(seconds=10), transcript)
    final = _state(suffix)
    ok = (
        _contains_all(first, "всё же", "если точно ничего")
        and mid.get("current_step") == "upsell_items"
        and (final.get("form_data") or {}).get("upsell_items") == ["не нужны"]
        and final.get("current_step") in {"client_name", "phone"}
        and "обычно к" not in second.lower().replace("ё", "е")
    )
    return StressResult(
        "Два касания допов с живыми отказами",
        ok,
        f"после второго отказа current_step={final.get('current_step')}",
        transcript,
    )


def stress_addon_price_then_choice(now: datetime) -> StressResult:
    suffix = "stress_addon_price_then_choice"
    transcript: list[tuple[str, str]] = []
    created = reg._create_reserved_conversation(
        suffix,
        now,
        reg._base_form(
            service_type="gazebo",
            service_variant="Беседка №6",
            date="2026-06-30",
            time="18:00",
            duration=6,
            guests_count=8,
            event_format="день рождения",
            client_name="Кирилл",
            phone=None,
            upsell_items=[],
            upsell_offer_count=0,
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
            form_data=created["conversation"]["form_data"],
        )
    price = _say(suffix, "а решотка и кальян по чем вообще?", now, transcript)
    chosen = _say(suffix, "ладно, тогда базовый мангальный набор", now + timedelta(seconds=10), transcript)
    state = _state(suffix)
    ok = (
        _contains_all(price, "мангальный набор", "кальян")
        and "формат отдыха" not in price.lower().replace("ё", "е")
        and (state.get("form_data") or {}).get("upsell_items")
        and "базовый" in str((state.get("form_data") or {}).get("upsell_items")).lower()
        and state.get("current_step") == "phone"
        and "телефон" in chosen.lower().replace("ё", "е")
    )
    return StressResult(
        "Цена допов не сбивает шаг и выбор сохраняется",
        ok,
        f"upsell_items={(state.get('form_data') or {}).get('upsell_items')}",
        transcript,
    )


def stress_mixed_addon_price_and_choice(now: datetime) -> StressResult:
    suffix = "stress_mixed_addon_price_choice"
    transcript: list[tuple[str, str]] = []
    created = reg._create_reserved_conversation(
        suffix,
        now,
        reg._base_form(
            service_type="gazebo",
            service_variant="Беседка №8",
            date="2026-06-30",
            time="15:00",
            duration=8,
            guests_count=12,
            event_format="компания друзей",
            client_name="Кирилл",
            phone=None,
            upsell_items=[],
            upsell_offer_count=0,
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
            form_data=created["conversation"]["form_data"],
        )
    reply = _say(suffix, "а вода и лед сколько стоят? если можно, добавьте воду и лед", now, transcript)
    state = _state(suffix)
    items = (state.get("form_data") or {}).get("upsell_items") or []
    ok = (
        _contains_all(reply, "точной отдельной цены", "добавим", "телефон")
        and {"вода", "лед"} <= set(items)
        and state.get("current_step") == "phone"
    )
    return StressResult(
        "В одном сообщении цена допов и выбор воды/льда",
        ok,
        f"items={items} current_step={state.get('current_step')}",
        transcript,
    )


def stress_second_service_references(now: datetime) -> StressResult:
    suffix = "stress_second_service_refs"
    transcript: list[tuple[str, str]] = []
    created = reg._create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201065",
        provider_record_id="local_stress_second_service_gazebo",
        phone="+79990000901",
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="date",
            next_step="date",
            form_data=reg._base_form(
                service_type="bathhouse",
                service_variant=None,
                date=None,
                time=None,
                duration=None,
                guests_count=None,
                event_format=None,
                phone="+79990000901",
                client_name="Кирилл",
                upsell_items=[],
            ),
        )
    first = _say(suffix, "баньку тем же днем что и беседка хочу", now, transcript)
    second = _say(suffix, "и часы как там же, без изменений", now + timedelta(seconds=10), transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        form.get("service_type") == "bathhouse"
        and form.get("date") == "2026-06-30"
        and form.get("time") == "18:00"
        and form.get("duration") == 6
        and "Беседка №" not in second.splitlines()[0]
    )
    return StressResult(
        "Вторая услуга: свободная ссылка на дату/время беседки",
        ok,
        f"form service={form.get('service_type')} date={form.get('date')} time={form.get('time')} duration={form.get('duration')}",
        transcript,
    )


def stress_current_bookings_weird_question(now: datetime) -> StressResult:
    suffix = "stress_summary_weird"
    transcript: list[tuple[str, str]] = []
    created = reg._create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_stress_summary_bath",
        phone="+79990000902",
    )
    reg._add_paid_booking(
        created,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 26),
        provider_record_id="local_stress_summary_gazebo",
    )
    reply = _say(suffix, "чо там на мне висит по записям, я уже забыл", now, transcript)
    ok = _contains_all(reply, "2 брони", "баня", "бесед")
    return StressResult(
        "Постбронь: странный вопрос про текущие брони",
        ok,
        "ожидаю список актуальных броней из БД",
        transcript,
    )


def stress_cancel_one_keep_other(now: datetime) -> StressResult:
    suffix = "stress_cancel_one"
    transcript: list[tuple[str, str]] = []
    created = reg._create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_stress_cancel_bath",
        phone="+79990000903",
    )
    reg._add_paid_booking(
        created,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 26),
        provider_record_id="local_stress_cancel_gazebo",
    )
    reply = _say(suffix, "баню убери пожалуйста, а беседку не трогай", now, transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    ok = (
        _contains_all(reply, "баня", "точно отменяем")
        and "беседку" not in reply.lower().replace("ё", "е").split("точно")[0]
        and (form.get("cancel_flow") or {}).get("stage") == "confirm_cancel"
    )
    return StressResult(
        "Отмена одной услуги, вторую оставить",
        ok,
        f"cancel_flow={form.get('cancel_flow')}",
        transcript,
    )


def stress_reschedule_loose_phrase(now: datetime) -> StressResult:
    suffix = "stress_reschedule_loose"
    transcript: list[tuple[str, str]] = []
    reg._create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_stress_reschedule_bath",
        phone="+79990000904",
    )
    reply = _say(suffix, "сдвинем баню на денек позже, часы те же", now, transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    flow = form.get("reschedule_flow") or {}
    ok = (
        _contains_all(reply, "перенести", "26 июня")
        and flow.get("stage") == "confirm_reschedule"
        and flow.get("date") == "2026-06-26"
        and flow.get("same_time") is True
    )
    return StressResult(
        "Перенос свободной фразой: на денек позже, часы те же",
        ok,
        f"reschedule_flow={flow}",
        transcript,
    )


def stress_info_during_form_context(now: datetime) -> StressResult:
    suffix = "stress_info_during_form_context"
    transcript: list[tuple[str, str]] = []
    created = reg._create_reserved_conversation(
        suffix,
        now,
        reg._base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-06-30",
            time=None,
            duration=3,
            guests_count=None,
            event_format=None,
            client_name="Каролина",
            phone="+79990000907",
            upsell_items=[],
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="time",
            next_step="time",
            form_data=created["conversation"]["form_data"],
        )
    reply1 = _say(suffix, "а если нас будет 30 человек", now, transcript)
    reply2 = _say(suffix, "ну хз\nя позже вам напишу", now + timedelta(seconds=10), transcript)
    state = _state(suffix)
    form = state.get("form_data") or {}
    joined = "\n".join([reply1, reply2]).lower().replace("ё", "е")
    ok = (
        form.get("service_type") == "bathhouse"
        and state.get("next_step") == "time"
        and "для 30 человек" in joined
        and "бан" in joined
        and "когда определитесь" in joined
        and "продолжим оформление" not in joined
        and reply2.lower().replace("ё", "е").count("во сколько") == 0
    )
    return StressResult(
        "Info-вопрос внутри анкеты держит контекст услуги и паузу",
        ok,
        f"state={state}",
        transcript,
    )


def stress_info_without_form(now: datetime) -> StressResult:
    suffix = "stress_info_no_form"
    transcript: list[tuple[str, str]] = []
    reply1 = _say(suffix, "а комары там заедят или вы травите территорию?", now, transcript)
    reply2 = _say(suffix, "а веник в баньку свой можно, чисто чуть чуть?", now + timedelta(seconds=10), transcript)
    reply3 = _say(suffix, "адрес где и парковка есть?", now + timedelta(seconds=20), transcript)
    joined = "\n".join([reply1, reply2, reply3]).lower().replace("ё", "е")
    ok = (
        "раз в неделю" in joined
        and "веник" in joined
        and "нельзя" in joined
        and "парков" in joined
        and "на какую дату" not in joined
        and "что планируете" not in joined
    )
    return StressResult(
        "Info-вопросы без анкеты не стартуют бронь",
        ok,
        "ожидаю ответы по базе знаний без вопроса анкеты",
        transcript,
    )


def stress_abort_draft(now: datetime) -> StressResult:
    suffix = "stress_abort_draft"
    transcript: list[tuple[str, str]] = []
    created = reg._create_reserved_conversation(
        suffix,
        now,
        reg._base_form(
            service_type="bathhouse",
            date="2026-06-30",
            time=None,
            duration=None,
            guests_count=5,
            client_name="Кирилл",
            phone="+79990000905",
            upsell_items=[],
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="time",
            next_step="time",
            form_data=created["conversation"]["form_data"],
        )
    reply = _say(suffix, "короче забей, не оформляем эту штуку", now, transcript)
    form = (_state(suffix).get("form_data") or {})
    ok = _contains_all(reply, "не оформляю") and form.get("service_type") is None and form.get("phone") == "+79990000905"
    return StressResult(
        "Отказ от незавершенной анкеты живой фразой",
        ok,
        f"form={form}",
        transcript,
    )


def stress_photo_request(now: datetime) -> StressResult:
    suffix = "stress_photo_request"
    transcript: list[tuple[str, str]] = []
    reply = _say(suffix, "кинь фотку 3й беседки, просто глянуть", now, transcript)
    ok = _contains_all(reply, "фото", "беседка №3")
    return StressResult(
        "Явный запрос фото без даты",
        ok,
        "ожидаю фото конкретной беседки без ограничения 12 часов",
        transcript,
    )


def stress_forced_gazebo_capacity_addons_and_cancel_typo(now: datetime) -> StressResult:
    suffix = "stress_forced_gazebo_capacity_cancel"
    transcript: list[tuple[str, str]] = []
    original_availability = message_handler.check_availability
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.check_availability = lambda *_args, **_kwargs: reg.AvailabilityResult(
        True,
        "ok",
        ["Беседка №6: дата свободна", "Беседка №4: дата свободна"],
    )
    try:
        first = _say(suffix, "29 мая 6 беседка", now, transcript)
        capacity = _say(suffix, "а если нас будет 15 человек", now + timedelta(seconds=10), transcript)
        variant = _say(suffix, "хорошо, 4 беседка", now + timedelta(seconds=20), transcript)
        prices = _say(suffix, "а какие цены на допы", now + timedelta(seconds=30), transcript)
        state = _state(suffix)
        form = state.get("form_data") or {}
        dialog_ok = (
            form.get("service_variant") == "Беседка №4"
            and form.get("guests_count") == 15
            and not form.get("time")
            and "сколько" in first.lower().replace("ё", "е")
            and "до 15" in capacity.lower().replace("ё", "е")
            and "04:00" not in variant
            and "кальян" in prices.lower().replace("ё", "е")
            and "сейчас расскажу" not in prices.lower().replace("ё", "е")
        )
    finally:
        message_handler.check_availability = original_availability

    paid_suffix = suffix + "_paid"
    reg._create_paid_booking_for_action(
        paid_suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 12),
        yclients_service_id="18201061",
        provider_record_id="local_stress_cancel_dya",
        phone="+79990000908",
    )
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        ask_cancel = _say(paid_suffix, "отмени бронь", now, transcript)
        done = _say(paid_suffix, "Дя", now + timedelta(seconds=10), transcript)
        ack = _say(paid_suffix, "Окей", now + timedelta(seconds=20), transcript)
        cancel_ok = (
            "точно" in ask_cancel.lower().replace("ё", "е")
            and "отменила" in done.lower().replace("ё", "е")
            and "бронь зафиксирована" not in ack.lower().replace("ё", "е")
        )
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing

    return StressResult(
        "Принудительный выбор беседки, вместимость, цены допов и «Дя» при отмене",
        dialog_ok and cancel_ok,
        f"dialog_ok={dialog_ok} cancel_ok={cancel_ok}",
        transcript,
    )


def main() -> None:
    reg.install_regression_suite_lock("dialog_stress_suite")
    now = _now()
    reg._cleanup()
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    scenarios = [
        stress_budget_selection,
        stress_upsell_informal_refusals,
        stress_addon_price_then_choice,
        stress_mixed_addon_price_and_choice,
        stress_second_service_references,
        stress_current_bookings_weird_question,
        stress_cancel_one_keep_other,
        stress_reschedule_loose_phrase,
        stress_info_during_form_context,
        stress_info_without_form,
        stress_abort_draft,
        stress_photo_request,
        stress_forced_gazebo_capacity_addons_and_cancel_typo,
    ]
    results: list[StressResult] = []
    try:
        for scenario in scenarios:
            result = scenario(now)
            results.append(result)
            _print_result(result)
    finally:
        message_handler.create_missing_yclients_records = original_create_missing
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
