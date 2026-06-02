from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2.extensions import connection as PgConnection

from app.core.config import get_settings
import json

from app.db.repositories import (
    bookings_repo,
    conversations_repo,
    payments_repo,
    slot_holds_repo,
    users_repo,
    webhook_events_repo,
)
from app.integrations.yookassa_client import YooKassaClient, YooKassaError
from app.services.availability_service import check_availability, load_services_map
from app.services.yclients_record_service import (
    create_missing_yclients_records,
    upsert_local_busy_interval_for_booking,
)


def calculate_prepayment_amount(
    bookings_count: int,
    *,
    base_prices: list[Decimal] | None = None,
) -> Decimal:
    settings = get_settings()
    mode = str(settings.prepayment_mode or "fixed").lower()
    if mode == "percent":
        prices = [price for price in (base_prices or []) if price is not None]
        if not prices:
            raise YooKassaError("Cannot calculate percent prepayment without base service prices")
        percent = Decimal(str(settings.prepayment_percent)) / Decimal("100")
        amount = sum(prices, Decimal("0")) * percent
    else:
        amount = Decimal(settings.prepayment_amount_rub) * Decimal(max(bookings_count, 1))
    return amount.quantize(Decimal("0.01"))


def create_payment_link_for_bookings(
    conn: PgConnection,
    *,
    conversation_id: int,
    user_id: int,
    booking_ids: list[int],
    client_name: str,
    phone: str,
) -> dict[str, Any]:
    settings = get_settings()
    if settings.payment_provider.lower() != "yookassa":
        raise YooKassaError("PAYMENT_PROVIDER is not yookassa")

    amount = calculate_prepayment_amount(
        len(booking_ids),
        base_prices=_base_prices_for_bookings(conn, booking_ids),
    )
    description = f"Предоплата за бронь, {client_name}, {phone}"
    payment = payments_repo.create_pending(
        conn,
        conversation_id=conversation_id,
        user_id=user_id,
        booking_ids=booking_ids,
        provider="yookassa",
        amount=amount,
        currency="RUB",
        description=description,
        raw_payload={
            "booking_ids": booking_ids,
            "state": "payment_intent_created",
        },
    )
    conn.commit()
    try:
        response = YooKassaClient().create_payment(
            amount=amount,
            description=description,
            metadata={
                "conversation_id": str(conversation_id),
                "user_id": str(user_id),
                "payment_id": str(payment["id"]),
                "booking_ids": ",".join(str(item) for item in booking_ids),
            },
            customer_phone=phone,
            idempotence_key=f"booking-payment-{payment['id']}",
        )
    except Exception as exc:
        payments_repo.mark_failed(
            conn,
            payment_id=payment["id"],
            raw_payload={
                "error": str(exc),
                "booking_ids": booking_ids,
                "state": "provider_create_failed",
            },
        )
        conn.commit()
        raise

    confirmation = response.get("confirmation") or {}
    status = response.get("status") or "pending"
    saved_payment = payments_repo.attach_provider_response(
        conn,
        payment_id=payment["id"],
        provider_payment_id=response.get("id"),
        payment_url=confirmation.get("confirmation_url"),
        status=status,
        raw_payload=response,
    )
    bookings_repo.update_payment_status_by_ids(
        conn,
        booking_ids=booking_ids,
        payment_status="awaiting_payment",
    )
    conn.commit()
    return saved_payment


def create_payment_link_for_holds(
    conn: PgConnection,
    *,
    conversation_id: int,
    user_id: int,
    hold_ids: list[int],
    client_name: str,
    phone: str,
    force_new: bool = False,
    raw_payload_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if settings.payment_provider.lower() != "yookassa":
        raise YooKassaError("PAYMENT_PROVIDER is not yookassa")
    if not hold_ids:
        raise YooKassaError("hold_ids are required for prepayment")

    normalized_hold_ids = [int(item) for item in hold_ids]
    amount = calculate_prepayment_amount(
        len(normalized_hold_ids),
        base_prices=_base_prices_for_holds(conn, normalized_hold_ids),
    )
    description = f"Предоплата за бронь, {client_name}, {phone}"
    existing_payment = payments_repo.find_active_for_hold_ids(
        conn,
        conversation_id=conversation_id,
        provider="yookassa",
        hold_ids=normalized_hold_ids,
    )
    if not force_new and existing_payment and existing_payment.get("payment_url"):
        return existing_payment

    raw_payload = {
        "hold_ids": normalized_hold_ids,
        "state": "payment_intent_created",
    }
    if raw_payload_extra:
        raw_payload.update(raw_payload_extra)

    payment = (None if force_new else existing_payment) or payments_repo.create_pending(
        conn,
        conversation_id=conversation_id,
        user_id=user_id,
        booking_ids=[],
        provider="yookassa",
        amount=amount,
        currency="RUB",
        description=description,
        raw_payload=raw_payload,
    )
    conn.commit()
    try:
        response = YooKassaClient().create_payment(
            amount=amount,
            description=description,
            metadata={
                "conversation_id": str(conversation_id),
                "user_id": str(user_id),
                "payment_id": str(payment["id"]),
                "hold_ids": ",".join(str(item) for item in normalized_hold_ids),
            },
            customer_phone=phone,
            idempotence_key=f"hold-payment-{payment['id']}",
        )
    except Exception as exc:
        payments_repo.mark_failed(
            conn,
            payment_id=payment["id"],
            raw_payload={
                "error": str(exc),
                "hold_ids": normalized_hold_ids,
                "state": "provider_create_failed",
            },
        )
        conn.commit()
        raise

    confirmation = response.get("confirmation") or {}
    status = response.get("status") or "pending"
    payload = dict(response)
    payload["hold_ids"] = normalized_hold_ids
    if raw_payload_extra:
        payload.update(raw_payload_extra)
    saved_payment = payments_repo.attach_provider_response(
        conn,
        payment_id=payment["id"],
        provider_payment_id=response.get("id"),
        payment_url=confirmation.get("confirmation_url"),
        status=status,
        raw_payload=payload,
    )
    conn.commit()
    return saved_payment


def finalize_bookings_for_paid_payment(
    conn: PgConnection,
    payment: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[int]:
    existing = _booking_ids(payment)
    if existing:
        for booking_id in existing:
            booking = bookings_repo.get_by_id(conn, booking_id=booking_id)
            if booking:
                upsert_local_busy_interval_for_booking(conn, booking=booking)
        return existing

    hold_ids = _hold_ids(payment)
    if not hold_ids:
        return []

    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    settings = get_settings()
    resolved_now = now or dt.now(ZoneInfo(settings.app_timezone))
    created_ids: list[int] = []
    slot_holds_repo.expire_old(conn, resolved_now)

    for hold_id in hold_ids:
        existing_booking = bookings_repo.find_by_hold_id(conn, slot_hold_id=hold_id)
        if existing_booking:
            created_ids.append(int(existing_booking["id"]))
            continue

        hold = slot_holds_repo.get_by_id(conn, hold_id)
        if not hold:
            continue
        if not _hold_can_be_finalized(conn, hold, resolved_now):
            continue

        conversation = conversations_repo.get_by_id(conn, int(hold["conversation_id"]))
        if not conversation:
            continue

        form_data = conversation.get("form_data") or {}
        user = users_repo.get_by_id(conn, int(hold["user_id"]))
        booking = bookings_repo.create_from_hold(
            conn,
            conversation_id=int(hold["conversation_id"]),
            user_id=int(hold["user_id"]),
            slot_hold_id=hold_id,
            service_type=str(hold["service_type"]),
            booking_date=hold["slot_date"],
            booking_time=hold["slot_time"],
            duration_minutes=hold.get("duration_minutes"),
            client_name=str(form_data.get("client_name") or (user or {}).get("name") or "Клиент"),
            phone=str(form_data.get("phone") or (user or {}).get("phone") or ""),
            guests_count=int(form_data["guests_count"]) if form_data.get("guests_count") else None,
            event_format=form_data.get("event_format"),
            preferences=form_data.get("preferences"),
            upsell_items=list(form_data.get("upsell_items") or []),
            status="confirmed",
            payment_status="paid",
        )
        booking = {
            **booking,
            "hold_yclients_service_id": hold.get("yclients_service_id"),
            "hold_yclients_staff_id": hold.get("yclients_staff_id"),
        }
        upsert_local_busy_interval_for_booking(conn, booking=booking)
        slot_holds_repo.mark_converted(conn, hold_id=hold_id, now=resolved_now)
        created_ids.append(int(booking["id"]))

    if created_ids:
        payments_repo.update_booking_ids(conn, payment_id=int(payment["id"]), booking_ids=created_ids)
    return created_ids


def _hold_can_be_finalized(conn: PgConnection, hold: dict[str, Any], now: datetime) -> bool:
    status = str(hold.get("status") or "")
    expires_at = hold.get("expires_at")
    if status == "active" and (not expires_at or expires_at > now):
        return True
    return False


def _availability_form_for_hold(conn: PgConnection, hold: dict[str, Any]) -> dict[str, Any]:
    conversation = conversations_repo.get_by_id(conn, int(hold["conversation_id"]))
    form_data = dict((conversation or {}).get("form_data") or {})
    slot_date = hold.get("slot_date")
    slot_time = hold.get("slot_time")
    if not slot_date or not slot_time:
        return {}
    service_type = str(hold.get("service_type") or "")
    form_data.update(
        {
            "service_type": service_type,
            "date": slot_date.isoformat() if hasattr(slot_date, "isoformat") else str(slot_date),
            "time": str(slot_time)[:5],
            "duration": hold.get("duration_minutes"),
        }
    )
    variant_title = _variant_title_for_hold(hold)
    if variant_title:
        form_data["service_variant"] = variant_title
    return form_data


def _variant_title_for_hold(hold: dict[str, Any]) -> str | None:
    service_type = hold.get("service_type")
    yclients_service_id = str(hold.get("yclients_service_id") or "").strip()
    if not service_type or not yclients_service_id:
        return None
    config = load_services_map().get(service_type) or {}
    for variant in config.get("variants") or []:
        if str(variant.get("yclients_service_id") or "").strip() == yclients_service_id:
            return str(variant.get("title") or "")
    return None


def _base_prices_for_bookings(conn: PgConnection, booking_ids: list[int]) -> list[Decimal]:
    if str(get_settings().prepayment_mode or "fixed").lower() != "percent":
        return []
    prices: list[Decimal] = []
    for booking_id in booking_ids:
        booking = bookings_repo.get_by_id(conn, booking_id=int(booking_id))
        price = _base_price_for_item(booking or {})
        if price is None:
            raise YooKassaError(f"Cannot calculate percent prepayment for booking #{booking_id}: price is unknown")
        prices.append(price)
    return prices


def _base_prices_for_holds(conn: PgConnection, hold_ids: list[int]) -> list[Decimal]:
    if str(get_settings().prepayment_mode or "fixed").lower() != "percent":
        return []
    prices: list[Decimal] = []
    for hold_id in hold_ids:
        hold = slot_holds_repo.get_by_id(conn, hold_id=int(hold_id))
        price = _base_price_for_item(hold or {})
        if price is None:
            raise YooKassaError(f"Cannot calculate percent prepayment for hold #{hold_id}: price is unknown")
        prices.append(price)
    return prices


def _base_price_for_item(item: dict[str, Any]) -> Decimal | None:
    service_type = str(item.get("service_type") or "").strip()
    if not service_type:
        return None
    config = load_services_map().get(service_type) or {}
    variant = _matching_price_variant(config, item)
    raw_price = variant.get("price") if variant else config.get("price")
    if raw_price in (None, ""):
        return None
    price = Decimal(str(raw_price))
    if service_type == "gazebo" and _is_gazebo_discount_day(item):
        return (price * Decimal("0.5")).quantize(Decimal("0.01"))
    return price.quantize(Decimal("0.01"))


def _matching_price_variant(config: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    variants = list(config.get("variants") or [])
    if not variants:
        return config if config.get("price") is not None else None

    service_id = str(
        item.get("hold_yclients_service_id")
        or item.get("yclients_service_id")
        or ""
    ).strip()
    staff_id = str(
        item.get("hold_yclients_staff_id")
        or item.get("yclients_staff_id")
        or ""
    ).strip()
    slot_date = item.get("booking_date") or item.get("slot_date")
    duration = item.get("duration_minutes")
    weekday = slot_date.weekday() if hasattr(slot_date, "weekday") else None

    for variant in variants:
        if service_id and str(variant.get("yclients_service_id") or "").strip() == service_id:
            return variant

    candidates: list[dict[str, Any]] = []
    for variant in variants:
        if staff_id and str(variant.get("yclients_staff_id") or "").strip() != staff_id:
            continue
        variant_duration = variant.get("duration_minutes")
        if duration and variant_duration and int(duration) != int(variant_duration):
            continue
        weekdays = variant.get("weekdays")
        if weekdays and weekday is not None and weekday not in weekdays:
            continue
        candidates.append(variant)
    return candidates[0] if candidates else None


def _is_gazebo_discount_day(item: dict[str, Any]) -> bool:
    slot_date = item.get("booking_date") or item.get("slot_date")
    return bool(hasattr(slot_date, "weekday") and slot_date.weekday() in {0, 1, 2, 3})


def sync_payment_statuses(conn: PgConnection, *, limit: int = 50) -> dict[str, int]:
    settings = get_settings()
    if settings.payment_provider.lower() != "yookassa":
        return {"checked": 0, "updated": 0, "paid": 0, "canceled": 0}

    client = YooKassaClient()
    candidates = payments_repo.list_sync_candidates(conn, provider="yookassa", limit=limit)
    result = {"checked": 0, "updated": 0, "paid": 0, "canceled": 0, "failed": 0}
    for payment in candidates:
        provider_payment_id = payment.get("provider_payment_id")
        if not provider_payment_id:
            continue
        result["checked"] += 1
        try:
            response = client.get_payment(str(provider_payment_id))
        except YooKassaError:
            result["failed"] += 1
            continue
        provider_status = str(response.get("status") or payment.get("status") or "pending")
        paid = bool(response.get("paid"))
        normalized_status = "paid" if paid or provider_status == "succeeded" else provider_status
        paid_at = _parse_yookassa_datetime(response.get("captured_at") or response.get("created_at")) if normalized_status == "paid" else None
        if normalized_status != payment.get("status") or paid_at:
            updated = payments_repo.update_provider_status(
                conn,
                payment_id=payment["id"],
                status=normalized_status,
                raw_payload=response,
                paid_at=paid_at,
            )
            if updated:
                result["updated"] += 1

        booking_ids = _booking_ids(payment)
        if normalized_status == "paid":
            result["paid"] += 1
            if _is_superseded_payment(payment):
                booking_ids = []
            else:
                booking_ids = finalize_bookings_for_paid_payment(conn, payment)
            if booking_ids:
                bookings_repo.update_payment_status_by_ids(
                    conn,
                    booking_ids=booking_ids,
                    payment_status="paid",
                )
        elif normalized_status == "canceled":
            result["canceled"] += 1
            if booking_ids:
                bookings_repo.update_payment_status_by_ids(
                    conn,
                    booking_ids=booking_ids,
                    payment_status="payment_canceled",
                )
            else:
                _cancel_payment_holds(conn, payment)
    return result


def process_yookassa_notification(
    conn: PgConnection,
    payload: dict[str, Any],
) -> dict[str, Any]:
    event_type = str(payload.get("event") or "")
    obj = payload.get("object") if isinstance(payload.get("object"), dict) else {}
    provider_payment_id = str(obj.get("id") or "")
    saved_event, is_new = webhook_events_repo.create_if_new(
        conn,
        provider="yookassa",
        event_type=event_type or "unknown",
        provider_object_id=provider_payment_id or None,
        payload=payload,
    )
    if not provider_payment_id:
        return {"ok": False, "reason": "missing_payment_id", "is_new": is_new}
    if not is_new:
        return {"ok": True, "reason": "duplicate", "is_new": False}
    if not event_type.startswith("payment."):
        if saved_event:
            webhook_events_repo.mark_processed(conn, event_id=saved_event["id"])
        return {
            "ok": True,
            "reason": "ignored_event",
            "event": event_type,
            "provider_object_id": provider_payment_id,
            "is_new": True,
        }

    payment = payments_repo.find_by_provider_payment_id(
        conn,
        provider="yookassa",
        provider_payment_id=provider_payment_id,
    )
    if not payment:
        return {"ok": False, "reason": "payment_not_found", "provider_payment_id": provider_payment_id}

    response = YooKassaClient().get_payment(provider_payment_id)
    provider_status = str(response.get("status") or obj.get("status") or payment.get("status") or "pending")
    paid = bool(response.get("paid"))
    normalized_status = "paid" if paid or provider_status == "succeeded" else provider_status
    paid_at = _parse_yookassa_datetime(response.get("captured_at") or response.get("created_at")) if normalized_status == "paid" else None
    updated_payment = payments_repo.update_provider_status(
        conn,
        payment_id=payment["id"],
        status=normalized_status,
        raw_payload=response | {"webhook_event": event_type},
        paid_at=paid_at,
    ) or payment

    booking_ids: list[int] = []
    if normalized_status == "paid":
        if _is_superseded_payment(payment):
            booking_ids = []
        else:
            booking_ids = finalize_bookings_for_paid_payment(conn, updated_payment)
        if booking_ids:
            bookings_repo.update_payment_status_by_ids(
                conn,
                booking_ids=booking_ids,
                payment_status="paid",
            )
        create_missing_yclients_records(conn)
    elif normalized_status == "canceled":
        booking_ids = _booking_ids(updated_payment)
        if booking_ids:
            bookings_repo.update_payment_status_by_ids(
                conn,
                booking_ids=booking_ids,
                payment_status="payment_canceled",
            )
        else:
            _cancel_payment_holds(conn, updated_payment)

    if saved_event:
        webhook_events_repo.mark_processed(conn, event_id=saved_event["id"])
    return {
        "ok": True,
        "status": normalized_status,
        "provider_payment_id": provider_payment_id,
        "booking_ids": booking_ids,
        "is_new": True,
    }


def _cancel_payment_holds(conn: PgConnection, payment: dict[str, Any]) -> int:
    hold_ids = _hold_ids(payment)
    if not hold_ids:
        return 0
    raw = payment.get("raw_payload") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    canceled_at = raw.get("canceled_at") if isinstance(raw, dict) else None
    settings = get_settings()
    now = _parse_yookassa_datetime(canceled_at) or datetime.now(ZoneInfo(settings.app_timezone))
    return slot_holds_repo.cancel_ids(conn, hold_ids=hold_ids, now=now)


def _is_superseded_payment(payment: dict[str, Any]) -> bool:
    if str(payment.get("status") or "") == "superseded":
        return True
    raw = payment.get("raw_payload") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return False
    return str(raw.get("state") or "").startswith("superseded")


def _hold_ids(payment: dict[str, Any]) -> list[int]:
    raw = payment.get("raw_payload") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return []
    ids = raw.get("hold_ids")
    if isinstance(ids, list):
        return [int(item) for item in ids if str(item).isdigit()]
    metadata = raw.get("metadata") or {}
    if isinstance(metadata, dict):
        text = str(metadata.get("hold_ids") or "")
        return [int(item) for item in text.split(",") if item.strip().isdigit()]
    return []


def _booking_ids(payment: dict[str, Any]) -> list[int]:
    raw = payment.get("booking_ids") or []
    if isinstance(raw, list):
        return [int(item) for item in raw if str(item).isdigit()]
    if isinstance(raw, str):
        return [int(item) for item in raw.split(",") if item.strip().isdigit()]
    return []


def _parse_yookassa_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
