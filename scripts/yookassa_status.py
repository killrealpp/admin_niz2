"""Read-only YooKassa configuration and webhook status check."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.integrations.yookassa_client import YooKassaClient, YooKassaError  # noqa: E402


def _redact_url(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.query:
        return value
    return urlunparse(parsed._replace(query="[redacted]"))


def main() -> None:
    settings = get_settings()
    configured = bool(settings.payment_shop_id and settings.payment_secret_key)
    result: dict[str, Any] = {
        "payment_provider": settings.payment_provider,
        "payment_configured": configured,
        "prepayment_mode": settings.prepayment_mode,
        "prepayment_amount_rub": settings.prepayment_amount_rub,
        "prepayment_percent": settings.prepayment_percent,
        "payment_status_sync_enabled": settings.payment_status_sync_enabled,
        "yookassa_webhook_enabled": settings.yookassa_webhook_enabled,
        "yookassa_webhook_path": settings.yookassa_webhook_path,
        "yookassa_webhook_url": _redact_url(settings.yookassa_webhook_url),
        "yookassa_webhook_secret_configured": bool(settings.yookassa_webhook_secret),
        "calls_yookassa_api": configured,
        "auth_check_path": "/payments?limit=1",
        "webhook_api_registration_supported": False,
        "webhook_setup": "manual_dashboard_http_notifications_for_basic_auth",
    }
    if not configured:
        result["status"] = "skipped"
        result["reason"] = "YooKassa credentials are not configured"
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    try:
        payload = YooKassaClient(timeout=10.0, attempts=1).list_payments(limit=1)
    except YooKassaError as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit(1) from exc

    result.update(
        {
            "status": "ok",
            "auth_ok": True,
            "payments_seen": len(payload.get("items") or []),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
