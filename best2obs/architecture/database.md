# Database

База данных - PostgreSQL. Схема описана в `app/db/migrations/001_init.sql`. Доступ и SSL задаются через `.env`.

## Подключение

- `app/db/connection.py` использует `psycopg2` и `RealDictCursor`.
- Для постоянного процесса бота включен connection pool: `DB_POOL_ENABLED=true`, `DB_POOL_MIN=1`, `DB_POOL_MAX=5`.
- Pool нужен, чтобы не открывать новый TLS/connect к удаленному PostgreSQL на каждое сообщение. В трассировке это видно как замена долгого `db.connect` на быстрый `db.pool.checkout`.

## Основные таблицы

- `users` - Telegram/VK/MAX пользователь, имя, телефон, handoff-статус.
- `conversations` - активная сессия, шаги анкеты, `form_data`.
- `messages` - история сообщений.
- `conversation_summaries` - сжатая старая история после retention.
- `slot_holds` - временный резерв слота на оплату.
- `bookings` - локальные брони, платежный статус, YCLIENTS id, допы, напоминания.
- `payments` - платежи ЮKassa, ссылки, статусы и metadata.
- `yclients_records` - локальная копия записей журнала YCLIENTS.
- `resource_busy_intervals` - нормализованные интервалы занятости для проверки свободности.
- `yclients_sync_state` - состояние фонового синка.
- `waitlist_requests` - запросы уведомить при освобождении места.
- `webhook_events` - идемпотентное хранение webhook-событий.
- `system_logs` - события для диагностики и уведомлений админа.

## Важные правила данных

- Проверка свободности должна опираться на актуальные `resource_busy_intervals`.
- `slot_holds` защищают от гонки, когда два клиента выбирают один слот.
- После оплаты бронь должна быть в `bookings`, а запись в YCLIENTS должна создаваться или ретраиться.
- Старые `messages` после 72 часов сжимаются в `conversation_summaries`.
- Напоминания используют поля `reminder_sent_at`, `reminder_response`, `reminder_response_at`.

## Риски

- Если YCLIENTS sync не работает, локальная доступность устаревает.
- Свежесть YCLIENTS sync проверяется через `scripts/yclients_sync_status.py`: смотреть `last_success_at`, age, `records_seen`, `records_upserted`, `last_error`. При `YCLIENTS_SYNC_INTERVAL_SECONDS=5` текущий guard считает sync старым после 10 минут.
- Если платеж прошел после истечения hold, финализация должна заново проверить доступность.
- Если запись YCLIENTS не создалась, статус может быть `journal_missing` или ошибка создания.
- Нужны регулярные проверки количества активных holds, failed payments и sync errors.
- Если DB pool начнет держать битые соединения после сетевых сбоев, нужно добавить health-check/recreate pool.
