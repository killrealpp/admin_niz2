"""Deterministic regression tests for the booking bot.

The suite stubs AI/payment/YCLIENTS side effects and uses isolated users.
It is safe to run against the shared DB: all rows with TEST_PREFIX are removed.
"""

from __future__ import annotations

import argparse
import atexit
import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import gettempdir
from time import perf_counter
from typing import Any, Callable
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
from app.db.repositories import bookings_repo, conversations_repo, payments_repo, slot_holds_repo, system_logs_repo, users_repo, waitlist_repo, yclients_records_repo  # noqa: E402
from app.services.admin_notification_service import format_admin_bookings_message  # noqa: E402
from app.services.availability_service import AvailabilityResult  # noqa: E402
from app.services import availability_service, knowledge_service, message_handler, payment_status_runner, waitlist_service  # noqa: E402
from app.services.media_service import media_for_bookings, media_for_client_message  # noqa: E402
from app.services import message_retention_runner, payment_service  # noqa: E402
from app.services.message_handler import IncomingMessage, handle_incoming  # noqa: E402
from app.services.yclients_record_service import build_book_record_payload  # noqa: E402


TEST_PREFIX = "local_regression_"
LOCK_PATH = Path(gettempdir()) / "best2_regression_suite.lock"
_INSTALLED_LOCK_FD: int | None = None
TEST_PHONE = "+79990000001"
OLD_BOOKING_TEST_PHONE = "+79990000002"
TEST_GROUPS = (
    "fresh",
    "payments",
    "post_booking",
    "services",
    "dates",
    "time",
    "gazebo",
    "media",
    "upsell",
    "prices",
    "waitlist",
    "handoff",
    "reschedule",
    "cancel",
    "reminder",
)


@dataclass
class Check:
    name: str
    ok: bool
    details: str = ""


def install_regression_suite_lock(owner: str) -> None:
    global _INSTALLED_LOCK_FD
    if _INSTALLED_LOCK_FD is not None:
        return
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError as exc:
        try:
            details = LOCK_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            details = ""
        suffix = f" ({details})" if details else ""
        raise RuntimeError(f"Regression suite is already running: {LOCK_PATH}{suffix}") from exc
    os.write(fd, f"owner={owner}; pid={os.getpid()}\n".encode("utf-8"))
    _INSTALLED_LOCK_FD = fd
    atexit.register(_release_regression_suite_lock)


def _release_regression_suite_lock() -> None:
    global _INSTALLED_LOCK_FD
    fd = _INSTALLED_LOCK_FD
    if fd is None:
        return
    _INSTALLED_LOCK_FD = None
    try:
        os.close(fd)
    finally:
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


def _cleanup() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            dependent_tables = (
                "waitlist_requests",
                "payments",
                "bookings",
                "slot_holds",
                "system_logs",
                "messages",
                "conversation_summaries",
            )
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
            if conversation_ids:
                for table in dependent_tables:
                    cur.execute(f"DELETE FROM {table} WHERE conversation_id = ANY(%s)", (conversation_ids,))
            for table in dependent_tables:
                cur.execute(
                    f"""
                    DELETE FROM {table} t
                    USING conversations c, users u
                    WHERE t.conversation_id = c.id
                      AND c.user_id = u.id
                      AND u.external_id LIKE %s
                    """,
                    (TEST_PREFIX + "%",),
                )
            cur.execute(
                """
                DELETE FROM conversations c
                USING users u
                WHERE c.user_id = u.id
                  AND u.external_id LIKE %s
                """,
                (TEST_PREFIX + "%",),
            )
            cur.execute("DELETE FROM users WHERE external_id LIKE %s", (TEST_PREFIX + "%",))
            cur.execute("DELETE FROM resource_busy_intervals WHERE source_record_id LIKE 'local_%'")
            cur.execute("DELETE FROM yclients_records WHERE yclients_record_id LIKE 'local_%'")
            cur.execute(
                """
                DELETE FROM resource_busy_intervals r
                WHERE r.source = 'bot_booking'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM bookings b
                      WHERE b.id::text = r.source_record_id
                         OR b.yclients_record_id::text = r.source_record_id
                  )
                """
            )


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
    actual_now = datetime.now(ZoneInfo(get_settings().app_timezone))
    expires_base = actual_now if actual_now > now else now
    test_resource_id = f"local_hold_{conversation['id']}"
    with get_connection() as conn:
        return slot_holds_repo.create(
            conn,
            conversation_id=conversation["id"],
            user_id=user["id"],
            service_type="gazebo",
            yclients_service_id=test_resource_id,
            slot_date=date(2026, 5, 23),
            slot_time=time(12, 0),
            duration_minutes=360,
            expires_at=expires_base + timedelta(minutes=15),
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


def _test_plain_new_service_request_resets_old_form(now: datetime) -> Check:
    suffix = "plain_new_service_reset"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №1",
            date="2026-06-30",
            time="18:00",
            duration=6,
            guests_count=22,
            event_format="день рождения",
            client_name="Кирилл",
            phone="+79990000044",
            upsell_items=["не нужны"],
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
            form_data=created["conversation"]["form_data"],
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
        reply = _send(suffix, "хочу баню", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "bathhouse"
            and form.get("client_name") == "Кирилл"
            and form.get("phone") == "+79990000044"
            and not form.get("service_variant")
            and not form.get("date")
            and not form.get("time")
            and not form.get("duration")
            and not form.get("guests_count")
            and not form.get("event_format")
            and not form.get("upsell_items")
            and state.get("current_step") == "date"
            and "22" not in reply
        )
        return Check("plain new service request resets old form", ok, f"{reply} | {form}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_service_correction_with_zhe_resets_old_form(now: datetime) -> Check:
    suffix = "zhe_want_bath_reset"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-05-29",
            time="15:00",
            duration=9,
            guests_count=10,
            event_format="день рождения ребенка",
            client_name="Ирина",
            phone="+79099667655",
            upsell_items=["базовый мангальный набор"],
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
            form_data=created["conversation"]["form_data"],
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="date",
            changed_fields=["service_type"],
            form_data_patch={"service_type": "bathhouse"},
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    try:
        reply = _send(suffix, "а я же хочу баньку", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "bathhouse"
            and form.get("client_name") == "Ирина"
            and form.get("phone") == "+79099667655"
            and not form.get("date")
            and not form.get("time")
            and not form.get("duration")
            and not form.get("guests_count")
            and not form.get("event_format")
            and not form.get("upsell_items")
            and state.get("current_step") == "date"
            and "29 мая" not in reply
            and "15:00" not in reply
            and "10" not in reply
        )
        return Check("service correction with zhe resets old form", ok, f"{reply} | {form}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_next_application_while_hold_starts_blank_not_ice(now: datetime) -> Check:
    suffix = "next_application_hold"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="09:00",
            duration=12,
            guests_count=10,
            event_format="семейный отдых",
            upsell_items=["не нужны"],
            client_name="Кирилл",
            phone="+79968533502",
        ),
    )
    _create_active_hold(created["conversation"], created["user"], now)
    reply = _send(suffix, "приступим к следующуей заявке?", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "допы" not in lowered
        and "обновила допы" not in lowered
        and "допы: лед" not in lowered
        and "что хотите забронировать" in lowered
        and state.get("current_step") == "service_type"
        and form.get("client_name") == "Кирилл"
        and form.get("phone") == "+79968533502"
        and not form.get("service_type")
        and not form.get("date")
        and not form.get("time")
        and not form.get("duration")
        and not form.get("upsell_items")
    )
    return Check("next application while hold starts blank not ice", ok, f"{reply} | {state}")


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


def _test_concurrent_active_hold_conflict(now: datetime) -> Check:
    real_now = datetime.now(ZoneInfo(get_settings().app_timezone))
    created_a = _create_reserved_conversation(
        "hold_conflict_a",
        real_now,
        _base_form(service_type="gazebo", service_variant="Р‘РµСЃРµРґРєР° в„–1", date="2026-06-12", time="12:00", duration=20),
    )
    created_b = _create_reserved_conversation(
        "hold_conflict_b",
        real_now,
        _base_form(service_type="gazebo", service_variant="Р‘РµСЃРµРґРєР° в„–1", date="2026-06-12", time="12:00", duration=20),
    )

    def create_for(created: dict[str, Any]) -> str:
        with get_connection() as conn:
            try:
                slot_holds_repo.create(
                    conn,
                    conversation_id=created["conversation"]["id"],
                    user_id=created["user"]["id"],
                    service_type="gazebo",
                    yclients_service_id="18201055",
                    yclients_staff_id="3828146",
                    slot_date=date(2026, 6, 12),
                    slot_time=time(12, 0),
                    duration_minutes=1200,
                    expires_at=real_now + timedelta(minutes=10),
                )
                return "created"
            except slot_holds_repo.SlotHoldConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create_for, created_a), executor.submit(create_for, created_b)]
        results = [future.result() for future in as_completed(futures)]

    with get_connection() as conn:
        active = slot_holds_repo.list_active_for_slot(
            conn,
            service_type="gazebo",
            slot_date=date(2026, 6, 12),
            now=real_now,
            yclients_staff_id="3828146",
        )
    ok = sorted(results) == ["conflict", "created"] and len(active) == 1
    return Check("concurrent active hold conflict", ok, f"results={results} active={len(active)}")


def _test_payment_intent_retry_no_duplicate_link(now: datetime) -> Check:
    suffix = "payment_intent_retry"
    created = _create_reserved_conversation(suffix, now, _base_form(service_type="gazebo", service_variant="Р‘РµСЃРµРґРєР° в„–2"))
    hold = _create_active_hold(created["conversation"], created["user"], now)
    settings = get_settings()
    original_provider = settings.payment_provider
    original_client = payment_service.YooKassaClient

    class FailingClient:
        def create_payment(self, **_: Any) -> dict[str, Any]:
            raise RuntimeError("provider down")

    class SuccessClient:
        def create_payment(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "id": "local_retry_success",
                "status": "pending",
                "paid": False,
                "metadata": kwargs.get("metadata") or {},
                "confirmation": {"confirmation_url": "https://example.test/payment-intent-retry"},
            }

    try:
        settings.payment_provider = "yookassa"
        payment_service.YooKassaClient = FailingClient
        with get_connection() as conn:
            failed = False
            try:
                payment_service.create_payment_link_for_holds(
                    conn,
                    conversation_id=created["conversation"]["id"],
                    user_id=created["user"]["id"],
                    hold_ids=[hold["id"]],
                    client_name="РљРёСЂРёР»Р»",
                    phone=TEST_PHONE,
                )
            except RuntimeError:
                failed = True

        payment_service.YooKassaClient = SuccessClient
        with get_connection() as conn:
            first = payment_service.create_payment_link_for_holds(
                conn,
                conversation_id=created["conversation"]["id"],
                user_id=created["user"]["id"],
                hold_ids=[hold["id"]],
                client_name="РљРёСЂРёР»Р»",
                phone=TEST_PHONE,
            )
            second = payment_service.create_payment_link_for_holds(
                conn,
                conversation_id=created["conversation"]["id"],
                user_id=created["user"]["id"],
                hold_ids=[hold["id"]],
                client_name="РљРёСЂРёР»Р»",
                phone=TEST_PHONE,
            )
            payments = payments_repo.list_for_conversation(conn, conversation_id=created["conversation"]["id"])

        paid_links = [item for item in payments if item.get("payment_url") == "https://example.test/payment-intent-retry"]
        failed_rows = [item for item in payments if item.get("status") == "failed"]
        ok = (
            failed
            and first.get("payment_url") == "https://example.test/payment-intent-retry"
            and second.get("id") == first.get("id")
            and len(paid_links) == 1
            and len(failed_rows) == 1
        )
        return Check("payment intent retry no duplicate link", ok, f"payments={[(p.get('id'), p.get('status'), p.get('payment_url')) for p in payments]}")
    finally:
        settings.payment_provider = original_provider
        payment_service.YooKassaClient = original_client


def _test_message_retention_48h_summarizes_and_deletes() -> Check:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    created = _create_reserved_conversation("retention_48h", now)
    original_hours = settings.message_summary_after_hours
    original_summarize = message_retention_runner.summarize_dialog_messages
    try:
        settings.message_summary_after_hours = 48
        message_retention_runner.summarize_dialog_messages = lambda messages: "retention summary: " + " | ".join(item["text"] for item in messages)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO messages (conversation_id, sender, text, created_at)
                    VALUES
                        (%s, 'user', 'old question about bathhouse', %s),
                        (%s, 'assistant', 'old answer with phone saved', %s),
                        (%s, 'user', 'recent message stays raw', %s)
                    """,
                    (
                        created["conversation"]["id"],
                        now - timedelta(hours=49),
                        created["conversation"]["id"],
                        now - timedelta(hours=48, minutes=30),
                        created["conversation"]["id"],
                        now - timedelta(hours=1),
                    ),
                )
        result = message_retention_runner.summarize_and_delete_old_messages_once()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) AS total FROM messages WHERE conversation_id = %s", (created["conversation"]["id"],))
                remaining_messages = cur.fetchone()["total"]
                cur.execute("SELECT summary FROM conversation_summaries WHERE conversation_id = %s", (created["conversation"]["id"],))
                summaries = [row["summary"] for row in cur.fetchall()]
            context = message_handler._context_summaries(conn, created["conversation"], {}, now + timedelta(hours=1))
        ok = (
            result["messages"] >= 2
            and remaining_messages == 1
            and any("old question about bathhouse" in item for item in summaries)
            and any("old question about bathhouse" in str(item.get("summary") or "") for item in context)
        )
        return Check("message retention 48h summarizes and deletes raw", ok, f"result={result} remaining={remaining_messages} summaries={summaries}")
    finally:
        settings.message_summary_after_hours = original_hours
        message_retention_runner.summarize_dialog_messages = original_summarize


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


def _test_gazebo_budget_preference_filters_cheapest() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant=None,
        date="2026-06-30",
        guests_count=15,
        last_available_gazebo_variants=[
            "Беседка №1",
            "Беседка №2",
            "Беседка №3",
            "Беседка №4",
            "Беседка №8",
            "Крытая беседка",
        ],
    )
    reply = message_handler._gazebo_budget_selection_text(form)
    lowered = (reply or "").lower().replace("ё", "е")
    ok = (
        reply is not None
        and "недорог" in lowered
        and "№2" in reply
        and "№4" in reply
        and "№1" not in reply
        and "№3" not in reply
        and "№8" not in reply
    )
    return Check("gazebo budget preference filters cheapest", ok, str(reply))


def _test_gazebo_budget_preference_during_choice(now: datetime) -> Check:
    suffix = "gazebo_budget_choice"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant=None,
            date="2026-06-30",
            time=None,
            duration=None,
            guests_count=15,
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
        )
    reply = _send(suffix, "а мне нужно что нибудь подешелве", now)
    state = _latest_state(suffix)
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "недорог" in lowered
        and "№2" in reply
        and "№4" in reply
        and "№1" not in reply
        and "№3" not in reply
        and "№8" not in reply
        and state.get("current_step") == "service_variant"
    )
    return Check("gazebo budget preference during choice", ok, f"{reply} | {state}")


def _test_gazebo_budget_without_date_asks_one_question(now: datetime) -> Check:
    suffix = "gazebo_budget_without_date"
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
            event_format=None,
            phone="+79990000041",
            upsell_items=[],
            last_suggested_free_dates=["2026-05-28", "2026-05-29", "2026-05-30"],
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
            form_data=created["conversation"]["form_data"],
        )
    reply = _send(suffix, "а че нас типо 10 челов\nкакую нам выбрать, что дешевле", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        form.get("guests_count") == 10
        and form.get("service_type") == "gazebo"
        and "недорог" in lowered
        and "назовите дату" in lowered
        and "продолжим оформление" not in lowered
        and "какую выбираете" not in lowered
        and state.get("next_step") == "date"
    )
    return Check("gazebo budget without date asks one question", ok, f"{reply} | {state}")


def _test_mixed_gazebo_selection_info_saves_variant(now: datetime) -> Check:
    suffix = "mixed_gazebo_selection_info"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant=None,
            date=None,
            time=None,
            duration=None,
            guests_count=10,
            event_format=None,
            phone="+79990000042",
            upsell_items=[],
            last_suggested_free_dates=["2026-05-28", "2026-05-29", "2026-05-30"],
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
            form_data=created["conversation"]["form_data"],
        )
    reply = _send(suffix, "ну окей давайте четвертую\nа с детьми можно?", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        form.get("service_variant") == "Беседка №4"
        and "с детьми можно" in lowered
        and "беседка №4" in lowered
        and "на какую дату" in lowered
        and state.get("next_step") == "date"
    )
    return Check("mixed gazebo selection info saves variant", ok, f"{reply} | {state}")


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


def _test_forced_gazebo_variant_asks_guests_before_time(now: datetime) -> Check:
    suffix = "forced_gazebo_variant_guests"
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(intent="booking_request", action="check_availability", current_step="date")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "ok", ["Беседка №6: дата свободна"])
    try:
        reply = _send(suffix, "29 мая 6 беседка", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            form.get("service_type") == "gazebo"
            and form.get("service_variant") == "Беседка №6"
            and form.get("date") == "2026-05-29"
            and not form.get("time")
            and state.get("current_step") == "guests_count"
            and "сколько" in lowered
            and "вместимости" in lowered
        )
        return Check("forced gazebo variant asks guests before time", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_gazebo_capacity_question_sets_guests_and_skips_repeat(now: datetime) -> Check:
    suffix = "gazebo_capacity_question_sets_guests"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №6",
            date="2026-05-29",
            time=None,
            duration=None,
            guests_count=None,
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
            current_step="time",
            next_step="time",
        )
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(intent="company_info", action="answer_info", current_step="time")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    try:
        reply = _send(suffix, "А если нас 15 человек", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            form.get("guests_count") == 15
            and form.get("service_variant") == "Беседка №6"
            and state.get("current_step") == "time"
            and "до 15" in lowered
            and "сколько примерно гостей" not in lowered
            and lowered.count("во сколько") <= 1
        )
        return Check("gazebo capacity question sets guests and skips repeat", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_hypothetical_guest_count_updates_capacity_question() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant=None,
        date="2026-06-30",
        time=None,
        duration=None,
        guests_count=20,
    )
    phrases = (
        "а если бы нас было 10 какие беседки подошли бы?",
        "а если нас 10, какие варианты?",
        "для 10 человек что подойдет?",
        "а если будет 10 человек, что лучше?",
    )
    replies = [(phrase, message_handler._deterministic_info_reply(phrase, form)) for phrase in phrases]
    ok = True
    details: list[str] = []
    for phrase, reply in replies:
        lowered = (reply or "").lower().replace("ё", "е")
        phrase_ok = bool(
            reply
            and "для 10 гостей" in lowered
            and "для 20 гостей" not in lowered
        )
        ok = ok and phrase_ok
        details.append(f"{phrase} => {reply}")
    return Check("hypothetical guest count updates capacity question", ok, "\n---\n".join(details))


def _test_on_site_upsell_refusal_paraphrases() -> Check:
    phrases = (
        "если что там на месте возьмем",
        "если что там на месте возьмём",
        "на месте возьмем если понадобится",
        "там на месте уже разберемся",
    )
    patches = [(phrase, message_handler._upsell_items_patch(phrase)) for phrase in phrases]
    ok = all(patch.get("upsell_items") == ["не нужны"] for _phrase, patch in patches)
    return Check("on-site upsell refusal paraphrases", ok, str(patches))


def _test_name_correction_paraphrases_keep_clean_value() -> Check:
    cases = (
        ("имя заменим на IVAN", "IVAN"),
        ("имя поменяем на IVAN", "IVAN"),
        ("замени имя на IVAN", "IVAN"),
        ("фио измени на IVAN", "IVAN"),
    )
    results = [
        (phrase, message_handler._form_detail_correction_patch(phrase, {"client_name": "Иван"}))
        for phrase, _expected in cases
    ]
    ok = all(result.get("client_name") == expected for (_phrase, expected), (_actual_phrase, result) in zip(cases, results))
    return Check("name correction paraphrases keep clean value", ok, str(results))


def _test_live_gazebo_twenty_guests_keeps_capacity_context(now: datetime) -> Check:
    suffix = "live_gazebo_20_guests"
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    seen: list[dict[str, Any]] = []

    def fake_call_ai(**kwargs: Any) -> AIResponse:
        text = str(kwargs.get("text") or "")
        patch: dict[str, Any] = {}
        changed: list[str] = []
        if "8 июня" in text:
            patch["date"] = "2026-06-08"
            changed.append("date")
        elif "5 июня" in text or "5 число" in text:
            patch["date"] = "2026-06-05"
            changed.append("date")
        if "20" in text:
            patch["guests_count"] = 20
            changed.append("guests_count")
        return AIResponse(
            intent="booking_request",
            action="check_availability",
            current_step="date",
            changed_fields=changed,
            form_data_patch=patch,
        )

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        seen.append(dict(form))
        if form.get("date") == "2026-06-08":
            return AvailabilityResult(
                True,
                "ok",
                [
                    "Беседка №1: дата свободна",
                    "Беседка №8: дата свободна",
                    "Беседка №3: дата свободна",
                ],
            )
        if form.get("date") == "2026-06-05":
            return AvailabilityResult(
                True,
                "ok",
                [
                    "Беседка №2: дата свободна",
                    "Беседка №5: дата свободна",
                ],
            )
        return AvailabilityResult(True, "ok", [])

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = fake_availability
    try:
        _send(suffix, "на 5 июня есть беседка", now)
        reply_20 = _send(suffix, "20 чел", now + timedelta(seconds=10))
        capacity_reply = _send(suffix, "так в итоге 20 человек влезит", now + timedelta(seconds=20))
        same_date_reply = _send(suffix, "только эта свободна на 5 июня", now + timedelta(seconds=30))
        june_8_reply = _send(suffix, "а на 8 июня свободно", now + timedelta(seconds=40))
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        combined_same_day = f"{reply_20}\n{capacity_reply}\n{same_date_reply}".lower().replace("ё", "е")
        june_8_lowered = june_8_reply.lower().replace("ё", "е")
        ok = (
            form.get("guests_count") == 20
            and "не подходят" in combined_same_day
            and "16 июня" not in same_date_reply.lower()
            and "20 июня" not in same_date_reply.lower()
            and "беседка №1" in june_8_lowered
            and "беседка №8" in june_8_lowered
            and "беседка №3" in june_8_lowered
        )
        return Check(
            "live gazebo 20 guests keeps capacity context",
            ok,
            f"20={reply_20} | capacity={capacity_reply} | same={same_date_reply} | 8={june_8_reply} | seen={seen} | {state}",
        )
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_gazebo_date_and_guests_first_message_checks_availability(now: datetime) -> Check:
    suffix = "gazebo_date_guests_first_message"
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
            event_format=None,
            phone="+79990000052",
            upsell_items=[],
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
            form_data=created["conversation"]["form_data"],
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    seen: list[dict[str, Any]] = []

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="check_availability",
            current_step="date",
            changed_fields=["date", "guests_count"],
            form_data_patch={"date": "2026-06-30", "guests_count": 20},
        )

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        seen.append(dict(form))
        if form.get("date") == "2026-06-30":
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

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "на 30 июня нас будет 20", now)
        state = _latest_state(suffix)
        lowered = reply.lower().replace("ё", "е")
        form = state.get("form_data") or {}
        ok = (
            seen
            and seen[0].get("date") == "2026-06-30"
            and form.get("guests_count") == 20
            and "беседка №1" in lowered
            and "беседка №8" in lowered
            and "30 июня" in lowered
            and "75 дней" not in lowered
            and "не нашла" not in lowered
            and state.get("current_step") == "service_variant"
        )
        return Check("gazebo date+guests first message checks availability", ok, f"{reply} | seen={seen} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_gazebo_no_capacity_on_date_offers_nearest_before_requested(now: datetime) -> Check:
    suffix = "gazebo_no_capacity_nearest"
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
            event_format=None,
            phone="+79990000053",
            upsell_items=[],
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
            form_data=created["conversation"]["form_data"],
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    seen_dates: list[str] = []

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="check_availability",
            current_step="date",
            changed_fields=["date", "guests_count"],
            form_data_patch={"date": "2026-06-30", "guests_count": 20},
        )

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        seen_dates.append(str(form.get("date")))
        if form.get("date") == "2026-06-29":
            return AvailabilityResult(True, "ok", ["Беседка №1: дата свободна", "Беседка №8: дата свободна"])
        return AvailabilityResult(True, "ok", [])

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "на 30 июня нас будет 20", now)
        state = _latest_state(suffix)
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "30 июня" not in lowered or "не нашла" in lowered
        ) and (
            "29 июня" in lowered
            and "беседка №1" in lowered
            and "75 дней" not in lowered
            and state.get("current_step") == "awaiting_new_date"
            and "2026-06-30" in seen_dates
            and "2026-06-29" in seen_dates
        )
        return Check("gazebo no capacity on date offers nearest suitable", ok, f"{reply} | seen={seen_dates} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_gazebo_small_slots_on_date_offers_nearest_suitable(now: datetime) -> Check:
    suffix = "gazebo_small_slots_nearest"
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
            event_format=None,
            phone="+79990000054",
            upsell_items=[],
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
            form_data=created["conversation"]["form_data"],
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    seen_dates: list[str] = []

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="check_availability",
            current_step="date",
            changed_fields=["date", "guests_count"],
            form_data_patch={"date": "2026-06-30", "guests_count": 20},
        )

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        seen_dates.append(str(form.get("date")))
        if form.get("date") == "2026-06-30":
            return AvailabilityResult(True, "ok", ["Беседка №2: дата свободна", "Беседка №5: дата свободна"])
        if form.get("date") == "2026-06-29":
            return AvailabilityResult(True, "ok", ["Беседка №1: дата свободна", "Беседка №8: дата свободна"])
        return AvailabilityResult(True, "ok", [])

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "на 30 июня нас будет 20", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "на 30 июня свободны" in lowered
            and "не подходят" in lowered
            and "29 июня" in lowered
            and "беседка №1" in lowered
            and "75 дней" not in lowered
            and state.get("current_step") == "awaiting_new_date"
            and form.get("guests_count") == 20
            and (form.get("last_unavailable") or {}).get("date") == "2026-06-30"
            and "2026-06-29" in seen_dates
        )
        return Check("gazebo small slots on date offers nearest suitable", ok, f"{reply} | seen={seen_dates} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_gazebo_variant_change_not_parsed_as_time(now: datetime) -> Check:
    suffix = "gazebo_variant_change_not_time"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №6",
            date="2026-05-29",
            time=None,
            duration=None,
            guests_count=15,
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
            current_step="time",
            next_step="time",
        )
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="check_availability",
            current_step="time",
            changed_fields=["service_variant", "time"],
            form_data_patch={"service_variant": "Беседка №4", "time": "04:00"},
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "ok", ["Беседка №4: дата свободна"])
    try:
        reply = _send(suffix, "Хорошо, 4 беседка", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            form.get("service_variant") == "Беседка №4"
            and not form.get("time")
            and state.get("current_step") == "time"
            and "04:00" not in reply
            and "во сколько" in lowered
        )
        return Check("gazebo variant change is not parsed as time", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_guest_count_reference_not_parsed_as_time(now: datetime) -> Check:
    suffix = "guest_reference_not_time"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-05-30",
            time=None,
            duration=None,
            guests_count=10,
            event_format=None,
            phone="+79990000044",
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
    original_call_ai = message_handler.call_ai

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="time",
            changed_fields=["time", "duration"],
            form_data_patch={"time": "10:00", "duration": 22},
        )

    message_handler.call_ai = fake_call_ai
    try:
        reply = _send(suffix, "я же говорил 10", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            form.get("guests_count") == 10
            and not form.get("time")
            and not form.get("duration")
            and state.get("current_step") == "time"
            and "10:00" not in reply
            and "записала" in lowered
            and "во сколько" in lowered
        )
        return Check("guest count reference is not parsed as time", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai


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


def _test_new_free_dates_request_resets_old_unavailable(now: datetime) -> Check:
    suffix = "new_free_dates_resets_unavailable"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date=None,
            time=None,
            duration=None,
            guests_count=None,
            event_format=None,
            phone="+79990000043",
            upsell_items=[],
            last_unavailable={
                "service_type": "bathhouse",
                "date": "2026-08-05",
                "time": None,
                "duration": None,
            },
            last_suggested_free_dates=["2026-08-06", "2026-08-07"],
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
            form_data=created["conversation"]["form_data"],
        )
    original_availability = message_handler.check_availability
    seen_dates: list[str] = []

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        seen_dates.append(str(form.get("date")))
        return AvailabilityResult(True, "ok", ["Баня: дата свободна"])

    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "начнем новую\nкакие ближайшие свободные даты для бани?", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            seen_dates[:1] == [now.date().isoformat()]
            and "август" not in lowered
            and form.get("service_type") == "bathhouse"
            and not form.get("last_unavailable")
            and state.get("current_step") == "awaiting_new_date"
        )
        return Check("new free dates request resets old unavailable", ok, f"{reply} | seen={seen_dates} | {form}")
    finally:
        message_handler.check_availability = original_availability


def _test_gazebo_free_dates_request_switches_service(now: datetime) -> Check:
    suffix = "gazebo_dates_switch_service"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date=None,
            time=None,
            duration=None,
            guests_count=None,
            event_format=None,
            phone="+79990000045",
            upsell_items=[],
            last_suggested_free_dates=["2026-05-20", "2026-05-21"],
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
            form_data=created["conversation"]["form_data"],
        )
    original_availability = message_handler.check_availability

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        if form.get("service_type") == "gazebo":
            return AvailabilityResult(True, "ok", ["Беседка №4: дата свободна", "Беседка №6: дата свободна"])
        return AvailabilityResult(True, "ok", ["Баня: дата свободна"])

    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "а беседки на какие даты есть?", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "ближайшие свободные даты" in lowered
            and "беседка" in lowered
            and "баня" not in lowered
            and form.get("service_type") == "gazebo"
            and state.get("current_step") == "awaiting_new_date"
        )
        return Check("gazebo free dates request switches service", ok, f"{reply} | {state}")
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


def _test_gazebo_explicit_period_with_longer_question_keeps_end_time(now: datetime) -> Check:
    suffix = "gazebo_period_longer_question"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time=None,
            duration=None,
            guests_count=10,
            event_format=None,
            upsell_items=[],
            client_name="Кирилл",
            phone="+79968533502",
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
        return AIResponse(
            intent="company_info",
            action="answer_info",
            current_step="time",
            form_data_patch={"time": "09:00", "duration": 23},
            reply_to_user="До утра можно, если сразу указать такой период.",
        )

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        seen.append(form)
        return AvailabilityResult(True, "ok", ["Беседка №4: 09:00-21:00"])

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "с 9 утра до 21 ночи, если что можно на дольше остаться?", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        checked = seen[-1] if seen else {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            form.get("time") == "09:00"
            and form.get("duration") == 12
            and checked.get("duration") == 12
            and "08:00" not in reply
            and "23 часа" not in lowered
            and state.get("current_step") == "event_format"
        )
        return Check("gazebo explicit period with longer question keeps end time", ok, f"{reply} | {form} | checked={checked}")
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


def _test_general_gazebo_photo_request_after_booking(now: datetime) -> Check:
    suffix = "general_gazebo_photo_after_booking"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 17),
        yclients_service_id="18201061",
        provider_record_id="local_general_gazebo_photo",
        phone="+79990000050",
    )
    reply = _send(suffix, "а беседки покажете?", now)
    paths = media_for_client_message("а беседки покажете?", reply)
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "фото беседок" in lowered
        and "беседка №1" in lowered
        and "уже отправ" not in lowered
        and len(paths) >= 3
        and "besedka1.jpg" in {path.name for path in paths}
    )
    return Check("general gazebo photo request sends gazebo media", ok, f"{reply} | {[path.name for path in paths]}")


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


def _test_booking_summary_uses_draft_when_no_active_booking(now: datetime) -> Check:
    suffix = "draft_summary_no_active_booking"
    _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-06-01",
            time=None,
            duration=None,
            guests_count=5,
            event_format=None,
            client_name="Кирилл",
            phone="+79990000046",
            upsell_items=["не нужны"],
        ),
    )
    reply = _send(suffix, "айоу, а че у меня по брони которую я хотел забронироватьэ", now)
    state = _latest_state(suffix)
    vague_reply = _send(suffix, "ну че нибудь", now + timedelta(seconds=10))
    vague_state = _latest_state(suffix)
    vague_form = vague_state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    vague_lowered = vague_reply.lower().replace("ё", "е")
    ok = (
        "оформленной брони пока нет" in lowered
        and "черновике" in lowered
        and "1 июня" in lowered
        and "во сколько" in lowered
        and "пока не вижу активных броней по вашему номеру" not in lowered
        and state.get("status") == "waiting_user"
        and state.get("current_step") == "time"
        and state.get("next_step") == "time"
        and (
            "во сколько" in vague_lowered
            or "какое время" in vague_lowered
            or "другое время" in vague_lowered
            or ("время" in vague_lowered and "удоб" in vague_lowered)
        )
        and vague_state.get("current_step") == "time"
        and vague_state.get("next_step") == "time"
        and not vague_form.get("time")
        and not vague_form.get("duration")
    )
    return Check("booking summary uses draft when no active booking", ok, f"{reply} | {state} | {vague_reply} | {vague_state}")


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


def _test_invalid_phone_reply_is_client_safe(now: datetime) -> Check:
    suffix = "invalid_phone"
    _create_reserved_conversation(
        suffix,
        now,
        _base_form(phone=None),
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE conversations c
                SET current_step = 'phone',
                    next_step = 'phone',
                    status = 'waiting_user'
                FROM users u
                WHERE c.user_id = u.id
                  AND u.external_id = %s
                """,
                (TEST_PREFIX + suffix,),
            )
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="phone",
            changed_fields=["phone"],
            form_data_patch={"phone": "+799968533502"},
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **_kwargs: "Попроси клиента"
    try:
        reply = _send(suffix, "+799968533502", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            "попроси клиента" not in reply.lower()
            and "+7XXXXXXXXXX" in reply
            and form.get("phone") is None
            and state.get("current_step") == "phone"
        )
        return Check("invalid phone reply is client safe", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_admin_notification_includes_booking_object(now: datetime) -> Check:
    suffix = "admin_booking_object"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201065",
        provider_record_id="local_admin_booking_object",
        phone="+79990000019",
    )
    with get_connection() as conn:
        message = format_admin_bookings_message(conn, conversation_id=created["conversation"]["id"])
    ok = "Беседка №8" in message and "(Беседка)" in message and "YCLIENTS" in message
    return Check("admin notification includes booking object", ok, message)


def _test_short_yes_confirms() -> Check:
    ok = message_handler._confirmation_yes("д") and message_handler._confirmation_yes("+")
    return Check("short yes confirms", ok, "д/+ should confirm")


def _test_soft_yes_confirms_from_confirmation(now: datetime) -> Check:
    suffix = "soft_yes_confirmation"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-06-30",
            time="09:00",
            duration=6,
            guests_count=10,
            event_format="спокойный отдых",
            client_name="Кирилл",
            phone="+79990000051",
            upsell_items=["не нужны"],
        ),
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
    original_payment = message_handler.create_payment_link_for_holds
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "Свободно.", ["Баня: свободно"])
    message_handler.create_payment_link_for_holds = lambda *_args, **_kwargs: {
        "payment_url": "https://example.test/soft-yes",
        "amount": "1.00",
        "status": "pending",
    }
    try:
        reply = _send(suffix, "ну вроде да", now)
        state = _latest_state(suffix)
        ok = (
            message_handler._confirmation_yes("ну вроде да")
            and "https://example.test/soft-yes" in reply
            and state.get("current_step") == "reserved"
        )
        return Check("soft yes confirms awaiting confirmation", ok, f"{reply} | {state}")
    finally:
        message_handler.check_availability = original_availability
        message_handler.create_payment_link_for_holds = original_payment


def _test_name_correction_replaces_value_after_na() -> Check:
    patch = message_handler._form_detail_correction_patch(
        "имя заменим на IVAN",
        {"client_name": "Иван"},
    )
    ok = patch.get("client_name") == "IVAN"
    return Check("name correction replaces value after na", ok, str(patch))


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


def _test_bathhouse_open_ended_duration_until_morning() -> Check:
    guessed = _base_form(
        service_type="bathhouse",
        service_variant=None,
        date="2026-06-30",
        time="12:00",
        duration="3 часа",
        guests_count=5,
    )
    updated = message_handler._apply_gazebo_default_duration(
        guessed,
        force=message_handler._gazebo_open_ended_duration_requested("с 12 а там посмотрим может до утра задержимся"),
    )
    ok = updated.get("duration") == 20
    return Check("bathhouse open-ended duration until morning", ok, str(updated))


def _test_bathhouse_rejects_non_fixed_duration(now: datetime) -> Check:
    with get_connection() as conn:
        result = message_handler.check_availability(
            conn,
            form_data=_base_form(
                service_type="bathhouse",
                service_variant=None,
                date="2026-06-30",
                time="09:00",
                duration=12,
                guests_count=10,
            ),
            now=now,
        )
    lowered = result.message.lower().replace("ё", "е")
    ok = (
        result.ok
        and not result.slots
        and "фиксирован" in lowered
        and "3, 4, 5, 6 или 7 часов" in lowered
    )
    return Check("bathhouse rejects non-fixed duration", ok, result.message)


def _test_fixed_service_rejects_missing_yclients_book_time(now: datetime) -> Check:
    original_loader = availability_service._load_yclients_book_times
    availability_service.clear_availability_cache()
    availability_service._load_yclients_book_times = lambda **_kwargs: ["14:00", "14:30", "15:00"]
    try:
        with get_connection() as conn:
            result = message_handler.check_availability(
                conn,
                form_data=_base_form(
                    service_type="bathhouse",
                    date="2026-06-30",
                    time="12:00",
                    duration=4,
                    guests_count=15,
                ),
                now=now,
            )
        lowered = result.message.lower().replace("ё", "е")
        ok = (
            result.ok
            and not result.slots
            and "12:00" in result.message
            and "14:00" in result.message
            and "недоступ" in lowered
        )
        return Check("fixed service rejects missing yclients book time", ok, result.message)
    finally:
        availability_service._load_yclients_book_times = original_loader
        availability_service.clear_availability_cache()


def _test_fixed_service_yclients_unavailable_does_not_claim_free(now: datetime) -> Check:
    original_loader = availability_service._load_yclients_book_times
    availability_service.clear_availability_cache()
    availability_service._load_yclients_book_times = lambda **_kwargs: None
    try:
        with get_connection() as conn:
            result = message_handler.check_availability(
                conn,
                form_data=_base_form(
                    service_type="bathhouse",
                    date="2026-06-30",
                    time="12:00",
                    duration=4,
                    guests_count=15,
                ),
                now=now,
            )
        lowered = result.message.lower().replace("ё", "е")
        ok = (
            not result.ok
            and not result.slots
            and "не могу надежно проверить" in lowered
            and "свобод" not in lowered
        )
        return Check("fixed service yclients unavailable does not claim free", ok, result.message)
    finally:
        availability_service._load_yclients_book_times = original_loader
        availability_service.clear_availability_cache()


def _test_first_upsell_no_gets_soft_push() -> Check:
    form = _base_form(service_type="gazebo", service_variant="Беседка №2")
    reply = message_handler._upsell_push_reply(form)
    no_patch = message_handler._upsell_items_patch("наверное ничего")
    typo_patch = message_handler._upsell_items_patch("наверное ничег")
    informal_patch = message_handler._upsell_items_patch("неа")
    repeat_patch = message_handler._upsell_items_patch("нет же говорю")
    keyboard_patch = message_handler._upsell_items_patch("ytn")
    ok = (
        "уголь" in reply.lower()
        and "напишите «нет» ещё раз" in reply.lower()
        and no_patch.get("upsell_items") == ["не нужны"]
        and typo_patch.get("upsell_items") == ["не нужны"]
        and informal_patch.get("upsell_items") == ["не нужны"]
        and repeat_patch.get("upsell_items") == ["не нужны"]
        and keyboard_patch.get("upsell_items") == ["не нужны"]
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


def _test_soft_upsell_accept_after_push(now: datetime) -> Check:
    suffix = "soft_upsell_accept"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="11:00",
            duration=13,
            guests_count=15,
            event_format="не указано",
            upsell_items=[],
            client_name="Кирилл",
            phone=None,
        ),
    )
    with get_connection() as conn:
        message_handler.messages_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            sender="assistant",
            text="Для такой компании к беседке обычно берут уголь, розжиг, решётку/шампуры, лёд и посуду. Что подготовить для вас?",
        )
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
        )

    first_reply = _send(suffix, "нет", now)
    second_reply = _send(suffix, "ну давайте", now)
    next_reply = _send(suffix, "нет", now + timedelta(seconds=5))
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    ok = (
        "мангальный минимум" in first_reply.lower()
        and form.get("upsell_items") == ["базовый мангальный набор"]
        and state.get("current_step") == "phone"
        and "если больше ничего не нужно" in second_reply.lower().replace("ё", "е")
        and "телефон" in next_reply.lower()
        and "что подготовить" not in second_reply.lower()
    )
    return Check("soft upsell accept after push adds basic set", ok, f"{first_reply} | {second_reply} | {next_reply} | {state}")


def _test_first_mangal_set_selection_from_price_list(now: datetime) -> Check:
    suffix = "first_mangal_set_selection"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №1",
            date="2026-07-30",
            time="18:00",
            duration=6,
            guests_count=30,
            event_format="компания друзей",
            upsell_items=[],
            client_name="Иван",
            phone=None,
        ),
    )
    with get_connection() as conn:
        message_handler.messages_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            sender="assistant",
            text=(
                "Мангальный набор №1 — 500 ₽: решётка, кочерга, опахало.\n"
                "Мангальный набор №2 — 1 000 ₽: шампуры, кочерга, опахало.\n"
                "Малый мангальный набор — 400 ₽: маленькие шампуры, кочерга, опахало.\n\n"
                "Что подготовить для вас?"
            ),
        )
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
        )

    reply = _send(suffix, "давайте первый набор", now)
    next_reply = _send(suffix, "нет", now + timedelta(seconds=5))
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    next_lowered = next_reply.lower().replace("ё", "е")
    ok = (
        form.get("upsell_items") == ["мангальный набор №1"]
        and state.get("current_step") == "phone"
        and "если больше ничего не нужно" in lowered
        and "телефон" in next_lowered
        and "что подготовить" not in next_lowered
        and "свободна" not in lowered
    )
    return Check("first mangal set selection from price list", ok, f"{reply} | {next_reply} | {state}")


def _test_informal_upsell_no_two_touch(now: datetime) -> Check:
    suffix = "informal_upsell_no"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-06-30",
            time="12:00",
            duration=24,
            guests_count=5,
            event_format="праздник дождя",
            upsell_items=[],
            client_name="Анатолий",
            phone=None,
        ),
    )
    with get_connection() as conn:
        messages_repo = message_handler.messages_repo
        messages_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            sender="assistant",
            text="Обычно к бане берут допы: вода, лед, посуда, кальян. Что подготовить для вас?",
        )
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
        )

    first_reply = _send(suffix, "неа", now)
    first_state = _latest_state(suffix)
    second_reply = _send(suffix, "нет же говорю", now)
    second_state = _latest_state(suffix)
    second_form = second_state.get("form_data") or {}
    ok = (
        "напишите «нет» ещё раз" in first_reply.lower()
        and (first_state.get("form_data") or {}).get("upsell_offer_count") == 1
        and second_form.get("upsell_items") == ["не нужны"]
        and second_state.get("current_step") == "phone"
        and "телефон" in second_reply.lower()
    )
    return Check("informal upsell no uses two-touch flow", ok, f"{first_reply} | {second_reply} | {second_state}")


def _test_nu_net_upsell_no_two_touch(now: datetime) -> Check:
    suffix = "nu_net_upsell_no"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №8",
            date="2026-06-02",
            time="12:00",
            duration=20,
            guests_count=20,
            event_format="корпоратив",
            upsell_items=[],
            client_name="Кирилл",
            phone=None,
        ),
    )
    with get_connection() as conn:
        message_handler.messages_repo.create(
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

    first_reply = _send(suffix, "ну нет", now)
    first_state = _latest_state(suffix)
    second_reply = _send(suffix, "нет", now)
    second_state = _latest_state(suffix)
    ok = (
        "напишите «нет» ещё раз" in first_reply.lower()
        and (first_state.get("form_data") or {}).get("upsell_offer_count") == 1
        and (second_state.get("form_data") or {}).get("upsell_items") == ["не нужны"]
        and second_state.get("current_step") == "phone"
        and "телефон" in second_reply.lower()
    )
    return Check("nu net upsell no uses two-touch flow", ok, f"{first_reply} | {second_reply} | {second_state}")


def _test_bare_ne_first_upsell_gets_soft_push(now: datetime) -> Check:
    suffix = "bare_ne_first_upsell"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-06-30",
            time="09:00",
            duration=6,
            guests_count=10,
            event_format="спокойный отдых",
            upsell_items=[],
            client_name=None,
            phone="+79990000052",
        ),
    )
    with get_connection() as conn:
        message_handler.messages_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            sender="assistant",
            text="Обычно к бане берут воду, лёд для напитков, посуду и кальян. Что подготовить для вас?",
        )
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
        )

    first_reply = _send(suffix, "не", now)
    first_state = _latest_state(suffix)
    second_reply = _send(suffix, "нет", now + timedelta(seconds=5))
    second_state = _latest_state(suffix)
    second_form = second_state.get("form_data") or {}
    ok = (
        first_state.get("current_step") == "upsell_items"
        and (first_state.get("form_data") or {}).get("upsell_offer_count") == 1
        and not (first_state.get("form_data") or {}).get("upsell_items")
        and "напишите «нет» ещё раз" in first_reply.lower()
        and second_state.get("current_step") == "client_name"
        and second_form.get("upsell_items") == ["не нужны"]
        and "имя" in second_reply.lower()
    )
    return Check("bare ne first upsell gets soft push", ok, f"{first_reply} | {first_state} || {second_reply} | {second_state}")


def _test_on_site_upsell_refusal_keeps_no_extras(now: datetime) -> Check:
    suffix = "onsite_upsell_refusal"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-05-29",
            time="15:00",
            duration=9,
            guests_count=10,
            event_format="день рождения ребенка",
            client_name="Ирина",
            phone="+79099667655",
            upsell_items=[],
            upsell_offer_count=1,
        ),
    )
    with get_connection() as conn:
        message_handler.messages_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            sender="assistant",
            text="Могу поставить минимум — уголь и розжиг. Что добавим? Если точно ничего не нужно, напишите «нет» ещё раз.",
        )
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
            form_data=created["conversation"]["form_data"],
        )

    reply = _send(suffix, "если что там на месте возьмем", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        form.get("upsell_items") == ["не нужны"]
        and state.get("current_step") == "awaiting_confirmation"
        and "допы: не нужны" in lowered
        and "базовый мангальный набор" not in lowered
    )
    return Check("on-site upsell refusal keeps no extras", ok, f"{reply} | {state}")


def _test_phone_completion_yes_creates_hold_not_second_confirmation(now: datetime) -> Check:
    suffix = "phone_yes_no_second_confirmation"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="15:00",
            duration=9,
            guests_count=10,
            event_format="день рождения ребенка",
            client_name="Ирина",
            phone=None,
            upsell_items=["не нужны"],
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="phone",
            next_step="phone",
        )
    original_availability = message_handler.check_availability
    original_payment = message_handler.create_payment_link_for_holds
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "Свободно.", ["Свободно."])
    message_handler.create_payment_link_for_holds = lambda *_args, **_kwargs: {
        "payment_url": "https://example.test/phone-confirm",
        "amount": "1.00",
        "status": "pending",
    }
    try:
        first_reply = _send(suffix, "+79099667655", now)
        first_state = _latest_state(suffix)
        second_reply = _send(suffix, "да", now + timedelta(seconds=5))
        second_state = _latest_state(suffix)
        first_lowered = first_reply.lower().replace("ё", "е")
        second_lowered = second_reply.lower().replace("ё", "е")
        ok = (
            first_state.get("current_step") == "awaiting_confirmation"
            and "проверила заявку" in first_lowered
            and "допы: не нужны" in first_lowered
            and "https://example.test/phone-confirm" in second_reply
            and "подтверждаете бронь" not in second_lowered
            and second_state.get("current_step") == "reserved"
        )
        return Check(
            "phone completion yes creates hold not second confirmation",
            ok,
            f"{first_reply} | {first_state} || {second_reply} | {second_state}",
        )
    finally:
        message_handler.check_availability = original_availability
        message_handler.create_payment_link_for_holds = original_payment


def _test_event_format_typo_moves_to_upsell(now: datetime) -> Check:
    suffix = "event_format_typo"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №5",
            date="2026-06-30",
            time="12:00",
            duration=20,
            guests_count=10,
            event_format=None,
            upsell_items=[],
            client_name="Иван",
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
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="event_format",
            changed_fields=["event_format"],
            form_data_patch={"event_format": "просто отдых"},
        )

    message_handler.call_ai = fake_call_ai
    try:
        reply = _send(suffix, "просто отдыз", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            form.get("event_format") == "просто отдых"
            and state.get("current_step") == "upsell_items"
            and "мангальный минимум" in lowered
            and "что подготовить" in lowered
            and "какой формат отдыха" not in lowered
        )
        return Check("event format typo moves to upsell", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai


def _test_addon_price_during_upsell_does_not_repeat_event_format(now: datetime) -> Check:
    suffix = "addon_price_no_event_repeat"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №5",
            date="2026-06-30",
            time="12:00",
            duration=20,
            guests_count=10,
            event_format="просто отдых",
            upsell_items=[],
            client_name="Иван",
            phone=None,
        ),
    )
    with get_connection() as conn:
        message_handler.messages_repo.create(
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
    original_call_ai = message_handler.call_ai

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(intent="price_question", action="answer_info", current_step="upsell_items")

    message_handler.call_ai = fake_call_ai
    try:
        reply = _send(suffix, "сколько стоит решетка?", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "500" in reply
            and "какой формат отдыха" not in lowered
            and "что подготовить" in lowered
            and not form.get("upsell_items")
            and state.get("current_step") == "upsell_items"
        )
        return Check("addon price during upsell does not repeat event format", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai


def _test_state_keeps_time_duration_event_after_upsell(now: datetime) -> Check:
    suffix = "state_keeps_time_duration_event"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №1",
            date="2026-06-08",
            time=None,
            duration=None,
            guests_count=20,
            event_format=None,
            client_name="Кирилл",
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
            current_step="time",
            next_step="time",
            form_data=created["conversation"]["form_data"],
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability

    def fake_call_ai(**kwargs: Any) -> AIResponse:
        text = str(kwargs.get("text") or "")
        if "кальян" in text.lower():
            return AIResponse(
                intent="booking_request",
                action="ask_next_question",
                current_step="upsell_items",
                changed_fields=["upsell_items"],
                form_data_patch={"upsell_items": ["кальян"]},
            )
        return AIResponse(intent="booking_request", action="ask_next_question", current_step="time")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "ok", ["Беседка №1: 18:00-23:00"])
    try:
        _send(suffix, "18,00", now + timedelta(seconds=10))
        _send(suffix, "на 5", now + timedelta(seconds=20))
        event_reply = _send(suffix, "встреча однокласников", now + timedelta(seconds=30))
        upsell_reply = _send(suffix, "кальян давайте", now + timedelta(seconds=40))
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = f"{event_reply}\n{upsell_reply}".lower().replace("ё", "е")
        ok = (
            form.get("time") == "18:00"
            and form.get("duration") == 5
            and form.get("event_format") == "компания друзей"
            and "кальян" in [str(item).lower() for item in (form.get("upsell_items") or [])]
            and state.get("current_step") != "time"
            and "во сколько" not in lowered
        )
        return Check("state keeps time duration event after upsell", ok, f"{event_reply} | {upsell_reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_kalik_addon_survives_to_confirmation(now: datetime) -> Check:
    suffix = "kalik_addon_confirmation"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="warm_gazebo",
            service_variant=None,
            date="2026-06-12",
            time="17:00",
            duration=3,
            guests_count=17,
            event_format="компания друзей",
            client_name=None,
            phone=None,
            upsell_items=[],
        ),
    )
    with get_connection() as conn:
        message_handler.messages_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            sender="assistant",
            text="Обычно к теплой беседке берут воду, лед, посуду и кальян. Что подготовить для вас?",
        )
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
            form_data=created["conversation"]["form_data"],
        )

    first_reply = _send(suffix, "Калик", now)
    next_reply = _send(suffix, "нет", now + timedelta(seconds=5))
    _send(suffix, "Павлик", now + timedelta(seconds=10))
    final_reply = _send(suffix, "89062786201", now + timedelta(seconds=15))
    no_reply = _send(suffix, "нет", now + timedelta(seconds=20))
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = final_reply.lower().replace("ё", "е")
    no_lowered = no_reply.lower().replace("ё", "е")
    ok = (
        form.get("upsell_items") == ["кальян"]
        and state.get("current_step") in {"awaiting_confirmation", "change_booking"}
        and "допы: кальян" in lowered
        and "допы: не нужны" not in lowered
        and "допы: не нужны" not in no_lowered
        and "что подготовить" not in lowered
        and "кальян" in first_reply.lower().replace("ё", "е")
        and "если больше ничего не нужно" in first_reply.lower().replace("ё", "е")
        and "на какое имя" in next_reply.lower().replace("ё", "е")
    )
    return Check("positive addon survives later negative", ok, f"{first_reply} | {next_reply} | {final_reply} | {no_reply} | {state}")


def _test_live_hookah_upsell_phrases() -> Check:
    phrases = {
        "кальянчик": ["кальян"],
        "калик один": ["кальян"],
        "давайте кальян": ["кальян"],
        "а сколько кальян": None,
        "ничего кроме кальяна": ["кальян"],
        "уберите все": ["не нужны"],
        "уберите все, кальян оставьте": ["кальян"],
    }
    patches = {phrase: message_handler._upsell_items_patch(phrase).get("upsell_items") for phrase in phrases}
    ok = all(patches[phrase] == expected for phrase, expected in phrases.items())
    return Check("live hookah upsell phrases", ok, str(patches))


def _test_state_text_guard_rebuilds_ai_added_without_state(now: datetime) -> Check:
    suffix = "state_text_guard_added_without_state"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="warm_gazebo",
            service_variant=None,
            date="2026-06-12",
            time="17:00",
            duration=3,
            guests_count=17,
            event_format="компания друзей",
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
            intent="other",
            action="ask_next_question",
            reply_to_user="Кальян добавлен ✅",
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    try:
        reply = _send(suffix, "пока думаю", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*) AS count
                    FROM system_logs sl
                    JOIN conversations c ON c.id = sl.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id = %s
                      AND sl.event_type = 'state_text_consistency_rebuilt'
                    """,
                    (TEST_PREFIX + suffix,),
                )
                log_count = cur.fetchone()["count"]
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "кальян добав" not in lowered
            and form.get("upsell_items") in ([], None)
            and log_count == 1
        )
        return Check("AI said added with empty state is rebuilt", ok, f"{reply} | {state} | logs={log_count}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_addon_prices_plural_question_replies_immediately(now: datetime) -> Check:
    suffix = "addon_prices_plural_immediate"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="18:00",
            duration=6,
            guests_count=10,
            event_format="компания друзей",
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
        )
    original_call_ai = message_handler.call_ai

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(intent="price_question", action="answer_info", current_step="upsell_items")

    message_handler.call_ai = fake_call_ai
    try:
        reply = _send(suffix, "А какие цены на допы", now)
        state = _latest_state(suffix)
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "кальян" in lowered
            and "мангальный набор" in lowered
            and "сейчас расскажу" not in lowered
            and "формат отдыха" not in lowered
            and state.get("current_step") == "upsell_items"
            and not (state.get("form_data") or {}).get("client_name")
        )
        return Check("addon prices plural question replies immediately", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai


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


def _test_positive_upsell_asks_for_more_then_continues(now: datetime) -> Check:
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
    second_reply = _send(suffix, "и лед", now + timedelta(seconds=5))
    next_reply = _send(suffix, "нет", now + timedelta(seconds=10))
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    ok = (
        "если больше ничего не нужно" in reply.lower().replace("ё", "е")
        and "если больше ничего не нужно" in second_reply.lower().replace("ё", "е")
        and "все верно" in next_reply.lower().replace("ё", "е")
        and state.get("status") == "awaiting_confirmation"
        and form.get("upsell_items") == ["вода", "лед"]
    )
    return Check("positive upsell asks for more then continues", ok, f"{reply} | {second_reply} | {next_reply} | {state}")


def _test_mixed_addon_price_and_selection_saves_items(now: datetime) -> Check:
    suffix = "mixed_addon_price_selection"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №6",
            date="2026-06-30",
            time="18:00",
            duration=6,
            guests_count=8,
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
    reply = _send(suffix, "а вода и лед сколько стоят? если можно, добавьте воду и лед", now)
    next_reply = _send(suffix, "нет", now + timedelta(seconds=5))
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    items = form.get("upsell_items") or []
    ok = (
        "точной отдельной цены" in reply.lower().replace("ё", "е")
        and "добавим" in reply.lower().replace("ё", "е")
        and "если больше ничего не нужно" in reply.lower().replace("ё", "е")
        and "телефон" in next_reply.lower().replace("ё", "е")
        and {"вода", "лед"} <= set(items)
        and state.get("current_step") == "phone"
    )
    return Check("mixed addon price and selection saves items", ok, f"{reply} | {next_reply} | {state}")


def _test_late_kalik_price_adds_addon_to_confirmation(now: datetime) -> Check:
    suffix = "late_kalik_price_confirmation"
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №4",
        date="2026-06-30",
        time="18:00",
        duration=6,
        guests_count=10,
        event_format="компания друзей",
        client_name="Иван",
        phone="+79000000001",
        upsell_items=["не нужны"],
    )
    created = _create_reserved_conversation(suffix, now, form)
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="awaiting_confirmation",
            current_step="awaiting_confirmation",
            next_step="confirmation",
            form_data=form,
        )

    reply = _send(suffix, "а я бы хотел добавить калик в допы, цена изменится?", now)
    state = _latest_state(suffix)
    updated = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "кальян — 1 500" in lowered
        and "добавила в допы" in lowered
        and "допы: кальян" in lowered
        and "допы: не нужны" not in lowered
        and updated.get("upsell_items") == ["кальян"]
        and state.get("current_step") == "awaiting_confirmation"
    )
    return Check("late kalik price adds addon to confirmation", ok, f"{reply} | {state}")


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


class _FakeWaitlistBot:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, *, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


def _create_waitlist_request(
    suffix: str,
    now: datetime,
    *,
    service_type: str = "gazebo",
    desired_date: date = date(2026, 6, 30),
    desired_time: time | None = time(18, 0),
    duration_minutes: int | None = 360,
    guests_count: int | None = 30,
    phone: str = TEST_PHONE,
) -> dict[str, Any]:
    form = _base_form(
        service_type=service_type,
        service_variant=None,
        date=desired_date.isoformat(),
        time=desired_time.strftime("%H:%M") if desired_time else None,
        duration=(duration_minutes // 60) if duration_minutes else None,
        guests_count=guests_count,
        phone=phone,
    )
    created = _create_reserved_conversation(suffix, now, form)
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="awaiting_new_date",
            next_step="date",
            form_data=form,
        )
        waitlist = waitlist_service.remember_waitlist_request(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            form_data=form,
        )
    return created | {"waitlist": waitlist, "form": form}


def _waitlist_status(waitlist_id: int) -> str | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM waitlist_requests WHERE id = %s", (waitlist_id,))
            row = cur.fetchone()
            return row["status"] if row else None


def _test_waitlist_notifies_only_relevant_requests(now: datetime) -> Check:
    active = _create_waitlist_request("waitlist_notify_active", now, phone="+79990000101")
    booked = _create_waitlist_request("waitlist_notify_booked", now, phone="+79990000102")
    declined = _create_waitlist_request("waitlist_notify_declined", now, phone="+79990000103")

    with get_connection() as conn:
        hold = slot_holds_repo.create(
            conn,
            conversation_id=booked["conversation"]["id"],
            user_id=booked["user"]["id"],
            service_type="gazebo",
            yclients_service_id="local_waitlist_notify_booked",
            slot_date=date(2026, 6, 30),
            slot_time=time(18, 0),
            duration_minutes=360,
            expires_at=now + timedelta(minutes=10),
        )
        bookings_repo.create_from_hold(
            conn,
            conversation_id=booked["conversation"]["id"],
            user_id=booked["user"]["id"],
            slot_hold_id=hold["id"],
            service_type="gazebo",
            booking_date=date(2026, 6, 30),
            booking_time=time(18, 0),
            duration_minutes=360,
            client_name="Кирилл",
            phone="+79990000102",
            guests_count=30,
            event_format="спокойный отдых",
            preferences=None,
            upsell_items=["не нужны"],
            status="created_in_yclients",
            payment_status="paid",
        )

    _send("waitlist_notify_declined", "не надо уведомлять, уже не актуально", now + timedelta(seconds=5))

    original_check = waitlist_service.check_availability
    original_list_active_due = waitlist_service.waitlist_repo.list_active_due
    target_waitlist_ids = {
        int(active["waitlist"]["id"]),
        int(booked["waitlist"]["id"]),
        int(declined["waitlist"]["id"]),
    }

    def fake_check_availability(*_args: Any, **_kwargs: Any) -> AvailabilityResult:
        return AvailabilityResult(True, "ok", ["Беседка №1: 18:00-00:00 следующего дня"])

    def fake_list_active_due(conn: Any, *, now: datetime, limit: int = 50) -> list[dict[str, Any]]:
        rows = original_list_active_due(conn, now=now, limit=limit)
        return [row for row in rows if int(row["id"]) in target_waitlist_ids]

    bot = _FakeWaitlistBot()
    waitlist_service.check_availability = fake_check_availability
    waitlist_service.waitlist_repo.list_active_due = fake_list_active_due
    try:
        sent = asyncio.run(waitlist_service.notify_waitlist_matches(bot))
    finally:
        waitlist_service.check_availability = original_check
        waitlist_service.waitlist_repo.list_active_due = original_list_active_due

    active_status = _waitlist_status(active["waitlist"]["id"])
    booked_status = _waitlist_status(booked["waitlist"]["id"])
    declined_status = _waitlist_status(declined["waitlist"]["id"])
    sent_text = "\n".join(text for _, text in bot.sent)
    ok = (
        sent == 1
        and len(bot.sent) == 1
        and "Появилось свободное место" in sent_text
        and active_status == "notified"
        and booked_status == "closed"
        and declined_status == "closed"
    )
    return Check(
        "waitlist notifies only relevant requests",
        ok,
        f"sent={sent}, statuses={(active_status, booked_status, declined_status)}, text={sent_text}",
    )


def _test_bathhouse_blocks_large_group(now: datetime) -> Check:
    suffix = "bathhouse_blocks_large_group"
    form = _base_form(
        service_type="bathhouse",
        service_variant=None,
        date="2026-06-29",
        time="18:00",
        duration=6,
        guests_count=None,
        event_format=None,
        upsell_items=[],
    )
    created = _create_reserved_conversation(suffix, now, form)
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="guests_count",
            next_step="guests_count",
            form_data=form,
        )
    reply = _send(suffix, "40", now)
    state = _latest_state(suffix)
    form_data = state.get("form_data") or {}
    ok = (
        "слишком большая компания" in reply.lower()
        and "бесед" in reply.lower()
        and form_data.get("guests_count") in (None, "")
        and state.get("current_step") in {"service_type", "guests_count"}
    )
    return Check("bathhouse blocks large group", ok, f"{reply} | {state}")


def _test_contextual_day_number_keeps_discussed_month(now: datetime) -> Check:
    patch = {"date": "2026-05-30", "service_type": "gazebo"}
    form_data = {
        "service_type": "bathhouse",
        "last_unavailable": {"service_type": "bathhouse", "date": "2026-06-30", "guests_count": 40},
    }
    updated = message_handler._apply_contextual_day_number_patch(
        patch,
        form_data,
        "хорошо давайте беседку тогда на 30 число",
        now,
    )
    ok = updated.get("date") == "2026-06-30"
    return Check("contextual day number keeps discussed month", ok, str(updated))


def _test_confirmation_no_is_not_upsell_correction(now: datetime) -> Check:
    suffix = "confirmation_no_not_upsell"
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №1",
        date="2026-06-29",
        time="18:00",
        duration=6,
        guests_count=40,
        event_format="спокойный отдых",
        upsell_items=["не нужны"],
    )
    created = _create_reserved_conversation(suffix, now, form)
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="awaiting_confirmation",
            current_step="awaiting_confirmation",
            next_step="confirmation",
            form_data=form,
        )
    reply = _send(suffix, "нет", now)
    state = _latest_state(suffix)
    ok = (
        "что нужно изменить" in reply.lower()
        and "обнов" not in reply.lower()
        and state.get("current_step") == "change_booking"
        and (state.get("form_data") or {}).get("upsell_items") == ["не нужны"]
    )
    return Check("confirmation no is not upsell correction", ok, f"{reply} | {state}")


def _test_generic_ok_after_upsell_info_does_not_accept_items(now: datetime) -> Check:
    suffix = "upsell_info_generic_ok"
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №1",
        date="2026-06-29",
        time="18:00",
        duration=6,
        guests_count=30,
        event_format="спокойный отдых",
        upsell_items=[],
    )
    created = _create_reserved_conversation(suffix, now, form)
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
            form_data=form,
        )
    info = _send(suffix, "парковка?", now)
    reply = _send(suffix, "ну окей", now + timedelta(seconds=5))
    state = _latest_state(suffix)
    form_data = state.get("form_data") or {}
    ok = (
        "парков" in info.lower()
        and form_data.get("upsell_items") in ([], None)
        and state.get("current_step") == "upsell_items"
        and "базовый мангальный набор" not in str(form_data.get("upsell_items"))
    )
    return Check("generic ok after upsell info does not accept items", ok, f"info={info} | reply={reply} | {state}")


def _test_upsell_parking_info_returns_to_empty_addons(now: datetime) -> Check:
    suffix = "upsell_parking_empty"
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №8",
        date="2026-06-30",
        time="18:00",
        duration=6,
        guests_count=12,
        event_format="компания друзей",
        client_name="Иван",
        phone=None,
        upsell_items=[],
    )
    created = _create_reserved_conversation(suffix, now, form)
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
            form_data=form,
        )

    reply = _send(suffix, "а че с парковкой как дела", now)
    state = _latest_state(suffix)
    updated = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "парковка есть" in lowered
        and "что подготовить для вас" in lowered
        and "телефон" not in lowered
        and not updated.get("upsell_items")
        and state.get("current_step") == "upsell_items"
    )
    return Check("upsell parking info returns to empty addons", ok, f"{reply} | {state}")


def _test_upsell_parking_info_keeps_selected_addon(now: datetime) -> Check:
    suffix = "upsell_parking_keeps_kalik"
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №8",
        date="2026-06-30",
        time="18:00",
        duration=6,
        guests_count=12,
        event_format="компания друзей",
        client_name="Иван",
        phone=None,
        upsell_items=[],
    )
    created = _create_reserved_conversation(suffix, now, form)
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
            form_data=form,
        )

    first_reply = _send(suffix, "калик один", now)
    parking_reply = _send(suffix, "а че с парковкой как дела", now + timedelta(seconds=5))
    no_reply = _send(suffix, "нет", now + timedelta(seconds=10))
    state = _latest_state(suffix)
    updated = state.get("form_data") or {}
    parking_lowered = parking_reply.lower().replace("ё", "е")
    ok = (
        updated.get("upsell_items") == ["кальян"]
        and "если хотите добавить что-то еще" in parking_lowered
        and "телефон" not in parking_lowered
        and "парковка есть" in parking_lowered
        and "кальян" in first_reply.lower().replace("ё", "е")
        and "телефон" in no_reply.lower().replace("ё", "е")
        and state.get("current_step") == "phone"
    )
    return Check("upsell parking info keeps selected addon", ok, f"{first_reply} | {parking_reply} | {no_reply} | {state}")


def _test_location_question_does_not_handoff() -> Check:
    samples = [
        "А где вы находитесь?",
        "Где находитесь",
        "Какой адрес?",
        "бля будем зажигать",
    ]
    ok = all(not message_handler._looks_like_handoff_needed(text) for text in samples)
    rude_ok = message_handler._looks_like_handoff_needed("вы меня бесите")
    complaint_ok = message_handler._looks_like_handoff_needed("бля, верните деньги")
    return Check("location question does not handoff", ok and rude_ok and complaint_ok, f"samples={samples}, rude_ok={rude_ok}, complaint_ok={complaint_ok}")


def _test_emotional_event_format_does_not_handoff(now: datetime) -> Check:
    suffix = "emotional_event_format"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="18:00",
            duration=6,
            guests_count=10,
            event_format=None,
            phone="+79990000047",
            upsell_items=[],
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
            form_data=created["conversation"]["form_data"],
        )
    original_call_ai = message_handler.call_ai

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="event_format",
            changed_fields=["event_format"],
            form_data_patch={"event_format": "компания друзей"},
        )

    message_handler.call_ai = fake_call_ai
    try:
        reply = _send(suffix, "бля будем зажигать", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            state.get("status") != "handoff"
            and form.get("event_format") == "компания друзей"
            and state.get("next_step") == "upsell_items"
            and ("доп" in lowered or "что подготовить" in lowered)
        )
        return Check("emotional event format does not handoff", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai


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
            {"service_type": "gazebo", "service_variant": "Беседка №1"},
        ]
    )
    current_bookings_media = media_for_client_message(
        "какие у меня брони?",
        (
            "У вас 2 брони:\n"
            "1. Беседка №1: 17 июня, с 17:00 до 08:00 следующего дня (15 часов), гостей: 30. оплата прошла, бронь подтверждена.\n"
            "2. Баня: 30 июня, с 12:00 до 16:00 (4 часа), гостей: 15. оплата прошла, бронь подтверждается в журнале."
        ),
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
        and [path.name for path in paid_media] == ["banya.jpg", "dom_gostevoy.jpg", "besedka8.jpg", "besedka1.jpg"]
        and [path.name for path in current_bookings_media] == ["besedka1.jpg", "banya.jpg"]
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


def _add_paid_payment_for_latest_booking(created: dict[str, Any], now: datetime) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM bookings
                WHERE conversation_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (created["conversation"]["id"],),
            )
            booking_id = int(cur.fetchone()["id"])
        payment = payments_repo.create_pending(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            booking_ids=[booking_id],
            provider="yookassa",
            amount=Decimal("1.00"),
            currency="RUB",
            description="local regression paid booking",
            raw_payload={"booking_ids": [booking_id]},
        )
        payments_repo.update_provider_status(
            conn,
            payment_id=payment["id"],
            status="paid",
            paid_at=now,
            raw_payload={"booking_ids": [booking_id], "status": "succeeded"},
        )


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
        yclients_service_id="18201061",
        provider_record_id="local_shared_phone_b",
        phone=shared_phone,
    )
    reply = _send("shared_phone_b", "какие у меня сейчас брони?", now)
    ok = "1 бронь" in reply and "1 июня" in reply and "30 мая" not in reply
    return Check("booking summary does not merge shared phone", ok, reply)


def _test_available_services_uses_active_booking_not_stale_form(now: datetime) -> Check:
    suffix = "available_services_active_booking"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 17),
        yclients_service_id="18201061",
        provider_record_id="local_available_services_active_gazebo",
        phone="+79990000051",
    )
    stale_form = _base_form(
        service_type="bathhouse",
        service_variant=None,
        date=None,
        time=None,
        duration=None,
        guests_count=None,
        event_format=None,
        phone="+79990000051",
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="payment_paid",
            current_step="reserved",
            next_step="payment_status",
            form_data=stale_form,
        )
    summary = _send(suffix, "а у меня сейчас есть брони?", now)
    reply = _send(suffix, "а что еще можно забронить?", now + timedelta(seconds=5))
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "у вас 1 брон" in summary.lower().replace("ё", "е")
        and "беседка №" in summary.lower().replace("ё", "е")
        and "кроме вашей беседки" in lowered
        and "помимо бани" not in lowered
        and "ожидает подтверждения" not in lowered
    )
    return Check("available services uses active booking not stale form", ok, f"{summary} | {reply}")


def _test_start_available_services_lists_all_primary_options(now: datetime) -> Check:
    suffix = "start_available_services_all"
    _send(suffix, "ну давай забронируем", now)
    reply = _send(suffix, "че можно?", now + timedelta(seconds=5))
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "обычные/летние беседки" in lowered
        and "крытую беседку" in lowered
        and "теплую беседку" in lowered
        and "баню с бассейном" in lowered
        and "гостевой дом" in lowered
        and state.get("current_step") == "service_type"
        and state.get("next_step") == "service_type"
        and not form.get("service_type")
    )
    return Check("start available services lists all primary options", ok, f"{reply} | {state}")


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
            and bool(flow.get("booking_id"))
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


def _test_second_service_same_time_keeps_current_service(now: datetime) -> Check:
    suffix = "second_service_same_time"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201065",
        provider_record_id="local_second_service_same_time_gazebo",
        phone="+79990000020",
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="duration",
            next_step="duration",
            form_data=_base_form(
                service_type="bathhouse",
                service_variant=None,
                date="2026-06-30",
                time="12:00",
                duration=None,
                guests_count=None,
                event_format=None,
                phone="+79990000020",
            ),
        )
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="duration",
            changed_fields=["service_type"],
            form_data_patch={"service_type": "gazebo"},
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "Баня свободна.", ["Баня: свободно"])
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "на то же время что и беседка", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "bathhouse"
            and form.get("time") == "18:00"
            and form.get("duration") == 6
            and "Беседка №" not in reply
        )
        return Check("second service same time keeps current service", ok, f"{reply} | {form}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _test_second_service_same_time_reference_on_time_step(now: datetime) -> Check:
    suffix = "second_service_same_time_on_time_step"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201065",
        provider_record_id="local_second_service_same_time_on_time_step_gazebo",
        phone="+79990000021",
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="time",
            next_step="time",
            form_data=_base_form(
                service_type="bathhouse",
                service_variant=None,
                date="2026-06-30",
                time=None,
                duration=None,
                guests_count=None,
                event_format=None,
                phone="+79990000021",
            ),
        )
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="time",
            changed_fields=[],
            form_data_patch={},
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "Баня свободна.", ["Баня: свободно"])
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "и часы как там же, без изменений", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "bathhouse"
            and form.get("time") == "18:00"
            and form.get("duration") == 6
            and "Беседка №" not in reply.splitlines()[0]
        )
        return Check("second service same time reference on time step", ok, f"{reply} | {form}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _test_second_service_same_date_keeps_current_service(now: datetime) -> Check:
    suffix = "second_service_same_date"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201065",
        provider_record_id="local_second_service_same_date_gazebo",
        phone="+79990000022",
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="date",
            next_step="date",
            form_data=_base_form(
                service_type="bathhouse",
                service_variant=None,
                date=None,
                time=None,
                duration=None,
                guests_count=None,
                event_format=None,
                phone="+79990000022",
            ),
        )
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="date",
            changed_fields=["service_type"],
            form_data_patch={"service_type": "gazebo"},
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "Баня свободна.", ["Баня: свободно"])
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "на ту же дату что и беседка", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "bathhouse"
            and form.get("date") == "2026-06-30"
            and "Беседка №" not in reply
            and state.get("current_step") in {"time", "duration"}
        )
        return Check("second service same date keeps current service", ok, f"{reply} | {form}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _test_second_service_same_number_wording_keeps_current_service(now: datetime) -> Check:
    suffix = "second_service_same_number_wording"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201065",
        provider_record_id="local_second_service_same_number_wording_gazebo",
        phone="+79990000025",
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="date",
            next_step="date",
            form_data=_base_form(
                service_type="bathhouse",
                service_variant=None,
                date=None,
                time=None,
                duration=None,
                guests_count=None,
                event_format=None,
                phone="+79990000025",
            ),
        )
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="date",
            changed_fields=["service_type"],
            form_data_patch={"service_type": "gazebo"},
        )

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "Баня свободна.", ["Баня: свободно"])
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "число такое же как у беседки", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            form.get("service_type") == "bathhouse"
            and form.get("date") == "2026-06-30"
            and not form.get("time")
            and not form.get("duration")
            and "на какую дату" not in lowered
            and state.get("current_step") in {"time", "duration"}
        )
        return Check("second service same number wording keeps current service", ok, f"{reply} | {form}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _test_live_135_paid_gazebo_then_bathhouse_same_number(now: datetime) -> Check:
    suffix = "live_135_paid_gazebo_then_bath"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201061",
        provider_record_id="local_live_135_gazebo",
        phone="+79990000023",
    )
    original_classifier = message_handler.classify_post_booking_message
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability
    original_create_missing = message_handler.create_missing_yclients_records

    def fake_classifier(**_: Any) -> PostBookingResponse:
        return PostBookingResponse(
            intent="new_booking_request",
            reply_to_user=(
                "Конечно! Можно забронировать беседки, баню, гостевой дом или тёплую беседку."
            ),
        )

    def fake_call_ai(**kwargs: Any) -> AIResponse:
        text = str(kwargs.get("text") or "").lower()
        if "бан" in text:
            return AIResponse(
                intent="booking_request",
                action="ask_next_question",
                current_step="date",
                changed_fields=["service_type"],
                form_data_patch={"service_type": "bathhouse"},
            )
        return AIResponse(intent="company_info", action="answer_info", reply_to_user="Да, по активной беседке всё нормально.")

    message_handler.classify_post_booking_message = fake_classifier
    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "Баня свободна.", ["Баня: свободно"])
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        options = _send(suffix, "хоршо\nможно еще что нибудь забронировать?", now + timedelta(seconds=10))
        after_options = _latest_state(suffix)
        bath = _send(suffix, "давайте еще баню на то же число что и беседка если можно", now + timedelta(seconds=20))
        bath_state = _latest_state(suffix)
        bath_form = bath_state.get("form_data") or {}
        info = _send(suffix, "а вообще норм беседка?", now + timedelta(seconds=30))
        info_state = _latest_state(suffix)
        info_form = info_state.get("form_data") or {}
        lowered_options = options.lower().replace("ё", "е")
        lowered_bath = bath.lower().replace("ё", "е")
        lowered_info = info.lower().replace("ё", "е")
        ok = (
            "ожидает подтверждения" not in lowered_options
            and after_options.get("current_step") == "reserved"
            and bath_form.get("service_type") == "bathhouse"
            and bath_form.get("date") == "2026-06-30"
            and bath_state.get("current_step") == "time"
            and "на какую дату" not in lowered_bath
            and "во сколько" in lowered_bath
            and info_form.get("service_type") == "bathhouse"
            and info_state.get("current_step") == "time"
            and "беседка №4" in lowered_info
            and "есть разные варианты" not in lowered_info
            and "по бане продолжим" in lowered_info
        )
        return Check(
            "live 135 paid gazebo then bathhouse keeps context",
            ok,
            f"options={options} | bath={bath} | bath_state={bath_state} | info={info} | info_state={info_state}",
        )
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability
        message_handler.create_missing_yclients_records = original_create_missing


def _test_paid_booking_payment_question_is_deterministic(now: datetime) -> Check:
    suffix = "paid_payment_question"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201061",
        provider_record_id="local_paid_payment_question_gazebo",
        phone="+79990000024",
    )
    _add_paid_payment_for_latest_booking(created, now)
    original_classifier = message_handler.classify_post_booking_message
    original_create_missing = message_handler.create_missing_yclients_records

    def bad_classifier(**_: Any) -> PostBookingResponse:
        return PostBookingResponse(
            intent="current_booking_question",
            reply_to_user="Нет, предоплата не поступила. Резерв истёк через 10 минут.",
        )

    message_handler.classify_post_booking_message = bad_classifier
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "а она уже активна, я вносил предоплату?", now + timedelta(seconds=5))
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "оплата получена" in lowered
            and "бронь подтверждена" in lowered
            and "предоплата не поступила" not in lowered
            and "резерв истек" not in lowered
        )
        return Check("paid booking payment question is deterministic", ok, reply)
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.create_missing_yclients_records = original_create_missing


def _test_paid_notification_includes_booking_summary() -> Check:
    text = payment_status_runner._paid_notification_text(
        {"amount": "1.00"},
        [
            {
                "service_type": "gazebo",
                "hold_yclients_service_id": "18201061",
                "booking_date": date(2026, 5, 29),
                "booking_time": time(15, 0),
                "duration_minutes": 540,
            }
        ],
    )
    lowered = text.lower().replace("ё", "е")
    ok = (
        "бронь в журнале" in lowered
        and "29 мая" in lowered
        and "15:00" in text
        and "предоплата: 1.00 ₽" in lowered
    )
    return Check("paid notification includes booking summary", ok, text)


def _test_new_bath_request_does_not_cancel_paid_gazebo(now: datetime) -> Check:
    suffix = "new_bath_not_cancel"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 6, 30),
        yclients_service_id="18201061",
        provider_record_id="local_new_bath_not_cancel_gazebo",
        phone="+79990000025",
    )
    original_classifier = message_handler.classify_post_booking_message
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_create_missing = message_handler.create_missing_yclients_records

    def bad_classifier(**_: Any) -> PostBookingResponse:
        return PostBookingResponse(
            intent="change_existing_booking",
            change_type="cancel",
            reply_to_user="Могу отменить бронь.",
        )

    def fake_call_ai(**kwargs: Any) -> AIResponse:
        text = str(kwargs.get("text") or "").lower()
        if "бан" in text:
            return AIResponse(
                intent="booking_request",
                action="ask_next_question",
                current_step="date",
                changed_fields=["service_type"],
                form_data_patch={"service_type": "bathhouse"},
            )
        return AIResponse(intent="other", action="ask_next_question")

    message_handler.classify_post_booking_message = bad_classifier
    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "давайте новую оформим, мне нужна баня", now + timedelta(seconds=5))
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status
                    FROM bookings b
                    JOIN users u ON u.id = b.user_id
                    WHERE u.external_id = %s
                    ORDER BY b.id DESC
                    LIMIT 1
                    """,
                    (TEST_PREFIX + suffix,),
                )
                booking_status = cur.fetchone()["status"]
        lowered = reply.lower().replace("ё", "е")
        ok = (
            form.get("service_type") == "bathhouse"
            and state.get("current_step") == "date"
            and "отмен" not in lowered
            and "на какую дату" in lowered
            and booking_status != "cancelled"
        )
        return Check("new bath request does not cancel paid gazebo", ok, f"{reply} | {state} | booking={booking_status}")
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.create_missing_yclients_records = original_create_missing


def _test_bathhouse_post_booking_info_then_generic_new_request(now: datetime) -> Check:
    suffix = "bath_info_generic_new"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=date(2026, 5, 29),
        yclients_service_id="18201061",
        provider_record_id="local_bath_info_generic_new_gazebo",
        phone="+79099667655",
    )
    original_classifier = message_handler.classify_post_booking_message
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_create_missing = message_handler.create_missing_yclients_records

    def bad_classifier(**_: Any) -> PostBookingResponse:
        return PostBookingResponse(
            intent="other",
            reply_to_user="Да, у нас есть русская баня и финская сауна. Можно добавить к текущей брони.",
        )

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="ask_next_question",
            current_step="date",
            changed_fields=[],
            form_data_patch={},
        )

    message_handler.classify_post_booking_message = bad_classifier
    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        info = _send(suffix, "ну все кайф, а в баньку можно будет сходить?", now + timedelta(seconds=5))
        info_state = _latest_state(suffix)
        how = _send(suffix, "а ее как бронировать нужно?", now + timedelta(seconds=10))
        how_state = _latest_state(suffix)
        start = _send(suffix, "давайте начнем новую заявку", now + timedelta(seconds=15))
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        info_lowered = info.lower().replace("ё", "е")
        how_lowered = how.lower().replace("ё", "е")
        start_lowered = start.lower().replace("ё", "е")
        ok = (
            "баня с бассейном" in info_lowered
            and "отдельной брон" in info_lowered
            and "не добавляется" in info_lowered
            and "русская баня" not in info_lowered
            and "финская сауна" not in info_lowered
            and (info_state.get("form_data") or {}).get("last_discussed_service_type") == "bathhouse"
            and "отдельной брон" in how_lowered
            and "не добавляется" in how_lowered
            and "русская баня" not in how_lowered
            and "финская сауна" not in how_lowered
            and (how_state.get("form_data") or {}).get("last_discussed_service_type") == "bathhouse"
            and form.get("service_type") == "bathhouse"
            and form.get("phone") == "+79099667655"
            and not form.get("date")
            and not form.get("time")
            and not form.get("duration")
            and not form.get("guests_count")
            and not form.get("event_format")
            and not form.get("upsell_items")
            and state.get("current_step") == "date"
            and "на какую дату" in start_lowered
        )
        return Check("bathhouse post-booking info then generic new request", ok, f"{info} | {how} | {start} | {state}")
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.create_missing_yclients_records = original_create_missing


def _test_gazebo_info_then_separate_booking_from_old_bath_draft(now: datetime) -> Check:
    suffix = "gazebo_info_separate_from_old_bath"
    _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            date="2026-06-30",
            time="09:00",
            duration=12,
            guests_count=10,
            event_format="просто так",
            upsell_items=["не нужны"],
            phone="+79099667655",
        ),
    )
    original_classifier = message_handler.classify_post_booking_message
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_create_missing = message_handler.create_missing_yclients_records

    def new_booking_classifier(**_: Any) -> PostBookingResponse:
        return PostBookingResponse(intent="new_booking_request", reply_to_user="")

    def dangerous_old_bath_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="check_availability",
            current_step="duration",
            changed_fields=[],
            form_data_patch={},
        )

    message_handler.classify_post_booking_message = new_booking_classifier
    message_handler.call_ai = dangerous_old_bath_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        info = _send(suffix, "а какие беседки есть", now + timedelta(seconds=5))
        info_state = _latest_state(suffix)
        start = _send(suffix, "хочу добвить отдельной бронью", now + timedelta(seconds=10))
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        info_form = info_state.get("form_data") or {}
        lowered_info = info.lower().replace("ё", "е")
        lowered_start = start.lower().replace("ё", "е")
        ok = (
            "№1" in info
            and "до 50" in lowered_info
            and info_form.get("service_type") == "bathhouse"
            and info_form.get("last_discussed_service_type") == "gazebo"
            and form.get("service_type") == "gazebo"
            and form.get("phone") == "+79099667655"
            and not form.get("date")
            and not form.get("time")
            and not form.get("duration")
            and not form.get("guests_count")
            and not form.get("event_format")
            and not form.get("upsell_items")
            and state.get("current_step") == "date"
            and "на какую дату" in lowered_start
            and "баня" not in lowered_start
            and "фиксирован" not in lowered_start
            and "12 часов" not in lowered_start
        )
        return Check("gazebo info then separate booking ignores old bath draft", ok, f"{info} | {start} | {state}")
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.create_missing_yclients_records = original_create_missing


def _test_bathhouse_post_booking_paraphrases_start_clean(now: datetime) -> Check:
    cases = (
        (
            "bath_paraphrase_1",
            "а банька у вас есть вообще?",
            "а как ее оформить?",
            "ну тогда оформим новую",
        ),
        (
            "bath_paraphrase_2",
            "баню вообще можно забронировать?",
            "как её забронировать?",
            "давай новую бронь тогда",
        ),
    )
    original_classifier = message_handler.classify_post_booking_message
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_create_missing = message_handler.create_missing_yclients_records

    def bad_classifier(**_: Any) -> PostBookingResponse:
        return PostBookingResponse(
            intent="other",
            reply_to_user="Да, можно добавить сауну к беседке.",
        )

    message_handler.classify_post_booking_message = bad_classifier
    message_handler.call_ai = lambda **_kwargs: AIResponse(intent="booking_request", action="ask_next_question")
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    results: list[str] = []
    ok = True
    try:
        for index, (suffix, info_text, how_text, start_text) in enumerate(cases):
            _create_paid_booking_for_action(
                suffix,
                now,
                service_type="gazebo",
                booking_date=date(2026, 5, 29),
                yclients_service_id="18201061",
                provider_record_id=f"local_bath_paraphrase_{index}",
                phone="+79099667655",
            )
            info = _send(suffix, info_text, now + timedelta(seconds=index * 10 + 1))
            how = _send(suffix, how_text, now + timedelta(seconds=index * 10 + 2))
            start = _send(suffix, start_text, now + timedelta(seconds=index * 10 + 3))
            state = _latest_state(suffix)
            form = state.get("form_data") or {}
            combined = "\n".join([info, how, start]).lower().replace("ё", "е")
            case_ok = (
                "саун" not in combined
                and "доп к беседке" not in combined
                and form.get("service_type") == "bathhouse"
                and form.get("phone") == "+79099667655"
                and not form.get("date")
                and not form.get("time")
                and not form.get("duration")
                and not form.get("guests_count")
                and not form.get("event_format")
                and not form.get("upsell_items")
                and state.get("current_step") == "date"
            )
            ok = ok and case_ok
            results.append(f"{info_text} / {how_text} / {start_text} => {state}")
        return Check("bathhouse post-booking paraphrases start clean", ok, "\n---\n".join(results))
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.create_missing_yclients_records = original_create_missing


def _test_payment_delay_does_not_start_reschedule(now: datetime) -> Check:
    suffix = "payment_delay_not_reschedule"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-07-01",
            time="18:00",
            duration=3,
            guests_count=15,
            event_format="праздник",
            client_name="Кирилл",
            phone="+79990000026",
            upsell_items=["не нужны"],
        ),
    )
    actual_now = datetime.now(ZoneInfo(get_settings().app_timezone))
    with get_connection() as conn:
        slot_holds_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            service_type="bathhouse",
            yclients_service_id="18490331",
            slot_date=date(2026, 7, 1),
            slot_time=time(18, 0),
            duration_minutes=180,
            expires_at=actual_now + timedelta(minutes=30),
        )
    original_classifier = message_handler.classify_post_booking_message

    def bad_classifier(**_: Any) -> PostBookingResponse:
        return PostBookingResponse(
            intent="change_existing_booking",
            change_type="reschedule",
            reply_to_user="Активной брони для переноса не нашла.",
        )

    message_handler.classify_post_booking_message = bad_classifier
    try:
        reply = _send(
            suffix,
            "да я и говорю что щас денег нет чтобы оплатить, щас все соберу с людей, и оплачу, подождете?",
            now + timedelta(seconds=5),
        )
        state = _latest_state(suffix)
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "перенос" not in lowered
            and "резерв держится 30 минут" in lowered
            and state.get("current_step") == "reserved"
        )
        return Check("payment delay does not start reschedule", ok, f"{reply} | {state}")
    finally:
        message_handler.classify_post_booking_message = original_classifier


def _test_fake_payment_request_does_not_mark_paid(now: datetime) -> Check:
    suffix = "fake_payment_request"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="09:00",
            duration=12,
            guests_count=10,
            event_format="семейный отдых",
            upsell_items=["не нужны"],
            client_name="Кирилл",
            phone="+79968533502",
        ),
    )
    _create_active_hold(created["conversation"], created["user"], now)
    reply = _send(suffix, "а ты можешь сделать будто бы я оплатил?", now)
    state = _latest_state(suffix)
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "не могу" in lowered
        and "будто" in lowered
        and "оплата получена" not in lowered
        and state.get("status") == "reserved"
        and state.get("current_step") == "reserved"
    )
    return Check("fake payment request does not mark paid", ok, f"{reply} | {state}")


def _test_resume_same_expired_hold_does_not_ask_date(now: datetime) -> Check:
    suffix = "resume_same_expired_hold"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date=None,
            time=None,
            duration=None,
            guests_count=None,
            event_format=None,
            client_name="Кирилл",
            phone="+79990000027",
        ),
    )
    actual_now = datetime.now(ZoneInfo(get_settings().app_timezone))
    with get_connection() as conn:
        hold = slot_holds_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            service_type="bathhouse",
            yclients_service_id="local_resume_same_expired_hold",
            slot_date=date(2026, 7, 1),
            slot_time=time(18, 0),
            duration_minutes=180,
            expires_at=actual_now - timedelta(minutes=1),
        )
        slot_holds_repo.expire_old(conn, actual_now)
        slot_holds_repo.mark_expired_notified(conn, hold_id=hold["id"], now=actual_now)

    original_classifier = message_handler.classify_post_booking_message
    original_availability = message_handler.check_availability
    message_handler.classify_post_booking_message = lambda **_: PostBookingResponse(intent="other", reply_to_user="На какую дату планируете отдых?")
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "Баня свободна.", ["Баня: свободно"])
    try:
        reply = _send(suffix, "я и говорю давай ее же оформлю", now + timedelta(seconds=5))
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            form.get("service_type") == "bathhouse"
            and form.get("date") == "2026-07-01"
            and form.get("time") == "18:00"
            and form.get("duration") == 3
            and "на какую дату" not in lowered
            and state.get("current_step") != "date"
        )
        return Check("resume same expired hold does not ask date", ok, f"{reply} | {state}")
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.check_availability = original_availability


def _test_abort_current_draft_keeps_contact(now: datetime) -> Check:
    suffix = "abort_current_draft"
    _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-06-30",
            time="12:00",
            duration=None,
            guests_count=None,
            event_format=None,
            phone="+79990000021",
        ),
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE conversations c
                SET status = 'waiting_user',
                    current_step = 'duration',
                    next_step = 'duration'
                FROM users u
                WHERE c.user_id = u.id
                  AND u.external_id = %s
                """,
                (TEST_PREFIX + suffix,),
            )
    reply = _send(suffix, "нет не хочу бронировать ее", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    ok = (
        "эту заявку не оформляю" in reply.lower()
        and form.get("phone") == "+79990000021"
        and not form.get("service_type")
        and state.get("current_step") == "service_type"
    )
    return Check("abort current draft keeps contact", ok, f"{reply} | {form}")


def _test_abort_current_draft_from_upsell_refusal(now: datetime) -> Check:
    suffix = "abort_current_draft_upsell_refusal"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="18:00",
            duration=6,
            guests_count=10,
            event_format="корпоратив",
            upsell_items=[],
            phone="+79990000023",
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
    reply = _send(suffix, "давай откажемся от брони", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "заявку не оформляю" in lowered
        and "свободно" not in lowered
        and "доп" not in lowered
        and form.get("phone") == "+79990000023"
        and not form.get("service_type")
        and state.get("current_step") == "service_type"
    )
    return Check("abort current draft from upsell refusal", ok, f"{reply} | {state}")


def _test_info_during_bath_form_keeps_service_context(now: datetime) -> Check:
    suffix = "info_during_bath_form_context"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-06-30",
            time=None,
            duration=3,
            guests_count=None,
            event_format=None,
            phone="+79990000025",
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

    reply = _send(suffix, "а если нас будет 30 человек", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        form.get("service_type") == "bathhouse"
        and not form.get("service_variant")
        and not form.get("guests_count")
        and state.get("next_step") == "time"
        and "бан" in lowered
        and "30" in lowered
        and "для 30 человек" in lowered
        and "продолжим оформление" not in lowered
    )
    return Check("info during bath form keeps service context", ok, f"{reply} | {state}")


def _test_later_pause_during_form_does_not_repeat_question(now: datetime) -> Check:
    suffix = "later_pause_during_form"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-06-30",
            time=None,
            duration=3,
            guests_count=None,
            event_format=None,
            phone="+79990000026",
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

    reply = _send(suffix, "ну хз\nя позже вам напишу", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ack_reply = _send(suffix, "кайф", now + timedelta(seconds=10))
    ack_state = _latest_state(suffix)
    ack_lowered = ack_reply.lower().replace("ё", "е")
    ok = (
        "когда определитесь" in lowered
        and "во сколько" not in lowered
        and "продолжим оформление" not in lowered
        and form.get("service_type") == "bathhouse"
        and state.get("next_step") == "time"
        and "что подготовить" not in ack_lowered
        and "доп" not in ack_lowered
        and ack_state.get("next_step") == "time"
    )
    return Check("later pause during form does not repeat question", ok, f"{reply} | {ack_reply} | {ack_state}")


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


def _test_paid_cancel_typo_dya_confirms(now: datetime) -> Check:
    suffix = "paid_cancel_typo_dya"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=now.date() + timedelta(days=10),
        yclients_service_id="18201061",
        provider_record_id="local_cancel_typo_dya",
        phone="+79990000034",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "удали бронь", now)
        done = _send(suffix, "Дя", now)
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
        ok = "точно" in reply.lower() and "отменила" in done.lower() and booking_status == "cancelled"
        return Check("paid cancel typo dya confirms", ok, f"{reply} | {done} | status={booking_status}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing


def _test_ack_after_cancel_does_not_say_booking_fixed(now: datetime) -> Check:
    suffix = "ack_after_cancel_not_fixed"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=now.date() + timedelta(days=10),
        yclients_service_id="18201061",
        provider_record_id="local_ack_after_cancel",
        phone="+79990000035",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        _send(suffix, "отмени бронь", now)
        done = _send(suffix, "да", now)
        reply = _send(suffix, "Окей", now)
        state = _latest_state(suffix)
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "отменила" in done.lower().replace("ё", "е")
            and "бронь зафиксирована" not in lowered
            and "новая бронь" in lowered
            and state.get("current_step") == "service_type"
        )
        return Check("ack after cancel does not say booking fixed", ok, f"{done} | {reply} | {state}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing


def _test_paid_cancel_refund_window_text(now: datetime) -> Check:
    suffix = "paid_cancel_refund_window"
    _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=now.date() + timedelta(days=12),
        yclients_service_id="18201061",
        provider_record_id="local_cancel_refund_window",
        phone="+79990000023",
    )
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "удали бронь", now)
        done = _send(suffix, "да", now)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM system_logs sl
                    JOIN conversations c ON c.id = sl.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id = %s
                      AND sl.event_type = 'refund_required'
                    ORDER BY sl.id DESC
                    LIMIT 1
                    """,
                    (TEST_PREFIX + suffix,),
                )
                refund_log = cur.fetchone()
        lowered_reply = reply.lower().replace("ё", "е")
        lowered_done = done.lower().replace("ё", "е")
        ok = (
            "аванс можно вернуть" in lowered_reply
            and "точно" in lowered_reply
            and "аванс можно вернуть" in lowered_done
            and "не возвращается" not in lowered_done
            and refund_log is not None
            and (refund_log.get("payload") or {}).get("booking_id")
        )
        return Check("paid cancel refund window text and admin refund log", ok, f"{reply} | {done} | refund_log={dict(refund_log or {})}")
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing


def _test_cancel_refund_boundaries(now: datetime) -> Check:
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    results: dict[int, dict[str, Any]] = {}
    try:
        for days in (6, 7, 8):
            suffix = f"cancel_refund_boundary_{days}"
            _create_paid_booking_for_action(
                suffix,
                now,
                service_type="gazebo",
                booking_date=now.date() + timedelta(days=days),
                yclients_service_id="18201061",
                provider_record_id=f"local_cancel_refund_boundary_{days}",
                phone=f"+799900000{days}",
            )
            _send(suffix, "отмени бронь", now)
            done = _send(suffix, "да", now)
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT count(*) AS count
                        FROM system_logs sl
                        JOIN conversations c ON c.id = sl.conversation_id
                        JOIN users u ON u.id = c.user_id
                        WHERE u.external_id = %s
                          AND sl.event_type = 'refund_required'
                        """,
                        (TEST_PREFIX + suffix,),
                    )
                    log_count = cur.fetchone()["count"]
            results[days] = {"reply": done, "refund_logs": log_count}
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing

    lowered = {days: item["reply"].lower().replace("ё", "е") for days, item in results.items()}
    ok = (
        "не возвращается" in lowered[6]
        and results[6]["refund_logs"] == 0
        and "аванс можно вернуть" in lowered[7]
        and results[7]["refund_logs"] == 1
        and "аванс можно вернуть" in lowered[8]
        and results[8]["refund_logs"] == 1
    )
    return Check("cancel refund boundary 6 7 8 days", ok, str(results))


def _test_refund_required_notifies_admin(now: datetime) -> Check:
    suffix = "refund_required_admin_notify"
    created = _create_reserved_conversation(suffix, now)
    with get_connection() as conn:
        log = system_logs_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            level="warning",
            event_type="refund_required",
            message="paid booking cancelled inside refundable window",
            payload={
                "booking_id": 12345,
                "booking": "Беседка №4: 1 июня, с 18:00 до 00:00 следующего дня (6 часов)",
                "client_name": "Кирилл",
                "phone": "+79990000023",
                "payment_status": "paid",
            },
        )

    class FakeBot:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        async def send_message(self, *, chat_id: str, text: str) -> None:
            self.messages.append((chat_id, text))

    settings = get_settings()
    original_chat_id = settings.admin_telegram_chat_id
    fake_bot = FakeBot()
    try:
        settings.admin_telegram_chat_id = "local_admin_chat"
        asyncio.run(payment_status_runner.notify_admin_about_refund_requests(fake_bot))  # type: ignore[arg-type]
    finally:
        settings.admin_telegram_chat_id = original_chat_id

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT admin_notified_at FROM system_logs WHERE id = %s", (log["id"],))
            notified_at = cur.fetchone()["admin_notified_at"]
    sent_text = next((text for _chat_id, text in fake_bot.messages if "12345" in text), "")
    lowered = sent_text.lower().replace("ё", "е")
    ok = (
        fake_bot.messages
        and any(chat_id == "local_admin_chat" and "12345" in text for chat_id, text in fake_bot.messages)
        and "требуется вернуть предоплату" in lowered
        and "кирилл" in lowered
        and "+79990000023" in sent_text
        and notified_at is not None
    )
    return Check("refund required notifies admin", ok, f"{fake_bot.messages} | notified_at={notified_at}")


def _test_ai_semantic_preflight_for_active_routes(now: datetime) -> Check:
    calls: list[str] = []
    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_delete = message_handler.delete_yclients_record_for_booking
    original_create_missing = message_handler.create_missing_yclients_records

    def fake_call_ai(**kwargs: Any) -> AIResponse:
        calls.append(str(kwargs.get("text") or ""))
        return AIResponse(intent="other", action="ask_next_question")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    message_handler.delete_yclients_record_for_booking = lambda *_args, **_kwargs: True
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        form_suffix = "semantic_preflight_form"
        form_created = _create_reserved_conversation(
            form_suffix,
            now,
            _base_form(client_name=None),
        )
        with get_connection() as conn:
            conversations_repo.update_after_message(
                conn,
                form_created["conversation"]["id"],
                now,
                status="waiting_user",
                current_step="client_name",
                next_step="client_name",
                form_data=form_created["conversation"]["form_data"],
            )
        _send(form_suffix, "Иван", now)

        upsell_suffix = "semantic_preflight_upsell"
        upsell_created = _create_reserved_conversation(
            upsell_suffix,
            now,
            _base_form(client_name=None, phone=None, upsell_items=[]),
        )
        with get_connection() as conn:
            message_handler.messages_repo.create(
                conn,
                conversation_id=upsell_created["conversation"]["id"],
                sender="assistant",
                text="Обычно к беседке берут допы: уголь, розжиг, лед, посуда, кальян. Что подготовить для вас?",
            )
            conversations_repo.update_after_message(
                conn,
                upsell_created["conversation"]["id"],
                now,
                status="waiting_user",
                current_step="upsell_items",
                next_step="upsell_items",
                form_data=upsell_created["conversation"]["form_data"],
            )
        _send(upsell_suffix, "кальянчик", now)

        confirmation_suffix = "semantic_preflight_confirmation"
        confirmation_created = _create_reserved_conversation(confirmation_suffix, now)
        with get_connection() as conn:
            conversations_repo.update_after_message(
                conn,
                confirmation_created["conversation"]["id"],
                now,
                status="awaiting_confirmation",
                current_step="awaiting_confirmation",
                next_step="confirmation",
                form_data=confirmation_created["conversation"]["form_data"],
            )
        _send(confirmation_suffix, "а это хорошая беседка?", now)

        cancel_suffix = "semantic_preflight_cancel"
        _create_paid_booking_for_action(
            cancel_suffix,
            now,
            service_type="gazebo",
            booking_date=now.date() + timedelta(days=10),
            yclients_service_id="18201061",
            provider_record_id="local_semantic_preflight_cancel",
            phone="+79990000041",
        )
        _send(cancel_suffix, "удали бронь", now)

        post_booking_suffix = "semantic_preflight_post_booking"
        _create_paid_booking_for_action(
            post_booking_suffix,
            now,
            service_type="gazebo",
            booking_date=now.date() + timedelta(days=10),
            yclients_service_id="18201061",
            provider_record_id="local_semantic_preflight_post_booking",
            phone="+79990000042",
        )
        _send(post_booking_suffix, "какие у меня брони?", now)
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing

    expected = {
        "Иван",
        "кальянчик",
        "а это хорошая беседка?",
        "удали бронь",
        "какие у меня брони?",
    }
    ok = expected.issubset(set(calls))
    return Check("AI semantic preflight for active routes", ok, f"calls={calls}")


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


def _test_multi_cancel_refund_only_paid_refundable(now: datetime) -> Check:
    suffix = "multi_cancel_refund_only_paid_refundable"
    created = _create_paid_booking_for_action(
        suffix,
        now,
        service_type="gazebo",
        booking_date=now.date() + timedelta(days=6),
        yclients_service_id="18201055",
        provider_record_id="local_multi_cancel_non_refundable_paid",
        phone="+79990000043",
    )
    _add_paid_booking(
        created,
        now,
        service_type="gazebo",
        booking_date=now.date() + timedelta(days=8),
        provider_record_id="local_multi_cancel_refundable_paid",
        yclients_service_id="18201056",
    )
    _add_paid_booking(
        created,
        now,
        service_type="gazebo",
        booking_date=now.date() + timedelta(days=8),
        provider_record_id="local_multi_cancel_refundable_unpaid",
        yclients_service_id="18201057",
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE bookings
                SET payment_status = 'not_paid'
                WHERE id = (
                    SELECT id
                    FROM bookings
                    WHERE conversation_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (created["conversation"]["id"],),
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
                    SELECT sl.payload
                    FROM system_logs sl
                    JOIN conversations c ON c.id = sl.conversation_id
                    JOIN users u ON u.id = c.user_id
                    WHERE u.external_id = %s
                      AND sl.event_type = 'refund_required'
                    ORDER BY sl.id ASC
                    """,
                    (TEST_PREFIX + suffix,),
                )
                payloads = [row["payload"] for row in cur.fetchall()]
    finally:
        message_handler.delete_yclients_record_for_booking = original_delete
        message_handler.create_missing_yclients_records = original_create_missing

    ok = (
        "могу отменить эти брони" in reply.lower().replace("ё", "е")
        and "отменила брони" in done.lower().replace("ё", "е")
        and len(payloads) == 1
        and payloads[0].get("payment_status") == "paid"
    )
    return Check("multi booking cancel refund only paid refundable", ok, f"{reply} | {done} | payloads={payloads}")


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


def _test_price_question_with_budet_not_children_info() -> Check:
    text = "ну вот я хочу на 30 июня, сколько будет стоить?"
    common_info = message_handler._policy_or_common_info_reply(text)
    form = _base_form(service_type="bathhouse", date="2026-06-30", duration=4)
    price_reply = message_handler._price_reply_if_known(text, form)
    lowered = (price_reply or "").lower().replace("ё", "е")
    ok = (
        common_info is None
        and price_reply is not None
        and "стоит" in lowered
        and "с детьми можно" not in lowered
    )
    return Check("price question with budet is not children info", ok, f"common={common_info!r}; price={price_reply!r}")


def _test_ai_semantic_price_question_without_price_keywords(now: datetime) -> Check:
    suffix = "semantic_price_no_keywords"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            date="2026-06-30",
            time="12:00",
            duration=4,
            guests_count=15,
            event_format=None,
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
        return AIResponse(
            intent="price_question",
            action="answer_info",
            current_step="event_format",
            changed_fields=[],
            form_data_patch={},
        )

    message_handler.call_ai = fake_call_ai
    try:
        reply = _send(suffix, "и во что мне это выйдет по итогу?", now)
        state = _latest_state(suffix)
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "8 400 ₽" in reply
            and "с детьми можно" not in lowered
            and state.get("current_step") == "event_format"
            and "какой формат" in lowered
        )
        return Check("AI semantic price question without price keywords", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai


def _test_truncated_people_word_extracts_guests() -> Check:
    patch = message_handler._guests_count_patch("а на когда есть ближайшие беседки нас если что 30 челове", "guests_count")
    ok = patch.get("guests_count") == 30
    return Check("truncated people word extracts guests", ok, str(patch))


def _test_friends_hangout_event_format_not_birthday() -> Check:
    patch = message_handler._event_format_patch("просто посидеть с друзьями")
    ok = patch.get("event_format") == "компания друзей" and patch.get("event_format") != "день рождения"
    return Check("friends hangout event format not birthday", ok, str(patch))


def _test_addon_price_question_does_not_add_item() -> Check:
    form = _base_form(service_type="gazebo", service_variant="Беседка №6")
    patch = message_handler._upsell_items_patch("а скольок стоит решетка?")
    reply = message_handler._price_reply_if_known("а скольок стоит решетка?", form)
    ok = patch == {} and bool(reply and "500 ₽" in reply and "добавим" not in reply.lower())
    return Check("addon price question does not add item", ok, f"{patch} | {reply}")


def _test_generic_upsell_price_question_uses_addon_prices() -> Check:
    form = _base_form(
        service_type="bathhouse",
        service_variant=None,
        event_format="спокойный отдых",
        upsell_items=[],
        upsell_offer_count=0,
    )
    reply = message_handler._price_reply_if_known("а скольок это все стоит?", form)
    ok = bool(
        reply
        and "Кальян" in reply
        and "Мангальный набор" in reply
        and "3 часа" not in reply
        and "Что подготовить" in reply
    )
    return Check("generic upsell price question uses addon prices", ok, str(reply))


def _test_prepayment_price_question_not_addons() -> Check:
    form = _base_form(service_type="gazebo", service_variant="Беседка №6")
    reply = message_handler._price_reply_if_known("а сколько стоит предоплата", form)
    ok = bool(reply and "Предоплата" in reply and "Кальян" not in reply and "Мангальный" not in reply)
    return Check("prepayment price question not addons", ok, str(reply))


def _test_gazebo_weekday_discount_reply() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №1",
        date="2026-06-08",
        time=None,
        duration=None,
        guests_count=20,
        event_format=None,
        upsell_items=[],
    )
    reply = message_handler._deterministic_info_reply("а со скидкой сколько будет?", form)
    ok = bool(reply and "50%" in reply and "10 500" in reply and "5 250" in reply)
    return Check("gazebo weekday discount reply", ok, str(reply))


def _test_best2info_retrieval_for_client_questions() -> Check:
    cases = (
        ("а скидка на беседку есть?", {"service_type": "gazebo"}, ("# rules/discounts.md", "50%")),
        ("сколько предоплата?", {}, ("# rules/payment.md", "Предоплата")),
        ("кальян сколько стоит?", {}, ("# prices/addons.md", "Кальян")),
        ("можно с детьми и где парковка?", {}, ("# rules/kids-pets.md", "# rules/location.md")),
    )
    misses: list[str] = []
    for text, form_data, expected in cases:
        knowledge = knowledge_service.retrieve_client_knowledge(text, form_data)
        knowledge_lowered = knowledge.lower().replace("ё", "е")
        for item in expected:
            expected_item = item.lower().replace("ё", "е")
            if expected_item not in knowledge_lowered:
                misses.append(f"{text}: missing {item}")
    unknown = knowledge_service.retrieve_client_knowledge("можно запускать фейерверки с крыши космолета?", {})
    unknown_lowered = unknown.lower().replace("ё", "е")
    if "# runtime.md" not in unknown or "не выдумывай" not in unknown_lowered:
        misses.append("unknown: runtime honesty rules missing")
    return Check("best2info retrieval for client questions", not misses, "; ".join(misses))


def _test_brooms_are_forbidden() -> Check:
    form = _base_form(service_type="bathhouse")
    patch = message_handler._upsell_items_patch("веники надо")
    reply = message_handler._deterministic_info_reply("веники надо", form)
    ok = patch == {} and bool(reply and "нельзя" in reply.lower() and "штраф" in reply.lower())
    return Check("brooms are forbidden", ok, f"{patch} | {reply}")


def _test_brooms_info_without_form_does_not_ask_booking() -> Check:
    reply = message_handler._deterministic_info_reply("можно ли веники в баню?", {})
    lowered = (reply or "").lower().replace("ё", "е")
    ok = bool(
        reply
        and "нельзя" in lowered
        and "штраф" in lowered
        and "что планируете" not in lowered
        and "на какую дату" not in lowered
    )
    return Check("brooms info without form does not ask booking", ok, str(reply))


def _test_kids_pets_parking_info_without_form_does_not_start_booking(now: datetime) -> Check:
    suffix = "kids_pets_parking_no_form"
    reply = _send(suffix, "а с детьми и собакой можно? парковка есть?", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "с детьми можно" in lowered
        and "по животным точного" in lowered
        and "парковка есть" in lowered
        and not form.get("service_type")
        and state.get("current_step") == "service_type"
        and "что хотите забронировать" not in lowered
        and "на какую дату" not in lowered
    )
    return Check("kids pets parking info without form does not start booking", ok, f"{reply} | {state}")


def _test_children_parking_info_during_form_uses_runtime_knowledge() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №8",
        date="2026-06-02",
        time=None,
        duration=None,
        guests_count=12,
    )
    knowledge = knowledge_service.retrieve_client_knowledge(
        "а детям можно? и парковка далеко?",
        form,
    ).lower().replace("ё", "е")
    reply = message_handler._deterministic_info_reply("а детям можно? и парковка далеко?", form)
    lowered = (reply or "").lower().replace("ё", "е")
    ok = (
        "с детьми можно" in lowered
        and "парковка есть" in lowered
        and "во сколько" in lowered
        and "с детьми можно" in knowledge
        and "живот" in knowledge
        and "впритык" in knowledge
    )
    return Check("children and parking info uses runtime knowledge", ok, str(reply))


def _test_gazebo_until_morning_info_keeps_time_step(now: datetime) -> Check:
    suffix = "gazebo_until_morning_info"
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №4",
        date="2026-06-30",
        time=None,
        duration=None,
        guests_count=10,
        event_format=None,
        phone="+79990000026",
    )
    created = _create_reserved_conversation(suffix, now, form)
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="time",
            next_step="time",
            form_data=form,
        )
    reply = _send(suffix, "а до утра можно отдыхать?", now)
    state = _latest_state(suffix)
    updated_form = state.get("form_data") or {}
    lowered = reply.lower().replace("ё", "е")
    ok = (
        "до 08:00" in lowered
        and "каждый час" in lowered
        and updated_form.get("service_type") == "gazebo"
        and updated_form.get("service_variant") == "Беседка №4"
        and not updated_form.get("time")
        and not updated_form.get("duration")
        and state.get("current_step") == "time"
    )
    return Check("gazebo until morning info keeps time step", ok, f"{reply} | {state}")


def _test_mosquito_question_during_confirmation() -> Check:
    form = _base_form(service_type="gazebo", service_variant="Крытая беседка")
    reply = message_handler._awaiting_confirmation_side_reply(
        text="а каморов там много",
        form_data=form,
        history=[],
    )
    ok = "раз в неделю" in reply.lower() and "репеллент" in reply.lower()
    return Check("mosquito question during confirmation", ok, reply)


def _test_mosquito_question_after_booking_bypasses_ai(now: datetime) -> Check:
    suffix = "mosquito_post_booking"
    _create_reserved_conversation(suffix, now)
    original_classifier = message_handler.classify_post_booking_message
    original_create_missing = message_handler.create_missing_yclients_records
    called = {"classifier": False}

    def bad_classifier(**_: Any) -> PostBookingResponse:
        called["classifier"] = True
        return PostBookingResponse(intent="other", reply_to_user="Комаров нет вообще.")

    message_handler.classify_post_booking_message = bad_classifier
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    try:
        reply = _send(suffix, "а комаров много?", now + timedelta(seconds=5))
        lowered = reply.lower().replace("ё", "е")
        ok = (
            not called["classifier"]
            and "раз в неделю" in lowered
            and "репеллент" in lowered
            and "нет вообще" not in lowered
        )
        return Check("mosquito question after booking bypasses AI", ok, f"{reply} | called={called}")
    finally:
        message_handler.classify_post_booking_message = original_classifier
        message_handler.create_missing_yclients_records = original_create_missing


def _test_bare_duration_answer() -> Check:
    patch = message_handler._current_step_patch("на 5", "duration", None)
    ok = patch.get("duration") == 5
    return Check("bare duration answer", ok, str(patch))


def _test_evening_time_choice_uses_early_option() -> Check:
    patch = message_handler._time_period_patch("к 4 или 5 вечера")
    ok = patch.get("time") == "16:00" and "duration" not in patch
    return Check("evening time choice uses early option", ok, str(patch))


def _test_until_midnight_uses_existing_start() -> Check:
    patch = message_handler._form_detail_correction_patch(
        "а мы не на 4 часа, можем до 12 ночи?",
        _base_form(service_type="gazebo", time="16:00", duration=4),
    )
    ok = patch.get("duration") == 8 and "time" not in patch
    return Check("until midnight uses existing start", ok, str(patch))


def _test_bathhouse_ten_hour_price_formula() -> Check:
    reply = message_handler._price_reply_if_known(
        "баня на 10 часов сколько стоит",
        _base_form(service_type="bathhouse", date="2026-06-16", duration=10),
    ) or ""
    ok = "19 200" in reply and "1 500" in reply
    return Check("bathhouse ten hour price formula", ok, reply)


def _test_coal_price_is_known() -> Check:
    reply = message_handler._price_reply_if_known(
        "уголь сколько стоит",
        _base_form(service_type="gazebo", service_variant="Беседка №2"),
    ) or ""
    ok = "270" in reply and "уголь" in reply.lower()
    return Check("coal price is known", ok, reply)


def _test_payment_reply_uses_30_minute_ttl_and_refund_note() -> Check:
    reply = message_handler._payment_reply_text({"payment_url": "https://example.test/pay", "amount": "1.00"})
    lowered = reply.lower()
    ok = "30 минут" in lowered and "7 дней" in lowered
    return Check("payment reply uses 30 minute ttl and refund note", ok, reply)


def _test_unpaid_reserved_date_correction_recreates_hold_and_link(now: datetime) -> Check:
    suffix = "unpaid_reserved_date_correction"
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №2",
        date="2026-06-12",
        time="16:00",
        duration=6,
    )
    created = _create_reserved_conversation(suffix, now, form)
    with get_connection() as conn:
        old_hold = slot_holds_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            service_type="gazebo",
            yclients_service_id="18201002",
            yclients_staff_id="3665292",
            slot_date=date(2026, 6, 12),
            slot_time=time(16, 0),
            duration_minutes=360,
            expires_at=now + timedelta(minutes=30),
        )
        payment = payments_repo.create_pending(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            booking_ids=[],
            provider="yookassa",
            amount=Decimal("1.00"),
            currency="RUB",
            description="test",
            raw_payload={"hold_ids": [int(old_hold["id"])]},
        )
        payments_repo.attach_provider_response(
            conn,
            payment_id=int(payment["id"]),
            provider_payment_id="old-unpaid-correction",
            payment_url="https://example.test/old",
            status="pending",
            raw_payload={"hold_ids": [int(old_hold["id"])]},
        )

    original_payment = message_handler.create_payment_link_for_holds
    original_availability = message_handler.check_availability

    def fake_payment(conn, *, conversation_id, user_id, hold_ids, **_kwargs):
        return {
            "id": 999999,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "payment_url": "https://example.test/new",
            "amount": "1.00",
            "raw_payload": {"hold_ids": hold_ids},
            "status": "pending",
        }

    message_handler.create_payment_link_for_holds = fake_payment
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "ok", ["free"])
    try:
        reply = _send(suffix, "хочу на 16 число, потом оплачу", now)
        state = _latest_state(suffix)
        form_after = state.get("form_data") or {}
        with get_connection() as conn:
            old_after = slot_holds_repo.get_by_id(conn, int(old_hold["id"]))
            active = slot_holds_repo.list_active_for_conversation(
                conn,
                conversation_id=created["conversation"]["id"],
                now=now,
            )
            payments = payments_repo.list_for_conversation(conn, conversation_id=created["conversation"]["id"])
        old_payment_after = next(item for item in payments if int(item["id"]) == int(payment["id"]))
        ok = (
            old_after
            and old_after.get("status") == "cancelled"
            and old_payment_after.get("status") == "superseded"
            and len(active) == 1
            and int(active[0]["id"]) != int(old_hold["id"])
            and form_after.get("date") == "2026-06-16"
            and "https://example.test/new" in reply
        )
        return Check("unpaid reserved date correction recreates hold and link", bool(ok), f"{reply} | {form_after} | {old_payment_after}")
    finally:
        message_handler.create_payment_link_for_holds = original_payment
        message_handler.check_availability = original_availability


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


def _test_stale_explicit_new_bath_request_skips_choice(now: datetime) -> Check:
    suffix = "stale_explicit_new_bath"
    old_time = now - timedelta(hours=3)
    created = _create_reserved_conversation(
        suffix,
        old_time,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-05-29",
            time="14:00",
            duration=9,
            guests_count=10,
            event_format="день рождения ребенка",
            client_name="Ирина",
            phone="+79099667655",
            upsell_items=["базовый мангальный набор"],
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            old_time,
            status="waiting_user",
            current_step="upsell_items",
            next_step="upsell_items",
            form_data=created["conversation"]["form_data"],
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(intent="booking_request", action="ask_next_question", current_step="duration")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    try:
        reply = _send(
            suffix,
            "я бы хотел баню на 30 июня\nс 9 утра до 21 ночи, если что можно на дольше остаться?",
            now,
        )
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "продолжаем эту заявку" not in lowered
            and "начнем новую анкету" not in lowered
            and form.get("service_type") == "bathhouse"
            and form.get("date") == "2026-06-30"
            and form.get("time") == "09:00"
            and form.get("guests_count") is None
            and form.get("event_format") is None
            and form.get("upsell_items") in (None, [])
            and state.get("current_step") == "duration"
            and "фиксирован" in lowered
        )
        return Check("stale explicit new bath request skips choice", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_stale_davaite_continues(now: datetime) -> Check:
    suffix = "stale_davaite_continue"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №5",
            date="2026-06-30",
            time=None,
            duration=None,
            guests_count=5,
            event_format=None,
            client_name="Кирилл",
            phone="+79990000032",
            upsell_items=[],
            stale_form_flow={"started_at": now.isoformat(), "previous_step": "time"},
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="stale_form_choice",
            next_step="stale_form_choice",
            form_data=created["conversation"]["form_data"],
        )
    reply = _send(suffix, "давайте", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    ok = (
        "уточните" not in reply.lower()
        and "продолжаем" in reply.lower()
        and not form.get("stale_form_flow")
        and state.get("current_step") == "time"
    )
    return Check("stale davaite continues", ok, f"{reply} | {state}")


def _test_stale_no_with_new_bath_request_processes_same_message(now: datetime) -> Check:
    suffix = "stale_no_new_bath_same_message"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="bathhouse",
            service_variant=None,
            date="2026-05-29",
            time="14:00",
            duration=9,
            guests_count=10,
            event_format="день рождения ребенка",
            client_name="Ирина",
            phone="+79099667655",
            upsell_items=["базовый мангальный набор"],
            stale_form_flow={"started_at": now.isoformat(), "previous_step": "time"},
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="stale_form_choice",
            next_step="stale_form_choice",
            form_data=created["conversation"]["form_data"],
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(intent="booking_request", action="ask_next_question", current_step="duration")

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = lambda **kwargs: str(kwargs.get("required_meaning") or "")
    try:
        reply = _send(
            suffix,
            "нет\nя бы хотел баню на 30 июня\nс 9 утра до 21 ночи, если что можно на дольше остаться?",
            now,
        )
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "уточните" not in lowered
            and not form.get("stale_form_flow")
            and form.get("service_type") == "bathhouse"
            and form.get("date") == "2026-06-30"
            and form.get("time") == "09:00"
            and form.get("guests_count") is None
            and form.get("event_format") is None
            and form.get("upsell_items") in (None, [])
            and state.get("current_step") == "duration"
            and "фиксирован" in lowered
        )
        return Check("stale no plus new bath request processes same message", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate


def _test_stale_free_dates_request_starts_fresh_lookup(now: datetime) -> Check:
    suffix = "stale_free_dates_fresh"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №5",
            date="2026-06-30",
            time="18:00",
            duration=6,
            guests_count=5,
            event_format="день рождения",
            client_name="Кирилл",
            phone="+79990000033",
            upsell_items=[],
            stale_form_flow={"started_at": now.isoformat(), "previous_step": "time"},
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="stale_form_choice",
            next_step="stale_form_choice",
            form_data=created["conversation"]["form_data"],
        )
    original_availability = message_handler.check_availability
    message_handler.check_availability = lambda *_args, **_kwargs: AvailabilityResult(True, "ok", ["Баня: свободно"])
    try:
        reply = _send(suffix, "а какие ближайшие свободные даты есть для бани", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            "ближайшие свободные даты" in reply.lower()
            and "на какую дату планируете" not in reply.lower()
            and form.get("service_type") == "bathhouse"
            and not form.get("date")
            and not form.get("guests_count")
            and not form.get("event_format")
            and state.get("current_step") == "awaiting_new_date"
        )
        return Check("stale free dates request starts fresh lookup", ok, f"{reply} | {form}")
    finally:
        message_handler.check_availability = original_availability


def _test_old_form_new_free_dates_skips_stale_choice(now: datetime) -> Check:
    suffix = "old_form_new_free_dates"
    old_time = now - timedelta(hours=3)
    created = _create_reserved_conversation(
        suffix,
        old_time,
        _base_form(
            service_type="house",
            service_variant=None,
            date="2026-08-06",
            time=None,
            duration=None,
            guests_count=None,
            event_format=None,
            client_name="Кирилл",
            phone="+79990000034",
            upsell_items=[],
            last_unavailable={"service_type": "house", "date": "2026-08-05"},
            last_suggested_free_dates=["2026-08-06", "2026-08-07"],
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            old_time,
            status="waiting_user",
            current_step="awaiting_new_date",
            next_step="date",
            form_data=created["conversation"]["form_data"],
        )
    original_availability = message_handler.check_availability
    seen: list[dict[str, Any]] = []

    def fake_availability(*_args: Any, **kwargs: Any) -> AvailabilityResult:
        form = kwargs.get("form_data") or {}
        seen.append(dict(form))
        return AvailabilityResult(True, "ok", ["Баня: свободно"])

    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "начнем новую\nкакие ближайшие свободные даты для бани?", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        lowered = reply.lower().replace("ё", "е")
        ok = (
            "продолжаем эту заявку" not in lowered
            and "ближайшие свободные даты" in lowered
            and form.get("service_type") == "bathhouse"
            and form.get("phone") == "+79990000034"
            and not form.get("date")
            and not form.get("last_unavailable")
            and state.get("current_step") == "awaiting_new_date"
            and seen
            and seen[0].get("service_type") == "bathhouse"
        )
        return Check("old form new free dates skips stale choice", ok, f"{reply} | seen={seen[:1]} | {form}")
    finally:
        message_handler.check_availability = original_availability


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


def _test_gazebo_quality_question_during_confirmation(now: datetime) -> Check:
    suffix = "gazebo_quality_confirmation"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="11:00",
            duration=13,
            guests_count=15,
            event_format="не указано",
            upsell_items=["базовый мангальный набор"],
            client_name="Кирилл",
            phone="+79990000001",
        ),
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
    reply = _send(suffix, "а это хорошая беседка?", now)
    state = _latest_state(suffix)
    ok = (
        "Беседка №4" in reply
        and "вторую бронь" not in reply.lower()
        and state.get("current_step") == "awaiting_confirmation"
        and state.get("next_step") == "confirmation"
    )
    return Check("gazebo quality question during confirmation stays in confirmation", ok, f"{reply} | {state}")


def _test_paid_finalize_busy_interval_uses_hold_variant(now: datetime) -> Check:
    suffix = "paid_finalize_hold_variant"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="gazebo",
            service_variant="Беседка №4",
            date="2026-06-30",
            time="11:00",
            duration=13,
            guests_count=15,
            event_format="не указано",
            upsell_items=["базовый мангальный набор"],
            client_name="Кирилл",
            phone="+79990000001",
        ),
    )
    actual_now = datetime.now(ZoneInfo(get_settings().app_timezone))
    with get_connection() as conn:
        hold = slot_holds_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            service_type="gazebo",
            yclients_service_id="18201061",
            yclients_staff_id="3828151",
            slot_date=date(2026, 6, 30),
            slot_time=time(11, 0),
            duration_minutes=780,
            expires_at=actual_now + timedelta(minutes=10),
        )
        payment = payments_repo.create_pending(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            booking_ids=[],
            provider="yookassa",
            amount=Decimal("1.00"),
            currency="RUB",
            description="test",
            raw_payload={"hold_ids": [hold["id"]]},
        )
        booking_ids = payment_service.finalize_bookings_for_paid_payment(conn, payment, now=actual_now)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT yclients_service_id, yclients_staff_id
                FROM resource_busy_intervals
                WHERE source = 'bot_booking'
                  AND source_record_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (str(booking_ids[0]) if booking_ids else "",),
            )
            interval = dict(cur.fetchone() or {})
    ok = (
        bool(booking_ids)
        and interval.get("yclients_service_id") == "18201061"
        and interval.get("yclients_staff_id") == "3828151"
    )
    return Check("paid finalize busy interval uses hold variant", ok, f"{booking_ids} | {interval}")


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


def _test_people_range_is_not_time() -> Check:
    period = message_handler._time_period_patch("на 15-17 человек")
    single = message_handler._single_time_patch("15 взрослых и дети", "time")
    guests_range = message_handler._guests_count_patch("на 15-17 человек", "guests_count")
    guests_adults = message_handler._guests_count_patch("15 взрослых и дети", "guests_count")
    guests_future = message_handler._guests_count_patch("на 30 июня нас будет 20", "guests_count")
    ok = (
        period == {}
        and single == {}
        and guests_range.get("guests_count") == 17
        and guests_adults.get("guests_count") == 15
        and guests_future.get("guests_count") == 20
    )
    return Check(
        "people range is not parsed as time",
        ok,
        f"period={period} single={single} guests={guests_range}/{guests_adults}/{guests_future}",
    )


def _test_afternoon_time_words_parse_pm() -> Check:
    three_pm = message_handler._single_time_patch("в 3 часа дня", "time")
    typo_pm = message_handler._single_time_patch("к 3 чиса дня", "time")
    period = message_handler._time_period_patch("с 3 часа дня до 11 ночи")
    ok = (
        three_pm.get("time") == "15:00"
        and typo_pm.get("time") == "15:00"
        and period.get("time") == "15:00"
        and period.get("duration") == 8
    )
    return Check("afternoon time words parse as PM", ok, f"{three_pm} | {typo_pm} | {period}")


def _test_duration_string_normalization_and_loose_period() -> Check:
    normalized = message_handler.merge_form_data(_base_form(duration="8 часов"), {})
    decimal = message_handler.merge_form_data(_base_form(duration=None), {"duration": "8.5 часа"})
    invalid = message_handler.merge_form_data(_base_form(duration="восемь часов"), {})
    period = message_handler._time_period_patch("после обеда, наверное к 3 дня и до 11 ночи")
    ok = (
        normalized.get("duration") == 8
        and decimal.get("duration") == 8.5
        and invalid.get("duration") is None
        and period.get("time") == "15:00"
        and period.get("duration") == 8
        and message_handler._duration_minutes_value("8 ч") == 480
    )
    return Check("duration strings normalize and loose period parses", ok, f"{normalized} | {decimal} | {invalid} | {period}")


def _test_large_gazebo_group_prioritizes_no1() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant=None,
        date="2026-06-02",
        time=None,
        duration=None,
        guests_count=20,
        last_available_gazebo_variants=[
            "Беседка №8",
            "Беседка №3",
            "Крытая беседка",
            "Беседка №1",
        ],
    )
    reply = message_handler._gazebo_selection_text(form)
    first_bullet = next((line for line in reply.splitlines() if line.startswith("- ")), "")
    ok = "Беседка №1" in first_bullet and "комфортнее" in reply.lower().replace("ё", "е")
    return Check("large gazebo group prioritizes gazebo 1", ok, reply)


def _test_switch_back_to_gazebo_preserves_context(now: datetime) -> Check:
    suffix = "switch_back_gazebo_context"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="house",
            service_variant=None,
            date=None,
            time=None,
            duration=None,
            guests_count=20,
            event_format=None,
            upsell_items=[],
            client_name="Кирилл",
            phone="+79990000001",
            last_unavailable={
                "service_type": "house",
                "date": "2026-06-02",
                "time": None,
                "duration": None,
                "guests_count": 20,
            },
        ),
    )
    with get_connection() as conn:
        conversations_repo.update_after_message(
            conn,
            created["conversation"]["id"],
            now,
            status="waiting_user",
            current_step="service_type",
            next_step="service_type",
        )

    original_call_ai = message_handler.call_ai
    original_generate = message_handler.generate_process_reply
    original_availability = message_handler.check_availability

    def fake_call_ai(**_: Any) -> AIResponse:
        return AIResponse(
            intent="booking_request",
            action="check_availability",
            current_step="service_variant",
            changed_fields=["service_type", "service_variant"],
            form_data_patch={"service_type": "gazebo", "service_variant": "Беседка №1"},
        )

    def fake_generate_process_reply(**kwargs: Any) -> str:
        return str(kwargs.get("required_meaning") or "")

    def fake_availability(_conn: Any, *, form_data: dict[str, Any], now: datetime) -> AvailabilityResult:
        if form_data.get("service_type") == "gazebo" and form_data.get("service_variant") == "Беседка №1":
            return AvailabilityResult(True, "ok", ["Беседка №1: дата свободна"])
        return AvailabilityResult(True, "busy", [])

    message_handler.call_ai = fake_call_ai
    message_handler.generate_process_reply = fake_generate_process_reply
    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "лан давайте беседку же выбираю перую беседку", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            form.get("service_type") == "gazebo"
            and form.get("service_variant") == "Беседка №1"
            and form.get("date") == "2026-06-02"
            and form.get("guests_count") == 20
            and state.get("current_step") == "time"
            and "во сколько" in reply.lower()
        )
        return Check("switch back to gazebo preserves date guests variant", ok, f"{reply} | {state}")
    finally:
        message_handler.call_ai = original_call_ai
        message_handler.generate_process_reply = original_generate
        message_handler.check_availability = original_availability


def _test_house_unavailable_offers_same_date_alternatives(now: datetime) -> Check:
    suffix = "house_unavailable_alternatives"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(
            service_type="house",
            service_variant=None,
            date=None,
            time=None,
            duration=None,
            guests_count=20,
            event_format=None,
            upsell_items=[],
            client_name="Кирилл",
            phone="+79990000001",
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

    original_availability = message_handler.check_availability

    def fake_availability(_conn: Any, *, form_data: dict[str, Any], now: datetime) -> AvailabilityResult:
        if form_data.get("service_type") == "house":
            return AvailabilityResult(True, "busy", [])
        if form_data.get("service_type") == "gazebo":
            return AvailabilityResult(True, "ok", ["Беседка №1: дата свободна", "Беседка №8: дата свободна"])
        return AvailabilityResult(True, "busy", [])

    message_handler.check_availability = fake_availability
    try:
        reply = _send(suffix, "а что есть на 2 июня?", now)
        state = _latest_state(suffix)
        form = state.get("form_data") or {}
        ok = (
            "гостевой дом" in reply.lower()
            and "другие варианты" in reply.lower()
            and "Беседка №1" in reply
            and "уведом" not in reply.lower()
            and (form.get("last_unavailable") or {}).get("date") == "2026-06-02"
        )
        return Check("house unavailable offers same-date alternatives", ok, f"{reply} | {state}")
    finally:
        message_handler.check_availability = original_availability


def _test_gazebo_duration_price_rule() -> Check:
    form = _base_form(
        service_type="gazebo",
        service_variant="Беседка №8",
        date="2026-06-02",
        time="12:00",
        duration=20,
        guests_count=20,
    )
    reply = message_handler._deterministic_info_reply("а че больше часов стоят больше денег?", form)
    lowered = (reply or "").lower().replace("ё", "е")
    ok = bool(reply) and "не считается как доплата за каждый час" in lowered and "бесед" in lowered
    return Check("gazebo duration price rule is not house price", ok, reply or "")


def _test_expired_hold_notifies_and_resets(now: datetime) -> Check:
    suffix = "expired_hold_notifies"
    created = _create_reserved_conversation(
        suffix,
        now,
        _base_form(service_type="gazebo", service_variant="Беседка №1", date="2026-06-08", time="15:00", duration=8),
    )
    with get_connection() as conn:
        slot_holds_repo.create(
            conn,
            conversation_id=created["conversation"]["id"],
            user_id=created["user"]["id"],
            service_type="gazebo",
            yclients_service_id="18201055",
            slot_date=date(2026, 6, 8),
            slot_time=time(15, 0),
            duration_minutes=480,
            expires_at=now - timedelta(minutes=1),
        )
    reply = _send(suffix, "что там с оплатой", now)
    state = _latest_state(suffix)
    form = state.get("form_data") or {}
    ok = (
        "резерв истек" in reply.lower().replace("ё", "е")
        and state.get("status") == "waiting_user"
        and state.get("next_step") == "service_type"
        and not form.get("date")
        and form.get("client_name") == "Кирилл"
    )
    return Check("expired hold notifies and resets draft", ok, f"{reply} | {state}")


def _test_reserved_yes_reuses_existing_payment_link(now: datetime) -> Check:
    suffix = "reserved_reuse_payment"
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
            description="existing hold payment",
        )
        payments_repo.attach_provider_response(
            conn,
            payment_id=payment["id"],
            provider_payment_id="local_existing_payment",
            payment_url="https://example.test/pay-existing",
            status="pending",
            raw_payload={"hold_ids": [hold["id"]]},
        )
    original_payment = message_handler.create_payment_link_for_holds

    def fail_payment(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("must reuse existing payment link")

    message_handler.create_payment_link_for_holds = fail_payment
    try:
        reply = _send(suffix, "да", now)
        ok = "https://example.test/pay-existing" in reply and "уже создана" in reply.lower().replace("ё", "е")
        return Check("reserved yes reuses existing payment link", ok, reply)
    finally:
        message_handler.create_payment_link_for_holds = original_payment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic local booking-bot regressions.")
    parser.add_argument(
        "--group",
        action="append",
        choices=TEST_GROUPS,
        help="Run only one regression group. Can be passed more than once.",
    )
    args = parser.parse_args()
    install_regression_suite_lock("local_regression_suite")
    selected_groups = set(args.group or [])
    if selected_groups:
        print(f"Running regression groups: {', '.join(sorted(selected_groups))}", flush=True)
    else:
        print("Running all regression groups", flush=True)

    settings = get_settings()
    now = datetime(2026, 5, 20, 12, 0, tzinfo=ZoneInfo(settings.app_timezone))
    original_create_missing = message_handler.create_missing_yclients_records
    original_call_ai_for_suite = message_handler.call_ai
    message_handler.create_missing_yclients_records = lambda *_args, **_kwargs: {"checked": 0, "created": 0, "failed": 0}
    if not os.environ.get("BEST2_REGRESSION_REAL_AI"):
        message_handler.call_ai = lambda **_kwargs: AIResponse(intent="other", action="ask_next_question")
    _cleanup()

    checks: list[Check] = []

    def run(group: str, factory: Callable[[], Check]) -> None:
        if selected_groups and group not in selected_groups:
            return
        started_at = perf_counter()
        check = factory()
        elapsed = perf_counter() - started_at
        checks.append(check)
        marker = "OK" if check.ok else "FAIL"
        print(f"{marker} [{elapsed:.1f}s]: {check.name}: {check.details}", flush=True)

    try:
        run("fresh", lambda: _test_second_booking_does_not_inherit_old_slot(now))
        run("fresh", lambda: _test_new_service_from_waiting_date_resets_old_slot(now))
        run("fresh", lambda: _test_plain_new_service_request_resets_old_form(now))
        run("fresh", lambda: _test_service_correction_with_zhe_resets_old_form(now))
        run("fresh", lambda: _test_next_application_while_hold_starts_blank_not_ice(now))
        run("payments", lambda: _test_reserved_yes_retries_payment_link(now))
        run("payments", lambda: _test_paid_status_refreshes_on_any_message(now))
        run("payments", lambda: _test_expired_hold_notifies_and_resets(now))
        run("payments", lambda: _test_reserved_yes_reuses_existing_payment_link(now))
        run("payments", lambda: _test_paid_booking_payment_question_is_deterministic(now))
        run("payments", _test_paid_notification_includes_booking_summary)
        run("payments", lambda: _test_payment_delay_does_not_start_reschedule(now))
        run("payments", lambda: _test_fake_payment_request_does_not_mark_paid(now))
        run("payments", lambda: _test_resume_same_expired_hold_does_not_ask_date(now))
        run("payments", lambda: _test_concurrent_active_hold_conflict(now))
        run("payments", lambda: _test_payment_intent_retry_no_duplicate_link(now))
        run("payments", _test_payment_reply_uses_30_minute_ttl_and_refund_note)
        run("payments", lambda: _test_unpaid_reserved_date_correction_recreates_hold_and_link(now))
        run("post_booking", lambda: _test_confirmation_info_answer_without_extra_ai(now))
        run("post_booking", _test_message_retention_48h_summarizes_and_deletes)
        run("post_booking", lambda: _test_post_booking_info_fallback_when_ai_unavailable(now))
        run("post_booking", lambda: _test_booking_summary_uses_draft_when_no_active_booking(now))
        run("services", lambda: _test_unconfigured_service_does_not_claim_free(now))
        run("services", lambda: _test_summer_gazebo_alias_uses_gazebo(now))
        run("services", lambda: _test_gazebo_bathhouse_alias_starts_with_gazebo(now))
        run("services", lambda: _test_bathhouse_gazebo_order_starts_with_bathhouse(now))
        run("services", lambda: _test_bathhouse_blocks_large_group(now))
        run("services", lambda: _test_start_available_services_lists_all_primary_options(now))
        run("dates", lambda: _test_deterministic_date_beats_stale_ai(now))
        run("dates", lambda: _test_contextual_day_number_keeps_discussed_month(now))
        run("gazebo", _test_gazebo_recommendations_use_only_available)
        run("gazebo", _test_gazebo_budget_preference_filters_cheapest)
        run("gazebo", lambda: _test_gazebo_budget_preference_during_choice(now))
        run("gazebo", lambda: _test_gazebo_budget_without_date_asks_one_question(now))
        run("gazebo", lambda: _test_mixed_gazebo_selection_info_saves_variant(now))
        run("gazebo", _test_gazebo_capacity_filter_rejects_tight_options)
        run("gazebo", _test_gazebo_date_reply_asks_guests_before_choice)
        run("gazebo", lambda: _test_forced_gazebo_variant_asks_guests_before_time(now))
        run("gazebo", lambda: _test_gazebo_capacity_question_sets_guests_and_skips_repeat(now))
        run("gazebo", _test_hypothetical_guest_count_updates_capacity_question)
        run("gazebo", lambda: _test_live_gazebo_twenty_guests_keeps_capacity_context(now))
        run("gazebo", lambda: _test_gazebo_date_and_guests_first_message_checks_availability(now))
        run("gazebo", lambda: _test_gazebo_no_capacity_on_date_offers_nearest_before_requested(now))
        run("gazebo", lambda: _test_gazebo_small_slots_on_date_offers_nearest_suitable(now))
        run("gazebo", lambda: _test_gazebo_variant_change_not_parsed_as_time(now))
        run("time", lambda: _test_guest_count_reference_not_parsed_as_time(now))
        run("gazebo", lambda: _test_next_free_dates_filter_gazebos_by_guests(now))
        run("dates", lambda: _test_new_free_dates_request_resets_old_unavailable(now))
        run("dates", lambda: _test_gazebo_free_dates_request_switches_service(now))
        run("gazebo", _test_large_gazebo_group_prioritizes_no1)
        run("gazebo", lambda: _test_switch_back_to_gazebo_preserves_context(now))
        run("services", lambda: _test_house_unavailable_offers_same_date_alternatives(now))
        run("time", lambda: _test_gazebo_start_time_defaults_until_morning(now))
        run("time", lambda: _test_gazebo_explicit_period_with_longer_question_keeps_end_time(now))
        run("time", _test_people_range_is_not_time)
        run("time", _test_afternoon_time_words_parse_pm)
        run("time", _test_duration_string_normalization_and_loose_period)
        run("time", _test_gazebo_open_ended_duration_overrides_ai_guess)
        run("time", _test_bathhouse_open_ended_duration_until_morning)
        run("time", lambda: _test_bathhouse_rejects_non_fixed_duration(now))
        run("services", lambda: _test_fixed_service_rejects_missing_yclients_book_time(now))
        run("services", lambda: _test_fixed_service_yclients_unavailable_does_not_claim_free(now))
        run("media", _test_media_waits_for_date_and_guests)
        run("media", _test_explicit_photo_request_ignores_availability_text)
        run("media", lambda: _test_explicit_photo_request_bypasses_ai(now))
        run("media", lambda: _test_explicit_service_photo_request_ignores_old_gazebo_state(now))
        run("media", lambda: _test_general_gazebo_photo_request_after_booking(now))
        run("prices", lambda: _test_price_question_during_form_not_booking_summary(now))
        run("gazebo", _test_single_available_gazebo_is_auto_selected)
        run("gazebo", _test_gazebo_variant_is_not_guessed)
        run("post_booking", lambda: _test_booking_summary_counts_all_bookings(now))
        run("post_booking", lambda: _test_new_conversation_sees_old_user_booking(now))
        run("post_booking", lambda: _test_new_conversation_sees_old_summary(now))
        run("post_booking", lambda: _test_customer_templates_do_not_mention_admin(now))
        run("post_booking", lambda: _test_admin_notification_includes_booking_object(now))
        run("post_booking", _test_short_yes_confirms)
        run("post_booking", lambda: _test_soft_yes_confirms_from_confirmation(now))
        run("post_booking", lambda: _test_confirmation_no_is_not_upsell_correction(now))
        run("post_booking", _test_name_correction_replaces_value_after_na)
        run("post_booking", _test_name_correction_paraphrases_keep_clean_value)
        run("fresh", lambda: _test_invalid_phone_reply_is_client_safe(now))
        run("dates", lambda: _test_bare_weekday_requires_confirmation(now))
        run("dates", lambda: _test_weekday_confirmation_yes_uses_saved_candidate(now))
        run("upsell", _test_first_upsell_no_gets_soft_push)
        run("upsell", lambda: _test_first_upsell_flow_before_phone(now))
        run("upsell", lambda: _test_soft_upsell_accept_after_push(now))
        run("upsell", lambda: _test_first_mangal_set_selection_from_price_list(now))
        run("upsell", lambda: _test_informal_upsell_no_two_touch(now))
        run("upsell", lambda: _test_nu_net_upsell_no_two_touch(now))
        run("upsell", lambda: _test_bare_ne_first_upsell_gets_soft_push(now))
        run("upsell", lambda: _test_on_site_upsell_refusal_keeps_no_extras(now))
        run("upsell", _test_on_site_upsell_refusal_paraphrases)
        run("payments", lambda: _test_phone_completion_yes_creates_hold_not_second_confirmation(now))
        run("upsell", lambda: _test_event_format_typo_moves_to_upsell(now))
        run("upsell", lambda: _test_addon_price_during_upsell_does_not_repeat_event_format(now))
        run("upsell", lambda: _test_state_keeps_time_duration_event_after_upsell(now))
        run("upsell", lambda: _test_kalik_addon_survives_to_confirmation(now))
        run("upsell", _test_live_hookah_upsell_phrases)
        run("upsell", lambda: _test_state_text_guard_rebuilds_ai_added_without_state(now))
        run("upsell", lambda: _test_addon_prices_plural_question_replies_immediately(now))
        run("upsell", lambda: _test_prefilled_first_upsell_no_still_gets_soft_push(now))
        run("time", _test_duration_24_formats_as_hours)
        run("upsell", lambda: _test_positive_upsell_asks_for_more_then_continues(now))
        run("upsell", lambda: _test_mixed_addon_price_and_selection_saves_items(now))
        run("upsell", lambda: _test_late_kalik_price_adds_addon_to_confirmation(now))
        run("upsell", lambda: _test_generic_ok_after_upsell_info_does_not_accept_items(now))
        run("upsell", lambda: _test_upsell_parking_info_returns_to_empty_addons(now))
        run("upsell", lambda: _test_upsell_parking_info_keeps_selected_addon(now))
        run("gazebo", lambda: _test_gazebo_quality_question_during_confirmation(now))
        run("payments", lambda: _test_paid_finalize_busy_interval_uses_hold_variant(now))
        run("waitlist", lambda: _test_free_dates_lookup_after_no_availability(now))
        run("waitlist", lambda: _test_waitlist_decline_does_not_handoff(now))
        run("waitlist", lambda: _test_waitlist_notifies_only_relevant_requests(now))
        run("handoff", _test_location_question_does_not_handoff)
        run("handoff", lambda: _test_emotional_event_format_does_not_handoff(now))
        run("media", _test_gazebo_media_selection)
        run("post_booking", lambda: _test_post_booking_summary_always_uses_db(now))
        run("post_booking", lambda: _test_booking_summary_does_not_merge_shared_phone(now))
        run("post_booking", lambda: _test_available_services_uses_active_booking_not_stale_form(now))
        run("reschedule", lambda: _test_reschedule_selects_service_after_list(now))
        run("reschedule", lambda: _test_reschedule_uses_target_date_not_source_date(now))
        run("reschedule", lambda: _test_reschedule_typo_pernesti_uses_target_date(now))
        run("reschedule", lambda: _test_reschedule_keeps_initial_date_after_selection(now))
        run("reschedule", lambda: _test_reschedule_can_change_gazebo_variant(now))
        run("reschedule", lambda: _test_reschedule_flow_answers_options_instead_of_loop(now))
        run("reschedule", lambda: _test_reschedule_flow_answers_info_question(now))
        run("reschedule", lambda: _test_multi_reschedule_same_date_for_all_bookings(now))
        run("cancel", lambda: _test_paid_cancel_asks_confirmation(now))
        run("cancel", lambda: _test_paid_cancel_typo_dya_confirms(now))
        run("cancel", lambda: _test_ack_after_cancel_does_not_say_booking_fixed(now))
        run("cancel", lambda: _test_paid_cancel_refund_window_text(now))
        run("cancel", lambda: _test_cancel_refund_boundaries(now))
        run("cancel", lambda: _test_refund_required_notifies_admin(now))
        run("post_booking", lambda: _test_ai_semantic_preflight_for_active_routes(now))
        run("cancel", lambda: _test_paid_cancel_all_asks_single_confirmation(now))
        run("cancel", lambda: _test_multi_cancel_refund_only_paid_refundable(now))
        run("cancel", lambda: _test_paid_bathhouse_cancel_without_hold(now))
        run("cancel", lambda: _test_ai_change_type_cancel_starts_flow(now))
        run("reschedule", lambda: _test_ai_change_type_reschedule_starts_flow(now))
        run("reschedule", lambda: _test_paid_reschedule_asks_confirmation(now))
        run("fresh", lambda: _test_generic_second_booking_keeps_only_contact(now))
        run("fresh", lambda: _test_abort_current_draft_keeps_contact(now))
        run("fresh", lambda: _test_abort_current_draft_from_upsell_refusal(now))
        run("prices", lambda: _test_info_during_bath_form_keeps_service_context(now))
        run("fresh", lambda: _test_later_pause_during_form_does_not_repeat_question(now))
        run("services", lambda: _test_second_service_same_time_keeps_current_service(now))
        run("services", lambda: _test_second_service_same_time_reference_on_time_step(now))
        run("services", lambda: _test_second_service_same_date_keeps_current_service(now))
        run("services", lambda: _test_second_service_same_number_wording_keeps_current_service(now))
        run("services", lambda: _test_live_135_paid_gazebo_then_bathhouse_same_number(now))
        run("services", lambda: _test_new_bath_request_does_not_cancel_paid_gazebo(now))
        run("services", lambda: _test_bathhouse_post_booking_info_then_generic_new_request(now))
        run("services", lambda: _test_gazebo_info_then_separate_booking_from_old_bath_draft(now))
        run("services", lambda: _test_bathhouse_post_booking_paraphrases_start_clean(now))
        run("prices", _test_price_replies_use_service_map)
        run("prices", _test_price_question_with_budet_not_children_info)
        run("prices", lambda: _test_ai_semantic_price_question_without_price_keywords(now))
        run("gazebo", _test_truncated_people_word_extracts_guests)
        run("fresh", _test_friends_hangout_event_format_not_birthday)
        run("prices", _test_addon_price_question_does_not_add_item)
        run("prices", _test_generic_upsell_price_question_uses_addon_prices)
        run("prices", _test_prepayment_price_question_not_addons)
        run("prices", _test_gazebo_weekday_discount_reply)
        run("prices", _test_best2info_retrieval_for_client_questions)
        run("prices", _test_gazebo_duration_price_rule)
        run("prices", _test_brooms_are_forbidden)
        run("prices", _test_brooms_info_without_form_does_not_ask_booking)
        run("prices", lambda: _test_kids_pets_parking_info_without_form_does_not_start_booking(now))
        run("prices", _test_children_parking_info_during_form_uses_runtime_knowledge)
        run("prices", lambda: _test_gazebo_until_morning_info_keeps_time_step(now))
        run("prices", _test_mosquito_question_during_confirmation)
        run("prices", lambda: _test_mosquito_question_after_booking_bypasses_ai(now))
        run("prices", _test_bathhouse_ten_hour_price_formula)
        run("prices", _test_coal_price_is_known)
        run("time", _test_bare_duration_answer)
        run("time", _test_evening_time_choice_uses_early_option)
        run("time", _test_until_midnight_uses_existing_start)
        run("time", lambda: _test_confirmation_time_correction_rechecks(now))
        run("gazebo", lambda: _test_gazebo_selected_variant_capacity_uses_known_free_list(now))
        run("fresh", lambda: _test_stale_form_after_two_hours_asks_choice(now))
        run("fresh", lambda: _test_stale_explicit_new_bath_request_skips_choice(now))
        run("fresh", lambda: _test_stale_davaite_continues(now))
        run("fresh", lambda: _test_stale_no_with_new_bath_request_processes_same_message(now))
        run("fresh", lambda: _test_stale_free_dates_request_starts_fresh_lookup(now))
        run("fresh", lambda: _test_old_form_new_free_dates_skips_stale_choice(now))
        run("fresh", lambda: _test_ai_event_format_is_not_invented(now))
        run("upsell", _test_basic_upsell_is_saved_to_yclients_comment)
        run("reschedule", lambda: _test_reschedule_preferences_recalculate_options(now))
        run("reschedule", lambda: _test_reschedule_da_da_confirms_and_clears_flow(now))
        run("reminder", lambda: _test_booking_reminder_yes_and_no(now))
    finally:
        message_handler.call_ai = original_call_ai_for_suite
        message_handler.create_missing_yclients_records = original_create_missing
        _cleanup()

    failed = [check for check in checks if not check.ok]
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
