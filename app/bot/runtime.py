from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aiogram import Bot

from app.bot.telegram_bot import create_bot as create_telegram_bot
from app.bot.telegram_bot import run_bot as run_telegram_bot
from app.core.config import get_settings
from app.core.constants import CHANNEL_MAX, CHANNEL_TELEGRAM
from app.services.message_retention_runner import run_message_retention_loop
from app.services.payment_status_runner import run_payment_status_loop
from app.services.yookassa_webhook_runner import start_yookassa_webhook_server
from app.services.yclients_sync_runner import run_yclients_sync_loop

logger = logging.getLogger(__name__)

ChannelRunner = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class RuntimeBackgroundServices:
    bot: Bot | None
    tasks: tuple[asyncio.Task[Any], ...]
    servers: tuple[Any, ...]


async def run_client_channels(
    *,
    telegram_runner: ChannelRunner | None = None,
    max_runner: ChannelRunner | None = None,
    manage_background_services: bool = True,
) -> None:
    settings = get_settings()
    channels = parse_client_channels(settings.client_channels)
    if not channels:
        raise RuntimeError("CLIENT_CHANNELS must include at least one channel")

    unknown = channels - {CHANNEL_TELEGRAM, CHANNEL_MAX}
    if unknown:
        raise RuntimeError(f"Unsupported CLIENT_CHANNELS values: {', '.join(sorted(unknown))}")

    runtime_bot = create_telegram_bot() if _needs_runtime_telegram_bot(channels, manage_background_services) else None
    background = RuntimeBackgroundServices(bot=None, tasks=(), servers=())
    runners: list[tuple[str, ChannelRunner]] = []
    if CHANNEL_MAX in channels:
        _ensure_max_runtime_allowed(settings)

    try:
        if manage_background_services:
            background = _start_background_services(runtime_bot)

        if CHANNEL_TELEGRAM in channels:
            runners.append(
                (
                    CHANNEL_TELEGRAM,
                    telegram_runner or _telegram_runner(runtime_bot),
                )
            )
        if CHANNEL_MAX in channels:
            runners.append((CHANNEL_MAX, max_runner or _max_runner(settings)))

        if not runners:
            raise RuntimeError("No runnable client channels configured")

        await _run_channel_runners(runners)
    finally:
        await _stop_background_services(background)
        if runtime_bot is not None:
            await runtime_bot.session.close()


def parse_client_channels(value: str) -> set[str]:
    return {
        item.strip().lower()
        for item in str(value or "").split(",")
        if item.strip()
    }


def _ensure_max_runtime_allowed(settings: Any) -> None:
    if not settings.max_bot_token.strip():
        raise RuntimeError("CLIENT_CHANNELS includes max, but MAX_BOT_TOKEN is not configured")
    mode = settings.max_mode.strip().lower()
    if mode == "polling":
        if settings.max_webhook_enabled:
            raise RuntimeError("MAX polling runtime requires MAX_WEBHOOK_ENABLED=false")
        if settings.app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("MAX polling runtime is forbidden in production")
        return
    if mode == "webhook":
        if not settings.max_webhook_enabled:
            raise RuntimeError("MAX webhook runtime requires MAX_WEBHOOK_ENABLED=true")
        if not settings.max_webhook_secret.strip():
            raise RuntimeError("MAX webhook runtime requires MAX_WEBHOOK_SECRET")
        return
    raise RuntimeError("MAX runtime requires MAX_MODE=polling or MAX_MODE=webhook")


def _needs_runtime_telegram_bot(
    channels: set[str],
    manage_background_services: bool,
) -> bool:
    return CHANNEL_TELEGRAM in channels or manage_background_services


def _telegram_runner(bot: Bot | None) -> ChannelRunner:
    async def _run() -> None:
        await run_telegram_bot(
            bot=bot,
            manage_background_services=False,
            close_bot=False,
        )

    return _run


def _max_runner(settings: Any) -> ChannelRunner:
    if settings.max_mode.strip().lower() == "webhook":
        return _run_max_webhook_channel
    return _run_max_polling_channel


def _start_background_services(bot: Bot | None) -> RuntimeBackgroundServices:
    loop = asyncio.get_running_loop()
    yookassa_server = start_yookassa_webhook_server(bot=bot, loop=loop)
    tasks = (
        asyncio.create_task(run_yclients_sync_loop(bot), name="yclients-sync"),
        asyncio.create_task(run_payment_status_loop(bot), name="payment-status-sync"),
        asyncio.create_task(run_message_retention_loop(), name="message-retention"),
    )
    logger.info("Runtime background services started")
    servers = (yookassa_server,) if yookassa_server is not None else ()
    return RuntimeBackgroundServices(bot=bot, tasks=tasks, servers=servers)


async def _stop_background_services(background: RuntimeBackgroundServices) -> None:
    for task in background.tasks:
        task.cancel()
    for task in background.tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    for server in background.servers:
        await asyncio.to_thread(server.shutdown)
        await asyncio.to_thread(server.server_close)


async def _run_channel_runners(runners: list[tuple[str, ChannelRunner]]) -> None:
    if len(runners) == 1:
        logger.info("Starting client channel: %s", runners[0][0])
        await runners[0][1]()
        return

    logger.info("Starting client channels: %s", ",".join(name for name, _ in runners))
    tasks = [
        asyncio.create_task(runner(), name=f"{name}-channel")
        for name, runner in runners
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            channel_name = task.get_name().removesuffix("-channel")
            if task.cancelled():
                raise RuntimeError(f"Client channel stopped unexpectedly: {channel_name}")
            exc = task.exception()
            if exc is not None:
                logger.exception(
                    "Client channel failed: %s",
                    channel_name,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                raise exc
            raise RuntimeError(f"Client channel stopped unexpectedly: {channel_name}")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _run_max_polling_channel() -> None:
    from app.bot.max_live_polling import run_max_live_polling

    settings = get_settings()
    await run_max_live_polling(
        send_media=settings.max_send_related_media,
        emit=lambda event: logger.info("MAX polling event: %s", event),
    )


async def _run_max_webhook_channel() -> None:
    from app.bot.max_message_processor import make_max_webhook_event_processor
    from app.bot.max_webhook_runner import start_max_webhook_server

    server = start_max_webhook_server(
        event_processor=make_max_webhook_event_processor(),
    )
    if server is None:
        raise RuntimeError("MAX webhook channel is configured but server did not start")
    logger.info("MAX webhook channel started")
    try:
        await asyncio.Event().wait()
    finally:
        await asyncio.to_thread(server.shutdown)
        await asyncio.to_thread(server.server_close)


__all__ = [
    "parse_client_channels",
    "run_client_channels",
]
