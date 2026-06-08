from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from app.bot.max_message_processor import MAX_TEXT_MVP_ERROR, process_max_update
from app.bot.max_router import max_update_type
from app.core.config import get_settings
from app.integrations.max_client import MaxApiClient, MaxApiError

POLL_TYPES = ("message_created", "bot_started")


class MaxLivePollingBlocked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MaxLivePollingOptions:
    marker: int | None = None
    limit: int = 10
    timeout: int = 20
    cycles: int = 0
    process_existing: bool = False
    send_media: bool = True
    skip_db_check: bool = False
    error_text: str = MAX_TEXT_MVP_ERROR


async def run_max_live_polling(
    *,
    marker: int | None = None,
    limit: int = 10,
    timeout: int = 20,
    cycles: int = 0,
    process_existing: bool = False,
    send_media: bool = True,
    skip_db_check: bool = False,
    error_text: str = MAX_TEXT_MVP_ERROR,
    emit: Callable[[dict[str, Any]], None] | None = None,
    stop_event: asyncio.Event | None = None,
) -> int:
    options = MaxLivePollingOptions(
        marker=marker,
        limit=limit,
        timeout=timeout,
        cycles=cycles,
        process_existing=process_existing,
        send_media=send_media,
        skip_db_check=skip_db_check,
        error_text=error_text,
    )
    return await _run(options, emit=emit, stop_event=stop_event)


async def _run(
    options: MaxLivePollingOptions,
    *,
    emit: Callable[[dict[str, Any]], None] | None,
    stop_event: asyncio.Event | None,
) -> int:
    settings = get_settings()
    client = MaxApiClient(timeout=max(20.0, float(options.timeout) + 10.0))
    if not settings.max_bot_token.strip():
        _emit(emit, {"status": "skipped", "reason": "MAX_BOT_TOKEN is not configured"})
        return 0

    me = await asyncio.to_thread(client.get_me)
    subscriptions = await asyncio.to_thread(client.get_subscriptions)
    ensure_max_live_polling_allowed(settings, subscriptions)
    if not options.skip_db_check:
        await asyncio.to_thread(check_db_ready)

    marker = options.marker
    if marker is None and not options.process_existing:
        payload = await asyncio.to_thread(
            client.get_updates,
            marker=None,
            limit=options.limit,
            timeout=0,
            types=POLL_TYPES,
        )
        skipped_updates = extract_updates(payload)
        marker = next_marker(payload, marker)
        _emit(
            emit,
            {
                "status": "ready",
                "mode": "live_polling",
                "bot": {
                    "user_id": me.get("user_id"),
                    "username": me.get("username"),
                    "is_bot": me.get("is_bot"),
                },
                "existing_updates_skipped": len(skipped_updates),
                "marker": marker,
                "send_media": bool(options.send_media),
            },
        )
    else:
        _emit(
            emit,
            {
                "status": "ready",
                "mode": "live_polling",
                "process_existing": bool(options.process_existing),
                "marker": marker,
                "send_media": bool(options.send_media),
            },
        )

    local_stop_event = stop_event or asyncio.Event()
    cycles_done = 0
    while not local_stop_event.is_set():
        if options.cycles > 0 and cycles_done >= options.cycles:
            break
        cycles_done += 1
        payload = await asyncio.to_thread(
            client.get_updates,
            marker=marker,
            limit=options.limit,
            timeout=options.timeout,
            types=POLL_TYPES,
        )
        marker = next_marker(payload, marker)
        updates = extract_updates(payload)
        processed = 0
        skipped = 0
        update_types: list[str] = []
        for update in updates:
            update_type = max_update_type(update)
            update_types.append(update_type)
            if update_type not in POLL_TYPES:
                skipped += 1
                continue
            ok = await process_max_update(
                update,
                error_text=options.error_text,
                send_related_media=options.send_media,
                log_context="max live polling",
            )
            if ok:
                processed += 1
            else:
                skipped += 1
        _emit(
            emit,
            {
                "status": "cycle",
                "cycle": cycles_done,
                "updates_count": len(updates),
                "processed_count": processed,
                "skipped_count": skipped,
                "update_types": update_types,
                "marker": marker,
            },
        )
    _emit(emit, {"status": "stopped", "marker": marker})
    return 0


def ensure_max_live_polling_allowed(settings: Any, subscriptions: dict[str, Any]) -> None:
    app_env = settings.app_env.strip().lower()
    if app_env in {"production", "prod"}:
        raise MaxLivePollingBlocked("MAX live polling is forbidden when APP_ENV=production")
    if settings.max_webhook_enabled:
        raise MaxLivePollingBlocked("MAX live polling is forbidden when MAX_WEBHOOK_ENABLED=true")
    if settings.max_mode.strip().lower() != "polling":
        raise MaxLivePollingBlocked("MAX live polling requires MAX_MODE=polling")
    if subscription_items(subscriptions):
        raise MaxLivePollingBlocked(
            "MAX bot has webhook subscriptions; disable webhook before polling"
        )


def check_db_ready() -> None:
    settings = get_settings()
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        sslmode=settings.db_sslmode,
        sslrootcert=str(Path(settings.db_sslrootcert).expanduser()),
        target_session_attrs=settings.db_target_session_attrs,
        connect_timeout=max(1, min(5, int(settings.db_connect_timeout))),
        cursor_factory=RealDictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
    finally:
        conn.close()


def extract_updates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    updates = payload.get("updates")
    if isinstance(updates, list):
        return [item for item in updates if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("updates"), list):
        return [item for item in data["updates"] if isinstance(item, dict)]
    return []


def next_marker(payload: dict[str, Any], current: int | None) -> int | None:
    value = payload.get("marker")
    if value is None:
        data = payload.get("data")
        if isinstance(data, dict):
            value = data.get("marker")
    if value is None:
        return current
    try:
        return int(value)
    except (TypeError, ValueError):
        return current


def subscription_items(payload: dict[str, Any]) -> list[Any]:
    subscriptions = payload.get("subscriptions")
    if isinstance(subscriptions, list):
        return subscriptions
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("subscriptions"), list):
        return data["subscriptions"]
    return []


def _emit(emit: Callable[[dict[str, Any]], None] | None, event: dict[str, Any]) -> None:
    if emit is not None:
        emit(event)


__all__ = [
    "MaxLivePollingBlocked",
    "MaxLivePollingOptions",
    "check_db_ready",
    "ensure_max_live_polling_allowed",
    "extract_updates",
    "next_marker",
    "run_max_live_polling",
    "subscription_items",
]
