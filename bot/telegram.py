from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from app.bot.media import paths_for_requested_media, extract_media_titles_from_reply
from aiogram.utils.media_group import MediaGroupBuilder

from app.core.config import get_settings
from app.dialog.availability_cache import refresh_availability_cache, refresh_availability_cache_if_stale
from app.dialog.engine import handle_text, pop_requested_media
from app.dialog.payment_status import sync_paid_bookings
from app.storage import sqlite


logger = logging.getLogger(__name__)
router = Router()
_chat_locks: dict[str, asyncio.Lock] = {}


def _chat_lock(chat_id: str) -> asyncio.Lock:
    lock = _chat_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _chat_locks[chat_id] = lock
    return lock


@router.message(Command("start"))
async def on_start(message: Message) -> None:
    chat_id = str(message.chat.id)
    async with _chat_lock(chat_id):
        sqlite.clear_messages(chat_id)
        sqlite.release_holds(chat_id)

        from app.dialog.state import BookingDraft
        draft = BookingDraft()
        sqlite.save_draft(chat_id, draft.to_dict(), status="waiting_user", current_step=draft.next_step())

        reply = "Здравствуйте! Это бот для бронирования на базе отдыха «Причал» в Выксе. Что хотите забронировать: беседку, баню, дом или тёплую беседку?"
        sqlite.add_message(chat_id, "user", "/start", raw={"telegram_message_id": message.message_id})
        sqlite.add_message(chat_id, "assistant", reply)

    await message.answer(reply)

@router.message(F.text)
async def on_text(message: Message) -> None:
    chat_id = str(message.chat.id)
    text = message.text or ""
    requested_media: list[str] = []
    typing_task = asyncio.create_task(_typing_loop(message))
    async with _chat_lock(chat_id):
        try:
            sqlite.add_message(chat_id, "user", text, raw={"telegram_message_id": message.message_id})
            reply = await _safe_handle(chat_id, message.from_user.full_name if message.from_user else "", text)
            requested_media = pop_requested_media(chat_id)
            marker_media = extract_media_titles_from_reply(reply)
            if marker_media:
                requested_media = marker_media

            logger.info(
                "MEDIA_DECISION chat_id=%s requested_media=%s marker_media=%s",
                chat_id,
                requested_media,
                marker_media,
            )

            sqlite.add_message(chat_id, "assistant", reply)
        finally:
            typing_task.cancel()
    if reply:
        await message.answer(reply)
    await _send_requested_media(message, requested_media)
    
async def _send_requested_media(message: Message, requested_media: list[str]) -> None:
    paths = paths_for_requested_media(requested_media)
    logger.info("MEDIA_SEND requested_media=%s paths=%s", requested_media, [str(path) for path in paths])
    if not paths:
        return
    try:
        if len(paths) == 1:
            await message.answer_photo(FSInputFile(paths[0]))
            return
        builder = MediaGroupBuilder()
        for path in paths:
            builder.add_photo(media=FSInputFile(path))
        await message.answer_media_group(builder.build())
    except Exception:
        logger.exception("Failed to send related media")

async def _typing_loop(message: Message) -> None:
    while True:
        try:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        except Exception:
            logger.debug("Failed to send typing action", exc_info=True)
        await asyncio.sleep(4)


async def run_bot() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")
    session = AiohttpSession(proxy=settings.telegram_proxy_url or None)
    bot = Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    payment_task = asyncio.create_task(_payment_status_loop(bot))
    admin_task = asyncio.create_task(_admin_notification_loop(bot))
    availability_task = asyncio.create_task(_availability_cache_loop())
    startup_availability_task: asyncio.Task[None] | None = None
    try:
        me = await bot.get_me()
        logger.info("Telegram bot started username=%s", me.username)
        startup_availability_task = asyncio.create_task(_startup_availability_cache_refresh())
        await dispatcher.start_polling(bot)
    finally:
        payment_task.cancel()
        admin_task.cancel()
        availability_task.cancel()
        if startup_availability_task is not None:
            startup_availability_task.cancel()
        await bot.session.close()


async def _safe_handle(chat_id: str, user_name: str, text: str) -> str:
    try:
        return await asyncio.to_thread(handle_text, chat_id, user_name, text)
    except Exception as exc:
        logger.exception("Dialog handling failed chat_id=%s", chat_id)
        sqlite.log_system("ERROR", "dialog_failed", str(exc), {"chat_id": chat_id, "text": text})
        sqlite.enqueue_admin_notification(
            f"Ошибка в диалоге {chat_id}.\nСообщение клиента: {text}\nОшибка: {exc}",
            chat_id=chat_id,
        )
        return "Сейчас не получилось обработать сообщение автоматически. Передала администратору, он поможет."


async def _payment_status_loop(bot: Bot) -> None:
    while True:
        try:
            events = await asyncio.to_thread(sync_paid_bookings)
            for event in events:
                await bot.send_message(event["chat_id"], event["message"])
            if events:
                logger.info("Processed paid bookings count=%s", len(events))
        except Exception:
            logger.exception("Payment status loop failed")
        await asyncio.sleep(10)


async def _admin_notification_loop(bot: Bot) -> None:
    settings = get_settings()
    while True:
        try:
            if settings.admin_telegram_chat_id:
                notifications = await asyncio.to_thread(sqlite.list_pending_admin_notifications)
                for item in notifications:
                    await bot.send_message(settings.admin_telegram_chat_id, item["message"])
                    await asyncio.to_thread(sqlite.mark_admin_notification_sent, int(item["id"]))
        except Exception:
            logger.exception("Admin notification loop failed")
        await asyncio.sleep(5)


async def _availability_cache_loop() -> None:
    while True:
        await asyncio.sleep(60 * 60)
        try:
            await asyncio.to_thread(refresh_availability_cache, days=21, max_seconds=180, reason="hourly")
        except Exception:
            logger.exception("Availability cache refresh failed")
        try:
            from app.integrations.yclients_sync_service import sync_records_once
            await asyncio.to_thread(sync_records_once, days_back=1, days_forward=60)
        except Exception:
            logger.exception("YCLIENTS sync failed")

async def _startup_availability_cache_refresh() -> None:
    await asyncio.sleep(10)
    try:
        logger.info("Initial availability cache background check started")
        await asyncio.to_thread(refresh_availability_cache_if_stale, days=21, max_seconds=180, max_age_seconds=900, reason="initial")
        from app.integrations.yclients_sync_service import sync_records_once
        await asyncio.to_thread(sync_records_once, days_back=1, days_forward=60)
    except Exception:
        logger.exception("Initial YCLIENTS sync failed")
