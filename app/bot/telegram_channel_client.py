from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.types import FSInputFile, Message
from aiogram.utils.media_group import MediaGroupBuilder

from app.bot.channel_types import DeliveryTarget


class TelegramChannelClient:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_text(
        self,
        target: DeliveryTarget,
        text: str,
        **options: Any,
    ) -> None:
        reply_to_message = options.get("reply_to_message")
        source_message = options.get("source_message")
        kwargs = _telegram_send_options(options)
        if isinstance(reply_to_message, Message):
            await reply_to_message.reply(text, **kwargs)
            return
        if isinstance(source_message, Message):
            await source_message.answer(text, **kwargs)
            return
        await self._bot.send_message(chat_id=target.address, text=text, **kwargs)

    async def send_media(
        self,
        target: DeliveryTarget,
        media_paths: Sequence[str | Path],
        caption: str | None = None,
        **options: Any,
    ) -> None:
        paths = [Path(path) for path in media_paths]
        if not paths:
            return

        source_message = options.get("source_message")
        kwargs = _telegram_send_options(options)
        if len(paths) == 1:
            photo = FSInputFile(paths[0])
            if isinstance(source_message, Message):
                await source_message.answer_photo(photo, caption=caption, **kwargs)
                return
            await self._bot.send_photo(
                chat_id=target.address,
                photo=photo,
                caption=caption,
                **kwargs,
            )
            return

        builder = MediaGroupBuilder()
        for index, path in enumerate(paths[:10]):
            builder.add_photo(
                media=FSInputFile(path),
                caption=caption if index == 0 else None,
            )
        if isinstance(source_message, Message):
            await source_message.answer_media_group(
                media=builder.build(),
                **kwargs,
            )
            return
        await self._bot.send_media_group(
            chat_id=target.address,
            media=builder.build(),
            **kwargs,
        )

    async def send_typing(self, target: DeliveryTarget) -> None:
        await self._bot.send_chat_action(
            chat_id=target.address,
            action=ChatAction.TYPING,
        )

    async def answer_callback(
        self,
        callback_id: str,
        message: str | None = None,
        notification: str | None = None,
    ) -> None:
        await self._bot.answer_callback_query(
            callback_query_id=callback_id,
            text=notification or message,
        )


def _telegram_send_options(options: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    parse_mode = options.get("parse_mode")
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if "notify" in options:
        kwargs["disable_notification"] = not bool(options["notify"])
    return kwargs


__all__ = ["TelegramChannelClient"]
