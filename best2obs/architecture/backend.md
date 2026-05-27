# Backend

Backend - Python-приложение на aiogram с сервисным слоем и PostgreSQL.

## Точка входа

- `main.py` - настройка логирования и запуск `run_bot`.
- `app/bot/telegram_bot.py` - Telegram polling и фоновые задачи.

## Основные сервисы

- `app/services/message_handler.py` - главный координатор диалога; пока ещё содержит большую часть state machine.
- `app/services/dialog/formatting.py` - общее форматирование дат, длительности и сумм.
- `app/services/dialog/price_info.py` - deterministic ответы по ценам, допам и базовым правилам.
- `app/services/dialog/stale_form.py` - checkpoint старой анкеты после паузы 2+ часа.
- `app/services/dialog/routing_guards.py` - чистые guards для маршрутизации вроде запросов свободных дат.
- `app/services/dialog/form_patches.py` - чистые patch-парсеры анкеты: услуга, беседка, телефон, формат отдыха, допы, гости, имя, ссылки на прошлую бронь.
- `app/services/dialog/form_corrections.py` - коррекция имени и текст подтверждения исправленных полей.
- `app/services/dialog/cancel_flow.py` - deterministic логика отмены: распознавание, выбор брони, подтверждения и тексты результата.
- `app/services/dialog/semantic_router.py` - компактный контекст для первого AI-прохода: AI понимает intent/action/fields, backend исполняет действие.
- `app/services/dialog/response_builder.py` - deterministic/fallback ответы для стандартных случаев, чтобы не отправлять клиенту внутренние инструкции.
- `app/services/dialog/performance.py` - трассировка этапов обработки сообщения и structured timing logs.
- `app/ai/ai_orchestrator.py` - вызовы AI, JSON-анализ, генерация ответов, post-booking classifier, summary.
- `app/services/booking_form_service.py` - структура анкеты и следующий вопрос.
- `app/services/availability_service.py` - проверка доступности по локальным таблицам `yclients_records` и `resource_busy_intervals`; live-запросы в YCLIENTS не используются в обычном клиентском ответе.
- `app/services/payment_service.py` - платежи ЮKassa, финализация брони после оплаты.
- `app/services/payment_status_runner.py` - polling платежей, уведомления, истекшие holds, напоминания.
- `app/services/yclients_sync_service.py` - синхронизация журнала YCLIENTS в локальные таблицы.
- `app/services/yclients_record_service.py` - создание/удаление записей YCLIENTS и локальных busy intervals.
- `app/services/message_retention_runner.py` - сжатие старой истории и удаление сообщений.
- `app/services/media_service.py` - выбор фотографий.
- `app/services/voice_transcription_service.py` - распознавание голосовых.

## Состояние диалога

Главное состояние хранится в `conversations.form_data`.

Важные flow:

- обычная анкета бронирования;
- `stale_form_flow` после паузы 2+ часа: короткое "давайте" продолжает старую анкету, а явный запрос новой услуги или свободных дат начинает чистую анкету с сохранением контакта;
- `cancel_flow`;
- `reschedule_flow`;
- `swap_reschedule_flow`;
- `last_unavailable` и waitlist;
- `media_state` для антиспама фото.

## Маршрутизация важных сообщений

- Информационные вопросы во время финального подтверждения обрабатываются confirmation-flow, а не post-booking classifier.
- Вопросы о ближайших свободных датах во время анкеты идут напрямую в availability по локальной таблице записей.
- Вопросы о цене в upsell-контексте отвечают по допам и возвращают клиента к выбору допов.
- Post-booking синхронизирует платежи/журнал только когда у разговора есть локальные платежи.
- В post-booking состоянии команды hold/payment обрабатываются первыми, затем AI/post-booking classifier может определить cancel/reschedule/current-booking/new-booking. Fresh-start новой анкеты запускается только после этого, чтобы свободные фразы вроде "сместим баню" не превращались в новую бронь из-за слова "баня".
- Основной AI-вызов работает как semantic-router: получает компактный context, возвращает intent/action/form_data_patch, а не пишет финальный текст. Полная база знаний подключается только для info-ответов и сложного post-booking.
- Для стандартных операций backend предпочитает шаблонный ответ: свободные варианты, один вариант, цены/предоплата/допы, payment link, successful payment, отмена, перенос, список броней, stale-form, явный запрос фото.

## План рефакторинга message_handler

- Дальше выносить `confirmation_flow`, `post_booking_flow`, `reschedule_flow`, `cancel_flow`, `availability_flow`.
- Цель: `message_handler.py` должен остаться тонким координатором, а смысл сообщения должен определяться semantic router / AI, после чего backend выполняет проверяемое действие.

## Фоновые процессы

Запускаются вместе с polling:

- YCLIENTS sync loop;
- payment status loop;
- message retention loop;
- YooKassa webhook server, если включен.

## Тесты

Главный локальный набор: `scripts/local_regression_suite.py`.

Покрывает диалоги бронирования, оплату, переносы, отмены, фото, цены, waitlist, summary и edge cases.

С 2026-05-26 suite можно запускать по группам через `--group`: `fresh`, `dates`, `gazebo`, `media`, `prices`, `upsell`, `time`, `payments`, `post_booking`, `services`, `waitlist`, `handoff`, `reschedule`, `cancel`, `reminder`.

## Обновление 2026-05-26

- Рефакторинг `message_handler.py` продолжен без изменения публичного поведения.
- Добавлен `app/services/dialog/booking_texts.py`: шаблоны подтверждения, оплаты, сводки броней и кратких строк брони.
- Добавлен `app/services/dialog/handoff.py`: определение активного handoff, фильтр конфликтных сообщений и создание handoff-лога.
- Добавлен `app/services/dialog/fresh_start.py`: политика, когда новая заявка должна сбросить старые поля анкеты и сохранить только контакт.
- Добавлен `app/services/dialog/booking_context.py`: получение актуальных броней пользователя, сверка с журналом/YCLIENTS, fallback на текущий conversation и summary-контекст для AI.
- Добавлены `app/services/dialog/date_parsing.py` и `app/services/dialog/time_parsing.py`: чистые парсеры дат, дней недели, времени, периодов и длительности.
- Добавлен `app/services/dialog/gazebo_options.py`: чистая логика свободных/подходящих беседок, вместимость, авто-выбор одной беседки, форматирование вариантов.
- Добавлен `app/services/dialog/cancel_flow.py`: выбор отменяемой брони и тексты cancel-flow вынесены из координатора.
- Добавлен `app/services/dialog/semantic_router.py`: основной AI-pass получает короткий router-context вместо полной базы знаний.
- Добавлен `app/services/dialog/response_builder.py`: стандартные готовые ответы и безопасный fallback, если AI вернул внутреннюю инструкцию.
- Добавлен `app/services/dialog/performance.py`: timing logs для DB, AI, availability, payment, YCLIENTS и media этапов.
- `availability_service.py` теперь использует локальную БД как единственный источник свободности в клиентском диалоге; YCLIENTS дергается фоновым sync-процессом и финальными create/delete операциями.
- `message_handler.py` пока остается координатором, но всё больше доменной логики вынесено в `app/services/dialog/`.

## Обновление 2026-05-27

- Добавлен `app/services/dialog/form_patches.py`: из `message_handler.py` вынесены чистые парсеры service/date-independent полей анкеты: тип услуги, вариант беседки, телефон, формат, допы, гости, имя и reference-фразы к прошлой брони.
- Добавлен `app/services/dialog/form_corrections.py`: из `message_handler.py` вынесены распознавание исправления имени и сборка текста "Поняла, обновила ...".
- Старые приватные имена в `message_handler.py` сохранены импортированными алиасами, чтобы regression suite и существующие вызовы не ломались.
- Цель следующего этапа рефакторинга: отделить `reschedule_flow` и `availability_flow`, потому что это самые крупные оставшиеся зоны координатора.
