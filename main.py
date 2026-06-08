import logging

import asyncio

from app.bot.runtime import run_client_channels
from app.core.config import get_settings
from app.core.logger import setup_logging


def main() -> None:
    setup_logging()
    settings = get_settings()
    logger = logging.getLogger(__name__)
    logger.info("Starting booking bot | %s", settings.safe_summary())
    asyncio.run(run_client_channels())


if __name__ == "__main__":
    main()
