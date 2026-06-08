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


def _webhook_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "id": item.get("id"),
                "event": item.get("event"),
                "active": item.get("active"),
                "url": _redact_url(str(item.get("url") or "")),
            }
        )
    return items


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
    }
    if not configured:
        result["status"] = "skipped"
        result["reason"] = "YooKassa credentials are not configured"
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    try:
        payload = YooKassaClient().list_webhooks()
    except YooKassaError as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit(1) from exc

    items = _webhook_items(payload)
    result.update(
        {
            "status": "ok",
            "webhooks_count": len(items),
            "webhooks": items,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
