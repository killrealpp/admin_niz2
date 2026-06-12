from __future__ import annotations

from decimal import Decimal
import logging

from app.core.config import get_settings
from app.data.services import service_title
from app.dialog.state import BookingDraft
from app.integrations.yookassa import YooKassaClient


logger = logging.getLogger(__name__)


def create_prepayment(draft: BookingDraft, *, chat_id: str, booking_id: int) -> tuple[str, str]:
    amount = Decimal(str(get_settings().prepayment_amount_rub))
    description = f"Предоплата за {service_title(draft.service_type)}"
    logger.info(
        "Creating prepayment chat_id=%s booking_id=%s amount=%s service_type=%s variant=%s",
        chat_id,
        booking_id,
        amount,
        draft.service_type,
        draft.service_variant,
    )
    response = YooKassaClient().create_payment(
        amount=amount,
        description=description,
        metadata={"chat_id": chat_id, "booking_id": str(booking_id), "source": "admin_niz_mvp"},
        customer_phone=draft.phone,
    )
    payment_id = str(response.get("id") or "")
    url = ((response.get("confirmation") or {}).get("confirmation_url") or "")
    if not payment_id or not url:
        raise RuntimeError(f"YooKassa did not return payment link: {response}")
    logger.info("Prepayment created chat_id=%s booking_id=%s payment_id=%s", chat_id, booking_id, payment_id)
    return payment_id, url
