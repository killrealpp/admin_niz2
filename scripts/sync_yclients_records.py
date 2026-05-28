"""Sync YCLIENTS journal records into local busy-interval tables."""

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.logger import setup_logging  # noqa: E402
from app.integrations.yclients_client import YClientsError  # noqa: E402
from app.services.yclients_sync_service import sync_records_once  # noqa: E402

logger = logging.getLogger(__name__)


def run_once(days_back: int, days_forward: int) -> None:
    result = sync_records_once(
        days_back=days_back,
        days_forward=days_forward,
    )
    print(
        f"OK: seen={result.records_seen} upserted={result.records_upserted} "
        f"window=-{days_back}/+{days_forward} days"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=1)
    parser.add_argument("--days-forward", type=int, default=60)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--once", action="store_true", help="Run one sync and exit. Kept for explicitness; this is the default.")
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args()

    setup_logging()
    while True:
        try:
            run_once(args.days_back, args.days_forward)
        except YClientsError as exc:
            logger.warning("YCLIENTS sync failed: %s", exc)
        if not args.loop:
            break
        time.sleep(max(args.interval_seconds, 30))


if __name__ == "__main__":
    main()
