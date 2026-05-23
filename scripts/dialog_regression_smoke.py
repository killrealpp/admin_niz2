"""Regression smoke tests for the Telegram dialog state machine.

The script uses isolated test users and removes them after the run.
It stubs payment creation so no real YooKassa/YCLIENTS side effects happen.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.connection import get_connection  # noqa: E402
from app.services import message_handler  # noqa: E402
from app.services.availability_service import check_availability  # noqa: E402
from app.services.booking_form_service import initial_form_data  # noqa: E402
from app.services.message_handler import IncomingMessage, handle_incoming  # noqa: E402


TEST_PREFIX = "regression_dialog_"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@dataclass
class Check:
    name: str
    ok: bool
    details: str


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
            cur.execute(
                """
                SELECT id
                FROM users
                WHERE external_id LIKE %s
                """,
                (TEST_PREFIX + "%",),
            )
            user_ids = [row["id"] for row in cur.fetchall()]

            if conversation_ids:
                cur.execute("DELETE FROM payments WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM bookings WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM slot_holds WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM system_logs WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM messages WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM conversation_summaries WHERE conversation_id = ANY(%s)", (conversation_ids,))
                cur.execute("DELETE FROM conversations WHERE id = ANY(%s)", (conversation_ids,))
            if user_ids:
                cur.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))


def _ru_date(value: date) -> str:
    months = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря",
    }
    return f"{value.day} {months[value.month]}"


def _find_free_gazebo_date(now: datetime) -> date:
    base = initial_form_data()
    base.update(
        {
            "service_type": "gazebo",
            "service_variant": "Беседка №2",
            "time": "12:00",
            "duration": 6,
            "guests_count": 8,
        }
    )
    with get_connection() as conn:
        for offset in range(1, 60):
            candidate = now.date() + timedelta(days=offset)
            form_data = base | {"date": candidate.isoformat()}
            result = check_availability(conn, form_data=form_data, now=now)
            if result.ok and result.slots:
                return candidate
    raise RuntimeError("No free gazebo date found for smoke test")


def _fake_payment(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "amount": "1.00",
        "currency": "RUB",
        "payment_url": "https://example.test/pay",
        "provider_payment_id": "smoke_payment",
        "status": "pending",
    }


def _send(user_suffix: str, text: str, now: datetime) -> str:
    return handle_incoming(
        IncomingMessage(
            channel="telegram",
            external_user_id=TEST_PREFIX + user_suffix,
            user_name="Smoke User",
            text=text,
            message_time=now,
            raw_payload={"source": "dialog_regression_smoke"},
        )
    )


def _expect(name: str, reply: str, *needles: str) -> Check:
    lowered = reply.lower().replace("ё", "е")
    missing = [needle for needle in needles if needle.lower().replace("ё", "е") not in lowered]
    return Check(name=name, ok=not missing, details=reply if not missing else f"missing={missing}; reply={reply}")


def _expect_any(name: str, reply: str, *needles: str) -> Check:
    lowered = reply.lower().replace("ё", "е")
    ok = any(needle.lower().replace("ё", "е") in lowered for needle in needles)
    return Check(name=name, ok=ok, details=reply if ok else f"missing_any={needles}; reply={reply}")


def _holds_count(user_suffix: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(1) AS total
                FROM slot_holds sh
                JOIN conversations c ON c.id = sh.conversation_id
                JOIN users u ON u.id = c.user_id
                WHERE u.external_id = %s
                """,
                (TEST_PREFIX + user_suffix,),
            )
            return int(cur.fetchone()["total"])


def _active_holds_count(user_suffix: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(1) AS total
                FROM slot_holds sh
                JOIN conversations c ON c.id = sh.conversation_id
                JOIN users u ON u.id = c.user_id
                WHERE u.external_id = %s
                  AND sh.status = 'active'
                """,
                (TEST_PREFIX + user_suffix,),
            )
            return int(cur.fetchone()["total"])


def _bookings_count(user_suffix: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(1) AS total
                FROM bookings b
                JOIN conversations c ON c.id = b.conversation_id
                JOIN users u ON u.id = c.user_id
                WHERE u.external_id = %s
                """,
                (TEST_PREFIX + user_suffix,),
            )
            return int(cur.fetchone()["total"])


def _conversation_state(user_suffix: str) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.*
                FROM conversations c
                JOIN users u ON u.id = c.user_id
                WHERE u.external_id = %s
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                (TEST_PREFIX + user_suffix,),
            )
            row = cur.fetchone()
    return dict(row or {})


def main() -> None:
    settings = get_settings()
    now = datetime(2026, 5, 20, 10, 0, tzinfo=ZoneInfo(settings.app_timezone))
    checks: list[Check] = []
    original_payment = message_handler.create_payment_link_for_holds
    message_handler.create_payment_link_for_holds = _fake_payment
    _cleanup()

    try:
        free_date = _find_free_gazebo_date(now)
        date_text = _ru_date(free_date)

        _send("gazebo_help", "нужна беседка", now)
        _send("gazebo_help", date_text, now)
        reply = _send("gazebo_help", "а какую лучше выбрать?", now)
        checks.append(_expect("gazebo advice question", reply, "Беседка", "Сколько"))
        reply = _send("gazebo_help", "8 человек", now)
        checks.append(_expect("guest count while choosing gazebo", reply, "8", "Беседка"))
        reply = _send("gazebo_help", "давай беседку номер два", now)
        checks.append(_expect("gazebo variant selected", reply, "Во сколько"))
        _send("gazebo_help", "с 17 до 00", now)
        reply = _send("gazebo_help", "а парковка есть?", now)
        checks.append(_expect("info question after guest count was inferred", reply, "парков"))

        _send("parking_without_guests", "нужна беседка", now)
        _send("parking_without_guests", date_text, now)
        _send("parking_without_guests", "беседка номер два", now)
        _send("parking_without_guests", "с 17 до 00", now)
        reply = _send("parking_without_guests", "а парковка есть?", now)
        checks.append(_expect("info question while waiting guests", reply, "парков", "Сколько", "гостей"))

        _send("info_confirm", "нужна беседка", now)
        _send("info_confirm", date_text, now)
        _send("info_confirm", "беседка номер два", now)
        _send("info_confirm", "с 12 до 18", now)
        _send("info_confirm", "8", now)
        _send("info_confirm", "день рождения", now)
        reply = _send("info_confirm", "нет", now)
        checks.append(_expect("first upsell no gets push", reply, "если точно ничего", "нет"))
        _send("info_confirm", "нет", now)
        _send("info_confirm", "Иван", now)
        reply = _send("info_confirm", "+79968533502", now)
        checks.append(_expect_any("confirmation reached", reply, "Подтверждаете бронь", "всё верно", "все верно"))
        reply = _send("info_confirm", "Меня зовут не Иван", now)
        checks.append(_expect("name correction asks value", reply, "Какое имя"))
        reply = _send("info_confirm", "Имя Петя", now)
        checks.append(_expect("name correction updates confirmation", reply, "Петя", "Подтверждаете"))
        reply = _send("info_confirm", "а там есть мангал?", now)
        checks.append(_expect("info question during confirmation", reply, "мангал", "напишите"))
        reply = _send("info_confirm", "да", now)
        checks.append(_expect("confirm creates fake payment", reply, "Оплатить можно по ссылке", "https://example.test/pay"))
        checks.append(
            Check(
                name="hold without booking before payment",
                ok=_holds_count("info_confirm") > 0 and _bookings_count("info_confirm") == 0,
                details=f"holds={_holds_count('info_confirm')}, bookings={_bookings_count('info_confirm')}",
            )
        )
        reply = _send("info_confirm", "А можно имя заменить на Сергей", now)
        checks.append(_expect("reserved name change keeps hold", reply, "обновила имя", "Резерв оставила активным"))
        checks.append(
            Check(
                name="reserved name change does not cancel hold",
                ok=_active_holds_count("info_confirm") == 1,
                details=f"active_holds={_active_holds_count('info_confirm')}",
            )
        )
        reply = _send("info_confirm", "хорошо, а есть бани?", now)
        checks.append(_expect("post booking service question", reply, "баня"))
        state = _conversation_state("info_confirm")
        checks.append(
            Check(
                name="reserved state after confirmation",
                ok=state.get("status") == "reserved" and state.get("current_step") == "reserved",
                details=str({key: state.get(key) for key in ("status", "current_step", "next_step")}),
            )
        )

        failed = [check for check in checks if not check.ok]
        for check in checks:
            marker = "OK" if check.ok else "FAIL"
            print(f"{marker}: {check.name}: {check.details}")
        if failed:
            raise SystemExit(1)
    finally:
        message_handler.create_payment_link_for_holds = original_payment
        _cleanup()


if __name__ == "__main__":
    main()
