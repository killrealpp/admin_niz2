"""Print safe Telegram bot status."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from aiogram import Bot  # noqa: E402
from app.bot.telegram_session import create_ipv4_session  # noqa: E402
from app.core.config import get_settings  # noqa: E402


async def main() -> None:
    settings = get_settings()
    bot = Bot(settings.telegram_bot_token, session=create_ipv4_session())
    try:
        me = await bot.get_me()
        webhook = await bot.get_webhook_info()
        print(
            {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "webhook_url": webhook.url,
                "pending_update_count": webhook.pending_update_count,
            }
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
