"""Smoke-check client notifications by user channel without DB/secrets/live calls."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bot.channel_types import CHANNEL_MAX, CHANNEL_TELEGRAM, DeliveryTarget  # noqa: E402
from app.bot.notification_router import NotificationRouter  # noqa: E402
from app.services import client_notification_service, payment_status_runner, waitlist_service  # noqa: E402
from app.services.availability_service import AvailabilityResult  # noqa: E402


class RecordingClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[DeliveryTarget, str]] = []

    async def send_text(self, target: DeliveryTarget, text: str, **_options: Any) -> None:
        if self.fail:
            raise RuntimeError("synthetic adapter failure")
        self.sent.append((target, text))

    async def send_media(
        self,
        target: DeliveryTarget,
        media_paths: Sequence[str],
        caption: str | None = None,
        **_options: Any,
    ) -> None:
        return None

    async def send_typing(self, target: DeliveryTarget) -> None:
        return None

    async def answer_callback(
        self,
        callback_id: str,
        message: str | None = None,
        notification: str | None = None,
    ) -> None:
        return None


class FakeSettings:
    app_timezone = "Europe/Moscow"
    hold_ttl_minutes = 30


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return datetime(2026, 6, 4, 12, 0, tzinfo=tz)


@contextmanager
def fake_connection():
    yield object()


def patch_attr(patches: list[tuple[Any, str, Any]], obj: Any, name: str, value: Any) -> None:
    patches.append((obj, name, getattr(obj, name)))
    setattr(obj, name, value)


async def assert_payment_reminders_by_channel() -> None:
    telegram = RecordingClient()
    max_client = RecordingClient()
    router = NotificationRouter({CHANNEL_TELEGRAM: telegram, CHANNEL_MAX: max_client})
    marked: list[int] = []
    messages: list[dict[str, Any]] = []
    system_logs: list[dict[str, Any]] = []

    rows = [
        _booking_row(1, CHANNEL_TELEGRAM, "tg-user"),
        _booking_row(2, CHANNEL_MAX, "max-user"),
        _booking_row(3, "unknown", "other-user"),
    ]

    patches: list[tuple[Any, str, Any]] = []
    try:
        patch_attr(patches, payment_status_runner, "datetime", FixedDateTime)
        patch_attr(patches, payment_status_runner, "get_settings", lambda: FakeSettings())
        patch_attr(patches, payment_status_runner, "get_connection", fake_connection)
        patch_attr(patches, client_notification_service, "get_connection", fake_connection)
        patch_attr(
            patches,
            payment_status_runner.bookings_repo,
            "list_due_reminders",
            lambda *_args, **_kwargs: list(rows),
        )
        patch_attr(
            patches,
            payment_status_runner.bookings_repo,
            "mark_reminder_sent",
            lambda _conn, *, booking_id, now: marked.append(int(booking_id)),
        )
        patch_attr(
            patches,
            payment_status_runner.messages_repo,
            "create",
            lambda _conn, **kwargs: messages.append(kwargs),
        )
        patch_attr(
            patches,
            client_notification_service.system_logs_repo,
            "create",
            lambda _conn, **kwargs: system_logs.append(kwargs),
        )
        patch_attr(
            patches,
            payment_status_runner,
            "load_services_map",
            lambda: {"gazebo": {"title": "Беседка"}},
        )

        await payment_status_runner.notify_booking_reminders_once(router)
    finally:
        restore(patches)

    assert [target.external_id for target, _text in telegram.sent] == ["tg-user"]
    assert [target.external_id for target, _text in max_client.sent] == ["max-user"]
    assert marked == [1, 2]
    assert len(messages) == 2
    assert len(system_logs) == 1
    assert system_logs[0]["event_type"] == "client_notification_delivery_failed"
    assert system_logs[0]["payload"]["user_channel"] == "unknown"


async def assert_waitlist_by_channel() -> None:
    telegram = RecordingClient()
    max_client = RecordingClient()
    router = NotificationRouter({CHANNEL_TELEGRAM: telegram, CHANNEL_MAX: max_client})
    checked: list[int] = []
    notified: list[int] = []
    system_logs: list[dict[str, Any]] = []
    rows = [
        _waitlist_row(10, CHANNEL_TELEGRAM, "tg-waitlist"),
        _waitlist_row(11, CHANNEL_MAX, "max-waitlist"),
    ]

    patches: list[tuple[Any, str, Any]] = []
    try:
        patch_attr(patches, waitlist_service, "datetime", FixedDateTime)
        patch_attr(patches, waitlist_service, "get_settings", lambda: FakeSettings())
        patch_attr(patches, waitlist_service, "get_connection", fake_connection)
        patch_attr(patches, client_notification_service, "get_connection", fake_connection)
        patch_attr(
            patches,
            waitlist_service.waitlist_repo,
            "list_active_due",
            lambda *_args, **_kwargs: list(rows),
        )
        patch_attr(
            patches,
            waitlist_service.waitlist_repo,
            "mark_checked",
            lambda _conn, *, waitlist_id, now: checked.append(int(waitlist_id)),
        )
        patch_attr(
            patches,
            waitlist_service.waitlist_repo,
            "mark_notified",
            lambda _conn, *, waitlist_id, now: notified.append(int(waitlist_id)),
        )
        patch_attr(
            patches,
            waitlist_service,
            "_waitlist_request_is_obsolete",
            lambda *_args, **_kwargs: False,
        )
        patch_attr(
            patches,
            waitlist_service,
            "check_availability",
            lambda *_args, **_kwargs: AvailabilityResult(True, "ok", ["slot"]),
        )
        patch_attr(
            patches,
            waitlist_service,
            "load_services_map",
            lambda: {"gazebo": {"title": "Беседка"}},
        )
        patch_attr(
            patches,
            client_notification_service.system_logs_repo,
            "create",
            lambda _conn, **kwargs: system_logs.append(kwargs),
        )

        sent = await waitlist_service.notify_waitlist_matches(router)
    finally:
        restore(patches)

    assert sent == 2
    assert checked == [10, 11]
    assert notified == [10, 11]
    assert [target.external_id for target, _text in telegram.sent] == ["tg-waitlist"]
    assert [target.external_id for target, _text in max_client.sent] == ["max-waitlist"]
    assert system_logs == []


async def assert_adapter_failure_not_delivered() -> None:
    failing_router = NotificationRouter({CHANNEL_MAX: RecordingClient(fail=True)})
    system_logs: list[dict[str, Any]] = []

    patches: list[tuple[Any, str, Any]] = []
    try:
        patch_attr(patches, client_notification_service, "get_connection", fake_connection)
        patch_attr(
            patches,
            client_notification_service.system_logs_repo,
            "create",
            lambda _conn, **kwargs: system_logs.append(kwargs),
        )
        result = await client_notification_service.send_client_text_notification(
            failing_router,
            {
                "conversation_id": 500,
                "user_channel": CHANNEL_MAX,
                "user_external_id": "max-failing",
            },
            "hello",
            notification_event="smoke_failure",
            entity_type="smoke",
            entity_id=500,
        )
    finally:
        restore(patches)

    assert not result.delivered
    assert result.target is not None
    assert len(system_logs) == 1
    assert system_logs[0]["event_type"] == "client_notification_delivery_failed"
    assert system_logs[0]["payload"]["error_type"] == "RuntimeError"


async def assert_expired_hold_resets_reserved_conversation() -> None:
    max_client = RecordingClient()
    router = NotificationRouter({CHANNEL_MAX: max_client})
    marked: list[int] = []
    messages: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    hold = {
        "id": 51,
        "conversation_id": 777,
        "user_channel": CHANNEL_MAX,
        "user_external_id": "max-expired",
        "service_type": "gazebo",
        "yclients_service_id": "18201055",
        "slot_date": date(2026, 6, 24),
        "slot_time": time(18, 0),
        "duration_minutes": 360,
    }
    conversation = {
        "id": 777,
        "status": "reserved",
        "current_step": "reserved",
        "next_step": "payment_status",
        "form_data": {
            "service_type": "gazebo",
            "service_variant": "Беседка №1",
            "date": "2026-06-24",
            "time": "18:00",
            "duration": 6,
            "client_name": "Евгений",
            "phone": "+79990000000",
            "upsell_items": ["уголь"],
            "payment_status": "pending",
        },
    }

    def update_after_message(_conn, conversation_id: int, now: datetime, **kwargs: Any) -> None:
        updates.append({"conversation_id": conversation_id, "now": now, **kwargs})

    patches: list[tuple[Any, str, Any]] = []
    try:
        patch_attr(patches, payment_status_runner, "datetime", FixedDateTime)
        patch_attr(patches, payment_status_runner, "get_settings", lambda: FakeSettings())
        patch_attr(patches, payment_status_runner, "get_connection", fake_connection)
        patch_attr(patches, client_notification_service, "get_connection", fake_connection)
        patch_attr(
            patches,
            payment_status_runner.slot_holds_repo,
            "expire_old",
            lambda _conn, now: 1,
        )
        patch_attr(
            patches,
            payment_status_runner.slot_holds_repo,
            "list_expired_unnotified",
            lambda _conn, limit=50: [hold],
        )
        patch_attr(
            patches,
            payment_status_runner.slot_holds_repo,
            "mark_expired_notified",
            lambda _conn, *, hold_id, now: marked.append(int(hold_id)),
        )
        patch_attr(
            patches,
            payment_status_runner.slot_holds_repo,
            "list_active_for_conversation",
            lambda _conn, *, conversation_id, now: [],
        )
        patch_attr(
            patches,
            payment_status_runner.bookings_repo,
            "list_active_for_conversation",
            lambda _conn, *, conversation_id: [],
        )
        patch_attr(
            patches,
            payment_status_runner.conversations_repo,
            "get_by_id",
            lambda _conn, conversation_id: dict(conversation),
        )
        patch_attr(
            patches,
            payment_status_runner.conversations_repo,
            "update_after_message",
            update_after_message,
        )
        patch_attr(
            patches,
            payment_status_runner.messages_repo,
            "create",
            lambda _conn, **kwargs: messages.append(kwargs),
        )
        patch_attr(
            patches,
            client_notification_service.system_logs_repo,
            "create",
            lambda _conn, **_kwargs: None,
        )
        patch_attr(
            patches,
            payment_status_runner,
            "load_services_map",
            lambda: {
                "gazebo": {
                    "title": "Беседка",
                    "variants": [{"title": "Беседка №1", "yclients_service_id": "18201055"}],
                }
            },
        )

        await payment_status_runner.notify_expired_holds_once(router)
    finally:
        restore(patches)

    assert [target.external_id for target, _text in max_client.sent] == ["max-expired"]
    assert marked == [51]
    assert len(messages) == 1
    assert updates, "expired hold notification must reset reserved conversation"
    update = updates[0]
    form_data = update["form_data"]
    assert update["conversation_id"] == 777
    assert update["status"] == "waiting_user"
    assert update["current_step"] == "service_type"
    assert update["next_step"] == "service_type"
    assert form_data["client_name"] == "Евгений"
    assert form_data["phone"] == "+79990000000"
    assert form_data["payment_status"] == "not_required_yet"
    assert form_data["upsell_items"] == []
    assert form_data["service_type"] is None
    assert form_data["date"] is None


def assert_repository_contracts_include_user_channel() -> None:
    files = [
        ROOT / "app/db/repositories/payments_repo.py",
        ROOT / "app/db/repositories/slot_holds_repo.py",
        ROOT / "app/db/repositories/bookings_repo.py",
        ROOT / "app/db/repositories/waitlist_repo.py",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "user_channel" in text, f"{path} must return user_channel for notifications"


def _booking_row(row_id: int, channel: str, external_id: str) -> dict[str, Any]:
    return {
        "id": row_id,
        "conversation_id": 100 + row_id,
        "service_type": "gazebo",
        "booking_date": date(2026, 6, 5),
        "booking_time": time(18, 0),
        "duration_minutes": 360,
        "user_channel": channel,
        "user_external_id": external_id,
    }


def _waitlist_row(row_id: int, channel: str, external_id: str) -> dict[str, Any]:
    return {
        "id": row_id,
        "conversation_id": 200 + row_id,
        "user_id": 300 + row_id,
        "status": "active",
        "service_type": "gazebo",
        "desired_date": date(2026, 6, 30),
        "desired_time": time(18, 0),
        "duration_minutes": 360,
        "guests_count": 20,
        "raw_payload": {"form_data": {"phone": "+79990000000"}},
        "user_channel": channel,
        "user_external_id": external_id,
    }


def restore(patches: list[tuple[Any, str, Any]]) -> None:
    for obj, name, original in reversed(patches):
        setattr(obj, name, original)


async def main() -> None:
    await assert_payment_reminders_by_channel()
    await assert_waitlist_by_channel()
    await assert_adapter_failure_not_delivered()
    await assert_expired_hold_resets_reserved_conversation()
    assert_repository_contracts_include_user_channel()
    print("channel_notifications_smoke=ok")


if __name__ == "__main__":
    asyncio.run(main())
