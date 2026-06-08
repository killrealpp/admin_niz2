"""Smoke-check local client runtime channel selection without live bot calls."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bot.runtime import parse_client_channels, run_client_channels  # noqa: E402
from app.core.config import get_settings  # noqa: E402


async def assert_dual_channel_runners_start() -> None:
    original = _save_env(
        "CLIENT_CHANNELS",
        "MAX_MODE",
        "MAX_WEBHOOK_ENABLED",
        "MAX_BOT_TOKEN",
    )
    calls: list[str] = []
    ready = asyncio.Event()
    stop = asyncio.Event()

    async def telegram_runner() -> None:
        calls.append("telegram")
        if len(calls) == 2:
            ready.set()
        await stop.wait()

    async def max_runner() -> None:
        calls.append("max")
        if len(calls) == 2:
            ready.set()
        await stop.wait()

    try:
        os.environ["CLIENT_CHANNELS"] = "telegram,max"
        os.environ["MAX_MODE"] = "polling"
        os.environ["MAX_WEBHOOK_ENABLED"] = "false"
        os.environ["MAX_BOT_TOKEN"] = "fake-token"
        get_settings.cache_clear()
        task = asyncio.create_task(
            run_client_channels(
                telegram_runner=telegram_runner,
                max_runner=max_runner,
                manage_background_services=False,
            )
        )
        await asyncio.wait_for(ready.wait(), timeout=1)
        stop.set()
        try:
            await task
        except RuntimeError as exc:
            assert "Client channel stopped unexpectedly" in str(exc)
        else:
            raise AssertionError("Dual-channel runtime must fail if a channel exits")
    finally:
        _restore_env(original)
        get_settings.cache_clear()

    assert calls == ["telegram", "max"]


async def assert_dual_channel_exits_fail_fast() -> None:
    original = _save_env(
        "CLIENT_CHANNELS",
        "MAX_MODE",
        "MAX_WEBHOOK_ENABLED",
        "MAX_BOT_TOKEN",
    )
    stop = asyncio.Event()
    cancelled: list[str] = []

    async def telegram_runner() -> None:
        return None

    async def max_runner() -> None:
        try:
            await stop.wait()
        finally:
            cancelled.append("max")

    try:
        os.environ["CLIENT_CHANNELS"] = "telegram,max"
        os.environ["MAX_MODE"] = "polling"
        os.environ["MAX_WEBHOOK_ENABLED"] = "false"
        os.environ["MAX_BOT_TOKEN"] = "fake-token"
        get_settings.cache_clear()
        try:
            await run_client_channels(
                telegram_runner=telegram_runner,
                max_runner=max_runner,
                manage_background_services=False,
            )
        except RuntimeError as exc:
            assert "telegram" in str(exc)
        else:
            raise AssertionError("Dual-channel runtime must fail when one channel exits")
    finally:
        stop.set()
        _restore_env(original)
        get_settings.cache_clear()

    assert cancelled == ["max"]


async def assert_unsafe_max_runtime_blocks() -> None:
    original = _save_env(
        "CLIENT_CHANNELS",
        "MAX_MODE",
        "MAX_WEBHOOK_ENABLED",
        "MAX_BOT_TOKEN",
    )
    try:
        os.environ["CLIENT_CHANNELS"] = "telegram,max"
        os.environ["MAX_MODE"] = "webhook"
        os.environ["MAX_WEBHOOK_ENABLED"] = "false"
        os.environ["MAX_BOT_TOKEN"] = "fake-token"
        get_settings.cache_clear()
        try:
            await run_client_channels(
                telegram_runner=_noop_runner,
                max_runner=_noop_runner,
                manage_background_services=False,
            )
        except RuntimeError as exc:
            assert "MAX_WEBHOOK_ENABLED=true" in str(exc)
        else:
            raise AssertionError("Unsafe MAX webhook config must block runtime")
    finally:
        _restore_env(original)
        get_settings.cache_clear()


async def assert_webhook_max_runtime_can_start() -> None:
    original = _save_env(
        "CLIENT_CHANNELS",
        "MAX_MODE",
        "MAX_WEBHOOK_ENABLED",
        "MAX_WEBHOOK_SECRET",
        "MAX_BOT_TOKEN",
    )
    calls: list[str] = []

    async def max_runner() -> None:
        calls.append("max-webhook")

    try:
        os.environ["CLIENT_CHANNELS"] = "max"
        os.environ["MAX_MODE"] = "webhook"
        os.environ["MAX_WEBHOOK_ENABLED"] = "true"
        os.environ["MAX_WEBHOOK_SECRET"] = "secret"
        os.environ["MAX_BOT_TOKEN"] = "fake-token"
        get_settings.cache_clear()
        await run_client_channels(
            max_runner=max_runner,
            manage_background_services=False,
        )
    finally:
        _restore_env(original)
        get_settings.cache_clear()

    assert calls == ["max-webhook"]


async def _noop_runner() -> None:
    return None


def _save_env(*keys: str) -> dict[str, str | None]:
    return {key: os.environ.get(key) for key in keys}


def _restore_env(values: dict[str, str | None]) -> None:
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def main() -> None:
    assert parse_client_channels(" telegram, max ,, ") == {"telegram", "max"}
    asyncio.run(assert_dual_channel_runners_start())
    asyncio.run(assert_dual_channel_exits_fail_fast())
    asyncio.run(assert_unsafe_max_runtime_blocks())
    asyncio.run(assert_webhook_max_runtime_can_start())
    print("max_runtime_smoke=ok")


if __name__ == "__main__":
    main()
