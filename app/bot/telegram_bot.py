import asyncio
import contextlib
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.bot.router import normalize_telegram_message
from app.bot.telegram_session import create_ipv4_session
from app.core.config import get_settings
from app.db.connection import get_connection
from app.services.message_handler import handle_incoming
from app.services.payment_status_runner import run_payment_status_loop
from app.services.yookassa_webhook_runner import start_yookassa_webhook_server
from app.services.yclients_sync_runner import run_yclients_sync_loop

logger = logging.getLogger(__name__)


async def on_start(message: Message) -> None:
    logger.info(
        "Incoming Telegram /start chat_id=%s user_id=%s",
        message.chat.id,
        message.from_user.id if message.from_user else None,
    )
    await message.answer(
        "Здравствуйте! Я Любовь, помощник по бронированию беседок и отдыха на базе.\n"
        "Напишите, что хотите забронировать — например: «беседка на субботу, 15 человек»."
    )


async def on_status(message: Message) -> None:
    settings = get_settings()
    logger.info(
        "Incoming Telegram /status chat_id=%s user_id=%s",
        message.chat.id,
        message.from_user.id if message.from_user else None,
    )
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(1) AS total FROM messages")
                messages_count = cur.fetchone()["total"]
        db_status = f"DB OK, messages={messages_count}"
    except Exception as exc:
        logger.exception("Status DB check failed")
        db_status = f"DB ERROR: {type(exc).__name__}"

    await message.answer(
        "status: running\n"
        f"pid: {os.getpid()}\n"
        f"bot: @{(await message.bot.get_me()).username}\n"
        f"db: {settings.db_name}@{settings.db_host}\n"
        f"{db_status}"
    )


async def on_text(message: Message) -> None:
    try:
        logger.info(
            "Incoming Telegram message chat_id=%s user_id=%s text=%r",
            message.chat.id,
            message.from_user.id if message.from_user else None,
            (message.text or message.caption or "")[:200],
        )
        incoming = normalize_telegram_message(message)
        processing_task = asyncio.create_task(asyncio.to_thread(handle_incoming, incoming))
        typing_task = asyncio.create_task(_show_typing_until_done(message, processing_task))
        try:
            reply = await processing_task
        finally:
            typing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing_task
        await message.reply(reply)
    except Exception:
        logger.exception("Failed to handle message chat_id=%s", message.chat.id)
        await message.reply(
            "Произошла ошибка. Попробуйте ещё раз через минуту."
        )


async def _show_typing_until_done(message: Message, task: asyncio.Task) -> None:
    while not task.done():
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        )
        await asyncio.sleep(4)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.message.register(on_start, CommandStart())
    dp.message.register(on_status, Command("status"))
    dp.message.register(on_text, F.text | F.caption)
    return dp


async def run_polling() -> None:
    settings = get_settings()
    bot = Bot(
        token=settings.telegram_bot_token,
        session=create_ipv4_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()
    loop = asyncio.get_running_loop()
    yookassa_server = start_yookassa_webhook_server(bot=bot, loop=loop)
    sync_task = asyncio.create_task(run_yclients_sync_loop(bot))
    payment_task = asyncio.create_task(run_payment_status_loop(bot))
    logger.info("Telegram polling started")
    try:
        await dp.start_polling(bot)
    finally:
        for task in (sync_task, payment_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if yookassa_server:
            yookassa_server.shutdown()
            yookassa_server.server_close()
        await bot.session.close()


async def run_bot() -> None:
    settings = get_settings()
    if settings.telegram_webhook_url:
        raise NotImplementedError("Webhook mode is not implemented yet; use polling")
    await run_polling()
