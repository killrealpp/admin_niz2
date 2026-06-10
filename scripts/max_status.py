"""Print safe MAX bot status."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.core.config import get_settings  # noqa: E402
from app.integrations.max_client import MaxApiClient, MaxApiError  # noqa: E402


def _safe_me(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": payload.get("user_id"),
        "name": payload.get("name"),
        "username": payload.get("username"),
        "is_bot": payload.get("is_bot"),
        "last_activity_time": payload.get("last_activity_time"),
    }


def _subscription_items(payload: dict[str, Any]) -> list[Any]:
    subscriptions = payload.get("subscriptions")
    if isinstance(subscriptions, list):
        return subscriptions
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("subscriptions"), list):
        return data["subscriptions"]
    return []


def _safe_subscription(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"raw_type": type(item).__name__}
    return {
        "url": item.get("url") or item.get("webhook_url"),
        "update_types": item.get("update_types") or item.get("events"),
        "created_at": item.get("created_at") or item.get("created_time"),
        "enabled": item.get("enabled") if "enabled" in item else item.get("active"),
    }


def main() -> None:
    settings = get_settings()
    if not settings.max_bot_token.strip():
        print(
            {
                "status": "skipped",
                "reason": "MAX_BOT_TOKEN is not configured",
                "base_url": settings.max_api_base_url,
                "max_configured": False,
            }
        )
        return

    client = MaxApiClient()
    try:
        me = client.get_me()
        subscriptions = client.get_subscriptions()
    except MaxApiError as exc:
        print(
            {
                "status": "blocker",
                "reason": str(exc),
                "base_url": settings.max_api_base_url,
                "max_configured": True,
            }
        )
        raise SystemExit(1) from exc

    subscription_items = _subscription_items(subscriptions)
    print(
        {
            "status": "ok",
            "base_url": settings.max_api_base_url,
            "max_configured": True,
            "me": _safe_me(me),
            "subscriptions_count": len(subscription_items),
            "subscriptions": [
                _safe_subscription(item) for item in subscription_items
            ],
        }
    )


if __name__ == "__main__":
    main()
