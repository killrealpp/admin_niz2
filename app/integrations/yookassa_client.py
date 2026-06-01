from __future__ import annotations

from decimal import Decimal
import re
import time
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import get_settings


class YooKassaError(RuntimeError):
    pass


class YooKassaClient:
    BASE_URL = "https://api.yookassa.ru/v3"

    def __init__(self) -> None:
        settings = get_settings()
        self.shop_id = settings.payment_shop_id
        self.secret_key = settings.payment_secret_key
        self.return_url = settings.payment_success_url or "https://t.me/fnsmvsvmpvpovbot"
        self.http_trust_env = settings.http_trust_env
        if not self.shop_id or not self.secret_key:
            raise YooKassaError("YooKassa credentials are not configured")

    def create_payment(
        self,
        *,
        amount: Decimal,
        description: str,
        metadata: dict[str, Any],
        customer_phone: str | None = None,
        idempotence_key: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB",
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": self.return_url,
            },
            "description": description[:128],
            "metadata": metadata,
        }
        if customer_phone:
            digits = re.sub(r"\D", "", customer_phone)
            if digits.startswith("9") and len(digits) == 10:
                digits = "7" + digits
            if digits.startswith("8") and len(digits) == 11:
                digits = "7" + digits[1:]
            if not (digits.startswith("7") and len(digits) == 11):
                raise YooKassaError("Invalid customer phone for YooKassa receipt")
            payload["receipt"] = {
                "customer": {"phone": digits},
                "items": [
                    {
                        "description": description[:128],
                        "quantity": "1.00",
                        "amount": {
                            "value": f"{amount:.2f}",
                            "currency": "RUB",
                        },
                        "vat_code": 1,
                        "payment_subject": "service",
                        "payment_mode": "partial_prepayment",
                    }
                ],
            }
        headers = {"Idempotence-Key": idempotence_key or str(uuid4())}
        response = self._request_with_retry(
            "POST",
            "/payments",
            json=payload,
            headers=headers,
        )
        return response

    def _request_with_retry(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        attempts = 3
        last_error: httpx.HTTPError | None = None
        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(timeout=30, trust_env=self.http_trust_env) as client:
                    response = client.request(
                        method,
                        f"{self.BASE_URL}{path}",
                        auth=(self.shop_id, self.secret_key),
                        **kwargs,
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise YooKassaError(f"YooKassa request failed: {exc}") from exc
                time.sleep(0.8 * attempt)
                continue
            except httpx.HTTPError as exc:
                raise YooKassaError(f"YooKassa request failed: {exc}") from exc
            if response.status_code >= 400:
                raise YooKassaError(f"YooKassa error {response.status_code}: {response.text}")
            if not response.text.strip():
                return {}
            return response.json()
        raise YooKassaError(f"YooKassa request failed: {last_error}")

    def get_payment(self, provider_payment_id: str) -> dict[str, Any]:
        return self._request_with_retry("GET", f"/payments/{provider_payment_id}")

    def create_webhook(self, *, event: str, url: str) -> dict[str, Any]:
        return self._request_with_retry(
            "POST",
            "/webhooks",
            json={"event": event, "url": url},
            headers={"Idempotence-Key": str(uuid4())},
        )

    def list_webhooks(self) -> dict[str, Any]:
        return self._request_with_retry("GET", "/webhooks")

    def delete_webhook(self, webhook_id: str) -> dict[str, Any]:
        return self._request_with_retry("DELETE", f"/webhooks/{webhook_id}")
