# Auth / Secrets

В проекте нет пользовательской авторизации в web-смысле. Доступы используются для внешних сервисов.

## Источники секретов

Все секреты берутся из `.env` через `app/core/config.py`.

Основные группы:

- Telegram: `TELEGRAM_BOT_TOKEN`.
- AI: `AI_PROVIDER`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `OPENAI_MODEL`.
- Voice: `VOICE_TRANSCRIPTION_ENABLED`, `VOICE_TRANSCRIPTION_PROVIDER`, `VOICE_TRANSCRIPTION_MODEL`.
- PostgreSQL: `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, SSL-настройки.
- YCLIENTS: `YCLIENTS_PARTNER_TOKEN`, `YCLIENTS_USER_TOKEN`, `YCLIENTS_COMPANY_ID`.
- ЮKassa: `PAYMENT_PROVIDER`, `PAYMENT_SHOP_ID`, `PAYMENT_SECRET_KEY`, success/fail URL.
- Webhook ЮKassa: `YOOKASSA_WEBHOOK_ENABLED`, host, port, path, secret, URL.
- Admin Telegram: `ADMIN_TELEGRAM_CHAT_ID`.

## Доступ клиента

Идентификация клиента идет по Telegram `external_id`, дополнительно сохраняется телефон в `users.phone` и `bookings.phone`.

## Риски

- `.env` содержит production-секреты и не должен попадать в git.
- Handoff и admin notifications могут раскрывать телефон клиента в Telegram admin chat.
- Webhook ЮKassa нужно защищать секретом и запускать только на сервере с публичным HTTPS/proxy.
- Любые диагностические логи не должны печатать полные токены.
