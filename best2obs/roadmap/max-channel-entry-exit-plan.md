# MAX Channel Entry/Exit Plan

Цель: добавить или перевести клиентский канал `best2` на мессенджер MAX без копирования диалоговой логики и без разрушения текущего Telegram-пути.

Статус: MAX transport/text/user-notification slices закрыты; 2026-06-04 Step 10 добавил post-MVP media upload и payment link button в MAX adapter/API; 2026-06-05 parity slice добавил typing, shared `/start`, единый local runtime и первый MAX voice/audio adapter с fallback. Contact `request_contact` остается later; voice/audio еще нужно подтвердить реальным MAX payload sample.

## Изученные источники

- MAX developer docs: `https://dev.max.ru/docs/chatbots/bots-coding/prepare`
- MAX API docs: `https://dev.max.ru/docs-api`
- MAX bot creation docs: `https://dev.max.ru/docs/chatbots/bots-create`
- MAX placement rules and requirements:
  - `https://dev.max.ru/docs/legal/rules`
  - `https://dev.max.ru/docs/legal/requirements`
  - `https://dev.max.ru/docs/legal/agreement`
  - `https://dev.max.ru/docs/legal/privacy`

## Ключевые факты MAX

- Production-прием событий должен идти через Webhook. Long Polling разрешен для разработки/теста, но не считается production-режимом.
- Нельзя одновременно использовать Webhook и Long Polling для одного бота.
- API вызывается через `https://platform-api.max.ru`; токен передается в заголовке `Authorization: <token>`, не через query string.
- Для стабильной работы нужно соблюдать лимит до `30 rps` на `platform-api.max.ru`.
- Webhook endpoint должен быть публичным `https://...` на внешнем порту `443`, с доверенным TLS-сертификатом, без самоподписанного сертификата.
- MAX webhook должен вернуть HTTP `200` за 30 секунд; при ошибках MAX делает retry и может автоматически отписать webhook, если 8 часов нет успешной доставки.
- Рекомендуется задавать `secret` при подписке и проверять заголовок `X-Max-Bot-Api-Secret`.
- Основные inbound-события для MVP: `message_created`, `bot_started`, позже `message_callback`.
- Основной outbound: `POST /messages?user_id=...` или `POST /messages?chat_id=...` с телом `NewMessageBody`.
- Текст сообщения до `4000` символов; поддерживаются `markdown` и `html`.
- Кнопки идут как `attachments` типа `inline_keyboard`; полезные типы: `callback`, `link`, `request_contact`, `message`, позже `open_app`.
- Медиа требуют отдельного upload-flow через `POST /uploads`, загрузку файла на выданный URL и отправку attachment с `token`; возможна ошибка `attachment.not.ready`, нужен retry/backoff.
- Диплинки передают payload до 128 символов через `bot_started`.
- Для размещения нужен профиль организации или ИП-резидента РФ на платформе MAX для партнеров, бот проходит модерацию; для одной организации доступно 5 ботов.
- Требования MAX отдельно обязывают поддерживать юридическую информацию, политику обработки персональных данных, поддержку пользователей и защиту от подмены/дублирования запросов.

## MVP decisions 2026-06-04

- MAX добавляется рядом с Telegram: оба канала остаются рабочими клиентскими входами.
- Первый MAX MVP text-only: `message_created`, `bot_started`, обычный текстовый ответ и payment link обычным текстом.
- MAX media upload, link-button для оплаты, contact-button и voice/audio adapter не входят в первый MVP и остаются следующими срезами.
- Первые живые проверки идут через dev-only polling, затем production webhook.
- Production webhook должен проверять `X-Max-Bot-Api-Secret`, быстро отвечать `200 OK` и переиспользовать `webhook_events(provider='max')` для защиты от дублей.
- Admin notifications на MVP остаются в Telegram.
- `scripts/register_max_webhook.py` должен быть ручным скриптом; webhook registration не запускается автоматически.

## Текущее состояние best2

- Главный вход сейчас жестко Telegram-oriented: `main.py -> app.bot.telegram_bot.run_bot()`.
- `app/bot/telegram_bot.py` владеет:
  - `/start` и `/status`;
  - text/caption/voice handlers;
  - per-user lock `channel:external_user_id`;
  - отправкой typing;
  - отправкой reply text;
  - автоотправкой фото/медиагрупп;
  - запуском фоновых loops: YCLIENTS sync, payment status, message retention, YooKassa webhook server.
- `app/bot/router.py` уже содержит полезный шов: Telegram payload нормализуется в `IncomingMessage`, а `normalize_incoming()` помечен как future MAX/VK adapter.
- Диалоговое ядро находится в `app/services/message_handler.py::handle_incoming(message: IncomingMessage) -> str`.
- БД уже channel-aware: `users(channel, external_id)` и `conversations.channel`.
- Но выходы пока Telegram-specific:
  - `payment_status_runner.py` принимает `aiogram.Bot` и отправляет `send_message/send_photo`;
  - `waitlist_service.py` принимает `aiogram.Bot`;
  - `admin_telegram_service.py` жестко Telegram;
  - `voice_transcription_service.py` скачивает файл через Telegram Bot API;
  - `telegram_bot.py` сам решает media/typing/reply delivery.
- `.env.example` уже содержит `MAX_BOT_TOKEN` и `MAX_WEBHOOK_SECRET`, но `app/core/config.py` пока их не читает.

## Целевая архитектура

Не переносить `message_handler.py` под MAX. Правильный срез: отделить транспорт от диалогового ядра.

Целевая схема:

```text
external platform update
  -> channel runtime: Telegram polling / MAX webhook / MAX dev polling
  -> channel normalizer
  -> IncomingMessage(channel, external_user_id, user_name, text, message_time, raw_payload)
  -> process_client_message()
  -> handle_incoming()
  -> Outbound delivery by channel adapter
```

Фоновые выходы должны идти так:

```text
payment/waitlist/reminder/admin event
  -> NotificationRouter
  -> ChannelClient by target.channel
  -> Telegram or MAX delivery
```

## Новые внутренние точки входа

1. `app/bot/runtime.py`
   - единый запуск shared loops и channel runtimes;
   - следит, чтобы общие фоновые loops стартовали один раз, даже если включены Telegram и MAX.

2. `app/bot/channel_types.py`
   - `CHANNEL_TELEGRAM = "telegram"`;
   - `CHANNEL_MAX = "max"`;
   - `DeliveryTarget(channel, external_id, chat_id=None)`;
   - `OutboundMessage(text, media_paths=None, parse_mode=None, notify=True)`.

3. `app/bot/channel_client.py`
   - Protocol/interface:
     - `send_text(target, text, **options)`;
     - `send_media(target, media_paths, caption=None)`;
     - `send_typing(target)`;
     - `answer_callback(callback_id, message=None, notification=None)`;
     - позже `download_voice/audio`.

4. `app/bot/client_message_processor.py`
   - общий processing path для Telegram/MAX:
     - per-user lock;
     - `handle_incoming()` в thread;
     - отправка ответа через `ChannelClient`;
     - media routing после ответа;
     - единая обработка ошибок.

## MAX-specific точки входа

1. `app/bot/max_client.py`
   - HTTPX client для `platform-api.max.ru`;
   - `Authorization: <MAX_BOT_TOKEN>`;
   - timeout, retry, 429/`Retry-After`, лимит 30 rps;
   - методы: `get_me`, `send_message`, `answer_callback`, `get_subscriptions`, `subscribe_webhook`, `unsubscribe_webhook`, `get_updates`, `upload`.

2. `app/bot/max_router.py`
   - `normalize_max_update(update) -> IncomingMessage | None`;
   - MVP:
     - `message_created` с текстом;
     - `bot_started` как `/start` или текстовый старт с payload в `raw_payload`;
   - later:
     - `message_callback`;
     - contact attachments;
     - media/audio.

3. `app/bot/max_webhook_runner.py`
   - internal HTTP endpoint, например `/webhooks/max`;
   - body limit;
   - JSON object validation;
   - проверка `X-Max-Bot-Api-Secret`;
   - быстрый `200 OK`;
   - очередь обработки, чтобы не держать webhook до завершения AI/DB/YCLIENTS;
   - duplicate safety через существующую `webhook_events` с `provider='max'` и стабильным MAX event key.

4. `app/bot/max_polling_runner.py`
   - только dev/test;
   - `GET /updates` с `marker`, `limit`, `timeout`;
   - выключен в production.

5. `scripts/max_status.py`
   - безопасно проверяет `GET /me` и `GET /subscriptions`;
   - не печатает токен.

6. `scripts/register_max_webhook.py`
   - регистрирует `POST /subscriptions`;
   - требует `MAX_WEBHOOK_URL`, `MAX_WEBHOOK_SECRET`;
   - не запускается автоматически.

## Новые выходы

1. Клиентский ответ:
   - сейчас: `message.reply(reply)`;
   - цель: `channel_client.send_text(target, reply)`.

2. Автофото:
   - сейчас: Telegram `FSInputFile`, `answer_photo`, `answer_media_group`;
   - цель: `channel_client.send_media(...)`;
   - для первого MAX MVP media не обязательно; post-MVP MAX реализация использует upload token и retry `attachment.not.ready`.

3. Payment/hold/reminder:
   - сейчас: `payment_status_runner(bot)` и `bot.send_message`;
   - цель: runner получает `NotificationRouter`, а репозитории возвращают `user_channel`;
   - сообщение уходит в тот канал, где создан пользователь/бронь.
   - MAX MVP отправляет payment link обычным текстом; link-button остается post-MVP улучшением.

4. Waitlist:
   - сейчас: `notify_waitlist_matches(bot)`;
   - цель: `notify_waitlist_matches(notifier)`.

5. Admin:
   - MVP: оставить Telegram admin channel, чтобы не смешивать клиентскую MAX-миграцию с backoffice.
   - Max-quality: `ADMIN_NOTIFICATION_CHANNEL=telegram|max`, отдельные `ADMIN_MAX_USER_ID`/`ADMIN_MAX_CHAT_ID`.

6. Voice/audio:
   - MVP MAX: ответить текстом, что голосовые пока лучше писать текстом.
   - Later: добавить MAX download adapter и переиспользовать `_transcribe_audio()`.

7. Contact button:
   - MVP: оставить текстовый ввод телефона.
   - Later: использовать MAX `request_contact` и проверять `hash` через HMAC-SHA256 от token + `vcf_info`.

## Пошаговый план

### Step 1. Transport contract без поведения

- Статус 2026-06-04: выполнено как пассивный contract skeleton, Telegram runtime не менялся.
- Добавлены channel constants и Settings для MAX:
  - `MAX_BOT_TOKEN`;
  - `MAX_API_BASE_URL=https://platform-api.max.ru`;
  - `MAX_WEBHOOK_ENABLED`;
  - `MAX_WEBHOOK_PATH=/webhooks/max`;
  - `MAX_WEBHOOK_URL`;
  - `MAX_WEBHOOK_SECRET`;
  - `MAX_MODE=webhook|polling`;
  - `CLIENT_CHANNELS=telegram|max|telegram,max`.
- Добавлены protocol/dataclasses для channel clients и delivery targets: `DeliveryTarget`, `OutboundMessage`, `ChannelClient`, `NotificationRouter`.
- Production behavior Telegram не менять.
- Tests: import/compile, fake ChannelClient unit tests.

Definition of Done:
- Новый контракт есть, но Telegram поведение побайтно остается старым.
- `handle_incoming()` не знает о MAX.

### Step 2. Behavior-preserving Telegram extraction

- Вынести общую обработку входящего client message из `telegram_bot.py` в `client_message_processor.py`.
- `telegram_bot.py` оставить Telegram adapter/runtime.
- Перевести отправку текста и медиа Telegram на `TelegramChannelClient`.
- Фоновые loops пока могут принимать Telegram client через adapter, но публичный contract уже не `aiogram.Bot`.

Definition of Done:
- Все текущие regression suites зеленые.
- `telegram_bot.py` стал тоньше, но Telegram polling работает как раньше.

### Step 3. MAX client + dev polling smoke

- Реализовать `MaxApiClient`.
- Реализовать `normalize_max_update()` для текстовых `message_created` и `bot_started`.
- Реализовать `MaxChannelClient.send_text()`.
- Добавить dev-only polling runtime.
- Сделать локальный smoke на тестовом MAX-боте без платежей и без production webhook.

Definition of Done:
- Через MAX dev polling можно написать боту текст и получить обычный ответ от `handle_incoming()`.
- В БД пользователь создается как `channel='max'`.

### Step 4. MAX production webhook

- Реализовать `max_webhook_runner.py`.
- Webhook должен быстро отвечать `200 OK`, валидировать secret и складывать событие в очередь обработки, не удерживая HTTP response до завершения AI/DB/YCLIENTS.
- Duplicate safety для первого MVP идет через существующую `webhook_events`:
  - `provider='max'`;
  - stable MAX event key;
  - raw payload или безопасная ссылка на payload;
  - повтор с тем же key не запускает вторую обработку.
- Настроить reverse proxy: внешний `https://domain/webhooks/max` на внутренний endpoint.
- Добавить `scripts/register_max_webhook.py`.

Definition of Done:
- `GET /subscriptions` показывает правильный webhook.
- Long polling выключен.
- Duplicate webhook event не создает двойной ответ/двойной hold.

### Step 5. User outbound by channel

- Обновить репозитории payment/holds/bookings/waitlist так, чтобы везде, где есть `user_external_id`, возвращался и `user_channel`.
- `payment_status_runner`, `waitlist_service`, reminders и expired holds отправляют через `NotificationRouter`.
- Если канал неизвестен или adapter недоступен, не помечать уведомление как доставленное; писать system log.

Definition of Done:
- Оплата/истечение резерва/напоминание приходят пользователю в его канал: Telegram пользователю в Telegram, MAX пользователю в MAX.

### Step 6. Post-MVP MAX media/buttons/contact

- Статус 2026-06-04: `send_media()` через upload flow и inline `link` button для payment link реализованы; contact request и callback answer для будущих callback-кнопок не реализованы.
- Реализовать `send_media()` через MAX upload flow.
- Добавить retry/backoff на `attachment.not.ready`.
- Добавить MAX inline keyboard для ссылок оплаты и, позже, contact request.
- Добавить callback answer для будущих кнопок.

Definition of Done:
- Фото беседок/бани уходят в MAX.
- Payment link можно отправлять link-button, при этом текстовый fallback сохраняется.

### Step 7. Admin channel decision

- На MVP оставить админку в Telegram.
- Если нужен полный MAX-only запуск, добавить `AdminNotifier`:
  - Telegram implementation;
  - MAX implementation;
  - config switch.

Definition of Done:
- Handoff, refund_required, AI provider issues и новые брони не теряются.

### Step 8. Release gates

- Обновить:
  - `best2obs/architecture/api.md`;
  - `best2obs/architecture/backend.md`;
  - `best2obs/operations/production-env-checklist.md`;
  - `best2obs/operations/production-runbook.md`;
  - `best2obs/roadmap/release-context-window-steps.md`.
- Добавить MAX checks:
  - `scripts/max_status.py`;
  - `scripts/register_max_webhook.py --dry-run` если возможно;
  - webhook hardening smoke;
  - MAX text smoke;
  - MAX media/button smoke только если post-MVP media/buttons включены в текущий launch scope;
  - full regression без изменения Telegram сценариев.

Definition of Done:
- Telegram release path не сломан.
- MAX production path не использует Long Polling.
- Health report видит MAX webhook/subscription status или отдельный `max_status.py` зеленый.

## Не делать

- Не копировать `message_handler.py` под MAX.
- Не заменять `channel='telegram'` в существующих пользователях на `max`.
- Не запускать одновременно MAX webhook и MAX long polling для одного бота.
- Не переносить все admin notifications на MAX в том же срезе, где впервые включается клиентский MAX.
- Не регистрировать webhook и не создавать реальные платежи без отдельного явного запроса.

## Решено для MVP

- MAX идет рядом с Telegram.
- Telegram остается admin channel на MVP.
- Duplicate safety первого MAX webhook использует `webhook_events(provider='max')`, отдельная `inbound_events` не требуется для MVP.
- Телефон в первом MAX MVP вводится текстом.
- MAX media не является обязательным для первого text-only MVP.

## Открытые решения после MVP

- Нужен ли полный MAX-only admin channel?
- Нужна ли отдельная durable inbound queue/observability поверх `webhook_events`?
- Когда включать MAX contact request / callback-rich flows как production scope?
