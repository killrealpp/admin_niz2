"""Prepare YooKassa HTTP-notification webhook setup.

For the shopId/secret-key HTTP Basic Auth integration used by this app,
YooKassa webhooks are configured in the merchant dashboard, not through
the `/v3/webhooks` OAuth API. This script validates and prints the safe
dashboard setup plan.
"""

from __future__ import annotations

import argparse
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

DEFAULT_EVENTS = ("payment.succeeded", "payment.canceled")


def _parse_events(value: str) -> list[str]:
    events = [item.strip() for item in value.split(",") if item.strip()]
    if not events:
        raise SystemExit("At least one YooKassa webhook event is required")
    return events


def _validate_webhook_url(webhook_url: str, expected_path: str) -> None:
    parsed = urlparse(webhook_url)
    if parsed.scheme != "https":
        raise SystemExit("YOOKASSA_WEBHOOK_URL must use https")
    if not parsed.netloc:
        raise SystemExit("YOOKASSA_WEBHOOK_URL must include a host")
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise SystemExit("YOOKASSA_WEBHOOK_URL has an invalid port") from exc
    if explicit_port is not None:
        raise SystemExit("YOOKASSA_WEBHOOK_URL must use external 443 without an explicit port")
    if parsed.fragment:
        raise SystemExit("YOOKASSA_WEBHOOK_URL must not include a fragment")
    if parsed.path.rstrip("/") != expected_path.rstrip("/"):
        raise SystemExit(
            "YOOKASSA_WEBHOOK_URL path must match YOOKASSA_WEBHOOK_PATH "
            f"{expected_path!r}; current path is {parsed.path!r}"
        )


def _redact_url(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.query:
        return value
    return urlunparse(parsed._replace(query="[redacted]"))


def _print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and print the YooKassa HTTP-notification setup plan. "
            "For HTTP Basic Auth shops, configure these notifications in the YooKassa dashboard."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Unsupported for HTTP Basic Auth shops; kept as a guard against accidental API calls.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the safe plan without calling YooKassa API. This is the default.",
    )
    parser.add_argument("--url", default=None, help="Override YOOKASSA_WEBHOOK_URL.")
    parser.add_argument(
        "--events",
        default=",".join(DEFAULT_EVENTS),
        help="Comma-separated YooKassa webhook events to register.",
    )
    args = parser.parse_args()

    settings = get_settings()
    webhook_url = (args.url if args.url is not None else settings.yookassa_webhook_url).strip()
    if not webhook_url:
        raise SystemExit("YOOKASSA_WEBHOOK_URL is empty")
    _validate_webhook_url(webhook_url, settings.yookassa_webhook_path)

    events = _parse_events(args.events)
    plan = {
        "status": "dry_run" if not args.apply else "apply_requested",
        "provider": "yookassa",
        "events": events,
        "url": _redact_url(webhook_url),
        "calls_yookassa_api": False,
        "method": "manual_dashboard",
        "dashboard_section": "Интеграция -> HTTP-уведомления",
        "api_registration_supported": False,
        "payment_configured": bool(settings.payment_shop_id and settings.payment_secret_key),
        "webhook_enabled": bool(settings.yookassa_webhook_enabled),
        "webhook_secret_configured": bool(settings.yookassa_webhook_secret),
    }
    _print_payload(plan)

    if not args.apply:
        return
    raise SystemExit(
        "YooKassa webhook API registration requires OAuth and is not supported for "
        "the current shopId/secret-key HTTP Basic Auth integration. Configure "
        "HTTP notifications manually in the YooKassa dashboard."
    )


if __name__ == "__main__":
    main()
