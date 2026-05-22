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
from app.db.repositories import bookings_repo, conversations_repo, payments_repo, slot_holds_repo, users_repo  # noqa: E402
from app.services.availability_service import AvailabilityResult  # noqa: E402
from app.services import message_handler  # noqa: E402
from app.services.media_service import media_for_client_message  # noqa: E402
from app.services.message_handler import IncomingMessage, handle_incoming  # noqa: E402


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
                cur.execute("DELETE FROM conversations WHERE id = ANY(%s)", (conversation_ids,))
            if user_ids:
                cur.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))


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
    all_media = media_for_client_message("какие беседки есть?", "Беседка №1, Беседка №2, Беседка №8")
    specific = media_for_client_message("покажи беседку 8", "Вот беседка №8")
    location = media_for_client_message("где вы находитесь?", "Адрес: Выкса")
    ok = (
        len(all_media) >= 6
        and [path.name for path in specific] == ["besedka8png.png"]
        and not location
    )
    return Check(
        "gazebo media selection",
        ok,
        f"all={len(all_media)}, specific={[path.name for path in specific]}, location={location}",
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
        slot_holds_repo.mark_converted(conn, hold_id=hold["id"], now=now)


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
    called = {"value": False}

    def fake_classifier(*_args: Any, **_kwargs: Any) -> PostBookingResponse:
        called["value"] = True
        return PostBookingResponse(intent="current_booking_question", reply_to_user="У вас одна бронь")

    message_handler.classify_post_booking_message = fake_classifier
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
        reply = _send(suffix, "могу ли я беседку на 8 которая на 23 мая перенеси на 26 июня", now)
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
        reply = _send(suffix, "тогда баня которая на 25 июня пернести на 26 июня", now)
        checked = seen[-1] if seen else {}
        ok = "26 июня" in reply and checked.get("date") == "2026-06-26"
        return Check("reschedule typo pernesti uses target date", ok, f"{reply} | checked={checked}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
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
        reply = _send(suffix, "давайте сместим баню на 26 июня", now)
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
        reply = _send(suffix, "баня которая 23 июня можно перенести на 24?", now)
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


def main() -> None:
    settings = get_settings()
    now = datetime(2026, 5, 20, 12, 0, tzinfo=ZoneInfo(settings.app_timezone))
    _cleanup()
    checks: list[Check] = []
    try:
        checks.append(_test_second_booking_does_not_inherit_old_slot(now))
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
        checks.append(_test_single_available_gazebo_is_auto_selected())
        checks.append(_test_booking_summary_counts_all_bookings(now))
        checks.append(_test_new_conversation_sees_old_user_booking(now))
        checks.append(_test_new_conversation_sees_old_summary(now))
        checks.append(_test_customer_templates_do_not_mention_admin(now))
        checks.append(_test_short_yes_confirms())
        checks.append(_test_bare_weekday_requires_confirmation(now))
        checks.append(_test_weekday_confirmation_yes_uses_saved_candidate(now))
        checks.append(_test_first_upsell_no_gets_soft_push())
        checks.append(_test_first_upsell_flow_before_phone(now))
        checks.append(_test_positive_upsell_goes_to_next_step(now))
        checks.append(_test_free_dates_lookup_after_no_availability(now))
        checks.append(_test_waitlist_decline_does_not_handoff(now))
        checks.append(_test_location_question_does_not_handoff())
        checks.append(_test_gazebo_media_selection())
        checks.append(_test_post_booking_summary_always_uses_db(now))
        checks.append(_test_reschedule_selects_service_after_list(now))
        checks.append(_test_reschedule_uses_target_date_not_source_date(now))
        checks.append(_test_reschedule_typo_pernesti_uses_target_date(now))
        checks.append(_test_paid_cancel_asks_confirmation(now))
        checks.append(_test_paid_bathhouse_cancel_without_hold(now))
        checks.append(_test_ai_change_type_cancel_starts_flow(now))
        checks.append(_test_ai_change_type_reschedule_starts_flow(now))
        checks.append(_test_paid_reschedule_asks_confirmation(now))
    finally:
        _cleanup()

    failed = [check for check in checks if not check.ok]
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        print(f"{marker}: {check.name}: {check.details}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
