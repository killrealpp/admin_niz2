import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile
from aiogram.utils.media_group import MediaGroupBuilder

from app.bot.client_notification_router import build_client_notification_router, ensure_client_notification_router
from app.bot.notification_router import NotificationRouter
from app.core.config import get_settings
from app.core.constants import CHANNEL_TELEGRAM
from app.db.connection import get_connection
from app.db.repositories import bookings_repo, conversations_repo, messages_repo, payments_repo, slot_holds_repo, system_logs_repo
from app.db.repositories import users_repo
from app.services.client_notification_service import (
    record_client_notification_failure,
    send_client_text_notification,
)
from app.services.admin_telegram_service import notify_admin_about_new_bookings, notify_admin_text
from app.services.availability_service import load_services_map
from app.services.dialog.booking_texts import booking_line_short, payment_reply_text
from app.services.media_service import media_for_bookings
from app.services.payment_service import create_payment_link_for_holds, sync_payment_statuses
from app.services.yclients_record_service import create_missing_yclients_records

logger = logging.getLogger(__name__)
MEDIA_SEND_TIMEOUT_SECONDS = 45
PAYMENT_LINK_RESEND_INTERVAL_MINUTES = 10
PAYMENT_LINK_RESEND_MAX_NEW_LINKS = 2
ClientNotifier = NotificationRouter | Bot


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
                client_notifier = build_client_notification_router(bot)
                await notify_admin_about_ai_provider_issues(bot)
                await notify_admin_about_refund_requests(bot)
                await notify_admin_about_handoffs(bot)
                await notify_admin_about_new_bookings(bot)
                await resend_active_hold_payment_links_once(client_notifier)
                await notify_paid_payments_once(client_notifier, admin_bot=bot)
                await notify_expired_holds_once(client_notifier)
                await notify_booking_reminders_once(client_notifier)
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


async def resend_active_hold_payment_links_once(notifier: ClientNotifier) -> None:
    settings = get_settings()
    router = ensure_client_notification_router(notifier)
    now = datetime.now(ZoneInfo(settings.app_timezone))
    if settings.payment_provider.lower() != "yookassa":
        return
    with get_connection() as conn:
        candidates = payments_repo.list_sync_candidates(conn, provider="yookassa", limit=100)

    for payment in candidates:
        with get_connection() as conn:
            decision = _payment_resend_decision(conn, payment, now)
            if not decision:
                continue
            hold_ids, resend_index, user, conversation = decision
            try:
                new_payment = create_payment_link_for_holds(
                    conn,
                    conversation_id=int(payment["conversation_id"]),
                    user_id=int(payment["user_id"]),
                    hold_ids=hold_ids,
                    client_name=str((conversation.get("form_data") or {}).get("client_name") or user.get("name") or "Клиент"),
                    phone=str((conversation.get("form_data") or {}).get("phone") or user.get("phone") or ""),
                    force_new=True,
                    raw_payload_extra={
                        "resend_of_payment_id": int(payment["id"]),
                        "resend_index": resend_index,
                        "state": "payment_link_auto_resent",
                    },
                )
            except Exception:
                logger.exception("Failed to auto-resend payment link payment_id=%s", payment.get("id"))
                continue
            old_payload = _payment_payload(payment) | {
                "state": "superseded_by_auto_resend",
                "superseded_by_payment_id": int(new_payment["id"]),
            }
            payments_repo.mark_superseded(conn, payment_id=int(payment["id"]), raw_payload=old_payload)
            conn.commit()

        text = (
            "Обновила ссылку на предоплату, резерв ещё активен ✅\n\n"
            f"{payment_reply_text(new_payment)}"
        )
        delivery = await send_client_text_notification(
            router,
            _user_notification_row(user, conversation_id=payment["conversation_id"]),
            text,
            notification_event="payment_link_auto_resent",
            entity_type="payment",
            entity_id=new_payment.get("id"),
        )
        if not delivery.delivered:
            continue
        with get_connection() as conn:
            messages_repo.create(
                conn,
                conversation_id=int(payment["conversation_id"]),
                sender="assistant",
                text=text,
                raw_payload={
                    "event": "payment_link_auto_resent",
                    "old_payment_id": int(payment["id"]),
                    "payment_id": int(new_payment["id"]),
                    "resend_index": resend_index,
                },
            )


def _payment_resend_decision(conn, payment: dict, now: datetime):
    created_at = payment.get("created_at")
    if not isinstance(created_at, datetime):
        return None
    if created_at.tzinfo is None and now.tzinfo is not None:
        created_at = created_at.replace(tzinfo=now.tzinfo)
    if now - created_at < timedelta(minutes=PAYMENT_LINK_RESEND_INTERVAL_MINUTES):
        return None
    hold_ids = _hold_ids_from_payment(payment)
    if not hold_ids:
        return None
    holds = [slot_holds_repo.get_by_id(conn, hold_id) for hold_id in hold_ids]
    if any(not hold for hold in holds):
        return None
    if any(str(hold.get("status") or "") != "active" or (hold.get("expires_at") and hold["expires_at"] <= now) for hold in holds if hold):
        return None

    same_hold_payments = [
        item
        for item in payments_repo.list_for_conversation(conn, conversation_id=int(payment["conversation_id"]))
        if item.get("provider") == "yookassa"
        and sorted(_hold_ids_from_payment(item)) == sorted(hold_ids)
        and item.get("payment_url")
    ]
    if same_hold_payments and int(same_hold_payments[0]["id"]) != int(payment["id"]):
        return None
    if len(same_hold_payments) >= PAYMENT_LINK_RESEND_MAX_NEW_LINKS + 1:
        return None

    user = users_repo.get_by_id(conn, int(payment["user_id"]))
    conversation = conversations_repo.get_by_id(conn, int(payment["conversation_id"]))
    if not user or not conversation:
        return None
    return hold_ids, len(same_hold_payments), user, conversation


def _admin_bot_from_notifier(notifier: ClientNotifier) -> Bot | None:
    return notifier if isinstance(notifier, Bot) else None


def _user_notification_row(user: dict[str, Any], *, conversation_id: int) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "user_channel": user.get("channel"),
        "user_external_id": user.get("external_id"),
    }


def _payment_payload(payment: dict) -> dict:
    raw = payment.get("raw_payload") or {}
    return dict(raw) if isinstance(raw, dict) else {}


async def notify_paid_payments_once(
    notifier: ClientNotifier,
    *,
    admin_bot: Bot | None = None,
) -> None:
    router = ensure_client_notification_router(notifier)
    admin_bot = admin_bot or _admin_bot_from_notifier(notifier)
    with get_connection() as conn:
        payments = payments_repo.list_paid_unnotified(conn, provider="yookassa")

    for payment in payments:
        with get_connection() as conn:
            bookings = _payment_bookings(conn, payment)
        if not bookings:
            await _notify_unfinalized_paid_payment(
                router,
                payment,
                admin_bot=admin_bot,
            )
            continue
        with get_connection() as conn:
            journal_ready = _payment_journal_ready(conn, payment)
        if not journal_ready:
            logger.info(
                "Skip paid notification until YCLIENTS record is ready payment_id=%s",
                payment.get("id"),
            )
            await _notify_paid_payment_waiting_for_journal_once(
                router,
                payment,
                bookings=bookings,
                admin_bot=admin_bot,
            )
            continue
        text = _paid_notification_text(payment, bookings)
        media_paths = media_for_bookings(bookings)
        delivery = await send_client_text_notification(
            router,
            payment,
            text,
            notification_event="payment_paid_notification",
            entity_type="payment",
            entity_id=payment.get("id"),
        )
        if not delivery.delivered:
            continue
        try:
            if delivery.target and delivery.target.channel == CHANNEL_TELEGRAM:
                media_bot = _admin_bot_from_notifier(notifier) or admin_bot
                if media_paths and media_bot is None:
                    record_client_notification_failure(
                        payment,
                        notification_event="payment_paid_media",
                        entity_type="payment",
                        entity_id=payment.get("id"),
                        reason="telegram media delivery requires bot",
                    )
                    continue
                await _send_booking_media(
                    media_bot,
                    chat_id=delivery.target.address,
                    media_paths=media_paths,
                )
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.exception(
                "Paid payment notification cannot be delivered payment_id=%s chat_id=%s",
                payment.get("id"),
                delivery.target.address if delivery.target else None,
            )
            record_client_notification_failure(
                payment,
                notification_event="payment_paid_media",
                entity_type="payment",
                entity_id=payment.get("id"),
                reason="telegram_media_delivery_failed",
            )
            continue
        except Exception:
            logger.exception(
                "Failed to notify paid payment payment_id=%s chat_id=%s",
                payment.get("id"),
                delivery.target.address if delivery.target else None,
            )
            record_client_notification_failure(
                payment,
                notification_event="payment_paid_media",
                entity_type="payment",
                entity_id=payment.get("id"),
                reason="telegram_media_delivery_failed",
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
        if admin_bot is not None:
            await notify_admin_text(
                admin_bot,
                (
                    "Оплата по заявке получена.\n"
                    f"Платеж #{payment.get('id')}, сумма: {payment.get('amount')} ₽.\n"
                    "Если запись в YCLIENTS не создалась автоматически, проверьте карточку заявки."
                ),
            )


async def notify_expired_holds_once(notifier: ClientNotifier) -> None:
    settings = get_settings()
    router = ensure_client_notification_router(notifier)
    now = datetime.now(ZoneInfo(settings.app_timezone))
    with get_connection() as conn:
        slot_holds_repo.expire_old(conn, now)
        holds = slot_holds_repo.list_expired_unnotified(conn, limit=50)

    for hold in holds:
        text = _expired_hold_notification_text(hold)
        delivery = await send_client_text_notification(
            router,
            hold,
            text,
            notification_event="slot_hold_expired",
            entity_type="slot_hold",
            entity_id=hold.get("id"),
        )
        if not delivery.delivered:
            continue
        with get_connection() as conn:
            slot_holds_repo.mark_expired_notified(conn, hold_id=hold["id"], now=now)
            messages_repo.create(
                conn,
                conversation_id=hold["conversation_id"],
                sender="assistant",
                text=text,
                raw_payload={"event": "slot_hold_expired", "hold_id": hold["id"]},
            )


async def notify_booking_reminders_once(notifier: ClientNotifier) -> None:
    settings = get_settings()
    router = ensure_client_notification_router(notifier)
    now = datetime.now(ZoneInfo(settings.app_timezone))
    if now.hour < 10:
        return
    reminder_date = now.date() + timedelta(days=1)
    with get_connection() as conn:
        bookings = bookings_repo.list_due_reminders(conn, reminder_date=reminder_date, limit=50)

    for booking in bookings:
        text = _booking_reminder_text(booking)
        delivery = await send_client_text_notification(
            router,
            booking,
            text,
            notification_event="booking_reminder",
            entity_type="booking",
            entity_id=booking.get("id"),
        )
        if not delivery.delivered:
            continue
        with get_connection() as conn:
            bookings_repo.mark_reminder_sent(conn, booking_id=int(booking["id"]), now=now)
            messages_repo.create(
                conn,
                conversation_id=booking["conversation_id"],
                sender="assistant",
                text=text,
                raw_payload={"event": "booking_reminder", "booking_id": booking["id"]},
            )


def _booking_reminder_text(booking: dict) -> str:
    return (
        f"Напоминаю: завтра у вас бронь {_booking_reminder_title(booking)}, "
        f"{_format_date_short(booking.get('booking_date'))}, с {str(booking.get('booking_time') or '')[:5]} "
        f"на {_format_duration_short(booking.get('duration_minutes'))}.\n\n"
        "Подтвердите, пожалуйста, что придёте: напишите «да» или «нет»."
    )


def _booking_reminder_title(booking: dict) -> str:
    config = load_services_map().get(booking.get("service_type")) or {}
    title = config.get("title") or booking.get("service_type") or "бронь"
    service_id = str(booking.get("hold_yclients_service_id") or "").strip()
    for variant in config.get("variants") or []:
        if service_id and str(variant.get("yclients_service_id") or "").strip() == service_id:
            return str(variant.get("title") or title)
    return str(title)


def _expired_hold_notification_text(hold: dict) -> str:
    settings = get_settings()
    service_type = hold.get("service_type")
    config = load_services_map().get(service_type) or {}
    title = config.get("title") or service_type or "бронь"
    service_id = str(hold.get("yclients_service_id") or "").strip()
    for variant in config.get("variants") or []:
        if service_id and str(variant.get("yclients_service_id") or "").strip() == service_id:
            title = variant.get("title") or title
            break
    date_text = _format_date_short(hold.get("slot_date"))
    time_text = str(hold.get("slot_time") or "")[:5]
    duration = _format_duration_short(hold.get("duration_minutes"))
    return (
        f"Резерв на {title}, {date_text}, с {time_text} на {duration} истёк: "
        f"предоплата не поступила в течение {settings.hold_ttl_minutes} минут.\n\n"
        "Слот снова доступен. Если всё ещё актуально, напишите — проверю свободность заново ✅"
    )


def _format_date_short(value) -> str:
    try:
        parsed = datetime.fromisoformat(str(value)).date()
    except ValueError:
        return str(value or "выбранную дату")
    months = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря",
    }
    return f"{parsed.day} {months[parsed.month]}"


def _format_duration_short(minutes) -> str:
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return "выбранное время"
    if value % 60:
        return f"{value} минут"
    hours = value // 60
    if hours % 10 == 1 and hours % 100 != 11:
        suffix = "час"
    elif hours % 10 in (2, 3, 4) and hours % 100 not in (12, 13, 14):
        suffix = "часа"
    else:
        suffix = "часов"
    return f"{hours} {suffix}"


async def _notify_unfinalized_paid_payment(
    router: NotificationRouter,
    payment: dict,
    *,
    admin_bot: Bot | None = None,
) -> None:
    text = (
        "Оплата поступила ✅\n\n"
        "Резерв по этой ссылке уже не был активен, поэтому бронь не закрепилась автоматически. "
        "Мы проверим выбранное время и напишем вам по сохранённому номеру."
    )
    delivery = await send_client_text_notification(
        router,
        payment,
        text,
        notification_event="payment_paid_without_booking",
        entity_type="payment",
        entity_id=payment.get("id"),
    )
    if not delivery.delivered:
        return
    with get_connection() as conn:
        payments_repo.mark_payment_notified(conn, payment_id=payment["id"])
        messages_repo.create(
            conn,
            conversation_id=payment["conversation_id"],
            sender="assistant",
            text=text,
            raw_payload={"event": "payment_paid_without_booking", "payment_id": payment["id"]},
        )
    hold_ids = _hold_ids_from_payment(payment)
    if admin_bot is not None:
        await notify_admin_text(
            admin_bot,
            (
                "Оплата получена, но бронь не создалась автоматически.\n"
                f"Платеж #{payment.get('id')}, сумма: {payment.get('amount')} ₽.\n"
                f"Клиент: {payment.get('user_name') or payment.get('user_external_id')}, Telegram ID: {payment.get('user_external_id')}.\n"
                f"Hold IDs: {', '.join(str(item) for item in hold_ids) or 'не найдены'}.\n"
                "Проверьте слот и решите оплату вручную."
            ),
        )


async def _send_booking_media(bot: Bot, *, chat_id: str, media_paths: list) -> None:
    if not media_paths:
        return
    try:
        await asyncio.wait_for(
            _send_booking_media_inner(bot, chat_id=chat_id, media_paths=media_paths),
            timeout=MEDIA_SEND_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Paid booking media send timed out chat_id=%s count=%s", chat_id, len(media_paths))


async def _send_booking_media_inner(bot: Bot, *, chat_id: str, media_paths: list) -> None:
    if len(media_paths) == 1:
        await bot.send_photo(chat_id=chat_id, photo=FSInputFile(media_paths[0]))
        return
    builder = MediaGroupBuilder()
    for path in media_paths[:10]:
        builder.add_photo(media=FSInputFile(path))
    await bot.send_media_group(chat_id=chat_id, media=builder.build())


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


async def notify_admin_about_refund_requests(bot: Bot) -> None:
    batch_limit = 50
    while True:
        with get_connection() as conn:
            logs = system_logs_repo.list_admin_unnotified(conn, event_type="refund_required", limit=batch_limit)
        if not logs:
            return

        all_sent = True
        for item in logs:
            payload = item.get("payload") or {}
            text = (
                "Требуется вернуть предоплату клиенту.\n"
                f"Бронь #{payload.get('booking_id') or 'не указана'}: {payload.get('booking') or 'нет описания'}.\n"
                f"Клиент: {payload.get('client_name') or 'не указано'}\n"
                f"Телефон: {payload.get('phone') or 'не указан'}\n"
                "Отмена сделана за 7+ дней до даты брони, аванс можно вернуть по правилам отмены."
            )
            sent = await notify_admin_text(bot, text)
            if sent:
                with get_connection() as conn:
                    system_logs_repo.mark_admin_notified(conn, log_id=item["id"])
            else:
                all_sent = False
        if len(logs) < batch_limit or not all_sent:
            return


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


def _payment_journal_ready(conn, payment: dict) -> bool:
    bookings = _payment_bookings(conn, payment)
    return bool(bookings) and all(booking.get("yclients_record_id") for booking in bookings)


async def _notify_paid_payment_waiting_for_journal_once(
    router: NotificationRouter,
    payment: dict,
    *,
    bookings: list[dict],
    admin_bot: Bot | None = None,
) -> None:
    with get_connection() as conn:
        if _journal_pending_notification_sent(conn, payment):
            return
    text = (
        "Оплата поступила ✅\n\n"
        "Сейчас закрепляю запись в журнале. Обычно это занимает пару минут. "
        "Финальное подтверждение пришлю сюда, когда запись будет создана."
    )
    delivery = await send_client_text_notification(
        router,
        payment,
        text,
        notification_event="payment_paid_journal_pending",
        entity_type="payment",
        entity_id=payment.get("id"),
    )
    if not delivery.delivered:
        return
    with get_connection() as conn:
        messages_repo.create(
            conn,
            conversation_id=payment["conversation_id"],
            sender="assistant",
            text=text,
            raw_payload={
                "event": "payment_paid_journal_pending",
                "payment_id": payment["id"],
            },
        )
        system_logs_repo.create(
            conn,
            level="warning",
            event_type="payment_paid_journal_pending",
            message="paid payment is waiting for YCLIENTS record",
            conversation_id=payment.get("conversation_id"),
            payload={
                "payment_id": payment.get("id"),
                "provider_payment_id": payment.get("provider_payment_id"),
                "booking_ids": [booking.get("id") for booking in bookings],
                "yclients_errors": [
                    booking.get("yclients_create_error")
                    for booking in bookings
                    if booking.get("yclients_create_error")
                ],
            },
        )
    if admin_bot is not None and any(booking.get("yclients_create_error") for booking in bookings):
        await notify_admin_text(
            admin_bot,
            (
                "Оплата получена, но запись в YCLIENTS пока не создана.\n"
                f"Платеж #{payment.get('id')}, сумма: {payment.get('amount')} ₽.\n"
                "Автосоздание будет повторяться; если ошибка не уйдет, проверьте заявку вручную."
            ),
        )


def _journal_pending_notification_sent(conn, payment: dict) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM messages
            WHERE conversation_id = %s
              AND raw_payload->>'event' = 'payment_paid_journal_pending'
              AND raw_payload->>'payment_id' = %s
            LIMIT 1
            """,
            (payment.get("conversation_id"), str(payment.get("id"))),
        )
        return cur.fetchone() is not None


def _payment_bookings(conn, payment: dict) -> list[dict]:
    booking_ids = _booking_ids_from_payment(payment)
    if not booking_ids:
        return []
    bookings: list[dict] = []
    for booking_id in booking_ids:
        booking = bookings_repo.get_by_id(conn, booking_id=int(booking_id))
        if booking:
            bookings.append(booking)
    return bookings


def _booking_ids_from_payment(payment: dict) -> list[int]:
    value = payment.get("booking_ids") or []
    if isinstance(value, list):
        return [int(item) for item in value if str(item).isdigit()]
    if isinstance(value, str):
        return [int(item) for item in value.split(",") if item.strip().isdigit()]
    return []


def _hold_ids_from_payment(payment: dict) -> list[int]:
    raw = payment.get("raw_payload") or {}
    if not isinstance(raw, dict):
        return []
    value = raw.get("hold_ids")
    if isinstance(value, list):
        return [int(item) for item in value if str(item).isdigit()]
    if isinstance(value, str):
        return [int(item) for item in value.split(",") if item.strip().isdigit()]
    return []


def _paid_notification_text(payment: dict, bookings: list[dict] | None = None) -> str:
    amount = payment.get("amount")
    booking_block = ""
    if bookings:
        lines = ["Бронь в журнале:"]
        for booking in bookings:
            lines.append(f"- {booking_line_short(booking)}")
        booking_block = "\n".join(lines) + "\n\n"
    return (
        "Поздравляем, бронь успешно подтверждена ✅\n\n"
        f"{booking_block}"
        "Запись создана в журнале, ждём вас на отдых. "
        "Пусть всё пройдёт легко, уютно и с хорошим настроением.\n\n"
        f"Предоплата: {amount} ₽.\n\n"
        "Если планы изменятся, аванс можно вернуть при отмене не позднее чем за 7 дней до даты брони."
    )
