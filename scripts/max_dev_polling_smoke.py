"""Run one safe dev-only MAX polling smoke without sending MAX replies."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bot.max_polling_runner import run_max_dev_polling_smoke  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poll MAX once and dry-run a text update through process_client_message()."
    )
    parser.add_argument("--marker", type=int, default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=5)
    args = parser.parse_args()

    result = asyncio.run(
        run_max_dev_polling_smoke(
            marker=args.marker,
            limit=args.limit,
            timeout=args.timeout,
        )
    )
    print(result)
    if result.get("status") == "blocker":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
