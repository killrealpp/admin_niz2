"""Safe release readiness report for best2.

The script only reads configuration/status. It does not create payments,
register webhooks, mutate MAX subscriptions, or write runtime data.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.core.config import get_settings  # noqa: E402


def _trim(value: str, *, max_chars: int = 5000) -> str:
    value = value.strip()
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def _run_check(
    name: str,
    args: list[str],
    *,
    timeout_seconds: int = 90,
    required: bool = True,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "required": required,
            "ok": False,
            "exit_code": None,
            "timeout": True,
            "command": [Path(sys.executable).name, *args],
            "stdout": _trim(exc.stdout or ""),
            "stderr": _trim(exc.stderr or ""),
        }

    return {
        "name": name,
        "required": required,
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "timeout": False,
        "command": [Path(sys.executable).name, *args],
        "stdout": _trim(completed.stdout),
        "stderr": _trim(completed.stderr),
    }


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _env_report(*, allow_fixed_test_prepayment: bool) -> dict[str, Any]:
    settings = get_settings()
    channels = [
        channel.strip().lower()
        for channel in settings.client_channels.split(",")
        if channel.strip()
    ]
    app_env = settings.app_env.strip().lower()
    prepayment_mode = settings.prepayment_mode.strip().lower()
    payment_provider = settings.payment_provider.strip().lower()
    blockers: list[str] = []
    warnings: list[str] = []

    if app_env not in {"production", "prod"}:
        blockers.append("app_env_not_production")
    if "telegram" not in channels:
        blockers.append("telegram_channel_disabled")
    if "max" not in channels:
        warnings.append("max_channel_not_enabled")

    if not settings.telegram_bot_token:
        blockers.append("missing_telegram_bot_token")

    if "max" in channels:
        if not settings.max_bot_token:
            blockers.append("missing_max_bot_token")
        if settings.max_mode != "webhook":
            blockers.append("max_mode_not_webhook")
        if not settings.max_webhook_enabled:
            blockers.append("max_webhook_disabled")
        if not _is_https_url(settings.max_webhook_url):
            blockers.append("invalid_max_webhook_url")
        if not settings.max_webhook_secret:
            blockers.append("missing_max_webhook_secret")

    if not settings.yclients_partner_token or not settings.yclients_user_token or not settings.yclients_company_id:
        blockers.append("missing_yclients_credentials")
    if not settings.yclients_sync_enabled:
        blockers.append("yclients_sync_disabled")

    if payment_provider != "yookassa":
        blockers.append("payment_provider_not_yookassa")
    else:
        if not settings.payment_shop_id or not settings.payment_secret_key:
            blockers.append("missing_yookassa_credentials")
        if not settings.payment_status_sync_enabled:
            blockers.append("payment_status_sync_disabled")
        if not settings.yookassa_webhook_enabled:
            blockers.append("yookassa_webhook_disabled")
        if not _is_https_url(settings.yookassa_webhook_url):
            blockers.append("invalid_yookassa_webhook_url")
        if not settings.yookassa_webhook_secret:
            blockers.append("missing_yookassa_webhook_secret")

    if prepayment_mode == "percent":
        prepayment_effective_source = "PREPAYMENT_PERCENT"
        if settings.prepayment_percent != 50:
            blockers.append("prepayment_percent_not_50")
    elif prepayment_mode == "fixed":
        prepayment_effective_source = "PREPAYMENT_AMOUNT_RUB"
        if settings.prepayment_amount_rub <= 0:
            blockers.append("invalid_fixed_prepayment_amount")
        if settings.prepayment_amount_rub <= 1 and not allow_fixed_test_prepayment:
            blockers.append("fixed_one_ruble_prepayment_requires_explicit_test_flag")
        warnings.append("fixed_prepayment_is_for_controlled_tests_not_public_release")
    else:
        prepayment_effective_source = "unknown"
        blockers.append("unsupported_prepayment_mode")

    if settings.db_pool_max > 5:
        warnings.append("db_pool_max_above_default_check_db_limits")
    if settings.yclients_sync_interval_seconds > 300:
        warnings.append("yclients_sync_interval_over_5_minutes")

    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "summary": {
            "app_env": settings.app_env,
            "client_channels": settings.client_channels,
            "db_host": settings.db_host,
            "db_pool_enabled": settings.db_pool_enabled,
            "db_pool_max": settings.db_pool_max,
            "telegram_configured": bool(settings.telegram_bot_token),
            "max_configured": bool(settings.max_bot_token),
            "max_mode": settings.max_mode,
            "max_webhook_enabled": settings.max_webhook_enabled,
            "payment_provider": settings.payment_provider,
            "payment_configured": bool(settings.payment_shop_id and settings.payment_secret_key),
            "prepayment_mode": settings.prepayment_mode,
            "prepayment_effective_source": prepayment_effective_source,
            "prepayment_amount_rub": settings.prepayment_amount_rub,
            "prepayment_percent": settings.prepayment_percent,
            "yookassa_webhook_enabled": settings.yookassa_webhook_enabled,
            "yookassa_webhook_secret_configured": bool(settings.yookassa_webhook_secret),
            "yclients_sync_enabled": settings.yclients_sync_enabled,
            "yclients_sync_interval_seconds": settings.yclients_sync_interval_seconds,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run safe best2 release readiness checks.")
    parser.add_argument("--limit", type=int, default=5, help="Rows per live-health detail section.")
    parser.add_argument(
        "--skip-yookassa-api",
        action="store_true",
        help="Skip the read-only YooKassa API auth check.",
    )
    parser.add_argument(
        "--allow-fixed-test-prepayment",
        action="store_true",
        help="Allow PREPAYMENT_MODE=fixed with a small amount for a controlled payment test.",
    )
    args = parser.parse_args()

    env = _env_report(allow_fixed_test_prepayment=args.allow_fixed_test_prepayment)
    settings = get_settings()
    checks = [
        _run_check("db_status", ["scripts/db_status.py"], timeout_seconds=60),
        _run_check("yclients_sync_status", ["scripts/yclients_sync_status.py", "--strict"], timeout_seconds=60),
        _run_check("telegram_status", ["scripts/telegram_status.py"], timeout_seconds=60),
        _run_check("live_health_report", ["scripts/live_health_report.py", "--limit", str(max(1, args.limit))], timeout_seconds=90),
        _run_check("live_db_hygiene_audit", ["scripts/live_db_hygiene_audit.py", "--limit", str(max(1, args.limit))], timeout_seconds=90),
    ]

    channels = {channel.strip().lower() for channel in settings.client_channels.split(",")}
    if "max" in channels or settings.max_bot_token:
        checks.append(_run_check("max_status", ["scripts/max_status.py"], timeout_seconds=60))

    if settings.payment_provider.strip().lower() == "yookassa":
        checks.append(
            _run_check(
                "register_yookassa_webhook_dry_run",
                ["scripts/register_yookassa_webhook.py", "--dry-run"],
                timeout_seconds=30,
                required=False,
            )
        )
        if not args.skip_yookassa_api:
            checks.append(_run_check("yookassa_status", ["scripts/yookassa_status.py"], timeout_seconds=45))

    failed_required = [
        check["name"]
        for check in checks
        if check["required"] and not check["ok"]
    ]
    report = {
        "status": "blocker" if env["blockers"] or failed_required else "ok",
        "env": env,
        "failed_required_checks": failed_required,
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
