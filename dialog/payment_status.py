from __future__ import annotations

import json
import logging
from typing import Any

from app.dialog.availability import build_yclients_payload, check_availability
from app.dialog.availability_cache import refresh_availability_cache
from app.dialog.state import BookingDraft
from app.dialog.admin_notify import (
    notify_admin_manual_review,
    notify_admin_payment_canceled,
    notify_admin_payment_received,
    notify_admin_yclients_error,
)
from app.integrations.yclients import YClientsClient
from app.integrations.yookassa import YooKassaClient
from app.storage import sqlite


logger = logging.getLogger(__name__)


def sync_paid_bookings() -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for row in sqlite.list_pending_payments():
        draft = BookingDraft.from_dict(json.loads(row["draft_json"]))
        if not draft.payment_id:
            continue
        try:
            payment = YooKassaClient().get_payment(draft.payment_id)
        except Exception:
            logger.exception("Failed to check YooKassa payment booking_id=%s", row["id"])
            continue
        if payment.get("status") != "succeeded" and not payment.get("paid"):
            if payment.get("status") in {"canceled", "expired"}:
                draft.status = "payment_canceled"
                sqlite.update_booking(int(row["id"]), draft.to_dict(), "payment_canceled")
                sqlite.save_draft(str(row["chat_id"]), draft.to_dict(), status="payment_canceled", current_step=draft.next_step())
                notify_admin_payment_canceled(
                    chat_id=str(row["chat_id"]),
                    booking_id=int(row["id"]),
                    draft=draft,
                    status=str(payment.get("status") or "payment_canceled"),
                )
                logger.info("Payment is no longer pending booking_id=%s status=%s", row["id"], payment.get("status"))
            continue
        result = check_availability(draft, chat_id=str(row["chat_id"]))
        if not result.ok:
            draft.status = "paid_needs_manual_review"
            sqlite.update_booking(int(row["id"]), draft.to_dict(), "paid_needs_manual_review")
            sqlite.save_draft(str(row["chat_id"]), draft.to_dict(), status="paid_needs_manual_review", current_step=draft.next_step())
            logger.warning("Paid booking unavailable booking_id=%s message=%s", row["id"], result.message)
            notify_admin_manual_review(
                chat_id=str(row["chat_id"]),
                booking_id=int(row["id"]),
                draft=draft,
                reason=result.message or "доступность не подтвердилась",
            )
            events.append(
                {
                    "chat_id": str(row["chat_id"]),
                    "message": "Оплату увидела, но место уже не подтверждается автоматически. Передала заявку на ручную проверку.",
                }
            )
            continue
        try:
            response = YClientsClient().create_book_record(build_yclients_payload(draft))
            logger.info("YCLIENTS create response shape=%s", _response_shape(response))
            draft.yclients_record_id = _extract_record_id(response)
            draft.status = "booked"
            sqlite.update_booking(int(row["id"]), draft.to_dict(), "booked")
            sqlite.save_draft(str(row["chat_id"]), draft.to_dict(), status="booked", current_step=draft.next_step())
            sqlite.convert_hold(str(row["chat_id"]))
            notify_admin_payment_received(
                chat_id=str(row["chat_id"]),
                booking_id=int(row["id"]),
                draft=draft,
            )
            try:
                refresh_availability_cache(days=14, max_seconds=180, reason="booking_created")
            except Exception:
                logger.exception("Failed to refresh availability cache after booking booking_id=%s", row["id"])
            events.append(
                {
                    "chat_id": str(row["chat_id"]),
                    "message": "Оплату получила ✅\nБронь подтверждена. Ждём вас!",
                }
            )
        except Exception:
            draft.status = "paid_yclients_error"
            sqlite.update_booking(int(row["id"]), draft.to_dict(), "paid_yclients_error")
            sqlite.save_draft(str(row["chat_id"]), draft.to_dict(), status="paid_yclients_error", current_step=draft.next_step())
            logger.exception("Failed to create YCLIENTS record booking_id=%s", row["id"])
            notify_admin_yclients_error(
                chat_id=str(row["chat_id"]),
                booking_id=int(row["id"]),
                draft=draft,
            )
            events.append(
                {
                    "chat_id": str(row["chat_id"]),
                    "message": "Оплату увидела ✅\nНо автоматически подтвердить бронь не получилось. Передала администратору.",
                }
            )
    return events


def _extract_record_id(response: Any) -> str | None:
    record_keys = ("record_id", "visit_id", "id")
    if isinstance(response, dict):
        for key in record_keys:
            if response.get(key):
                return str(response[key])
        data = response.get("data")
        if isinstance(data, dict):
            for key in record_keys:
                if data.get(key):
                    return str(data[key])
            for value in data.values():
                found = _extract_record_id(value)
                if found:
                    return found
        if isinstance(data, list) and data:
            for item in data:
                found = _extract_record_id(item)
                if found:
                    return found
        for key in ("records", "visits", "appointments"):
            value = response.get(key)
            found = _extract_record_id(value)
            if found:
                return found
    if isinstance(response, list):
        for item in response:
            found = _extract_record_id(item)
            if found:
                return found
    return None


def _response_shape(response: Any) -> Any:
    if isinstance(response, dict):
        return {key: _response_shape(value) for key, value in response.items()}
    if isinstance(response, list):
        return [_response_shape(response[0])] if response else []
    return type(response).__name__
