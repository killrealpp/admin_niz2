"""Prepare or apply YooKassa webhook registration.

Default mode is dry-run and does not call YooKassa API. Use --apply manually
only after the public HTTPS endpoint and the local webhook runner are ready.
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

from app.core.config import get_settings  # noqa: E402
from app.integrations.yookassa_client import YooKassaClient  # noqa: E402


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
            "Dry-run or manually apply YooKassa webhook registration. "
            "Default mode does not call YooKassa API."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Actually call YooKassa API. Without this flag the script is dry-run only.",
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
        "calls_yookassa_api": bool(args.apply),
        "method": "POST",
        "path": "/webhooks",
        "payment_configured": bool(settings.payment_shop_id and settings.payment_secret_key),
        "webhook_enabled": bool(settings.yookassa_webhook_enabled),
        "webhook_secret_configured": bool(settings.yookassa_webhook_secret),
    }
    _print_payload(plan)

    if not args.apply:
        return
    if not settings.payment_shop_id or not settings.payment_secret_key:
        raise SystemExit("YooKassa credentials are not configured")

    client = YooKassaClient()
    results = []
    for event in events:
        response = client.create_webhook(event=event, url=webhook_url)
        results.append(
            {
                "event": event,
                "id": response.get("id"),
                "active": response.get("active"),
                "url": _redact_url(str(response.get("url") or "")),
            }
        )
    _print_payload({"status": "applied", "response": results})


if __name__ == "__main__":
    main()
