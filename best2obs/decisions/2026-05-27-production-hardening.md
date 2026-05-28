# Production hardening: holds, payments, sync

## Decision

Для production первым закрываем целостность бронирования:

- активный hold должен быть атомарным на уровне БД;
- ссылка ЮKassa создается после локального сохранения payment intent;
- YCLIENTS sync делает сетевой fetch без открытой DB transaction, затем короткий apply phase;
- raw messages сжимаются через 48 часов, summary остается доступным AI;
- основной постоянный процесс на сервере один: `main.py`.

## Rules

- `slot_holds` хранит `yclients_staff_id`; активный резерв блокируется по `service_type + resource/staff + date`.
- При гонке двух клиентов один hold создается, второй получает конфликт и должен выбрать другую дату/время.
- Для платежа сначала сохраняется локальная pending-запись, затем вызывается ЮKassa, затем provider response прикрепляется к payment.
- Повторное подтверждение активного hold переиспользует существующую pending-ссылку.
- Если provider-call упал, payment остается `failed` с `hold_ids`; hold не теряется.
- Availability в клиентском диалоге продолжает опираться на локальные `yclients_records` / `resource_busy_intervals`.

## Server

- Временно можно запускать в `screen`, но только один процесс: `.venv/bin/python main.py` или Windows-аналог.
- Не запускать параллельный `sync_yclients_records.py --loop`, если уже работает `main.py`.
- Диагностика: `scripts/db_status.py`, `scripts/yclients_sync_status.py --strict`, разовый recovery sync: `scripts/sync_yclients_records.py --once`.

