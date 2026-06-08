"""Run a dev-only live MAX polling loop and send replies to MAX.

This script is intentionally operator-facing: no webhook registration, no
production mode, no polling when a webhook subscription exists.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ERROR_TEXT = "MAX message processing failed. Try again later."


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dev-only live MAX polling runner. It reads MAX updates and sends "
            "real MAX replies through MaxChannelClient."
        )
    )
    parser.add_argument("--marker", type=int, default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Number of polling cycles to run. 0 means run until Ctrl+C.",
    )
    parser.add_argument(
        "--process-existing",
        action="store_true",
        help="Process already queued MAX updates instead of skipping the current backlog.",
    )
    parser.add_argument(
        "--send-media",
        action="store_true",
        help="Allow related media upload/send during local MAX testing.",
    )
    parser.add_argument(
        "--allow-real-payments",
        action="store_true",
        help=(
            "Do not disable PAYMENT_PROVIDER in this process. Without this flag "
            "YooKassa payment creation is blocked for safer local tests."
        ),
    )
    parser.add_argument(
        "--skip-db-check",
        action="store_true",
        help="Skip startup DB SELECT 1 preflight. Not recommended.",
    )
    return parser.parse_args()


def _apply_local_safety_overrides(args: argparse.Namespace) -> None:
    if args.allow_real_payments:
        return
    os.environ["PAYMENT_PROVIDER"] = "disabled"
    os.environ["PAYMENT_STATUS_SYNC_ENABLED"] = "false"
    os.environ["YOOKASSA_WEBHOOK_ENABLED"] = "false"


async def _run(args: argparse.Namespace) -> int:
    from app.bot.max_live_polling import MaxLivePollingBlocked, run_max_live_polling
    from app.integrations.max_client import MaxApiError

    stop_event = asyncio.Event()

    def _stop() -> None:
        stop_event.set()

    try:
        with _install_signal_handler(signal.SIGINT, _stop):
            return await run_max_live_polling(
                marker=args.marker,
                limit=args.limit,
                timeout=args.timeout,
                cycles=args.cycles,
                process_existing=bool(args.process_existing),
                send_media=bool(args.send_media),
                skip_db_check=bool(args.skip_db_check),
                error_text=ERROR_TEXT,
                emit=lambda event: print(event, flush=True),
                stop_event=stop_event,
            )
    except (MaxApiError, MaxLivePollingBlocked) as exc:
        print({"status": "blocker", "reason": str(exc)})
        return 1
    except Exception as exc:
        print(
            {
                "status": "blocker",
                "reason": "MAX live polling preflight failed",
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }
        )
        return 1


class _install_signal_handler:
    def __init__(self, sig: signal.Signals, callback: Any) -> None:
        self._sig = sig
        self._callback = callback
        self._previous: Any = None

    def __enter__(self) -> None:
        self._previous = signal.getsignal(self._sig)
        signal.signal(self._sig, lambda *_args: self._callback())

    def __exit__(self, *_exc: Any) -> None:
        signal.signal(self._sig, self._previous)


def main() -> None:
    args = _parse_args()
    _apply_local_safety_overrides(args)
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
