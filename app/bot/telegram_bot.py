import asyncio
import contextlib
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

from app.bot.router import normalize_telegram_message, normalize_telegram_voice_message
from app.bot.telegram_session import create_ipv4_session
from app.core.config import get_settings
from app.db.connection import get_connection
from app.services.media_service import media_for_client_message
from app.services.message_handler import handle_incoming
from app.services.message_retention_runner import run_message_retention_loop
from app.services.payment_status_runner import run_payment_status_loop
from app.services.voice_transcription_service import (
    VoiceTranscriptionError,
    transcribe_telegram_voice,
)
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
        await _send_related_media(message, incoming.text, reply)
    except Exception:
        logger.exception("Failed to handle message chat_id=%s", message.chat.id)
        await message.reply(
            "Произошла ошибка. Попробуйте ещё раз через минуту."
        )


async def on_voice(message: Message) -> None:
    settings = get_settings()
    if not settings.voice_transcription_enabled:
        await message.reply("Голосовые сообщения скоро подключим. Пока напишите, пожалуйста, текстом.")
        return
    try:
        logger.info(
            "Incoming Telegram voice chat_id=%s user_id=%s duration=%s",
            message.chat.id,
            message.from_user.id if message.from_user else None,
            message.voice.duration if message.voice else None,
        )
        transcription_task = asyncio.create_task(transcribe_telegram_voice(message.bot, message))
        typing_task = asyncio.create_task(_show_typing_until_done(message, transcription_task))
        try:
            transcribed_text = await transcription_task
        finally:
            typing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing_task

        incoming = normalize_telegram_voice_message(message, transcribed_text)
        processing_task = asyncio.create_task(asyncio.to_thread(handle_incoming, incoming))
        typing_task = asyncio.create_task(_show_typing_until_done(message, processing_task))
        try:
            reply = await processing_task
        finally:
            typing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing_task
        await message.reply(reply)
        await _send_related_media(message, incoming.text, reply)
    except VoiceTranscriptionError as exc:
        logger.warning("Voice transcription skipped chat_id=%s reason=%s", message.chat.id, exc)
        await message.reply("Не получилось разобрать голосовое. Напишите, пожалуйста, текстом.")
    except Exception:
        logger.exception("Failed to handle voice message chat_id=%s", message.chat.id)
        await message.reply("Не получилось обработать голосовое. Напишите, пожалуйста, текстом.")


async def _show_typing_until_done(message: Message, task: asyncio.Task) -> None:
    while not task.done():
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        )
        await asyncio.sleep(4)


async def _send_related_media(message: Message, text: str, reply: str) -> None:
    paths = media_for_client_message(text, reply)
    for path in paths:
        try:
            await message.answer_photo(FSInputFile(path))
        except Exception:
            logger.exception("Failed to send media path=%s chat_id=%s", path, message.chat.id)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.message.register(on_start, CommandStart())
    dp.message.register(on_status, Command("status"))
    dp.message.register(on_voice, F.voice)
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
    retention_task = asyncio.create_task(run_message_retention_loop())
    logger.info("Telegram polling started")
    try:
        await dp.start_polling(bot)
    finally:
        for task in (sync_task, payment_task, retention_task):
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
