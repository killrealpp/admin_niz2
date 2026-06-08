# MAX Telegram Parity Completion Plan

## 2026-06-07 Status Update

- Done: Phase 4 runtime ownership cleanup is implemented for `main.py`. Background loops and lightweight webhook servers are owned by `app/bot/runtime.py` and start once per process; Telegram polling can run as a channel runner without duplicating those loops.
- Done: Phase 5 code wiring is implemented. `CLIENT_CHANNELS=telegram,max`, `MAX_MODE=webhook`, `MAX_WEBHOOK_ENABLED=true` and `MAX_WEBHOOK_SECRET` now start the MAX webhook runner with the real event processor from the shared runtime. This does not register the webhook and does not mutate subscriptions.
- Done: local dual-channel runner was started and reached ready once: PID `13284`, log `runtime_logs/main_telegram_max_20260607_2054.out.log`, `MAX_MODE=polling`, `MAX_WEBHOOK_ENABLED=false`, `MAX_SEND_RELATED_MEDIA=true`, payments disabled. It was then stopped after a Telegram network disconnect exposed a half-live supervision bug; the runtime now fails fast if any channel exits.
- Done: automated checks/regressions passed after the runtime changes: compileall, MAX/channel smokes, `max_runtime_smoke.py`, `max_webhook_runner_smoke.py`, `media+fresh`, `services`, `post_booking`, `payments`, live health, hygiene, Telegram status and MAX status.
- Still open: Phase 1 manual paired smoke must be completed by sending the same scenarios in Telegram and MAX and comparing user-facing behavior/state. As of 2026-06-07 evening, local Python DNS fails for `api.telegram.org`/`platform-api.max.ru`, so no current `main.py` runner is active. Special attention after DNS recovery: real MAX voice payload, typing visibility, media delivery, payment-link text/button fallback and no Telegram regression.
- Still open: production Step 12 Launch Gate. Required: public HTTPS `MAX_WEBHOOK_URL`, `MAX_WEBHOOK_SECRET`, reverse proxy HTTPS 443 to the internal runner, confirmation that the production webhook runner is live, explicit permission for `scripts/register_max_webhook.py --apply`, expected update types `message_created` and `bot_started`, and active subscription visible in `scripts/max_status.py`.

Дата: 2026-06-05.

Цель: MAX должен быть настоящей второй клиентской точкой входа/выхода рядом с Telegram. Под "таким же поведением" понимаем одинаковый смысл ответов, одинаковые переходы анкеты, одинаковое сохранение состояния, одинаковую работу текста, `/start`, typing, voice, media и payment-link сценариев настолько, насколько это позволяет интерфейс MAX. UI-детали мессенджеров могут отличаться, но клиент не должен получать худший сценарий в MAX.

## Текущее состояние

- MAX text path уже идет через общий `process_client_message()` и `handle_incoming()`, без форка `message_handler.py`.
- MAX typing реализован через `POST /chats/{chatId}/actions`.
- MAX `bot_started` отвечает тем же `START_WELCOME_TEXT`, что Telegram `/start`, и не запускает анкету.
- MAX voice/audio имеет первый adapter: пробует получить полный payload, скачать аудио и переиспользовать `transcribe_audio_bytes()`; при невозможности отвечает понятным fallback.
- `main.py` умеет локально запускать `CLIENT_CHANNELS=telegram,max` при `MAX_MODE=polling` и `MAX_WEBHOOK_ENABLED=false`.
- Текущий локальный runner поднят для ручного smoke: PID `26216`, log `runtime_logs/main_max_parity_live.out.log`; платежи/YooKassa/YCLIENTS loop отключены для безопасности.
- Production MAX launch gate не закрыт: нет public HTTPS webhook URL, active subscription, подтвержденного reverse proxy 443 и production webhook runner startup.

## Принципы

- Telegram не ломать и не ухудшать.
- `message_handler.py` не копировать под MAX.
- Admin notifications на MVP остаются в Telegram.
- MAX webhook не регистрировать без отдельного явного запроса.
- `POST /subscriptions` и `DELETE /subscriptions` не вызывать без отдельного явного запроса.
- Реальные YooKassa платежи не делать без отдельного явного запроса.
- Long polling использовать только local/dev; production MAX должен идти через webhook.

## Definition Of Parity

MAX считается parity-ready с Telegram, когда выполнены все пункты:

- `/start` в Telegram и старт в MAX дают одинаковый welcome-смысл и не портят состояние анкеты.
- Обычный текст в обоих каналах проходит один и тот же dialog core и дает одинаковое состояние в БД с разным `channel`.
- Typing виден или, если платформа показывает его иначе, MAX adapter хотя бы успешно отправляет chat action во время долгой обработки.
- Voice в Telegram и MAX либо транскрибируется в общий dialog path, либо дает одинаково понятный fallback без молчания.
- Explicit photo / related media отправляются в обоих каналах или дают понятный fallback.
- Payment link в MAX не хуже Telegram: клиент получает текст ссылки, а link-button остается дополнительным удобством, не единственным способом оплаты.
- Ошибки adapter-а не ломают диалог и не оставляют пользователя без ответа.
- Client notifications по пользовательскому каналу работают для MAX там, где они должны уходить клиенту; admin/backoffice остается Telegram.
- После paired smoke в БД нет мусорных активных holds/payments/bookings, YCLIENTS cache fresh, hygiene clean.

## Phase 1. Manual Local Parity Smoke

Назначение: подтвердить живое поведение MAX рядом с Telegram на текущем локальном runner.

Команды перед smoke:

```powershell
.\.venv\Scripts\python.exe scripts\telegram_status.py
.\.venv\Scripts\python.exe scripts\max_status.py
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
.\.venv\Scripts\python.exe scripts\live_health_report.py
```

Если YCLIENTS stale:

```powershell
.\.venv\Scripts\python.exe scripts\sync_yclients_records.py --once
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
```

Ручные paired scenarios:

- Telegram `/start` и MAX start: одинаковый welcome-смысл, без анкеты.
- Telegram text и MAX text: `что можно забронировать?`, затем обычный booking flow.
- Telegram voice и MAX voice: либо транскрибация, либо понятный fallback.
- Explicit photo request в обоих каналах: например `пришли фото беседки 1`.
- Related media after recommendation: убедиться, что MAX media действительно отправляется при `MAX_SEND_RELATED_MEDIA=true`.
- Payment-link path без реальной оплаты: проверить текст/кнопку только в safe/fake режиме или на disabled provider fallback.
- Long running ответ: проверить typing в MAX визуально и по логам.

После smoke:

```powershell
.\.venv\Scripts\python.exe scripts\live_health_report.py
.\.venv\Scripts\python.exe scripts\live_db_hygiene_audit.py --limit 20
.\.venv\Scripts\python.exe scripts\max_status.py
.\.venv\Scripts\python.exe scripts\telegram_status.py
```

Если smoke создал ненужные runtime-данные, очистить только после решения, что их не нужно сохранять:

```powershell
.\.venv\Scripts\python.exe scripts\clear_db.py
.\.venv\Scripts\python.exe scripts\sync_yclients_records.py --once
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
```

## Phase 2. Fix Live Parity Gaps From Smoke

Назначение: править только подтвержденные расхождения, не переписывая dialog core.

Ожидаемые возможные правки:

- MAX voice payload shape: если реальный voice не содержит поддерживаемый downloadable URL, сохранить raw shape в bugs/log и добавить узкий extractor в MAX adapter.
- MAX typing visibility: если `typing_on` успешно вызывается, но в клиенте не видно, проверить частоту отправки, lifetime chat action и нужное значение action по фактическому MAX behavior.
- MAX media delivery: если upload/token/attachment shape отличается от fake smoke, исправить только `MaxApiClient`/`MaxChannelClient`.
- MAX formatting: если HTML/line breaks отличаются, держать default plain text и включать `format='html'` только по явному `parse_mode`.
- MAX payment link: если link-button не отображается, URL в тексте остается обязательным fallback.
- MAX non-text fallback: уточнить тексты для image/sticker/document отдельно от voice fallback, если live UX покажет путаницу.

Запрещено в этой фазе:

- Копировать `message_handler.py`.
- Менять Telegram user-facing behavior ради MAX.
- Вызывать webhook registration или реальные платежи.

## Phase 3. Automated Parity Coverage

Назначение: закрепить parity не только ручным smoke.

Добавить или расширить smokes:

- `scripts/max_inbound_normalization_smoke.py`: реальные формы payload из live samples.
- `scripts/max_outbound_text_smoke.py`: typing, start, splitting, parse format, link fallback.
- Новый `scripts/channel_parity_smoke.py`: один и тот же normalized text/voice сценарий должен попадать в одинаковый shared processing path для Telegram и MAX.
- Новый fake voice smoke: Telegram voice contract и MAX audio contract оба используют `transcribe_audio_bytes()`.
- Новый runtime smoke: `CLIENT_CHANNELS=telegram,max` стартует оба канала, unsafe configs fail-fast.

Регрессии после кода:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\max_api_client_smoke.py
.\.venv\Scripts\python.exe scripts\max_inbound_normalization_smoke.py
.\.venv\Scripts\python.exe scripts\max_outbound_text_smoke.py
.\.venv\Scripts\python.exe scripts\max_media_buttons_smoke.py
.\.venv\Scripts\python.exe scripts\channel_contract_smoke.py
.\.venv\Scripts\python.exe scripts\channel_notifications_smoke.py
.\.venv\Scripts\python.exe scripts\max_runtime_smoke.py
```

Минимальные dialog regression groups после adapter/runtime правок:

```powershell
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group media --group fresh
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group services
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group post_booking
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group payments
```

## Phase 4. Runtime Ownership Cleanup

Назначение: сделать MAX не "прицепом к Telegram", а равным каналом в runtime.

Оставшиеся задачи:

- Перенести ownership фоновых loops из `telegram_bot.run_polling()` в общий runtime-слой, чтобы YCLIENTS sync, payment status, retention и webhooks запускались один раз независимо от набора каналов.
- Telegram adapter должен владеть только Telegram polling/handlers.
- MAX adapter должен владеть MAX polling/webhook intake.
- Admin notifications могут продолжать использовать Telegram bot object, но это должно быть явно передано как admin notifier, а не неявно держать все фоновые loops внутри Telegram runtime.
- Проверить, что `CLIENT_CHANNELS=telegram,max` не создает двойных loops и не оставляет loops выключенными случайно.

Эта фаза важна для ощущения "запущен проект - работают и Telegram, и MAX".

## Phase 5. Production MAX Webhook Runtime

Назначение: подготовить production MAX без dev polling.

Оставшиеся задачи:

- Подключить production `MAX_MODE=webhook` path в общий runtime: при `CLIENT_CHANNELS` содержит `max`, `MAX_MODE=webhook`, `MAX_WEBHOOK_ENABLED=true` должен стартовать `max_webhook_runner` с processor-ом.
- В production запретить MAX long polling.
- Проверить внутренний listener `GET /webhooks/max` через reverse proxy и локальный порт.
- Проверить `X-Max-Bot-Api-Secret`, body size limit, duplicate safety через `webhook_events(provider='max')`.
- Добавить startup smoke, который не регистрирует webhook, но подтверждает, что listener реально жив.

До этой фазы Step 12 Launch Gate не закрывать.

## Phase 6. Production Launch Gate

Нужные данные и подтверждения:

- `MAX_BOT_TOKEN` в production env.
- Production `MAX_WEBHOOK_URL`: public HTTPS URL с path `/webhooks/max`, без query/fragment/явного порта.
- `MAX_WEBHOOK_SECRET`: 5-256 символов `[A-Za-z0-9_-]`.
- `MAX_MODE=webhook`.
- `MAX_WEBHOOK_ENABLED=true`.
- `MAX_WEBHOOK_HOST=127.0.0.1` за reverse proxy.
- `MAX_WEBHOOK_PORT=8089` или фактический внутренний порт.
- `MAX_WEBHOOK_PATH=/webhooks/max`.
- `CLIENT_CHANNELS=telegram,max`.
- Подтверждение, что reverse proxy HTTPS 443 настроен и TLS trusted.
- Подтверждение, что internal MAX webhook runner реально стартует и отвечает.
- Ожидаемый subscription scope/update_types: `message_created`, `bot_started`.
- Явное разрешение вручную выполнить:

```powershell
.\.venv\Scripts\python.exe scripts\register_max_webhook.py --apply
```

После apply:

```powershell
.\.venv\Scripts\python.exe scripts\max_status.py
.\.venv\Scripts\python.exe scripts\telegram_status.py
.\.venv\Scripts\python.exe scripts\live_health_report.py
.\.venv\Scripts\python.exe scripts\live_db_hygiene_audit.py --limit 20
```

Launch Gate можно считать закрытым только если:

- Telegram polling жив, Telegram webhook URL пустой.
- MAX subscription active и показывает ожидаемый production URL.
- Production MAX работает webhook mode, long polling не запущен.
- Smoke clean по text/start/voice fallback/media/payment-link.
- DB/YCLIENTS/hygiene clean.
- `best2obs/log.md` обновлен финальным summary.

## Phase 7. Rollback Plan

Если production MAX webhook не работает:

- Не запускать dev polling, пока active subscription существует.
- Сначала собрать `max_status.py`, logs и webhook runner output.
- Если нужно откатить subscription, сначала dry-run:

```powershell
.\.venv\Scripts\python.exe scripts\register_max_webhook.py --unsubscribe --dry-run
```

- Реальный unsubscribe только по отдельному явному запросу:

```powershell
.\.venv\Scripts\python.exe scripts\register_max_webhook.py --unsubscribe --apply
```

## Next Recommended Step

Ближайший шаг: провести Phase 1 manual local parity smoke на уже запущенном `main.py` PID `26216`. Особое внимание: MAX voice, MAX typing visibility, MAX media, обычный booking flow и отсутствие деградации Telegram.

Если MAX voice не сработает идеально, это не повод переписывать dialog core: нужно сохранить фактический payload shape и узко расширить MAX adapter.
