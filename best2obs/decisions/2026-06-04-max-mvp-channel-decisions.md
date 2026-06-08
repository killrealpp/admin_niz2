# 2026-06-04 MAX MVP Channel Decisions

Статус: принято.

Контекст: MAX внедряется в `best2` как новый клиентский канал. Архитектурная база остается в [[roadmap/max-channel-entry-exit-plan]], а пошаговый операционный маршрут для новых чатов находится в [[roadmap/max-context-window-steps]].

## Решения

- MAX добавляется рядом с Telegram, а не заменяет Telegram первым срезом.
- Telegram остается рабочим клиентским каналом на время MAX-внедрения.
- Admin notifications на MVP остаются в Telegram.
- `message_handler.py` не копируется и не форкается под MAX; транспорт отделяется от диалогового ядра через channel adapters/contracts.
- MVP-срез MAX = text-only клиентский канал: входящий текст, `bot_started`, обычный текстовый ответ и обычная ссылка оплаты текстом.
- MAX media, link-button для оплаты, contact-button и voice/audio adapter не входят в первый MVP и переносятся в следующие срезы.
- Первые живые проверки идут через dev-only polling; production-режим MAX должен идти через HTTPS webhook.
- Для защиты от дублей MAX webhook переиспользуется существующая таблица `webhook_events` с `provider='max'`, без введения отдельной `inbound_events` в первом MVP.
- `scripts/register_max_webhook.py` должен быть ручным скриптом; автоматическая регистрация webhook при старте приложения запрещена.

## Следствия

- Existing Telegram users не мигрируются в `channel='max'`.
- MAX production path должен использовать HTTPS webhook; long polling допустим только для dev/test.
- Админский backoffice не смешивается с клиентским MAX-срезом до отдельного решения.
- Операционная работа по MAX идет по одному шагу из [[roadmap/max-context-window-steps]] за чат.
- Payment link в MAX MVP не требует inline keyboard: ссылка может быть отправлена как обычный текст, как сейчас в Telegram-тексте.
- Dev polling нельзя запускать, если у того же MAX-бота уже активен webhook subscription.
- Для live MAX smoke нужны `MAX_BOT_TOKEN`, тестовый MAX-аккаунт и подтверждение, что у бота нет активного webhook при polling-проверке.
