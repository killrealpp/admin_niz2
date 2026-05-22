from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.integrations.yookassa_client import YooKassaClient


def main() -> None:
    response = YooKassaClient().create_payment(
        amount=Decimal("1.00"),
        description="Тестовая ссылка оплаты Booking Bot",
        metadata={"source": "booking_bot_smoke"},
        customer_phone="+79099667655",
        idempotence_key=f"booking-bot-smoke-1-rub-{uuid4()}",
    )
    confirmation = response.get("confirmation") or {}
    print("id:", response.get("id"))
    print("status:", response.get("status"))
    print("paid:", response.get("paid"))
    print("confirmation_url:", confirmation.get("confirmation_url"))


if __name__ == "__main__":
    main()
