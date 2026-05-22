import asyncio
import logging

from aiogram import Bot

from app.core.config import get_settings
from app.db.connection import get_connection
from app.db.repositories import conversations_repo, messages_repo, payments_repo, system_logs_repo
from app.db.repositories import users_repo
from app.services.admin_telegram_service import notify_admin_about_new_bookings, notify_admin_text
from app.services.payment_service import sync_payment_statuses
from app.services.yclients_record_service import create_missing_yclients_records

logger = logging.getLogger(__name__)


async def run_payment_status_loop(bot: Bot | None = None) -> None:
    settings = get_settings()
    if not settings.payment_status_sync_enabled:
        logger.info("Payment status sync disabled")
        return
    if settings.payment_provider.lower() != "yookassa":
        logger.info("Payment status sync skipped: provider is not yookassa")
        return

    interval = max(settings.payment_status_sync_interval_seconds, 5)
    logger.info("Payment status sync loop started interval=%s", interval)
    while True:
        try:
            result = await asyncio.to_thread(_sync_once)
            if result["checked"]:
                logger.info(
                    "Payment status sync checked=%s updated=%s paid=%s canceled=%s",
                    result["checked"],
                    result["updated"],
                    result["paid"],
                    result["canceled"],
                )
            if bot:
                await notify_admin_about_ai_provider_issues(bot)
                await notify_admin_about_handoffs(bot)
                await notify_admin_about_new_bookings(bot)
                await notify_paid_payments_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Payment status sync failed")
        await asyncio.sleep(interval)


def _sync_once() -> dict[str, int]:
    with get_connection() as conn:
        result = sync_payment_statuses(conn)
        yclients_result = create_missing_yclients_records(conn)
        return result | {
            "yclients_checked": yclients_result["checked"],
            "yclients_created": yclients_result["created"],
            "yclients_failed": yclients_result["failed"],
        }


async def notify_paid_payments_once(bot: Bot) -> None:
    with get_connection() as conn:
        payments = payments_repo.list_paid_unnotified(conn, provider="yookassa")

    for payment in payments:
        chat_id = str(payment.get("user_external_id") or "")
        if not chat_id:
            continue
        text = _paid_notification_text(payment)
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception(
                "Failed to notify paid payment payment_id=%s chat_id=%s",
                payment.get("id"),
                chat_id,
            )
            continue
        with get_connection() as conn:
            payments_repo.mark_payment_notified(conn, payment_id=payment["id"])
            messages_repo.create(
                conn,
                conversation_id=payment["conversation_id"],
                sender="assistant",
                text=text,
                raw_payload={"event": "payment_paid_notification", "payment_id": payment["id"]},
            )
            conversations_repo.update_after_message(
                conn,
                payment["conversation_id"],
                payment.get("paid_at") or payment.get("updated_at"),
                status="payment_paid",
                intent="payment_status",
                current_step="reserved",
                next_step="payment_status",
            )
        await notify_admin_text(
            bot,
            (
                "Оплата по заявке получена.\n"
                f"Платеж #{payment.get('id')}, сумма: {payment.get('amount')} ₽.\n"
                "Если запись в YCLIENTS не создалась автоматически, проверьте карточку заявки."
            ),
        )


async def notify_admin_about_ai_provider_issues(bot: Bot) -> None:
    with get_connection() as conn:
        logs = system_logs_repo.list_admin_unnotified(conn)

    for item in logs:
        payload = item.get("payload") or {}
        text = (
            "Проблема с AI/OpenRouter.\n"
            f"Событие #{item.get('id')}, conversation_id={item.get('conversation_id')}.\n"
            f"Причина: {item.get('message') or 'не указана'}.\n"
            f"HTTP/status: {payload.get('status_code') or 'unknown'}.\n"
            "Бот продолжит работать на безопасных правилах, но ответы AI могут быть хуже."
        )
        sent = await notify_admin_text(bot, text)
        if sent:
            with get_connection() as conn:
                system_logs_repo.mark_admin_notified(conn, log_id=item["id"])


async def notify_admin_about_handoffs(bot: Bot) -> None:
    settings = get_settings()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo(settings.app_timezone))
    with get_connection() as conn:
        users = users_repo.list_handoffs_to_notify(conn, now=now)

    for user in users:
        text = (
            "Нужен живой ответ клиенту.\n"
            f"Клиент: {user.get('name') or 'не указано'}\n"
            f"Telegram ID: {user.get('external_id')}\n"
            f"Телефон: {user.get('phone') or 'не указан'}\n"
            f"Причина: {user.get('handoff_reason') or 'не указана'}\n\n"
            f"Контекст: {user.get('handoff_summary') or 'нет'}"
        )
        sent = await notify_admin_text(bot, text)
        if sent:
            with get_connection() as conn:
                users_repo.mark_handoff_notified(conn, user_id=user["id"])


def _paid_notification_text(payment: dict) -> str:
    amount = payment.get("amount")
    return (
        "Оплата прошла, спасибо ✅\n\n"
        "Бронь успешно подтверждена. Запись создана в журнале. "
        f"Сумма оплаты: {amount} ₽."
    )
