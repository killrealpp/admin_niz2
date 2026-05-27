# API / Integrations

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
