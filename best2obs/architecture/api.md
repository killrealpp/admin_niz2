# API / Integrations

## 2026-05-27 YooKassa webhook hardening

- `app/services/yookassa_webhook_runner.py` оставлен как встроенный lightweight webhook listener, который стартует вместе с `main.py`, если `YOOKASSA_WEBHOOK_ENABLED=true`.
- Для production (`APP_ENV=production/prod`) теперь обязательно нужен `YOOKASSA_WEBHOOK_SECRET`; без него server fail-fast не стартует.
- Входящий POST проверяет path, secret (`X-Webhook-Secret` или query `secret`) через constant-time compare, обязательный `Content-Length`, лимит `YOOKASSA_WEBHOOK_MAX_BODY_BYTES`, непустое/полное тело и JSON-object.
- Это снижает риск мусорных/слишком больших запросов, но наружный production всё равно должен идти через reverse proxy + HTTPS + firewall/body limits на уровне сервера.
- Smoke: `python scripts/yookassa_webhook_hardening_smoke.py`.

## Telegram

Библиотека: `aiogram`.

Режим сейчас: polling. Telegram webhook mode в коде явно не реализован.

## OpenRouter / OpenAI

Используется OpenAI-compatible клиент.

Основные сценарии:

- анализ сообщения и JSON patch анкеты;
- генерация человекочитаемого ответа;
- классификация post-booking сообщений;
- summary старых сообщений;
- transcription голосовых через OpenRouter или OpenAI.

## YCLIENTS

Используется для:

- проверки расписания, если локальный sync еще не готов;
- синка записей в `yclients_records`;
- создания записи после оплаты;
- удаления записи при отмене/переносе.

Конфигурация услуг: `config/services_map.yaml`.

## ЮKassa

Используется для предоплаты.

Сейчас есть:

- создание payment link;
- polling статусов;
- webhook runner;
- сохранение webhook events.

Webhook требует серверной настройки URL и секретов.

## Admin Telegram

Используется для уведомлений о важных событиях: AI provider issues, handoff, новые брони, проблемы с записью.

## Риски интеграций

- OpenRouter quota/credits влияет на качество и скорость ответов.
- YCLIENTS API может возвращать неожиданные структуры, поэтому sync нормализует разные поля.
- ЮKassa webhook без публичного URL не даст мгновенного подтверждения.
- Telegram voice/download/media может падать по таймауту.
