"""Prepare or apply MAX webhook subscription changes.

Default mode is dry-run and does not call MAX API. Use --apply manually only
after the public HTTPS endpoint and the internal MAX webhook runner are ready.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402


DEFAULT_UPDATE_TYPES = ("message_created", "bot_started")
SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{5,256}$")


def _parse_update_types(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise SystemExit("At least one MAX update type is required")
    return items


def _validate_webhook_url(webhook_url: str, expected_path: str) -> None:
    parsed = urlparse(webhook_url)
    if parsed.scheme != "https":
        raise SystemExit("MAX_WEBHOOK_URL must use https")
    if not parsed.netloc:
        raise SystemExit("MAX_WEBHOOK_URL must include a host")
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise SystemExit("MAX_WEBHOOK_URL has an invalid port") from exc
    if explicit_port is not None:
        raise SystemExit("MAX_WEBHOOK_URL must use external 443 without an explicit port")
    if parsed.query or parsed.fragment:
        raise SystemExit("MAX_WEBHOOK_URL must not include query or fragment")
    if parsed.path.rstrip("/") != expected_path.rstrip("/"):
        raise SystemExit(
            "MAX_WEBHOOK_URL path must match MAX_WEBHOOK_PATH "
            f"{expected_path!r}; current path is {parsed.path!r}"
        )


def _validate_secret(secret: str) -> None:
    if not SECRET_PATTERN.fullmatch(secret):
        raise SystemExit(
            "MAX_WEBHOOK_SECRET must be 5-256 characters and contain only "
            "A-Z, a-z, 0-9, underscore or hyphen"
        )


def _json_response(response: httpx.Response) -> Any:
    if not response.text.strip():
        return {}
    try:
        return response.json()
    except ValueError:
        return {"text": response.text[:500]}


def _safe_error_text(response: httpx.Response, token: str) -> str:
    text = response.text[:500]
    if token:
        text = text.replace(token, "[redacted]")
    return text


def _print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _call_max_subscription_api(
    *,
    action: str,
    base_url: str,
    token: str,
    webhook_url: str,
    update_types: list[str],
    secret: str,
    timeout: float,
    trust_env: bool,
) -> Any:
    api_url = f"{base_url.rstrip('/')}/subscriptions"
    headers = {
        "Accept": "application/json",
        "Authorization": token,
    }
    with httpx.Client(timeout=timeout, trust_env=trust_env) as client:
        if action == "unsubscribe":
            response = client.request(
                "DELETE",
                api_url,
                headers=headers,
                params={"url": webhook_url},
            )
        else:
            response = client.request(
                "POST",
                api_url,
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "url": webhook_url,
                    "update_types": update_types,
                    "secret": secret,
                },
            )
    if response.status_code >= 400:
        raise SystemExit(
            f"MAX API returned HTTP {response.status_code}: "
            f"{_safe_error_text(response, token)}"
        )
    return _json_response(response)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or manually apply MAX webhook subscription registration. "
            "Default mode does not call MAX API."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Actually call MAX API. Without this flag the script is dry-run only.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the safe plan without calling MAX API. This is the default.",
    )
    parser.add_argument(
        "--unsubscribe",
        action="store_true",
        help="Use DELETE /subscriptions?url=... instead of POST /subscriptions.",
    )
    parser.add_argument("--url", default=None, help="Override MAX_WEBHOOK_URL.")
    parser.add_argument("--secret", default=None, help="Override MAX_WEBHOOK_SECRET.")
    parser.add_argument(
        "--types",
        default=",".join(DEFAULT_UPDATE_TYPES),
        help="Comma-separated update types for POST /subscriptions.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    settings = get_settings()
    webhook_url = (args.url if args.url is not None else settings.max_webhook_url).strip()
    secret = (args.secret if args.secret is not None else settings.max_webhook_secret).strip()
    if not webhook_url:
        raise SystemExit("MAX_WEBHOOK_URL is empty")

    _validate_webhook_url(webhook_url, settings.max_webhook_path)

    action = "unsubscribe" if args.unsubscribe else "register"
    update_types = _parse_update_types(args.types)
    if action == "register":
        _validate_secret(secret)

    token = settings.max_bot_token.strip()
    plan = {
        "status": "dry_run" if not args.apply else "apply_requested",
        "action": action,
        "base_url": settings.max_api_base_url,
        "token_configured": bool(token),
        "url": webhook_url,
        "update_types": update_types if action == "register" else None,
        "secret_configured": bool(secret) if action == "register" else None,
        "calls_max_api": bool(args.apply),
        "method": "DELETE" if action == "unsubscribe" else "POST",
        "path": "/subscriptions",
    }
    _print_payload(plan)

    if not args.apply:
        return
    if not token:
        raise SystemExit("MAX_BOT_TOKEN is not configured")

    result = _call_max_subscription_api(
        action=action,
        base_url=settings.max_api_base_url,
        token=token,
        webhook_url=webhook_url,
        update_types=update_types,
        secret=secret,
        timeout=args.timeout,
        trust_env=bool(settings.http_trust_env),
    )
    _print_payload({"status": "applied", "action": action, "response": result})


if __name__ == "__main__":
    main()
