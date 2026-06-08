import asyncio
import contextlib
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.bot.channel_types import DeliveryTarget
from app.bot.client_message_processor import process_client_message, show_typing_until_done
from app.bot.router import normalize_telegram_message, normalize_telegram_voice_message
from app.bot.telegram_channel_client import TelegramChannelClient
from app.bot.telegram_session import create_ipv4_session
from app.bot.welcome_texts import START_WELCOME_TEXT
from app.core.config import get_settings
from app.core.constants import CHANNEL_TELEGRAM
from app.db.connection import get_connection
from app.services.message_retention_runner import run_message_retention_loop
from app.services.payment_status_runner import run_payment_status_loop
from app.services.voice_transcription_service import (
    VoiceTranscriptionError,
    transcribe_telegram_voice,
)
from app.services.yookassa_webhook_runner import start_yookassa_webhook_server
from app.services.yclients_sync_runner import run_yclients_sync_loop

logger = logging.getLogger(__name__)
TEXT_MESSAGE_ERROR = "Произошла ошибка. Попробуйте ещё раз через минуту."
VOICE_MESSAGE_PROCESSING_ERROR = "Не получилось обработать голосовое. Напишите, пожалуйста, текстом."


async def on_start(message: Message) -> None:
    logger.info(
        "Incoming Telegram /start chat_id=%s user_id=%s",
        message.chat.id,
        message.from_user.id if message.from_user else None,
    )
    await message.answer(START_WELCOME_TEXT)


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
        await process_client_message(
            incoming,
            _telegram_target(message, incoming.external_user_id),
            TelegramChannelClient(message.bot),
            error_text=TEXT_MESSAGE_ERROR,
            text_options={"reply_to_message": message},
            media_options={"source_message": message},
            log_context=f"telegram chat_id={message.chat.id}",
        )
    except Exception:
        logger.exception("Failed to handle message chat_id=%s", message.chat.id)
        await message.reply(TEXT_MESSAGE_ERROR)


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
        channel_client = TelegramChannelClient(message.bot)
        target = _telegram_target(message)
        transcription_task = asyncio.create_task(transcribe_telegram_voice(message.bot, message))
        typing_task = asyncio.create_task(
            show_typing_until_done(channel_client, target, transcription_task)
        )
        try:
            transcribed_text = await transcription_task
        finally:
            typing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing_task
        logger.info(
            "Telegram voice transcribed chat_id=%s text=%r",
            message.chat.id,
            transcribed_text[:200],
        )

        incoming = normalize_telegram_voice_message(message, transcribed_text)
        await process_client_message(
            incoming,
            _telegram_target(message, incoming.external_user_id),
            channel_client,
            error_text=VOICE_MESSAGE_PROCESSING_ERROR,
            text_options={"reply_to_message": message},
            media_options={"source_message": message},
            log_context=f"telegram voice chat_id={message.chat.id}",
        )
    except VoiceTranscriptionError as exc:
        logger.warning("Voice transcription skipped chat_id=%s reason=%s", message.chat.id, exc)
        await message.reply("Не получилось разобрать голосовое. Напишите, пожалуйста, текстом.")
    except Exception:
        logger.exception("Failed to handle voice message chat_id=%s", message.chat.id)
        await message.reply(VOICE_MESSAGE_PROCESSING_ERROR)


def _telegram_target(message: Message, external_user_id: str | None = None) -> DeliveryTarget:
    if external_user_id is None:
        external_user_id = str(message.from_user.id) if message.from_user else str(message.chat.id)
    return DeliveryTarget(
        channel=CHANNEL_TELEGRAM,
        external_id=str(external_user_id),
        chat_id=str(message.chat.id),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.message.register(on_start, CommandStart())
    dp.message.register(on_status, Command("status"))
    dp.message.register(on_voice, F.voice)
    dp.message.register(on_text, F.text | F.caption)
    return dp


def create_bot() -> Bot:
    settings = get_settings()
    return Bot(
        token=settings.telegram_bot_token,
        session=create_ipv4_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def run_polling(
    *,
    bot: Bot | None = None,
    manage_background_services: bool = True,
    close_bot: bool = True,
) -> None:
    bot = bot or create_bot()
    dp = create_dispatcher()
    loop = asyncio.get_running_loop()
    yookassa_server = None
    background_tasks: tuple[asyncio.Task[None], ...] = ()
    if manage_background_services:
        yookassa_server = start_yookassa_webhook_server(bot=bot, loop=loop)
        background_tasks = (
            asyncio.create_task(run_yclients_sync_loop(bot), name="yclients-sync"),
            asyncio.create_task(run_payment_status_loop(bot), name="payment-status-sync"),
            asyncio.create_task(run_message_retention_loop(), name="message-retention"),
        )
    logger.info("Telegram polling started")
    try:
        await dp.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if yookassa_server:
            yookassa_server.shutdown()
            yookassa_server.server_close()
        if close_bot:
            await bot.session.close()


async def run_bot(
    *,
    bot: Bot | None = None,
    manage_background_services: bool = True,
    close_bot: bool = True,
) -> None:
    settings = get_settings()
    if settings.telegram_webhook_url:
        raise NotImplementedError("Webhook mode is not implemented yet; use polling")
    await run_polling(
        bot=bot,
        manage_background_services=manage_background_services,
        close_bot=close_bot,
    )
