"""Read-only YooKassa configuration and webhook status check."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    warnings: list[str] = []
    blockers: list[str] = []
    prepayment_mode = settings.prepayment_mode.strip().lower()
    public_like_env = settings.app_env.strip().lower() in {"prod", "production"}

    if prepayment_mode == "percent":
        effective_source = "PREPAYMENT_PERCENT"
        prepayment_note = "PREPAYMENT_AMOUNT_RUB is ignored while PREPAYMENT_MODE=percent"
        if settings.prepayment_percent <= 0 or settings.prepayment_percent > 100:
            blockers.append("invalid_prepayment_percent")
        if public_like_env and settings.prepayment_percent != 50:
            blockers.append("production_prepayment_percent_not_50")
    elif prepayment_mode == "fixed":
        effective_source = "PREPAYMENT_AMOUNT_RUB"
        prepayment_note = "Fixed amount applies to new payment links"
        if settings.prepayment_amount_rub <= 0:
            blockers.append("invalid_fixed_prepayment_amount")
        if public_like_env and settings.prepayment_amount_rub <= 1:
            blockers.append("production_fixed_one_ruble_prepayment")
    else:
        effective_source = "unknown"
        prepayment_note = "Unsupported PREPAYMENT_MODE"
        blockers.append("unsupported_prepayment_mode")

    if public_like_env and prepayment_mode != "percent":
        warnings.append("production_public_release_expected_percent_prepayment")
    if settings.payment_provider == "yookassa" and not configured:
        blockers.append("missing_yookassa_credentials")
    if settings.yookassa_webhook_enabled and not settings.yookassa_webhook_secret:
        blockers.append("missing_yookassa_webhook_secret")

    result: dict[str, Any] = {
        "app_env": settings.app_env,
        "payment_provider": settings.payment_provider,
        "payment_configured": configured,
        "prepayment_mode": settings.prepayment_mode,
        "prepayment_amount_rub": settings.prepayment_amount_rub,
        "prepayment_percent": settings.prepayment_percent,
        "prepayment_effective_source": effective_source,
        "prepayment_note": prepayment_note,
        "payment_status_sync_enabled": settings.payment_status_sync_enabled,
        "yookassa_webhook_enabled": settings.yookassa_webhook_enabled,
        "yookassa_webhook_path": settings.yookassa_webhook_path,
        "yookassa_webhook_url": _redact_url(settings.yookassa_webhook_url),
        "yookassa_webhook_secret_configured": bool(settings.yookassa_webhook_secret),
        "warnings": warnings,
        "local_config_blockers": blockers,
        "calls_yookassa_api": configured,
        "auth_check_path": "/payments?limit=1",
        "auth_check_timeout_seconds": 10.0,
        "auth_check_attempts": 1,
        "webhook_api_registration_supported": False,
        "webhook_setup": "manual_dashboard_http_notifications_for_basic_auth",
    }
    if not configured:
        result["status"] = "skipped"
        result["reason"] = "YooKassa credentials are not configured"
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if blockers:
            raise SystemExit(1)
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
            "status": "blocker" if blockers else "ok",
            "auth_ok": True,
            "payments_seen": len(payload.get("items") or []),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if blockers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
