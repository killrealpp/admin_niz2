import asyncio
import logging

from aiogram import Bot

from app.core.config import get_settings
from app.services.availability_service import clear_availability_cache
from app.services.yclients_sync_service import sync_records_once
from app.services.waitlist_service import notify_waitlist_matches

logger = logging.getLogger(__name__)


async def run_yclients_sync_loop(bot: Bot | None = None) -> None:
    settings = get_settings()
    if not settings.yclients_sync_enabled:
        logger.info("YCLIENTS records sync disabled")
        return

    interval = max(settings.yclients_sync_interval_seconds, 5)
    logger.info("YCLIENTS records sync loop started interval=%s", interval)
    while True:
        try:
            result = await asyncio.to_thread(_sync_once)
            logger.info(
                "YCLIENTS records sync completed seen=%s upserted=%s",
                result.records_seen,
                result.records_upserted,
            )
            clear_availability_cache()
            if bot:
                await notify_waitlist_matches(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("YCLIENTS records sync failed")
        await asyncio.sleep(interval)


def _sync_once():
    settings = get_settings()
    return sync_records_once(
        days_back=settings.yclients_sync_days_back,
        days_forward=settings.yclients_sync_days_forward,
    )
