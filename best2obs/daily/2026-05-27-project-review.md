# 2026-05-27 Project Review

## Контекст

Запрос: полностью оценить проект как senior Python-разработчик, восстановить логику работы, найти недоработки, предложить исправления, отметить сильные/слабые места и дать оценку.

Production-код не менялся. Проверялись wiki, архитектура, основные сервисы, БД, интеграции, тесты и текущие риски.

## Логика проекта

`best2` - Telegram-бот бронирования базы отдыха. Поток:

1. `main.py` запускает aiogram polling.
2. `app/bot/telegram_bot.py` нормализует текст/голос, показывает typing, вызывает `handle_incoming` в thread и отдельно отправляет связанные фото.
3. `app/services/message_handler.py` ведет диалог, состояние анкеты, cancel/reschedule/post-booking, holds, payment link и переходы.
4. AI через `app/ai/ai_orchestrator.py` помогает понять смысл сообщения и формирует JSON/ответы, но backend валидирует состояние.
5. Availability смотрит локальные `yclients_records` и `resource_busy_intervals`, которые наполняет фоновый YCLIENTS sync.
6. При подтверждении создается `slot_holds` на 10 минут, затем ссылка ЮKassa.
7. После оплаты payment polling/webhook финализирует booking, создает локальный busy interval и пытается создать запись в YCLIENTS.

## Что сделано хорошо

- У проекта есть рабочая доменная модель: пользователи, диалоги, сообщения, holds, bookings, payments, waitlist, YCLIENTS cache.
- Хороший принцип: AI понимает смысл, backend исполняет и валидирует state/availability/payment.
- Много edge-case регрессий: паузы, свежие заявки, допы, переносы, отмены, опечатки, фото, post-booking.
- Есть LLM Wiki `best2obs`, которая реально помогает не терять контекст.
- Есть fallback от внутренних AI-инструкций в клиентский ответ.
- `.env` не отслеживается git; секреты вынесены в env.
- `compileall app scripts` проходит.

## Главные риски

- `message_handler.py` около 6000 строк и остается центром почти всех сценариев. Это главный источник регрессий и сложности ревью.
- Нет явного уникального ограничения/lock на активный hold слота. `slot_holds` имеет только обычный индекс, а `_create_hold` просто вставляет строку. При двух одновременных клиентах возможна гонка, если оба прошли availability до создания hold.
- Создание платежа ЮKassa происходит внутри открытой DB transaction: сначала вставляется локальный pending payment, потом вызывается внешний API, потом transaction коммитится. Если внешний платеж создан, а локальный commit/connection падает, возникает reconciliation-проблема.
- YCLIENTS sync держит DB transaction вокруг сетевой загрузки и upsert всей пачки. При медленном API это долго держит соединение/транзакцию и ухудшает отказоустойчивость.
- `scripts/local_regression_suite.py` и `scripts/dialog_stress_suite.py` нельзя запускать параллельно: общий `local_regression_%` cleanup дает гонки и FK-конфликты.
- `validate_yclients_map.py` на текущем прогоне не завершился за 124 секунды. Это может быть сетевой/внешний timeout, но для pre-launch лучше иметь явный timeout/диагностику.
- Webhook ЮKassa использует простой `ThreadingHTTPServer`; для production лучше отдавать его за reverse proxy/ASGI/WSGI с HTTPS, body-size limit и обязательным secret.
- В репозитории отслеживаются `recovered_pyc/` и крупный `docx`; это исторический мусор/сырье, которое лучше вынести в docs/archive или удалить после подтверждения.

## Рекомендации

1. Сначала закрыть атомарность hold: partial unique index на активные holds по `service_type, yclients_service_id, slot_date, slot_time`, плюс обработка `IntegrityError`; для сложных длительностей дополнительно advisory lock или exclusion constraint по interval.
2. Вынести payment creation в outbox/reconciliation flow: локально создать payment intent, commit, затем вызвать ЮKassa, затем attach provider response. Добавить recovery job для intents без provider id.
3. Разрезать `message_handler.py`: `availability_flow`, `confirmation_flow`, `post_booking_flow`, `reschedule_flow`, затем тонкий coordinator.
4. YCLIENTS sync разделить на fetch phase без DB transaction и apply phase короткой транзакцией.
5. Добавить per-test timeout и запрет параллельного запуска regression suite через lock-файл или уникальный test prefix per process.
6. Оформить тесты как pytest-пакет, оставив scripts как CLI-обертки.
7. Удалить/архивировать `recovered_pyc/`, старые recovered artifacts и решить судьбу исходного `.docx`.
8. Перед production обязательно проверить webhook, payment late/expired hold, YCLIENTS map, admin notifications, живые voice/media сценарии.

## Проверки

- `python -m compileall app scripts` - OK.
- `scripts/db_status.py` - OK, таблицы доступны.
- `scripts/local_regression_suite.py --group fresh --group payments` - OK.
- `scripts/dialog_stress_suite.py` функционально прошел основные сценарии, но завершился FK cleanup error из-за параллельного запуска с local regression; затем `_cleanup()` выполнен отдельно успешно.
- `scripts/validate_yclients_map.py` - timeout 124s.

## Оценка

Текущая оценка: 7/10.

Для стадии активной разработки бот сильный: домен продуман, есть регрессии, интеграции и память проекта. Для production без оговорок пока рано из-за атомарности hold/payment, размера координатора и зависимости от внешней БД/API по latency.
