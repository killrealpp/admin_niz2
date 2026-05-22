import asyncio
import logging

from app.bot.telegram_bot import run_bot
from app.core.config import get_settings
from app.core.logger import setup_logging


def main() -> None:
    setup_logging()
    settings = get_settings()
    logger = logging.getLogger(__name__)
    logger.info("Starting booking bot | %s", settings.safe_summary())
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
