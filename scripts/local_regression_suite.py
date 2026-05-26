"""Deterministic regression tests for the booking bot.

The suite stubs AI/payment/YCLIENTS side effects and uses isolated users.
It is safe to run against the shared DB: all rows with TEST_PREFIX are removed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.errors import AIProviderUnavailable  # noqa: E402
from app.ai.schemas import AIResponse, PostBookingResponse  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.connection import get_connection  # noqa: E402
from app.db.repositories import bookings_repo, conversations_repo, payments_repo, slot_holds_repo, users_repo, yclients_records_repo  # noqa: E402
from app.services.availability_service import AvailabilityResult  # noqa: E402
from app.services import message_handler  # noqa: E402
from app.services.media_service import media_for_bookings, media_for_client_message  # noqa: E402
from app.services.message_handler import IncomingMessage, handle_incoming  # noqa: E402
from app.services.yclients_record_service import build_book_record_payload  # noqa: E402


TEST_PREFIX = "local_regression_"
TEST_PHONE = "+79990000001"
OLD_BOOKING_TEST_PHONE = "+79990000002"


@dataclass
class Check:
    name: str
    ok: bool
    details: str = ""


def _cleanup() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE u.external_id LIKE %s
                """,
                (TEST_PREFIX + "%",),
            )
            conversation_ids = [row["id"] for row in cur.fetchall()]
            cur.execute("SELECT id FROM users WHERE external_id LIKE %s", (TEST_PREFIX + "%",))
            user_ids = [row["id"] for row in cur.fetchall()]
            if conversation_ids:
                cur.execute("DELETE FROM waitlist_requests WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM payments WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM bookings WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM slot_holds WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM system_logs WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM messages WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM conversation_summaries WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute(
                    """
                    DELETE FROM slot_holds sh
                    USING conversations c, users u
                    WHERE sh.conversation_id = c.id
                      AND c.user_id = u.id
                      AND u.external_id LIKE %s
                    """,
                    (TEST_PREFIX + "%",),
                )
                cur.execute(
                    """
                    DELETE FROM messages m
                    USING conversations c, users u
                    WHERE m.conversation_id = c.id
                      AND c.user_id = u.id
                      AND u.external_id LIKE %s
                    """,
                    (TEST_PREFIX + "%",),
                )
                cur.execute(
                    """
                    DELETE FROM conversation_summaries cs
                    USING conversations c, users u
                    WHERE cs.conversation_id = c.id
                      AND c.user_id = u.id
                      AND u.external_id LIKE %s
                    """,
                    (TEST_PREFIX + "%",),
                )
                cur.execute("DELETE FROM conversations WHERE id = ANY(%s)", (conversation_ids,))
            if user_ids:
                cur.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
            cur.execute("DELETE FROM resource_busy_intervals WHERE source_record_id LIKE 'local_%'")
            cur.execute("DELETE FROM yclients_records WHERE yclients_record_id LIKE 'local_%'")


def _base_form(**overrides: Any) -> dict[str, Any]:
    form = {
        "service_type": "bathhouse",
        "service_variant": None,
        "date": "2026-05-23",
        "time": "17:00",
        "duration": 7,
        "guests_count": 7,
        "event_format": "отдых",
        "preferences": None,
        "client_name": "Кирилл",
        "phone": TEST_PHONE,
        "upsell_items": ["не нужны"],
        "comment": None,
        "payment_status": "not_required_yet",
    }
    form.update(overrides)
    return form


def _create_reserved_conversation(suffix: str, now: datetime, form_data: dict[str, Any] | None = None) -> dict[str, Any]:
    external_id = TEST_PREFIX + suffix
    with get_connection() as conn:
        user = users_repo.create(conn, "telegram", external_id, "Кирилл", now)
        conversation = conversations_repo.create(conn, user["id"], "telegram", now, form_data=form_data or _base_form())
        conversations_repo.update_after_message(
            conn,
            conversation["id"],
            now,
            status="reserved",
            current_step="reserved",
            next_step="payment_status",
        )
        return {"user": user, "conversation": conversation}


def _latest_state(suffix: str) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.status, c.current_step, c.next_step, c.form_data
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE u.external_id = %s
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                (TEST_PREFIX + suffix,),
            )
            row = cur.fetchone()
            return dict(row or {})


def _send(suffix: str, text: str, now: datetime) -> str:
    return handle_incoming(
        IncomingMessage(
            channel="telegram",
            external_user_id=TEST_PREFIX + suffix,
            user_name="Кирилл",
            text=text,
            message_time=now,
            raw_payload={"source": "local_regression_suite"},
        )
    )


def _create_active_hold(conversation: dict[str, Any], user: dict[str, Any], now: datetime) -> dict[str, Any]:
    with get_connection() as conn:
        return slot_holds_repo.create(
            conn,
            conversation_id=conversation["id"],
            user_id=user["id"],
            service_type="gazebo",
            yclients_service_id="18201056",
            slot_date=date(2026, 5, 23),
            slot_time=time(12, 0),
            duration_minutes=360,
            expires_at=now + timedelta(minutes=15),
        )


def _test_second_booking_does_not_inherit_old_slot(now: datetime) -> Check:
    suffix = "second_booking"
    _create_reserved_conversation(suffix, now)

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="service_type",
            changed_fields=["service_type"],
            form_data_patch={
                "service_type": "gazebo",
            },
        )

    def fake_generate_process_reply(**kwargs: Any) -> str:
        return str(kwargs.get("required_meaning") or "")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = fake_generate_process_reply
    try:
        reply = _send(suffix, "а можно еще беседку забронировать?", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "gazebo"
            and not form.get("date")
            and not form.get("time")
            and not form.get("duration")
            and form.get("client_name") == "Кирилл"
            and form.get("phone") == TEST_PHONE
            and state.get("current_step") == "date"
            and not reply.lower().startswith("привет")
            and "телефон" in reply.lower()
        )
        return Check("second booking resets slot fields", ok, reply)
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_new_service_from_waiting_date_resets_old_slot(now: datetime) -> Check:
    suffix = "new_service_from_waiting_date"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            date=None,
            time=None,
            duration=None,
            guests_count=5,
            last_unavailable={
                "service_type": "bathhouse",
                "date": "2026-05-30",
                "time": "12:00",
                "duration": 20,
                "guests_count": 5,
            },
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="awaiting_new_date",
            next_step="date",
            form_data={
                **created["conversation"]["form_data"],
                "service_type": "bathhouse",
                "date": None,
                "time": None,
                "duration": None,
                "last_unavailable": {
                    "service_type": "bathhouse",
                    "date": "2026-05-30",
                    "time": "12:00",
                    "duration": 20,
                    "guests_count": 5,
                },
            },
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="service_type",
            changed_fields=["service_type"],
            form_data_patch={"service_type": "bathhouse"},
        )

    def fake_generate_process_reply(**kwargs: Any) -> str:
        return str(kwargs.get("required_meaning") or "")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = fake_generate_process_reply
    try:
        reply = _send(suffix, "хлчу баню", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "bathhouse"
            and not form.get("date")
            and not form.get("time")
            and not form.get("duration")
            and not form.get("last_unavailable")
            and state.get("current_step") == "date"
            and "30 мая" not in reply
            and "12:00" not in reply
        )
        return Check("new service while awaiting date resets old slot", ok, f"{reply} | {form}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_reserved_yes_retries_payment_link(now: datetime) -> Check:
    suffix = "payment_retry"
    created = _create_reserved_conversation(suffix, now, _base_form(service_type="gazebo", service_variant="Беседка №2"))
    _create_active_hold(created["conversation"], created["user"], now)

    original_payment = message_handler.create_payment_link_for_holds

    def fake_payment(*_: Any, **__: Any) -> dict[str, Any]:
        return {
            "amount": "1.00",
            "currency": "RUB",
            "payment_url": "https://example.test/retry-pay",
            "provider_payment_id": "local_retry",
            "status": "pending",
        }

    message_handler.create_payment_link_for_holds = fake_payment
    try:
        reply = _send(suffix, "да", now)
        ok = (
            "https://example.test/retry-pay" in reply
            and "предоплат" in reply.lower()
            and "после оплаты" in reply.lower()
            and "подтвержд" in reply.lower()
        )
        return Check("reserved yes retries payment link", ok, reply)
    finally:
        message_handler.create_payment_link_for_holds = original_payment


def _test_paid_status_refreshes_on_any_message(now: datetime) -> Check:
    suffix = "paid_refresh"
    created = _create_reserved_conversation(suffix, now, _base_form(service_type="gazebo", service_variant="Беседка №2"))
    hold = _create_active_hold(created["conversation"], created["user"], now)

    with get_connection() as conn:
        payment = payments_repo.create_pending(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            booking_ids=[],
            provider="yookassa",
            amount=Decimal("1.00"),
            currency="RUB",
            description="local paid regression",
        )
        payments_repo.attach_provider_response(
            conn,
            payment_id=payment["id"],
            provider_payment_id="local_paid_refresh",
            payment_url="https://example.test/paid",
            status="paid",
            raw_payload={"hold_ids": [hold["id"]], "paid": True},
        )

    original_classifier = message_handler.classify_post_booking_message
    original_create_records = message_handler.create_missing_yclients_records

    def fake_classifier(**_: Any) -> PostBookingResponse:
        return PostBookingResponse(
            intent="current_booking_question",
            confidence=0.99,
            reply_to_user="Да, баня с бассейном есть. Можем оформить её отдельной бронью.",
        )

    message_handler.classify_post_booking_message = fake_classifier
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "а есть бани?", now)
        state = _latest_state(suffix)
        ok = "баня" in reply.lower() and state.get("status") == "payment_paid"
        return Check("paid status refreshes on any post-booking message", ok, f"{reply} | {state}")
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.create_missing_yclients_records = original_create_records


def _test_confirmation_info_answer_without_extra_ai(now: datetime) -> Check:
    suffix = "confirmation_info"
    created = _create_reserved_conversation(suffix, now, _base_form(service_type="gazebo", service_variant="Беседка №2"))
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="awaiting_confirmation",
            current_step="awaiting_confirmation",
            next_step="confirmation",
        )

    reply = _send(suffix, "мангал входит?", now)
    state = _latest_state(suffix)
    ok = "мангал" in reply.lower() and state.get("status") == "awaiting_confirmation"
    return Check("confirmation info question stays informative", ok, f"{reply} | {state}")


def _test_post_booking_info_fallback_when_ai_unavailable(now: datetime) -> Check:
    suffix = "post_booking_ai_unavailable"
    _create_reserved_conversation(suffix, now, _base_form(service_type="gazebo", service_variant="Беседка №2"))
    original_classifier = message_handler.classify_post_booking_message

    def unavailable_classifier(**_: Any) -> PostBookingResponse:
        raise AIProviderUnavailable("local unavailable")

    message_handler.classify_post_booking_message = unavailable_classifier
    try:
        reply = _send(suffix, "а есть бани?", now)
        ok = "бан" in reply.lower() and "сохранена" not in reply.lower()
        return Check("post-booking info fallback when AI unavailable", ok, reply)
    finally:
        message_handler.classify_post_booking_message = original_classifier


def _test_unconfigured_service_does_not_claim_free(now: datetime) -> Check:
    suffix = "unconfigured_service"
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="check_availability",
            current_step="date",
            changed_fields=["service_type", "date"],
            form_data_patch={"service_type": "unknown_service", "date": "2026-05-25"},
        )

    def fake_generate_process_reply(**kwargs: Any) -> str:
        return str(kwargs.get("required_meaning") or "")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = fake_generate_process_reply
    try:
        reply = _send(suffix, "хочу неизвестную услугу на 25 мая", now)
        lowered = reply.lower().replace("ё", "е")
        state = _latest_state(suffix)
        ok = (
            "пока не подключена" in lowered
            and "свободна" not in lowered
            and "свободен" not in lowered
            and state.get("status") == "waiting_user"
        )
        return Check("unconfigured service does not claim availability", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_summer_gazebo_alias_uses_gazebo(now: datetime) -> Check:
    suffix = "summer_alias"
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="service_type",
            changed_fields=["service_type"],
            form_data_patch={"service_type": "summer_gazebo"},
        )

    def fake_generate_process_reply(**kwargs: Any) -> str:
        return str(kwargs.get("required_meaning") or "")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = fake_generate_process_reply
    try:
        reply = _send(suffix, "хочу летнюю беседку", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "gazebo"
            and "летняя беседка" in str(form.get("preferences") or "").lower()
            and "пока не подключена" not in reply.lower()
        )
        return Check("summer gazebo is a gazebo alias", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_gazebo_bathhouse_alias_starts_with_gazebo(now: datetime) -> Check:
    suffix = "combo_alias"
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="service_type",
            changed_fields=["service_type", "guests_count"],
            form_data_patch={"service_type": "gazebo_bathhouse", "guests_count": 12},
        )

    def fake_generate_process_reply(**kwargs: Any) -> str:
        return str(kwargs.get("required_meaning") or "")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = fake_generate_process_reply
    try:
        reply = _send(suffix, "хочу беседку и баню, нас 12", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "gazebo"
            and "бан" in str(form.get("preferences") or "").lower()
            and "баню оформим" in reply.lower()
            and "пока не подключена" not in reply.lower()
        )
        return Check("gazebo+bathhouse starts with gazebo booking", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_bathhouse_gazebo_order_starts_with_bathhouse(now: datetime) -> Check:
    suffix = "bath_combo_order"
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="service_type",
            changed_fields=["service_type", "guests_count"],
            form_data_patch={"service_type": "bathhouse", "guests_count": 12},
        )

    def fake_generate_process_reply(**kwargs: Any) -> str:
        return str(kwargs.get("required_meaning") or "")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = fake_generate_process_reply
    try:
        reply = _send(suffix, "хочу баню и беседку, нас 12", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "bathhouse"
            and "бесед" in str(form.get("preferences") or "").lower()
            and state.get("current_step") in {"date", "duration"}
            and "пока не подключена" not in reply.lower()
        )
        return Check("bathhouse+gazebo starts with bathhouse booking", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_deterministic_date_beats_stale_ai(now: datetime) -> Check:
    suffix = "date_precedence"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(date=None, time=None, duration=None, service_type="bathhouse"),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="date",
            next_step="date",
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="date",
            changed_fields=["date"],
            form_data_patch={"date": "2025-05-21"},
        )

    def fake_generate_process_reply(**kwargs: Any) -> str:
        return str(kwargs.get("required_meaning") or "")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = fake_generate_process_reply
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "ok", ["Баня: дата свободна"])
    try:
        _send(suffix, "на завтра", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = form.get("date") == "2026-05-21"
        return Check("deterministic relative date beats stale AI", ok, str(form))
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_gazebo_recommendations_use_only_available() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant=None,
        guests_count=10,
        last_available_gazebo_variants=["Беседка №4", "Беседка №6"],
    )
    reply = message_handler._gazebo_selection_text(form)
    lowered = reply.lower()
    ok = (
        "№4" in reply
        and "№6" in reply
        and "№5" not in reply
        and "свобод" in lowered
        and "сколько" not in lowered
    )
    return Check("gazebo recommendations use only available variants", ok, reply)


def _test_gazebo_capacity_filter_rejects_tight_options() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant=None,
        date="2026-05-30",
        guests_count=30,
        last_available_gazebo_variants=["Беседка №5", "Беседка №2", "Беседка №4", "Беседка №6"],
    )
    reply = message_handler._gazebo_selection_text(form)
    paths = media_for_client_message("а на 30 чел", reply)
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "не подходят" in lowered
        and "какую закрепляем" not in lowered
        and not paths
    )
    return Check("gazebo capacity filter rejects tight options", ok, f"{reply} | media={paths}")


def _test_gazebo_date_reply_asks_guests_before_choice() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant=None,
        date="2026-05-30",
        time=None,
        duration=None,
        guests_count=None,
    )
    form = message_handler._remember_available_gazebo_variants(
        form,
        ["Беседка №5: дата свободна", "Беседка №2: дата свободна", "Беседка №4: дата свободна"],
    )
    reply, next_key = message_handler._availability_reply(
        "Нашёл свободные варианты для «Беседка».",
        ["Беседка №5: дата свободна", "Беседка №2: дата свободна", "Беседка №4: дата свободна"],
        form,
    )
    lowered = reply.lower().replace("ё", "е")
    ok = (
        next_key == "guests_count"
        and "сколько" in lowered
        and "человек" in lowered
        and "какую беседку выбираете" not in lowered
    )
    return Check("gazebo date reply asks guests before choice", ok, reply)


def _test_next_free_dates_filter_gazebos_by_guests(now: datetime) -> Check:
    suffix = "gazebo_next_dates_by_guests"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant=None,
            date="2026-05-30",
            time=None,
            duration=None,
            guests_count=20,
        ),
    )
    original_availability = message_handler.check_availability
    seen_dates: list[str] = []

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        seen_dates.append(str(form.get("date")))
        if form.get("date") == "2026-05-31":
            return AvailabilityResult(True, "ok", ["Беседка №5: дата свободна", "Беседка №2: дата свободна"])
        if form.get("date") == "2026-06-01":
            return AvailabilityResult(True, "ok", ["Беседка №3: дата свободна", "Беседка №8: дата свободна"])
        return AvailabilityResult(True, "ok", [])

    message_handler.check_availability = fake_availability
    try:
        with get_connection() as conn:
            reply = message_handler._next_free_dates_reply(
                conn,
                created["conversation"],
                _base_form(
                    service_type="gazebo",
                    service_variant=None,
                    date="2026-05-30",
                    time=None,
                    duration=None,
                    guests_count=20,
                ),
                now,
                limit=1,
                days_ahead=5,
            )
        lowered = (reply or "").lower().replace("ё", "е")
        ok = (
            reply is not None
            and "20 гостей" in lowered
            and "1 июня" in lowered
            and "беседка №3" in lowered
            and "беседка №8" in lowered
            and "беседка №5" not in lowered
            and "2026-05-30" not in seen_dates
        )
        return Check("next free dates filter gazebos by guests", ok, f"{reply} | seen={seen_dates}")
    finally:
        message_handler.check_availability = original_availability


def _test_gazebo_start_time_defaults_until_morning(now: datetime) -> Check:
    suffix = "gazebo_time_until_morning"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №2",
            date="2026-05-30",
            time=None,
            duration=None,
            guests_count=10,
            event_format=None,
            upsell_items=[],
            client_name="Кирилл",
            phone=None,
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
        )
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    seen: list[dict[str, Any]] = []

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(intent="booking_request", action="ask_next_question", current_step="time")

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        seen.append(kwargs.get("form_data") or {})
        return AvailabilityResult(True, "ok", ["Беседка №2: 17:00-08:00"])

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "примерно с 5 вечера а там как пойдет", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        checked = seen[-1] if seen else {}
        ok = (
            form.get("time") == "17:00"
            and form.get("duration") == 15
            and checked.get("duration") == 15
            and "на сколько часов" not in reply.lower()
            and state.get("current_step") == "event_format"
        )
        return Check("gazebo start time defaults until morning", ok, f"{reply} | {form} | checked={checked}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_media_waits_for_date_and_guests() -> Check:
    date_only_reply = "На 30 мая свободны: Беседка №5, Беседка №2, Беседка №4, Беседка №6."
    guest_reply = (
        "Для 10 гостей из свободных на выбранную дату вариантов подходят:\n"
        "- Беседка №2: до 15 человек, 3 200 ₽\n"
        "- Беседка №4: до 15 человек, 3 200 ₽"
    )
    date_only = media_for_client_message("30 мая", date_only_reply)
    after_guests = media_for_client_message("нас 10 человек", guest_reply)
    ok = (
        not date_only
        and {path.name for path in after_guests} == {"besedka2.jpg", "besedka4.jpg"}
    )
    return Check("media waits for date and guests", ok, f"date_only={date_only}, after_guests={[p.name for p in after_guests]}")


def _test_explicit_photo_request_ignores_availability_text() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant=None,
        date="2026-05-30",
        guests_count=10,
    )
    reply = message_handler._deterministic_info_reply("покажи беседку №2", form)
    paths = media_for_client_message("покажи беседку №2", reply or "")
    lowered = (reply or "").lower().replace("ё", "е")
    ok = (
        reply is not None
        and "сейчас отправлю" in lowered
        and "не могу" not in lowered
        and "только для свободных" not in lowered
        and [path.name for path in paths] == ["besedka2.jpg"]
    )
    return Check("explicit photo request ignores availability text", ok, f"{reply} | {[p.name for p in paths]}")


def _test_explicit_photo_request_bypasses_ai(now: datetime) -> Check:
    suffix = "explicit_photo_bypass_ai"
    original_call_ai = message_handler.call_ai

    def fail_call_ai(**_: Any) -> AIResponse:
        raise AssertionError("AI must not be called for explicit photo request")

    message_handler.call_ai = fail_call_ai
    try:
        reply = _send(suffix, "а можете показать беседку 3", now)
        paths = media_for_client_message("а можете показать беседку 3", reply)
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "сейчас отправлю" in lowered
            and "беседка №3" in lowered
            and "не могу" not in lowered
            and [path.name for path in paths] == ["besedka3.jpg"]
        )
        return Check("explicit photo request bypasses ai", ok, f"{reply} | {[p.name for p in paths]}")
    finally:
        message_handler.call_ai = original_call_ai


def _test_explicit_service_photo_request_ignores_old_gazebo_state(now: datetime) -> Check:
    suffix = "explicit_service_photo_old_state"
    _create_reserved_conversation(
        suffix,
        now,
        _base_form(service_type="gazebo", service_variant="Беседка №2"),
    )
    reply = _send(suffix, "покажи баню", now)
    paths = media_for_client_message("покажи баню", reply)
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "баня" in lowered
        and "беседка №2" not in lowered
        and [path.name for path in paths] == ["banya.jpg"]
    )
    return Check("explicit service photo ignores old gazebo state", ok, f"{reply} | {[p.name for p in paths]}")


def _test_price_question_during_form_not_booking_summary(now: datetime) -> Check:
    suffix = "price_during_form"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №2",
            date="2026-05-30",
            time="17:00",
            duration=15,
            guests_count=10,
            event_format=None,
            upsell_items=[],
            client_name="Кирилл",
            phone=None,
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="event_format",
            next_step="event_format",
        )
    original_call_ai = message_handler.call_ai

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(intent="price_question", action="ask_next_question", current_step="event_format")

    message_handler.call_ai = fake_call_ai
    try:
        reply = _send(suffix, "сколько стоит беседка в итоге", now)
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "3200" in reply.replace(" ", "")
            and "пока не вижу активных броней" not in lowered
            and "формат" in lowered
        )
        return Check("price question during form not booking summary", ok, reply)
    finally:
        message_handler.call_ai = original_call_ai


def _test_single_available_gazebo_is_auto_selected() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant=None,
        date="2026-05-22",
        time=None,
        duration=None,
        guests_count=None,
        last_available_gazebo_variants=[],
    )
    form = message_handler._remember_available_gazebo_variants(
        form,
        ["Беседка №6: дата свободна"],
    )
    form = message_handler._auto_select_single_available_gazebo(form)
    reply, next_key = message_handler._availability_reply(
        "Нашёл свободные варианты для «Беседка».",
        ["Беседка №6: дата свободна"],
        form,
    )
    lowered = reply.lower().replace("ё", "е")
    ok = (
        form.get("service_variant") == "Беседка №6"
        and next_key == "guests_count"
        and "беседка №6" in lowered
        and "какую беседку" not in lowered
        and "сколько" in lowered
    )
    return Check("single available gazebo is auto selected", ok, f"{reply} | {form}")


def _test_gazebo_variant_is_not_guessed() -> Check:
    guests_only = message_handler._normalize_gazebo_variant(
        _base_form(
            service_type="gazebo",
            service_variant=None,
            guests_count=30,
        )
    )
    broad_choice = message_handler._normalize_gazebo_variant(
        _base_form(
            service_type="gazebo",
            service_variant="Большая беседка",
            guests_count=30,
            preferences=None,
        )
    )
    ok = (
        not guests_only.get("service_variant")
        and not broad_choice.get("service_variant")
        and "большая беседка" in str(broad_choice.get("preferences") or "").lower()
    )
    return Check("gazebo variant is not guessed", ok, f"{guests_only} | {broad_choice}")


def _test_booking_summary_counts_all_bookings(now: datetime) -> Check:
    suffix = "booking_summary"
    created = _create_reserved_conversation(suffix, now)
    conversation = created["conversation"]
    user = created["user"]

    with get_connection() as conn:
        bath_hold = slot_holds_repo.create(
            conn,
            conversation_id=conversation["id"],
            user_id=user["id"],
            service_type="bathhouse",
            yclients_service_id="18490331",
            slot_date=date(2026, 5, 23),
            slot_time=time(18, 0),
            duration_minutes=360,
            expires_at=now + timedelta(minutes=10),
        )
        gazebo_hold = slot_holds_repo.create(
            conn,
            conversation_id=conversation["id"],
            user_id=user["id"],
            service_type="gazebo",
            yclients_service_id="18201061",
            slot_date=date(2026, 5, 24),
            slot_time=time(12, 0),
            duration_minutes=360,
            expires_at=now + timedelta(minutes=10),
        )
        for hold in (bath_hold, gazebo_hold):
            bookings_repo.create_from_hold(
                conn,
                conversation_id=conversation["id"],
                user_id=user["id"],
                slot_hold_id=hold["id"],
                service_type=hold["service_type"],
                booking_date=hold["slot_date"],
                booking_time=hold["slot_time"],
                duration_minutes=hold["duration_minutes"],
                client_name="Кирилл",
                phone=TEST_PHONE,
                guests_count=5,
                event_format="спокойный отдых",
                preferences=None,
                upsell_items=["не нужны"],
                status="created_in_yclients",
                payment_status="paid",
            )
            slot_holds_repo.mark_converted(conn, hold_id=hold["id"], now=now)

    reply = _send(suffix, "а теперь сколько у меня броней?", now)
    ok = "2 брони" in reply and "Баня" in reply and "Беседка №4" in reply
    return Check("booking summary counts all bookings", ok, reply)


def _test_new_conversation_sees_old_user_booking(now: datetime) -> Check:
    suffix = "old_booking_lookup"
    old_now = now - timedelta(days=10)
    external_id = TEST_PREFIX + suffix
    with get_connection() as conn:
        user = users_repo.create(conn, "telegram", external_id, "Кирилл", old_now)
        users_repo.update_phone(conn, user["id"], OLD_BOOKING_TEST_PHONE)
        conversation = conversations_repo.create(conn, user["id"], "telegram", old_now, form_data=_base_form())
        hold = slot_holds_repo.create(
            conn,
            conversation_id=conversation["id"],
            user_id=user["id"],
            service_type="bathhouse",
            yclients_service_id="18490331",
            slot_date=date(2026, 6, 20),
            slot_time=time(18, 0),
            duration_minutes=360,
            expires_at=old_now + timedelta(minutes=10),
        )
        bookings_repo.create_from_hold(
            conn,
            conversation_id=conversation["id"],
            user_id=user["id"],
            slot_hold_id=hold["id"],
            service_type=hold["service_type"],
            booking_date=hold["slot_date"],
            booking_time=hold["slot_time"],
            duration_minutes=hold["duration_minutes"],
            client_name="Кирилл",
                phone=OLD_BOOKING_TEST_PHONE,
            guests_count=5,
            event_format="спокойный отдых",
            preferences=None,
            upsell_items=["не нужны"],
            status="created_in_yclients",
            payment_status="paid",
        )
        slot_holds_repo.mark_converted(conn, hold_id=hold["id"], now=old_now)

    reply = _send(suffix, "что у меня забронировано?", now)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS total
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE u.external_id = %s
                """,
                (external_id,),
            )
            total_conversations = cur.fetchone()["total"]
    ok = "1 бронь" in reply and "Баня" in reply and "20 июня" in reply and total_conversations >= 2
    return Check("new conversation sees old user booking", ok, f"{reply} | conversations={total_conversations}")


def _test_new_conversation_sees_old_summary(now: datetime) -> Check:
    suffix = "old_summary_context"
    created = _create_reserved_conversation(suffix, now)
    old_conversation_id = created["conversation"]["id"]
    user_id = created["user"]["id"]
    later = now + timedelta(hours=73)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_summaries (
                    conversation_id, summary, messages_from, messages_to, messages_count
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    old_conversation_id,
                    "Старый диалог: клиент хотел баню, имя Кирилл, телефон сохранен.",
                    now - timedelta(hours=74),
                    now - timedelta(hours=73),
                    12,
                ),
            )
        new_conversation = conversations_repo.create(conn, user_id, "telegram", later)
        summaries = message_handler._context_summaries(conn, new_conversation, {}, later)
    ok = any("Старый диалог" in str(item.get("summary") or "") for item in summaries)
    return Check("new conversation sees old summary", ok, str(summaries))


def _test_customer_templates_do_not_mention_admin(now: datetime) -> Check:
    forbidden = ("админ", "администратор", "администрац")
    hold = {
        "service_type": "gazebo",
        "slot_date": date(2026, 5, 23),
        "slot_time": time(12, 0),
        "duration_minutes": 360,
    }
    form = _base_form(service_type="gazebo", service_variant="Беседка №2")
    replies = [
        message_handler._format_hold_summary([hold], form),
        message_handler._payment_reply_text(None),
        message_handler._fallback_reply(form)[0],
    ]
    combined = "\n\n".join(replies).lower().replace("ё", "е")
    ok = not any(word in combined for word in forbidden) and "номер" in combined
    return Check("customer templates do not mention admin", ok, "\n---\n".join(replies))


def _test_short_yes_confirms() -> Check:
    ok = message_handler._confirmation_yes("д") and message_handler._confirmation_yes("+")
    return Check("short yes confirms", ok, "д/+ should confirm")


def _test_bare_weekday_requires_confirmation(now: datetime) -> Check:
    patch = message_handler._relative_date_patch("в субботу", now)
    reply = message_handler._bare_weekday_confirmation("в субботу", now)
    ok = patch == {} and bool(reply and "суббот" in reply.lower())
    return Check("bare weekday asks clarification", ok, f"patch={patch}, reply={reply}")


def _test_weekday_confirmation_yes_uses_saved_candidate(now: datetime) -> Check:
    suffix = "weekday_confirm_yes"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant=None,
            date=None,
            time=None,
            duration=None,
            guests_count=None,
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="date",
            next_step="date",
        )

    first_reply = _send(suffix, "в субботу", now)
    state = _latest_state(suffix)
    pending_date = ((state.get("form_data") or {}).get("pending_date_confirmation") or {}).get("date")

    original_availability = message_handler.check_availability
    original_generate = message_handler.generate_process_reply
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(
        True,
        "Нашёл свободные варианты для «Беседка».",
        ["Беседка №6: дата свободна"],
    )
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    try:
        second_reply = _send(suffix, "да", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            "23 мая" in first_reply
            and pending_date == "2026-05-23"
            and form.get("date") == "2026-05-23"
            and not form.get("pending_date_confirmation")
            and "23 мая" in second_reply
            and "24 мая" not in second_reply
        )
        return Check("weekday confirmation yes uses saved candidate", ok, f"{first_reply} | {second_reply} | {form}")
    finally:
        message_handler.check_availability = original_availability
        message_handler.generate_process_reply = original_generate


def _test_gazebo_open_ended_duration_overrides_ai_guess() -> Check:
    guessed = _base_form(
        service_type="gazebo",
        service_variant="Беседка №2",
        date="2026-05-30",
        time="17:00",
        duration="6 часов",
        guests_count=10,
    )
    updated = message_handler._apply_gazebo_default_duration(
        guessed,
        force=message_handler._gazebo_open_ended_duration_requested("примерно с 5 вечера, а там как пойдёт"),
    )
    ok = updated.get("duration") == 15
    return Check("gazebo open-ended duration overrides AI guess", ok, str(updated))


def _test_first_upsell_no_gets_soft_push() -> Check:
    form = _base_form(service_type="gazebo", service_variant="Беседка №2")
    reply = message_handler._upsell_push_reply(form)
    no_patch = message_handler._upsell_items_patch("наверное ничего")
    typo_patch = message_handler._upsell_items_patch("наверное ничег")
    ok = (
        "уголь" in reply.lower()
        and "напишите «нет» ещё раз" in reply.lower()
        and no_patch.get("upsell_items") == ["не нужны"]
        and typo_patch.get("upsell_items") == ["не нужны"]
    )
    return Check("first upsell no gets soft push", ok, reply)


def _test_first_upsell_flow_before_phone(now: datetime) -> Check:
    suffix = "first_upsell_flow"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №8",
            date="2026-05-23",
            time="18:00",
            duration=6,
            guests_count=5,
            event_format="спокойный отдых",
            upsell_items=[],
            client_name="Кирилл",
            phone=None,
        ),
    )
    with get_connection() as conn:
        messages_repo = message_handler.messages_repo
        messages_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            sender="assistant",
            text="Обычно к беседке берут допы: уголь, розжиг, решетка/шампуры, лед, посуда, кальян. Что подготовить для вас?",
        )
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
        )

    reply = _send(suffix, "наверное ничего", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    ok = (
        "напишите «нет» ещё раз" in reply.lower()
        and form.get("upsell_offer_count") == 1
        and not form.get("upsell_items")
        and state.get("current_step") == "upsell_items"
    )
    return Check("first upsell flow before phone gets soft push", ok, f"{reply} | {state}")


def _test_prefilled_first_upsell_no_still_gets_soft_push(now: datetime) -> Check:
    suffix = "prefilled_first_upsell_flow"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-06",
            time="12:00",
            duration=24,
            guests_count=5,
            event_format="день рождения",
            upsell_items=["не нужны"],
            upsell_offer_count=0,
            client_name="Кирилл",
            phone=None,
        ),
    )
    with get_connection() as conn:
        messages_repo = message_handler.messages_repo
        messages_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            sender="assistant",
            text="Обычно к беседке берут допы: уголь, розжиг, решётку или шампуры, лёд, посуду, кальян. Что подготовить для вашего праздника?",
        )
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="phone",
            next_step="phone",
        )

    first_reply = _send(suffix, "нет", now)
    first_state = _latest_state(suffix)
    first_form = first_state.get("form_data") or {}
    second_reply = _send(suffix, "нет", now + timedelta(seconds=1))
    second_state = _latest_state(suffix)
    second_form = second_state.get("form_data") or {}
    ok = (
        "напишите «нет» ещё раз" in first_reply.lower()
        and first_form.get("upsell_offer_count") == 1
        and not first_form.get("upsell_items")
        and "телефон" in second_reply.lower()
        and second_form.get("upsell_items") == ["не нужны"]
        and second_state.get("current_step") == "phone"
    )
    return Check(
        "prefilled first upsell no still gets soft push",
        ok,
        f"{first_reply} | {first_state} | {second_reply} | {second_state}",
    )


def _test_duration_24_formats_as_hours() -> Check:
    hold = {"duration_minutes": 1440}
    ok = (
        message_handler._format_duration(24) == "24 часа"
        and message_handler._format_duration(hold["duration_minutes"]) == "24 часа"
    )
    return Check("duration 24 formats as hours", ok, message_handler._format_duration(24))


def _test_positive_upsell_goes_to_next_step(now: datetime) -> Check:
    suffix = "positive_upsell"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-06-23",
            time="18:00",
            duration=6,
            guests_count=5,
            event_format="спокойный отдых",
            upsell_items=[],
            client_name="Кирилл",
            phone="+79990000003",
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
        )

    reply = _send(suffix, "давайте воду", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    ok = (
        "что ещё подготовить" not in reply.lower()
        and state.get("status") == "awaiting_confirmation"
        and form.get("upsell_items") == ["вода"]
    )
    return Check("positive upsell goes to confirmation", ok, f"{reply} | {state}")


def _test_free_dates_lookup_after_no_availability(now: datetime) -> Check:
    suffix = "free_dates_lookup"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date=None,
            time=None,
            duration=None,
            guests_count=5,
            last_unavailable={"service_type": "bathhouse", "date": "2026-06-23"},
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="awaiting_new_date",
            next_step="date",
        )

    original_availability = message_handler.check_availability

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        if form.get("date") == "2026-06-25":
            return AvailabilityResult(True, "ok", ["Баня: дата свободна"])
        return AvailabilityResult(True, "no", [])

    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "а когда свободно?", now)
        ok = "25 июня" in reply and "24 июня" not in reply and "ближайшие свободные даты" in reply.lower()
        return Check("free dates lookup after no availability", ok, reply)
    finally:
        message_handler.check_availability = original_availability


def _test_waitlist_decline_does_not_handoff(now: datetime) -> Check:
    suffix = "waitlist_decline"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_waitlist_decline_record",
        phone="+79990000006",
    )
    original_classifier = message_handler.classify_post_booking_message
    called = {"value": False}

    def fake_classifier(*_args: Any, **_kwargs: Any) -> PostBookingResponse:
        called["value"] = True
        return PostBookingResponse(intent="other", reply_to_user="fallback", handoff_to_human=True)

    message_handler.classify_post_booking_message = fake_classifier
    try:
        reply = _send(suffix, "нет, не актуально", now)
        state = _latest_state(suffix)
        ok = "запрос" in reply.lower() and state.get("status") != "handoff" and not called["value"]
        return Check("waitlist decline does not handoff", ok, f"{reply} | {state}")
    finally:
        message_handler.classify_post_booking_message = original_classifier


def _test_location_question_does_not_handoff() -> Check:
    samples = [
        "А где вы находитесь?",
        "Где находитесь",
        "Какой адрес?",
    ]
    ok = all(not message_handler._looks_like_handoff_needed(text) for text in samples)
    rude_ok = message_handler._looks_like_handoff_needed("вы меня бесите")
    return Check("location question does not handoff", ok and rude_ok, f"samples={samples}, rude_ok={rude_ok}")


def _test_gazebo_media_selection() -> Check:
    general = media_for_client_message("какие беседки есть?", "Напишите дату — проверю свободные беседки и отправлю фото.")
    date_only = media_for_client_message("30 мая", "На 30 мая свободны: Беседка №4, Беседка №6.")
    free = media_for_client_message(
        "нас 10",
        "Для 10 гостей на 25 июня из свободных подойдут: Беседка №4, Беседка №6.",
    )
    rejected = media_for_client_message(
        "нас 30",
        "На 25 июня свободны: Беседка №4, Беседка №6, но для 30 гостей по вместимости они не подходят.",
    )
    specific = media_for_client_message("покажи беседку 8", "Вот беседка №8")
    bath_explicit = media_for_client_message("покажи баню", "Конечно, сейчас отправлю фото бани.")
    bath_auto = media_for_client_message("на 26 июня", "На 26 июня баня свободна с 18:00 на 3 часа.")
    bath_busy = media_for_client_message("на 26 июня", "На 26 июня свободных вариантов для «Баня» не нашёл.")
    house_explicit = media_for_client_message("покажи гостевой дом", "Конечно, сейчас отправлю фото гостевого дома.")
    house_auto = media_for_client_message("на 27 июня", "На 27 июня гостевой дом свободен с 18:00 на сутки.")
    paid_media = media_for_bookings(
        [
            {"service_type": "bathhouse"},
            {"service_type": "house"},
            {"service_type": "gazebo", "hold_yclients_service_id": "18201065"},
        ]
    )
    time_reply = media_for_client_message("на 18:00", "Беседка №4: с 18:00 до 00:00 свободно.")
    location = media_for_client_message("где вы находитесь?", "Адрес: Выкса")
    nearest = media_for_client_message(
        "нас 25",
        (
            "Беседка №2 рассчитана до 15 человек, а вас будет 25.\n"
            "Чтобы не было тесно, эту беседку не закрепляю.\n\n"
            "Сейчас не вижу подходящих свободных вариантов для такого количества гостей на выбранную дату.\n\n"
            "Ближайшие даты, где есть беседки для 25 гостей:\n"
            "- 1 июня: Беседка №1\n"
            "- 2 июня: Беседка №1\n\n"
            "Какую дату выбираете?"
        ),
    )
    ok = (
        not general
        and not date_only
        and [path.name for path in free] == ["besedka4.jpg", "besedka6.jpg"]
        and not rejected
        and [path.name for path in specific] == ["besedka8.jpg"]
        and [path.name for path in bath_explicit] == ["banya.jpg"]
        and [path.name for path in bath_auto] == ["banya.jpg"]
        and not bath_busy
        and [path.name for path in house_explicit] == ["dom_gostevoy.jpg"]
        and [path.name for path in house_auto] == ["dom_gostevoy.jpg"]
        and [path.name for path in paid_media] == ["banya.jpg", "dom_gostevoy.jpg", "besedka8.jpg"]
        and not time_reply
        and not location
        and [path.name for path in nearest] == ["besedka1.jpg"]
    )
    return Check(
        "gazebo media selection",
        ok,
        (
            f"general={general}, date_only={date_only}, free={[path.name for path in free]}, "
            f"rejected={[path.name for path in rejected]}, specific={[path.name for path in specific]}, "
            f"bath_explicit={[path.name for path in bath_explicit]}, bath_auto={[path.name for path in bath_auto]}, "
            f"bath_busy={[path.name for path in bath_busy]}, house_explicit={[path.name for path in house_explicit]}, "
            f"house_auto={[path.name for path in house_auto]}, paid_media={[path.name for path in paid_media]}, "
            f"time={[path.name for path in time_reply]}, location={location}, nearest={[path.name for path in nearest]}"
        ),
    )


def _add_paid_booking(
    created: dict[str, Any],
    now: datetime,
    *,
    service_type: str,
    booking_date: date,
    provider_record_id: str,
    yclients_service_id: str | None = None,
) -> None:
    service_id = yclients_service_id or ("18201056" if service_type == "gazebo" else "18490331")
    with get_connection() as conn:
        hold = slot_holds_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            service_type=service_type,
            yclients_service_id=service_id,
            slot_date=booking_date,
            slot_time=time(18, 0),
            duration_minutes=360,
            expires_at=now + timedelta(minutes=10),
        )
        booking = bookings_repo.create_from_hold(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            slot_hold_id=hold["id"],
            service_type=service_type,
            booking_date=booking_date,
            booking_time=time(18, 0),
            duration_minutes=360,
            client_name="Кирилл",
            phone="+79990000007",
            guests_count=5,
            event_format="спокойный отдых",
            preferences=None,
            upsell_items=["не нужны"],
            status="created_in_yclients",
            payment_status="paid",
        )
        bookings_repo.mark_yclients_created(conn, booking_id=booking["id"], yclients_record_id=provider_record_id)
        _upsert_test_yclients_record(
            conn,
            now=now,
            record_id=provider_record_id,
            service_type=service_type,
            yclients_service_id=service_id,
            start_date=booking_date,
            start_time=time(18, 0),
            duration_minutes=360,
            phone="+79990000007",
        )
        slot_holds_repo.mark_converted(conn, hold_id=hold["id"], now=now)


def _upsert_test_yclients_record(
    conn,
    *,
    now: datetime,
    record_id: str,
    service_type: str,
    yclients_service_id: str,
    start_date: date,
    start_time: time,
    duration_minutes: int,
    phone: str,
) -> None:
    tz = ZoneInfo(get_settings().app_timezone)
    start_at = datetime.combine(start_date, start_time, tzinfo=tz)
    end_at = start_at + timedelta(minutes=duration_minutes)
    service_title = "Беседка №8" if service_type == "gazebo" else "Баня с бассейном"
    raw_payload = {
        "id": record_id,
        "deleted": False,
        "comment": "local regression Telegram record",
        "client": {"name": "Кирилл", "phone": phone},
        "services": [{"id": yclients_service_id, "title": service_title}],
    }
    record = {
        "yclients_record_id": record_id,
        "company_id": "local",
        "service_type": service_type,
        "yclients_service_id": yclients_service_id,
        "yclients_staff_id": "local_staff",
        "service_title": service_title,
        "staff_title": service_title,
        "client_name": "Кирилл",
        "client_phone": phone,
        "status": "active",
        "attendance": 0,
        "start_at": start_at,
        "end_at": end_at,
        "duration_minutes": duration_minutes,
        "raw_payload": raw_payload,
        "synced_at": now,
        "updated_at": now,
    }
    yclients_records_repo.upsert_record(conn, record)
    yclients_records_repo.upsert_busy_interval(
        conn,
        {
            "source": "yclients",
            "source_record_id": record_id,
            "service_type": service_type,
            "yclients_service_id": yclients_service_id,
            "yclients_staff_id": "local_staff",
            "title": service_title,
            "start_at": start_at,
            "end_at": end_at,
            "status": "active",
            "raw_payload": raw_payload,
            "updated_at": now,
        },
    )


def _test_post_booking_summary_always_uses_db(now: datetime) -> Check:
    suffix = "summary_uses_db"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_summary_bath",
        phone="+79990000007",
    )
    _add_paid_booking(created, now, service_type="gazebo", booking_date=date(2026, 6, 25), provider_record_id="local_summary_gazebo")
    original_classifier = message_handler.classify_post_booking_message
    original_create_missing = message_handler.create_missing_yclients_records
    called = {"value": False}

    def fake_classifier(*_args: Any, **_kwargs: Any) -> PostBookingResponse:
        called["value"] = True
        return PostBookingResponse(intent="current_booking_question", reply_to_user="У вас одна бронь")

    message_handler.classify_post_booking_message = fake_classifier
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "какие теперь у меня есть брони?", now)
        reply2 = _send(suffix, "и это все?", now)
        ok = (
            "2 брони" in reply
            and "Баня" in reply
            and "Бесед" in reply
            and "2 брони" in reply2
            and not called["value"]
        )
        return Check("post booking summary always uses db", ok, f"{reply} | {reply2}")
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.create_missing_yclients_records = original_create_missing


def _test_booking_summary_does_not_merge_shared_phone(now: datetime) -> Check:
    shared_phone = "+79968533502"
    _create_paid_booking_for_action(
        "shared_phone_a",
        now,
        service_type="gazebo",
        booking_date=date(2026, 5, 30),
        yclients_service_id="18201063",
        provider_record_id="local_shared_phone_a",
        phone=shared_phone,
    )
    _create_paid_booking_for_action(
        "shared_phone_b",
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 1),
        yclients_service_id="18201055",
        provider_record_id="local_shared_phone_b",
        phone=shared_phone,
    )
    reply = _send("shared_phone_b", "какие у меня сейчас брони?", now)
    ok = "1 бронь" in reply and "1 июня" in reply and "30 мая" not in reply
    return Check("booking summary does not merge shared phone", ok, reply)


def _test_reschedule_selects_service_after_list(now: datetime) -> Check:
    suffix = "reschedule_select_service"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_reschedule_select_bath",
        phone="+79990000008",
    )
    _add_paid_booking(created, now, service_type="gazebo", booking_date=date(2026, 6, 25), provider_record_id="local_reschedule_select_gazebo")
    original_delete = message_handler.delete_yclients_record_for_booking
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "ok", ["Баня: свободно"])
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        first = _send(suffix, "могу ли я перенести с 25 на 26 то же время?", now)
        second = _send(suffix, "баню которая на 25 июня хочу перенести на 26", now)
        ok = (
            "какую бронь переносим" in first.lower()
            and "перенести бронь" in second.lower()
            and "баня" in second.lower()
            and "26 июня" in second
        )
        return Check("reschedule selects service after list", ok, f"{first} | {second}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _test_reschedule_uses_target_date_not_source_date(now: datetime) -> Check:
    suffix = "reschedule_target_date"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 5, 23),
        yclients_service_id="18201065",
        provider_record_id="local_reschedule_target_gazebo8",
        phone="+79990000009",
    )
    _add_paid_booking(
        created,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        provider_record_id="local_reschedule_target_bath",
    )
    _add_paid_booking(
        created,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 25),
        provider_record_id="local_reschedule_target_gazebo5",
        yclients_service_id="18201062",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records
    seen: list[dict[str, Any]] = []

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = dict(kwargs.get("form_data") or {})
        seen.append(form)
        return AvailabilityResult(True, "ok", [f"{form.get('service_variant') or 'Бронь'}: свободно"])

    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.check_availability = fake_availability
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "могу ли я беседку на 8 которая на 23 мая перенеси на 26 июня на то же время", now)
        checked = seen[-1] if seen else {}
        ok = (
            "26 июня" in reply
            and checked.get("date") == "2026-06-26"
            and checked.get("service_type") == "gazebo"
            and checked.get("service_variant") == "Беседка №8"
        )
        return Check("reschedule uses target date not source date", ok, f"{reply} | checked={checked}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _test_reschedule_typo_pernesti_uses_target_date(now: datetime) -> Check:
    suffix = "reschedule_typo_pernesti"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_reschedule_typo_bath",
        phone="+79990000010",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records
    seen: list[dict[str, Any]] = []

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = dict(kwargs.get("form_data") or {})
        seen.append(form)
        return AvailabilityResult(True, "ok", ["Баня: свободно"])

    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.check_availability = fake_availability
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "тогда баня которая на 25 июня пернести на 26 июня на то же время", now)
        checked = seen[-1] if seen else {}
        ok = "26 июня" in reply and checked.get("date") == "2026-06-26"
        return Check("reschedule typo pernesti uses target date", ok, f"{reply} | checked={checked}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _test_reschedule_keeps_initial_date_after_selection(now: datetime) -> Check:
    suffix = "reschedule_keeps_initial_date"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 29),
        yclients_service_id="18201062",
        provider_record_id="local_reschedule_initial_gazebo5",
        phone="+79990000016",
    )
    _add_paid_booking(
        created,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 29),
        provider_record_id="local_reschedule_initial_gazebo2",
        yclients_service_id="18201056",
    )
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        first = _send(suffix, "хочу перенести бронь на 30 июня", now)
        second = _send(suffix, "вторую бронь", now)
        state = _latest_state(suffix)
        flow = (state.get("form_data") or {}).get("reschedule_flow") or {}
        ok = (
            "какую бронь переносим" in first.lower()
            and "30 июня" in second
            and "во сколько" in second.lower()
            and "новую дату" not in second.lower()
            and flow.get("date") == "2026-06-30"
            and flow.get("booking_id")
        )
        return Check("reschedule keeps initial date after selection", ok, f"{first} | {second} | {flow}")
    finally:
        message_handler.create_missing_yclients_records = original_create_missing


def _test_reschedule_can_change_gazebo_variant(now: datetime) -> Check:
    suffix = "reschedule_change_gazebo_variant"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 29),
        yclients_service_id="18201065",
        provider_record_id="local_reschedule_change_gazebo8",
        phone="+79990000017",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records
    original_create_record = message_handler.create_yclients_record_for_booking
    seen: list[dict[str, Any]] = []

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = dict(kwargs.get("form_data") or {})
        seen.append(form)
        return AvailabilityResult(True, "ok", [f"{form.get('service_variant')}: свободно"])

    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.check_availability = fake_availability
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    message_handler.create_yclients_record_for_booking = lambda *_args, **_kwargs: {}
    try:
        reply = _send(suffix, "перенеси беседку 8 на 30 июня на беседку 6 на то же время", now)
        done = _send(suffix, "да", now)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sh.yclients_service_id
                    FROM bookings b
                    JOIN conversations c ON c.id = b.conversation_id
                    JOIN users u ON u.id = c.user_id
                    JOIN slot_holds sh ON sh.id = b.slot_hold_id
                    WHERE u.external_id = %s
                    LIMIT 1
                    """,
                    (TEST_PREFIX + suffix,),
                )
                row = cur.fetchone()
        checked = seen[-1] if seen else {}
        ok = (
            "30 июня" in reply
            and "Беседка №6" in reply
            and "перенесла" in done.lower()
            and row
            and row["yclients_service_id"] == "18201063"
            and checked.get("service_variant") == "Беседка №6"
        )
        return Check("reschedule can change gazebo variant", ok, f"{reply} | {done} | {row} | checked={checked}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing
        message_handler.create_yclients_record_for_booking = original_create_record


def _test_reschedule_flow_answers_options_instead_of_loop(now: datetime) -> Check:
    suffix = "reschedule_options_no_loop"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 26),
        yclients_service_id="18201061",
        provider_record_id="local_reschedule_options_gazebo1",
        phone="+79990000013",
    )
    _add_paid_booking(created, now, service_type="gazebo", booking_date=date(2026, 6, 26), provider_record_id="local_reschedule_options_gazebo2")
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    with get_connection() as conn:
        conversation = conversations_repo.get_by_id(conn, created["conversation"]["id"])
        form = dict((conversation or {}).get("form_data") or {})
        form["reschedule_flow"] = {"stage": "reschedule", "booking_id": None}
        conversations_repo.update_after_message(conn, created["conversation"]["id"], now, form_data=form)
    try:
        reply = _send(suffix, "а как я еще могу перенести", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            "можно перенести" in reply.lower()
            and "обе брони" in reply.lower()
            and "какую бронь переносим" not in reply.lower()
            and not form.get("reschedule_flow")
            and (form.get("swap_reschedule_flow") or {}).get("stage") == "collect_swap"
        )
        return Check("reschedule flow answers options instead of loop", ok, f"{reply} | {form}")
    finally:
        message_handler.create_missing_yclients_records = original_create_missing


def _test_reschedule_flow_answers_info_question(now: datetime) -> Check:
    suffix = "reschedule_info_question"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 26),
        yclients_service_id="18201061",
        provider_record_id="local_reschedule_info_gazebo1",
        phone="+79990000014",
    )
    _add_paid_booking(created, now, service_type="gazebo", booking_date=date(2026, 6, 26), provider_record_id="local_reschedule_info_gazebo2")
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    with get_connection() as conn:
        conversation = conversations_repo.get_by_id(conn, created["conversation"]["id"])
        form = dict((conversation or {}).get("form_data") or {})
        form["reschedule_flow"] = {"stage": "reschedule", "booking_id": None}
        conversations_repo.update_after_message(conn, created["conversation"]["id"], now, form_data=form)
    try:
        reply = _send(suffix, "а есть парковка у вас", now)
        ok = "парковка есть" in reply.lower() and "какую бронь переносим" not in reply.lower()
        return Check("reschedule flow answers info question", ok, reply)
    finally:
        message_handler.create_missing_yclients_records = original_create_missing


def _test_multi_reschedule_same_date_for_all_bookings(now: datetime) -> Check:
    suffix = "multi_reschedule_same_date"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 26),
        yclients_service_id="18201061",
        provider_record_id="local_multi_reschedule_gazebo1",
        phone="+79990000015",
    )
    _add_paid_booking(created, now, service_type="gazebo", booking_date=date(2026, 6, 26), provider_record_id="local_multi_reschedule_gazebo2")
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records
    seen: list[dict[str, Any]] = []

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        seen.append(kwargs.get("form_data") or {})
        return AvailabilityResult(True, "ok", ["Беседка: свободно"])

    message_handler.check_availability = fake_availability
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "хочу перенести обе брони на 27 число", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        flow = form.get("swap_reschedule_flow") or {}
        assignments = flow.get("assignments") or []
        ignored = set()
        for item in seen:
            ignored.update(item.get("ignore_source_record_ids") or [])
        ok = (
            "27 июня" in reply
            and "подтверждаете перенос" in reply.lower()
            and flow.get("stage") == "confirm_swap"
            and len(assignments) == 2
            and {item.get("date") for item in assignments} == {"2026-06-27"}
            and {"local_multi_reschedule_gazebo1", "local_multi_reschedule_gazebo2"} <= ignored
        )
        return Check("multi reschedule same date for all bookings", ok, f"{reply} | {flow} | ignored={ignored}")
    finally:
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _create_paid_booking_for_action(
    suffix: str,
    now: datetime,
    *,
    service_type: str,
    booking_date: date,
    yclients_service_id: str,
    provider_record_id: str,
    phone: str,
) -> dict[str, Any]:
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type=service_type,
            service_variant="Беседка №8" if service_type == "gazebo" else None,
            date=booking_date.isoformat(),
            time="18:00",
            duration=6,
            guests_count=5,
            event_format="спокойный отдых",
            client_name="Кирилл",
            phone=phone,
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="payment_paid",
            current_step="reserved",
            next_step="payment_status",
        )
        hold = slot_holds_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            service_type=service_type,
            yclients_service_id=yclients_service_id,
            slot_date=booking_date,
            slot_time=time(18, 0),
            duration_minutes=360,
            expires_at=now + timedelta(minutes=10),
        )
        booking = bookings_repo.create_from_hold(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            slot_hold_id=hold["id"],
            service_type=service_type,
            booking_date=booking_date,
            booking_time=time(18, 0),
            duration_minutes=360,
            client_name="Кирилл",
            phone=phone,
            guests_count=5,
            event_format="спокойный отдых",
            preferences=None,
            upsell_items=["не нужны"],
            status="created_in_yclients",
            payment_status="paid",
        )
        bookings_repo.mark_yclients_created(conn, booking_id=booking["id"], yclients_record_id=provider_record_id)
        _upsert_test_yclients_record(
            conn,
            now=now,
            record_id=provider_record_id,
            service_type=service_type,
            yclients_service_id=yclients_service_id,
            start_date=booking_date,
            start_time=time(18, 0),
            duration_minutes=360,
            phone=phone,
        )
        slot_holds_repo.mark_converted(conn, hold_id=hold["id"], now=now)
    return created


def _test_paid_cancel_asks_confirmation(now: datetime) -> Check:
    suffix = "paid_cancel"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 5, 23),
        yclients_service_id="18201061",
        provider_record_id="local_cancel_record",
        phone="+79990000004",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "можно беседку на 23 мая удалить?", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        confirm_ok = "аванс" in reply.lower() and "точно" in reply.lower() and form.get("cancel_flow")
        done = _send(suffix, "да", now)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT b.status
                    FROM bookings b
                    JOIN conversations c ON c.id = b.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id = %s
                    LIMIT 1
                    """,
                    (TEST_PREFIX + suffix,),
                )
                booking_status = cur.fetchone()["status"]
        ok = confirm_ok and "отменила" in done.lower() and booking_status == "cancelled"
        return Check("paid cancel asks confirmation", ok, f"{reply} | {done} | status={booking_status}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing


def _test_paid_cancel_all_asks_single_confirmation(now: datetime) -> Check:
    suffix = "paid_cancel_all"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 5, 27),
        yclients_service_id="18201055",
        provider_record_id="local_cancel_all_gazebo1",
        phone="+79990000018",
    )
    _add_paid_booking(
        created,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 1),
        provider_record_id="local_cancel_all_gazebo2",
        yclients_service_id="18201056",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "удали все брони", now)
        done = _send(suffix, "да", now)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*) AS active_count
                    FROM bookings b
                    JOIN conversations c ON c.id = b.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id = %s
                      AND b.status != 'cancelled'
                    """,
                    (TEST_PREFIX + suffix,),
                )
                active_count = cur.fetchone()["active_count"]
        ok = (
            "могу отменить эти брони" in reply.lower()
            and "авансы" in reply.lower()
            and "отменила брони" in done.lower()
            and active_count == 0
        )
        return Check("paid cancel all asks single confirmation", ok, f"{reply} | {done} | active={active_count}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing


def _test_paid_bathhouse_cancel_without_hold(now: datetime) -> Check:
    suffix = "paid_bath_cancel_no_hold"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_cancel_bath_record",
        phone="+79990000011",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "хочу баню которая на 25 июня отменить", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        confirm_ok = (
            "баня" in reply.lower()
            and "аванс" in reply.lower()
            and "точно" in reply.lower()
            and (form.get("cancel_flow") or {}).get("stage") == "confirm_cancel"
        )
        done = _send(suffix, "да", now)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT b.status
                    FROM bookings b
                    JOIN conversations c ON c.id = b.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id = %s
                    LIMIT 1
                    """,
                    (TEST_PREFIX + suffix,),
                )
                booking_status = cur.fetchone()["status"]
        ok = confirm_ok and "отменила" in done.lower() and booking_status == "cancelled"
        return Check("paid bathhouse cancel without hold", ok, f"{reply} | {done} | status={booking_status}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing


def _test_ai_change_type_cancel_starts_flow(now: datetime) -> Check:
    suffix = "ai_change_cancel"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_ai_cancel_bath_record",
        phone="+79990000012",
    )
    original_classifier = message_handler.classify_post_booking_message
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records

    def fake_classifier(*_args: Any, **_kwargs: Any) -> PostBookingResponse:
        return PostBookingResponse(
            intent="change_existing_booking",
            confidence=0.98,
            change_type="cancel",
            reply_to_user="",
        )

    message_handler.classify_post_booking_message = fake_classifier
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "планы поменялись, баня 25 июня не нужна", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            "аванс" in reply.lower()
            and "точно" in reply.lower()
            and (form.get("cancel_flow") or {}).get("stage") == "confirm_cancel"
        )
        return Check("ai change_type cancel starts flow", ok, f"{reply} | {form}")
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing


def _test_ai_change_type_reschedule_starts_flow(now: datetime) -> Check:
    suffix = "ai_change_reschedule"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 25),
        yclients_service_id="18490331",
        provider_record_id="local_ai_reschedule_bath_record",
        phone="+79990000013",
    )
    original_classifier = message_handler.classify_post_booking_message
    original_delete = message_handler.delete_yclients_record_for_booking
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records
    original_create_record = message_handler.create_yclients_record_for_booking

    def fake_classifier(*_args: Any, **_kwargs: Any) -> PostBookingResponse:
        return PostBookingResponse(
            intent="change_existing_booking",
            confidence=0.98,
            change_type="reschedule",
            reply_to_user="",
        )

    message_handler.classify_post_booking_message = fake_classifier
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(
        True,
        "ok",
        ["Баня: свободно"],
    )
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    message_handler.create_yclients_record_for_booking = lambda *_args, **_kwargs: {}
    try:
        reply = _send(suffix, "давайте сместим баню на 26 июня на то же время", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        flow = form.get("reschedule_flow") or {}
        ok = (
            "26 июня" in reply
            and "подтверждаете" in reply.lower()
            and flow.get("stage") == "confirm_reschedule"
            and flow.get("date") == "2026-06-26"
        )
        return Check("ai change_type reschedule starts flow", ok, f"{reply} | {flow}")
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing
        message_handler.create_yclients_record_for_booking = original_create_record


def _test_paid_reschedule_asks_confirmation(now: datetime) -> Check:
    suffix = "paid_reschedule"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 23),
        yclients_service_id="18490331",
        provider_record_id="local_reschedule_record",
        phone="+79990000005",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records
    original_create_record = message_handler.create_yclients_record_for_booking
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(
        True,
        "ok",
        ["Баня: свободно"],
    )
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    message_handler.create_yclients_record_for_booking = lambda *_args, **_kwargs: {}
    try:
        reply = _send(suffix, "баня которая 23 июня можно перенести на 24 на то же время?", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        confirm_ok = (
            "24 июня" in reply
            and "подтверждаете" in reply.lower()
            and (form.get("reschedule_flow") or {}).get("stage") == "confirm_reschedule"
        )
        done = _send(suffix, "да", now)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT booking_date
                    FROM bookings b
                    JOIN conversations c ON c.id = b.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id = %s
                    LIMIT 1
                    """,
                    (TEST_PREFIX + suffix,),
                )
                booking_date_value = cur.fetchone()["booking_date"]
        ok = confirm_ok and "перенесла" in done.lower() and str(booking_date_value) == "2026-06-24"
        return Check("paid reschedule asks confirmation", ok, f"{reply} | {done} | date={booking_date_value}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing
        message_handler.create_yclients_record_for_booking = original_create_record


def _test_generic_second_booking_keeps_only_contact(now: datetime) -> Check:
    suffix = "generic_second_booking"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №5",
            date="2026-06-21",
            time="12:00",
            duration=20,
            guests_count=15,
            client_name="Евгений",
            phone="+79875426252",
        ),
    )
    _create_active_hold(created["conversation"], created["user"], now)
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="service_type",
            changed_fields=[],
            form_data_patch={},
            reply_to_user="",
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    try:
        _send(suffix, "еще одну надо", now)
        reply = _send(suffix, "баню", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("client_name") == "Евгений"
            and form.get("phone") == "+79875426252"
            and form.get("service_type") == "bathhouse"
            and not form.get("date")
            and not form.get("time")
            and not form.get("duration")
            and "21 июня" not in reply
            and "12:00" not in reply
        )
        return Check("generic second booking keeps only contact", ok, f"{reply} | {form}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_price_replies_use_service_map() -> Check:
    form = _base_form(
        service_type="bathhouse",
        service_variant=None,
        date="2026-07-18",
        time="17:00",
        duration=5,
    )
    reply = message_handler._price_reply_if_known("а сколько денег стоит баня", form)
    ok = bool(reply and "13 250 ₽" in reply and "3 000" not in reply)
    return Check("price replies use service map", ok, str(reply))


def _test_addon_price_question_does_not_add_item() -> Check:
    form = _base_form(service_type="gazebo", service_variant="Беседка №6")
    patch = message_handler._upsell_items_patch("а скольок стоит решетка?")
    reply = message_handler._price_reply_if_known("а скольок стоит решетка?", form)
    ok = patch == {} and bool(reply and "500 ₽" in reply and "добавим" not in reply.lower())
    return Check("addon price question does not add item", ok, f"{patch} | {reply}")


def _test_prepayment_price_question_not_addons() -> Check:
    form = _base_form(service_type="gazebo", service_variant="Беседка №6")
    reply = message_handler._price_reply_if_known("а сколько стоит предоплата", form)
    ok = bool(reply and "Предоплата" in reply and "Кальян" not in reply and "Мангальный" not in reply)
    return Check("prepayment price question not addons", ok, str(reply))


def _test_brooms_are_forbidden() -> Check:
    form = _base_form(service_type="bathhouse")
    patch = message_handler._upsell_items_patch("веники надо")
    reply = message_handler._deterministic_info_reply("веники надо", form)
    ok = patch == {} and bool(reply and "нельзя" in reply.lower() and "штраф" in reply.lower())
    return Check("brooms are forbidden", ok, f"{patch} | {reply}")


def _test_mosquito_question_during_confirmation() -> Check:
    form = _base_form(service_type="gazebo", service_variant="Крытая беседка")
    reply = message_handler._awaiting_confirmation_side_reply(
        text="а каморов там много",
        form_data=form,
        history=[],
    )
    ok = "раз в неделю" in reply.lower() and "репеллент" in reply.lower()
    return Check("mosquito question during confirmation", ok, reply)


def _test_bare_duration_answer() -> Check:
    patch = message_handler._current_step_patch("на 5", "duration", None)
    ok = patch.get("duration") == 5
    return Check("bare duration answer", ok, str(patch))


def _test_confirmation_time_correction_rechecks(now: datetime) -> Check:
    suffix = "confirmation_time_correction"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(service_type="bathhouse", date="2026-06-21", time="12:00", duration=20),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="awaiting_confirmation",
            current_step="awaiting_confirmation",
            next_step="confirmation",
        )
    original_availability = message_handler.check_availability
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(
        True,
        "ok",
        ["Баня: свободно"],
    )
    try:
        reply = _send(suffix, "нет 18 июля с 17 до 22", now)
        form = _latest_state(suffix).get("form_data") or {}
        ok = (
            form.get("date") == "2026-07-18"
            and form.get("time") == "17:00"
            and form.get("duration") == 5
            and "проверяю" not in reply.lower()
            and "подтверждаете" in reply.lower()
        )
        return Check("confirmation time correction rechecks", ok, f"{reply} | {form}")
    finally:
        message_handler.check_availability = original_availability


def _test_gazebo_selected_variant_capacity_uses_known_free_list(now: datetime) -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №5",
        date="2026-05-30",
        time="18:00",
        duration=6,
        guests_count=25,
    )
    form["last_available_gazebo_variants"] = ["Беседка №5", "Беседка №2", "Беседка №4"]
    original_next_free = message_handler._next_free_dates_reply
    message_handler._next_free_dates_reply = lambda *_args, **_kwargs: "1 июня: Беседка №1\nКакую дату выбираете?"
    try:
        with get_connection() as conn:
            result = message_handler._gazebo_capacity_mismatch_reply(
                conn,
                {"id": 1, "user_id": 1},
                form,
                now,
            )
        if not result:
            return Check("gazebo selected variant capacity uses known free list", False, "no mismatch")
        reply, current_step, next_key, updated = result
        ok = (
            "до 10 человек" in reply
            and "25" in reply
            and "Беседка №8" not in reply
            and "Беседка №1" in reply
            and current_step == "awaiting_new_date"
            and next_key == "date"
            and not updated.get("service_variant")
        )
        return Check("gazebo selected variant capacity uses known free list", ok, f"{reply} | {updated}")
    finally:
        message_handler._next_free_dates_reply = original_next_free


def _test_stale_form_after_two_hours_asks_choice(now: datetime) -> Check:
    suffix = "stale_form_choice"
    old_time = now - timedelta(hours=3)
    created = _create_reserved_conversation(
        suffix,
        old_time,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №5",
            date="2026-06-30",
            time=None,
            duration=None,
            guests_count=5,
            event_format="день рождения",
            client_name="Кирилл",
            phone="+79990000022",
            upsell_items=[],
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            old_time,
            status="waiting_user",
            current_step="time",
            next_step="time",
            form_data=created["conversation"]["form_data"],
        )
    first = _send(suffix, "хочу баню", now)
    first_state = _latest_state(suffix)
    first_form = first_state.get("form_data") or {}
    second = _send(suffix, "новую", now + timedelta(seconds=10))
    second_state = _latest_state(suffix)
    second_form = second_state.get("form_data") or {}
    ok = (
        "продолжаем" in first.lower()
        and "новую" in first.lower()
        and first_form.get("stale_form_flow")
        and second_form.get("client_name") == "Кирилл"
        and second_form.get("phone") == "+79990000022"
        and not second_form.get("service_type")
        and not second_form.get("date")
        and not second_form.get("time")
        and not second_form.get("duration")
        and not second_form.get("guests_count")
        and not second_form.get("event_format")
        and second_state.get("current_step") == "service_type"
    )
    return Check("stale form after two hours asks choice", ok, f"{first} | {second} | {second_form}")


def _test_ai_event_format_is_not_invented(now: datetime) -> Check:
    suffix = "ai_event_format_not_invented"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №6",
            date="2026-06-30",
            time="18:00",
            duration=6,
            guests_count=10,
            event_format=None,
            client_name=None,
            phone=None,
            upsell_items=[],
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="client_name",
            next_step="client_name",
            form_data=created["conversation"]["form_data"],
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="client_name",
            changed_fields=["client_name", "phone", "event_format"],
            form_data_patch={
                "client_name": "Наталья",
                "phone": "+79991369991",
                "event_format": "день рождения",
            },
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    try:
        reply = _send(suffix, "Наталья 89991369991", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("client_name") == "Наталья"
            and form.get("phone") == "+79991369991"
            and not form.get("event_format")
            and state.get("next_step") == "event_format"
        )
        return Check("ai event_format is not invented", ok, f"{reply} | {form}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_basic_upsell_is_saved_to_yclients_comment() -> Check:
    patch = message_handler._upsell_items_patch("давайте базовый набор")
    payload = build_book_record_payload(
        {
            "id": 900001,
            "service_type": "gazebo",
            "hold_yclients_service_id": "18201056",
            "booking_date": date(2026, 6, 30),
            "booking_time": time(18, 0),
            "duration_minutes": 360,
            "client_name": "Кирилл",
            "phone": "+79990000001",
            "guests_count": 8,
            "event_format": "компания друзей",
            "upsell_items": patch.get("upsell_items") or [],
        }
    )
    comment = payload.get("comment") or ""
    ok = patch.get("upsell_items") == ["базовый мангальный набор"] and "базовый мангальный набор" in comment
    return Check("basic upsell is saved to yclients comment", ok, f"{patch} | {comment}")


def _test_reschedule_preferences_recalculate_options(now: datetime) -> Check:
    suffix = "reschedule_recalc_options"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 7, 16),
        yclients_service_id="18201055",
        provider_record_id="local_reschedule_recalc_gazebo1",
        phone="+79990000023",
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE bookings
                SET guests_count = 22
                WHERE id IN (
                    SELECT b.id
                    FROM bookings b
                    JOIN conversations c ON c.id = b.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id = %s
                )
                """,
                (TEST_PREFIX + suffix,),
            )
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        return AvailabilityResult(
            True,
            "ok",
            [
                "Беседка №3: свободно",
                "Беседка №8: свободно",
                "Беседка №5: свободно",
            ],
        )

    message_handler.check_availability = fake_availability
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        first = _send(suffix, "хочу перенести на поменьше и со светом", now)
        second = _send(suffix, "нас 10 человек", now)
        state = _latest_state(suffix)
        flow = (state.get("form_data") or {}).get("reschedule_flow") or {}
        ok = (
            "оставляем ту же" not in first.lower()
            and "Беседка №3" in first
            and "Беседка №8" in first
            and "Беседка №5" not in first
            and "Беседка №3" in second
            and "Беседка №8" in second
            and "Беседка №5" not in second
            and flow.get("stage") == "choose_reschedule_variant"
            and flow.get("guests_count") == 10
        )
        return Check("reschedule preferences recalculate options", ok, f"{first} | {second} | {flow}")
    finally:
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _test_reschedule_da_da_confirms_and_clears_flow(now: datetime) -> Check:
    suffix = "reschedule_da_da"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="bathhouse",
        booking_date=date(2026, 6, 23),
        yclients_service_id="18490331",
        provider_record_id="local_reschedule_da_da_bath",
        phone="+79990000024",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records
    original_create_record = message_handler.create_yclients_record_for_booking
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "ok", ["Баня: свободно"])
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    message_handler.create_yclients_record_for_booking = lambda *_args, **_kwargs: {}
    try:
        first = _send(suffix, "перенести баню на 24 июня на то же время", now)
        done = _send(suffix, "да да", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT b.booking_date
                    FROM bookings b
                    JOIN conversations c ON c.id = b.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id = %s
                    LIMIT 1
                    """,
                    (TEST_PREFIX + suffix,),
                )
                booking_date_value = cur.fetchone()["booking_date"]
        ok = (
            "подтверждаете" in first.lower()
            and "перенесла" in done.lower()
            and not form.get("reschedule_flow")
            and str(booking_date_value) == "2026-06-24"
        )
        return Check("reschedule da da confirms and clears flow", ok, f"{first} | {done} | {form}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing
        message_handler.create_yclients_record_for_booking = original_create_record


def _test_booking_reminder_yes_and_no(now: datetime) -> Check:
    yes_suffix = "reminder_yes"
    no_suffix = "reminder_no"
    tomorrow = now.date() + timedelta(days=1)
    _create_paid_booking_for_action(
        yes_suffix,
        now,
        service_type="gazebo",
        booking_date=tomorrow,
        yclients_service_id="18201062",
        provider_record_id="local_reminder_yes_gazebo5",
        phone="+79990000025",
    )
    _create_paid_booking_for_action(
        no_suffix,
        now,
        service_type="gazebo",
        booking_date=tomorrow,
        yclients_service_id="18201063",
        provider_record_id="local_reminder_no_gazebo6",
        phone="+79990000026",
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE bookings b
                SET reminder_sent_at = %s,
                    reminder_response = NULL
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE c.id = b.conversation_id
                  AND u.external_id IN (%s, %s)
                """,
                (now - timedelta(minutes=5), TEST_PREFIX + yes_suffix, TEST_PREFIX + no_suffix),
            )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        yes_reply = _send(yes_suffix, "да да", now)
        no_reply = _send(no_suffix, "нет, не придем", now)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.external_id, b.status, b.reminder_response
                    FROM bookings b
                    JOIN conversations c ON c.id = b.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id IN (%s, %s)
                    ORDER BY u.external_id
                    """,
                    (TEST_PREFIX + yes_suffix, TEST_PREFIX + no_suffix),
                )
                rows = {row["external_id"]: dict(row) for row in cur.fetchall()}
        yes_row = rows.get(TEST_PREFIX + yes_suffix) or {}
        no_row = rows.get(TEST_PREFIX + no_suffix) or {}
        ok = (
            "ждём вас завтра" in yes_reply.lower()
            and yes_row.get("reminder_response") == "yes"
            and "отменила" in no_reply.lower()
            and no_row.get("reminder_response") == "no"
            and no_row.get("status") == "cancelled"
        )
        return Check("booking reminder yes and no", ok, f"{yes_reply} | {no_reply} | {rows}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing


def main() -> None:
    settings = get_settings()
    now = datetime(2026, 5, 20, 12, 0, tzinfo=ZoneInfo(settings.app_timezone))
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    _cleanup()
    checks: list[Check] = []
    try:
        checks.append(_test_second_booking_does_not_inherit_old_slot(now))
        checks.append(_test_new_service_from_waiting_date_resets_old_slot(now))
        checks.append(_test_reserved_yes_retries_payment_link(now))
        checks.append(_test_paid_status_refreshes_on_any_message(now))
        checks.append(_test_confirmation_info_answer_without_extra_ai(now))
        checks.append(_test_post_booking_info_fallback_when_ai_unavailable(now))
        checks.append(_test_unconfigured_service_does_not_claim_free(now))
        checks.append(_test_summer_gazebo_alias_uses_gazebo(now))
        checks.append(_test_gazebo_bathhouse_alias_starts_with_gazebo(now))
        checks.append(_test_bathhouse_gazebo_order_starts_with_bathhouse(now))
        checks.append(_test_deterministic_date_beats_stale_ai(now))
        checks.append(_test_gazebo_recommendations_use_only_available())
        checks.append(_test_gazebo_capacity_filter_rejects_tight_options())
        checks.append(_test_gazebo_date_reply_asks_guests_before_choice())
        checks.append(_test_next_free_dates_filter_gazebos_by_guests(now))
        checks.append(_test_gazebo_start_time_defaults_until_morning(now))
        checks.append(_test_gazebo_open_ended_duration_overrides_ai_guess())
        checks.append(_test_media_waits_for_date_and_guests())
        checks.append(_test_explicit_photo_request_ignores_availability_text())
        checks.append(_test_explicit_photo_request_bypasses_ai(now))
        checks.append(_test_explicit_service_photo_request_ignores_old_gazebo_state(now))
        checks.append(_test_price_question_during_form_not_booking_summary(now))
        checks.append(_test_single_available_gazebo_is_auto_selected())
        checks.append(_test_gazebo_variant_is_not_guessed())
        checks.append(_test_booking_summary_counts_all_bookings(now))
        checks.append(_test_new_conversation_sees_old_user_booking(now))
        checks.append(_test_new_conversation_sees_old_summary(now))
        checks.append(_test_customer_templates_do_not_mention_admin(now))
        checks.append(_test_short_yes_confirms())
        checks.append(_test_bare_weekday_requires_confirmation(now))
        checks.append(_test_weekday_confirmation_yes_uses_saved_candidate(now))
        checks.append(_test_first_upsell_no_gets_soft_push())
        checks.append(_test_first_upsell_flow_before_phone(now))
        checks.append(_test_prefilled_first_upsell_no_still_gets_soft_push(now))
        checks.append(_test_duration_24_formats_as_hours())
        checks.append(_test_positive_upsell_goes_to_next_step(now))
        checks.append(_test_free_dates_lookup_after_no_availability(now))
        checks.append(_test_waitlist_decline_does_not_handoff(now))
        checks.append(_test_location_question_does_not_handoff())
        checks.append(_test_gazebo_media_selection())
        checks.append(_test_post_booking_summary_always_uses_db(now))
        checks.append(_test_booking_summary_does_not_merge_shared_phone(now))
        checks.append(_test_reschedule_selects_service_after_list(now))
        checks.append(_test_reschedule_uses_target_date_not_source_date(now))
        checks.append(_test_reschedule_typo_pernesti_uses_target_date(now))
        checks.append(_test_reschedule_keeps_initial_date_after_selection(now))
        checks.append(_test_reschedule_can_change_gazebo_variant(now))
        checks.append(_test_reschedule_flow_answers_options_instead_of_loop(now))
        checks.append(_test_reschedule_flow_answers_info_question(now))
        checks.append(_test_multi_reschedule_same_date_for_all_bookings(now))
        checks.append(_test_paid_cancel_asks_confirmation(now))
        checks.append(_test_paid_cancel_all_asks_single_confirmation(now))
        checks.append(_test_paid_bathhouse_cancel_without_hold(now))
        checks.append(_test_ai_change_type_cancel_starts_flow(now))
        checks.append(_test_ai_change_type_reschedule_starts_flow(now))
        checks.append(_test_paid_reschedule_asks_confirmation(now))
        checks.append(_test_generic_second_booking_keeps_only_contact(now))
        checks.append(_test_price_replies_use_service_map())
        checks.append(_test_addon_price_question_does_not_add_item())
        checks.append(_test_prepayment_price_question_not_addons())
        checks.append(_test_brooms_are_forbidden())
        checks.append(_test_mosquito_question_during_confirmation())
        checks.append(_test_bare_duration_answer())
        checks.append(_test_confirmation_time_correction_rechecks(now))
        checks.append(_test_gazebo_selected_variant_capacity_uses_known_free_list(now))
        checks.append(_test_stale_form_after_two_hours_asks_choice(now))
        checks.append(_test_ai_event_format_is_not_invented(now))
        checks.append(_test_basic_upsell_is_saved_to_yclients_comment())
        checks.append(_test_reschedule_preferences_recalculate_options(now))
        checks.append(_test_reschedule_da_da_confirms_and_clears_flow(now))
        checks.append(_test_booking_reminder_yes_and_no(now))
    finally:
        message_handler.create_missing_yclients_records = original_create_missing
        _cleanup()

    failed = [check for check in checks if not check.ok]
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        print(f"{marker}: {check.name}: {check.details}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
