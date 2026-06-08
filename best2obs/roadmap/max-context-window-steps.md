# MAX Context Window Steps

## 2026-06-07 Step 12 / Parity Runtime Status

- Safe local/runtime slice completed: `main.py` can start `telegram,max` together, and production `MAX_MODE=webhook` is wired to the MAX webhook runner through shared runtime.
- Current local manual-test runner: not active. PID `13284` reached ready once and was stopped after a Telegram network disconnect; a later restart failed because local Python DNS could not resolve `api.telegram.org`. Manual paired smoke waits on local DNS/network recovery.
- Automated preflight/regression checks passed on 2026-06-07 after YCLIENTS one-shot sync; final live health was `status=ok`, hygiene clean, Telegram status OK, MAX status OK with `subscriptions_count=0`.
- Step 12 Launch Gate is not fully complete: no production HTTPS `MAX_WEBHOOK_URL`, no configured/confirmed production reverse proxy 443, no production active MAX webhook subscription, and no `scripts/register_max_webhook.py --apply` permission/run.
- Next work must be manual paired smoke on the running local runner: compare Telegram and MAX `/start`/start, same text flow, voice/fallback, typing, media and payment-link behavior.

Цель: добавить MAX рядом с Telegram, не ломая Telegram и не копируя диалоговую логику. Этот маршрут разбивает внедрение MAX на шаги, каждый из которых должен помещаться в один новый чат/контекстное окно.

Архитектурная основа: [[roadmap/max-channel-entry-exit-plan]]. Этот файл не заменяет архитектурный план, а превращает его в операционный маршрут: новый чат берет один шаг, доводит его до Definition of Done, обновляет память и останавливается.

Целевой режим для MVP:

- MAX добавляется рядом с Telegram.
- Telegram остается рабочим клиентским каналом на время внедрения.
- Admin notifications на MVP остаются в Telegram.
- `message_handler.py` не копируется и не форкается под MAX.
- MVP MAX = text-only: входящий текст, `bot_started`, обычный текстовый ответ и обычная ссылка оплаты текстом.
- MAX media, link-button оплаты, contact-button и voice/audio adapter остаются post-MVP срезами.
- Первые живые проверки идут через dev-only polling; production MAX позже включается через HTTPS webhook.
- Защита от дублей webhook должна переиспользовать существующую `webhook_events` с `provider='max'`.

## Live parity backlog после smoke 2026-06-05

Текущий MAX text path использует общий `process_client_message()`/`handle_incoming()`, но живой smoke показал, что этого недостаточно для ощущения паритета с Telegram. До полного client-facing parity нужны отдельные follow-up задачи, не закрывающие Step 12 launch gate сами по себе:

Статус 2026-06-05 после parity implementation slice:

- Выполнено: MAX typing реализован через chat action в `MaxApiClient`/`MaxChannelClient.send_typing()`.
- Выполнено: attachment-only MAX updates больше не игнорируются молча. Audio/voice пытается получить полное сообщение, скачать аудио и переиспользовать общий `transcribe_audio_bytes()`; unsupported/failed paths получают понятный fallback.
- Выполнено: MAX `bot_started` отвечает тем же `START_WELCOME_TEXT`, что Telegram `/start`, напрямую через adapter и без запуска анкеты.
- Выполнено: local parity smoke может включать MAX media через `MAX_SEND_RELATED_MEDIA=true`; `scripts/max_dev_live_polling.py` переиспользует общий MAX polling loop.
- Выполнено: `main.py` умеет единый локальный runtime `CLIENT_CHANNELS=telegram,max` при safe polling guards.
- Осталось подтвердить вручную: реальный MAX voice payload должен содержать поддерживаемую downloadable audio URL shape; иначе текущий fallback с логированием payload shape станет основанием для следующего узкого adapter patch.
- Step 12 Launch Gate это не закрывает полностью: production webhook URL/secret, reverse proxy HTTPS 443, реально запущенный webhook runner и active MAX subscription всё ещё нужны отдельно.
- Подробный план оставшейся работы до пользовательского паритета MAX с Telegram: [[roadmap/max-telegram-parity-completion-plan]].

## Общий стартовый промпт для каждого нового чата

```text
Прочитай AGENTS.md, best2obs/index.md, best2obs/log.md, best2obs/roadmap/max-channel-entry-exit-plan.md и best2obs/roadmap/max-context-window-steps.md.
Работаем только над Шагом N из max-context-window-steps.md.
MAX добавляется рядом с Telegram; Telegram должен остаться рабочим.
Admin notifications на MVP остаются в Telegram.
MAX MVP text-only: payment link отправляется обычным текстом, media/buttons/contact/voice не входят в первый срез.
Не переходи к следующему шагу без отдельного запроса.
Не копируй message_handler.py и не создавай параллельную MAX-версию диалогового ядра.
Не регистрируй MAX webhook и не делай реальные платежи без отдельного явного запроса.
После значимых изменений обнови best2obs/log.md, а если меняется архитектура, решение, roadmap, runbook или bugs - обнови соответствующие страницы best2obs/.
```

Заменить `N` на номер текущего шага.

## Общие правила для всех шагов

- Перед любыми командами читать `AGENTS.md`, свежие `best2obs/index.md`, `best2obs/log.md`, [[roadmap/max-channel-entry-exit-plan]] и этот файл.
- Для архитектуры, рефакторинга и поиска места правки сначала использовать Graphify query, затем открывать конкретные файлы:

```powershell
.\best2graph\.venv\Scripts\graphify.exe query "QUESTION" --graph .\best2graph\graphify-out\graph.json --budget 1200
```

- После production-code changes обновлять Graphify:

```powershell
.\best2graph\update_graph.ps1
```

- После wiki-only изменений Graphify не обновлять.
- После значимых изменений обязательно обновлять `best2obs/log.md`.
- Если найден баг, фиксировать его в `best2obs/bugs/`.
- Если изменена архитектура, обновлять `best2obs/architecture/`.
- Если принято решение, записывать его в `best2obs/decisions/`.
- Если появились или изменились задачи, обновлять `best2obs/roadmap/`.
- Если есть DB-mutating regression или live smoke, после него выполнять cleanup + fresh sync:

```powershell
.\.venv\Scripts\python.exe scripts\clear_db.py
.\.venv\Scripts\python.exe scripts\sync_yclients_records.py --once
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
.\.venv\Scripts\python.exe scripts\live_db_hygiene_audit.py --limit 20
```

## Запреты

- Не копировать `message_handler.py` под MAX.
- Не заменять существующих Telegram-пользователей на `channel='max'`.
- Не запускать MAX webhook и MAX long polling одновременно для одного бота.
- Не переносить admin notifications на MAX в MVP-срезе клиентского MAX.
- Не регистрировать MAX webhook без отдельного явного запроса.
- Не делать реальные YooKassa-платежи или реальные платежные smoke без отдельного явного запроса.
- Не менять production-код в wiki-only шагах.
- Не втягивать MAX media, link-button оплаты, contact-button или voice/audio adapter в первый text-only MVP без отдельного явного решения.

## Шаг 1. MAX Inventory И Freeze

Назначение: сверить текущее состояние MAX-подготовки, Telegram-bound точки, `.env.example`, config и roadmap, затем заморозить безопасный scope.

В новом чате использовать общий промпт и добавить:

```text
Шаг 1: сделай MAX inventory и freeze. Не исправляй production-код, только проверь Telegram-bound точки, .env.example, config, roadmap, dirty tree и обнови wiki.
```

Действия:

- Прочитать `AGENTS.md`, `best2obs/index.md`, `best2obs/log.md`, [[roadmap/max-channel-entry-exit-plan]], этот файл.
- Через Graphify найти текущие Telegram-bound runtime/output точки:

```powershell
.\best2graph\.venv\Scripts\graphify.exe query "Where are Telegram-bound runtime, inbound, outbound, payment, waitlist, reminder, media and admin notification points for MAX migration?" --graph .\best2graph\graphify-out\graph.json --budget 1200
```

- Открыть только релевантные файлы после Graphify: `main.py`, `app/bot/telegram_bot.py`, `app/bot/router.py`, `app/core/config.py`, `.env.example`, фоновые notification/payment/waitlist modules.
- Выполнить read-only inventory команд:

```powershell
git status --short
git diff --stat
git diff --name-status
git diff --name-status --diff-filter=D
```

- Сверить, что roadmap фиксирует целевой режим: MAX рядом с Telegram, Telegram не ломать, admin MVP в Telegram.
- Зафиксировать freeze: до закрытия transport contract и Telegram extraction не начинать MAX feature work, который требует копии `message_handler.py`.

Definition of Done:

- Понятно, какие Telegram-bound точки есть сейчас.
- Понятно, какие MAX env/config поля уже есть, а каких не хватает.
- Нет неожиданных tracked deletions или они явно вынесены пользователю.
- Scope зафиксирован: MAX рядом с Telegram, admin MVP в Telegram, `message_handler.py` не копируется.

Обновление памяти:

- Обновить `best2obs/log.md` с inventory summary.
- Если найдены новые устойчивые архитектурные факты, обновить [[roadmap/max-channel-entry-exit-plan]] или `best2obs/architecture/`.
- Если найдены реальные баги, обновить `best2obs/bugs/`.

## Шаг 2. Transport Contract

Назначение: спланировать и ввести общий transport contract без изменения Telegram-поведения.

В новом чате использовать общий промпт и добавить:

```text
Шаг 2: введи transport contract для каналов. Нужны ChannelClient, DeliveryTarget, NotificationRouter и channel constants, но Telegram behavior должен остаться прежним.
```

Действия:

- Через Graphify найти существующие типы inbound/outbound и места отправки сообщений.
- Добавить или спланировать минимальные точки:
  - `CHANNEL_TELEGRAM = "telegram"`;
  - `CHANNEL_MAX = "max"`;
  - `DeliveryTarget`;
  - `OutboundMessage` при необходимости;
  - `ChannelClient` protocol;
  - `NotificationRouter` skeleton;
  - settings для MAX: `MAX_BOT_TOKEN`, `MAX_API_BASE_URL`, `MAX_WEBHOOK_ENABLED`, `MAX_WEBHOOK_PATH`, `MAX_WEBHOOK_URL`, `MAX_WEBHOOK_SECRET`, `MAX_MODE`, `CLIENT_CHANNELS`.
- Не подключать MAX runtime.
- Не менять `handle_incoming()` под MAX.
- Добавить focused tests/import checks для новых contract types.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
```

Definition of Done:

- Общий transport contract существует и импортируется.
- Telegram polling/output поведение не изменено.
- `handle_incoming()` не знает о MAX.
- Тесты/compile для нового contract зелёные.

Обновление памяти:

- Обновить `best2obs/log.md`.
- Если contract стал архитектурным фактом, обновить `best2obs/architecture/backend.md` и при необходимости [[roadmap/max-channel-entry-exit-plan]].
- После production-code changes обновить Graphify.

## Шаг 3. Telegram Behavior-Preserving Extraction

Назначение: вынести текущий Telegram runtime в adapter/processor без изменения поведения клиента.

В новом чате использовать общий промпт и добавить:

```text
Шаг 3: сделай behavior-preserving Telegram extraction. Не добавляй MAX-функции; цель - вынести общий processing path и TelegramChannelClient без изменения Telegram UX.
```

Действия:

- Через Graphify найти `telegram_bot.py` inbound handler, reply/media delivery, locks и background loop ownership.
- Вынести общий processing path в `client_message_processor.py` или ближайший существующий слой:
  - per-user lock;
  - вызов `handle_incoming()` в текущем безопасном режиме;
  - отправка ответа через `ChannelClient`;
  - media routing после ответа;
  - error handling.
- Оставить `telegram_bot.py` как Telegram adapter/runtime.
- Ввести `TelegramChannelClient` поверх текущего `aiogram.Bot`.
- Фоновые loops пока могут оставаться Telegram-first, но новый публичный output contract не должен требовать прямой `aiogram.Bot` там, где это уже безопасно заменить.
- Не менять тексты ответов и порядок Telegram delivery.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --list-cases
```

Для широкого среза запустить релевантные regression groups по измененным зонам; если прогон меняет БД, выполнить cleanup + fresh sync из общих правил.

Definition of Done:

- Telegram polling работает как раньше.
- Текущий Telegram text/media reply path покрыт adapter-ом.
- Regression-срезы зелёные.
- Нет копии `message_handler.py`.

Обновление памяти:

- Обновить `best2obs/log.md`.
- Обновить `best2obs/architecture/backend.md`, если extraction стал новым стабильным слоем.
- Если найдены regressions, зафиксировать их в `best2obs/bugs/`.
- После production-code changes обновить Graphify.

## Шаг 4. MAX API Client И Status Scripts

Назначение: добавить безопасный MAX API client и status scripts без webhook registration и без реальных платежей.

В новом чате использовать общий промпт и добавить:

```text
Шаг 4: реализуй MAX API client и status scripts. Используй platform-api.max.ru, Authorization header, GET /me и subscriptions. Не регистрируй webhook.
```

Действия:

- Реализовать `MaxApiClient` с base URL `https://platform-api.max.ru`.
- Передавать токен только в header `Authorization: <token>`, не в query string.
- Добавить timeout, безопасную обработку 429/`Retry-After`, базовый retry/backoff.
- Реализовать методы:
  - `get_me`;
  - `get_subscriptions`;
  - позже используемые `send_message`, `get_updates`, `subscribe_webhook`, `unsubscribe_webhook` можно добавить как typed wrappers без live registration.
- Добавить `scripts/max_status.py`:
  - проверяет `GET /me`;
  - проверяет `GET /subscriptions`;
  - не печатает токен;
  - ясно говорит, если `MAX_BOT_TOKEN` не настроен.
- Добавить tests с fake HTTP/client там, где возможно.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\max_status.py
```

Если нет `MAX_BOT_TOKEN`, `max_status.py` должен завершиться понятным skip/blocker без утечки секретов.

Definition of Done:

- MAX client умеет безопасно вызвать `GET /me` и `GET /subscriptions`.
- Status script не печатает секреты.
- Webhook не зарегистрирован.
- Production Telegram behavior не изменено.

Обновление памяти:

- Обновить `best2obs/log.md` с результатом status/skip.
- Обновить `best2obs/architecture/api.md` при появлении стабильного MAX API client.
- После production-code changes обновить Graphify.

## Шаг 5. MAX Dev Polling Smoke

Назначение: сделать локальный dev/test smoke через MAX long polling, не production.

В новом чате использовать общий промпт и добавить:

```text
Шаг 5: добавь MAX dev polling smoke только для локальной проверки. Не включай polling в production и не используй его одновременно с webhook для одного MAX-бота.
```

Действия:

- Реализовать или включить `max_polling_runner.py` только для dev/test.
- Использовать `GET /updates` с `marker`, `limit`, `timeout`.
- Явно защитить production: polling запрещен при `APP_ENV=production` или `MAX_MODE=webhook`.
- Перед live smoke проверить `scripts/max_status.py`.
- Если у тестового MAX-бота уже есть webhook subscription, не запускать polling для него; остановиться и записать blocker.
- Сделать минимальный локальный smoke: получить update от тестового MAX-бота и вывести безопасный summary без токена и без персональных данных сверх нужного минимума.
- Не подключать реальные платежи и не регистрировать webhook.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\max_status.py
```

Definition of Done:

- Есть dev-only polling runner или smoke command.
- Production path не использует long polling.
- Для одного MAX-бота не включены одновременно webhook и polling.
- Smoke получает update или фиксирует понятный blocker/skip.

Обновление памяти:

- Обновить `best2obs/log.md` с smoke result или причиной skip.
- Если smoke выявил расхождение с MAX docs, обновить [[roadmap/max-channel-entry-exit-plan]].
- После production-code changes обновить Graphify.

## Шаг 6. MAX Webhook Runner

Назначение: подготовить production-grade webhook runner: HTTPS path за reverse proxy, secret header, быстрый `200 OK`, duplicate safety.

В новом чате использовать общий промпт и добавить:

```text
Шаг 6: реализуй MAX webhook runner. Не регистрируй webhook без отдельного запроса; сейчас нужен endpoint/runner, secret validation, quick 200 OK и duplicate safety.
```

Действия:

- Реализовать `max_webhook_runner.py` или встроить MAX endpoint в существующий webhook/runtime слой.
- Endpoint должен:
  - принимать только ожидаемый path, например `/webhooks/max`;
  - иметь body-size limit;
  - валидировать JSON object;
  - проверять `X-Max-Bot-Api-Secret`;
  - возвращать быстрый `200 OK`;
  - не держать HTTP response до завершения AI/DB/YCLIENTS.
- Добавить очередь обработки так, чтобы HTTP response не ждал AI/DB/YCLIENTS; для первого среза допустима in-memory очередь, если duplicate safety уже durable.
- Реализовать duplicate safety через существующую таблицу `webhook_events`: записывать/проверять событие с `provider='max'` и стабильным MAX event key до обработки.
- Не вводить отдельную `inbound_events` в первом MVP без отдельного решения.
- Добавить tests/smoke для secret mismatch, bad JSON, duplicate event, quick accept.
- Не вызывать `POST /subscriptions` без отдельного запроса.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
```

Definition of Done:

- Webhook runner принимает валидный MAX payload и быстро отвечает `200 OK`.
- Secret header проверяется.
- Duplicate event с тем же `provider='max'`/event key в `webhook_events` не приводит к двойной обработке.
- Webhook registration не выполнялась.

Обновление памяти:

- Обновить `best2obs/log.md`.
- Обновить `best2obs/architecture/api.md` и `best2obs/architecture/backend.md`.
- Если всё же потребуется отдельная durable inbound queue вместо `webhook_events`, записать новое решение в `best2obs/decisions/` перед реализацией.
- После production-code changes обновить Graphify.

## Шаг 7. MAX Inbound Normalization

Назначение: нормализовать MAX inbound events в общий `IncomingMessage`.

В новом чате использовать общий промпт и добавить:

```text
Шаг 7: реализуй MAX inbound normalization для message_created и bot_started. Callback/contact/media только подготовь как later, если не требуется MVP.
```

Действия:

- Реализовать `normalize_max_update(update) -> IncomingMessage | None`.
- MVP events:
  - `message_created` с текстом;
  - `bot_started` как `/start` или стартовый текст с payload в `raw_payload`.
- Later placeholders:
  - `message_callback`;
  - contact attachments;
  - media/audio.
- Сохранить `channel='max'`, `external_user_id`, `user_name`, `message_time`, `raw_payload`.
- Убедиться, что Telegram `normalize_incoming()` не меняет поведение.
- Добавить unit tests на реальных shape-примерах MAX payload без секретов.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
```

Definition of Done:

- `message_created` и `bot_started` превращаются в корректный `IncomingMessage`.
- Неизвестные MAX events безопасно игнорируются или логируются без падения.
- Telegram normalization не сломана.

Обновление памяти:

- Обновить `best2obs/log.md`.
- Обновить `best2obs/architecture/backend.md`, если normalization стал стабильным слоем.
- После production-code changes обновить Graphify.

## Шаг 8. MAX Outbound Text

Назначение: отправлять обычные клиентские ответы в MAX через `POST /messages`.

В новом чате использовать общий промпт и добавить:

```text
Шаг 8: подключи MAX outbound text. Обычный текст от handle_incoming() должен уходить через POST /messages; payment link в MVP отправляй обычным текстом, без медиа, кнопок и платежного smoke.
```

Действия:

- Реализовать `MaxChannelClient.send_text()`.
- Использовать `POST /messages?user_id=...` или `POST /messages?chat_id=...` по выбранному `DeliveryTarget`.
- Учитывать MAX limit текста до `4000` символов: длинный текст делить или явно логировать невозможность отправки.
- Подключить MAX inbound normalization к `client_message_processor`.
- Проверить, что пользователь в БД создается/используется как `channel='max'`.
- Сделать безопасный text smoke на тестовом MAX-боте: клиент пишет текст, бот отвечает обычным текстом.
- Не делать реальные платежи; если fake/local flow формирует payment link, в MAX MVP он отправляется обычным текстом, не link-button.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
```

После live/dev smoke, если менялась БД, выполнить cleanup + fresh sync из общих правил.

Definition of Done:

- MAX text message проходит через общий `handle_incoming()` path.
- Ответ уходит клиенту в MAX.
- Payment link, если он появляется в fake/local flow, уходит обычным текстом.
- В БД user/conversation имеют `channel='max'`.
- Telegram text path не сломан.

Обновление памяти:

- Обновить `best2obs/log.md` с smoke summary.
- Если найден баг маршрутизации, обновить `best2obs/bugs/`.
- После production-code changes обновить Graphify.

## Шаг 9. User Notifications By Channel

Назначение: перевести клиентские payment/hold/reminder/waitlist notifications на `NotificationRouter`, чтобы уведомление уходило в канал пользователя.

В новом чате использовать общий промпт и добавить:

```text
Шаг 9: переведи пользовательские notifications на NotificationRouter. Payment/hold/reminder/waitlist должны идти в канал пользователя; admin MVP остается в Telegram.
```

Действия:

- Через Graphify найти текущие выходы:
  - `payment_status_runner`;
  - expired hold notifications;
  - reminders;
  - `waitlist_service`;
  - booking/payment repositories, где возвращается `user_external_id`.
- Обновить repository/query contracts так, чтобы вместе с `user_external_id` возвращался `user_channel`.
- Реализовать `NotificationRouter` dispatch по `DeliveryTarget.channel`.
- Если channel неизвестен или adapter недоступен, не помечать notification как доставленную; писать system log.
- Admin notifications на MVP оставить в Telegram, не смешивать с клиентским MAX.
- Добавить tests на Telegram target, MAX target, unknown channel, adapter failure.
- Не создавать реальные платежи; использовать fake/local payment status tests.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
```

Запустить focused regression по payment/waitlist/reminder зонам. После DB-mutating checks выполнить cleanup + fresh sync.

Definition of Done:

- Telegram-пользователь получает клиентские notifications в Telegram.
- MAX-пользователь получает клиентские notifications в MAX.
- Unknown/failing channel не помечается как delivered.
- Admin notifications MVP всё еще в Telegram.
- Telegram release path не сломан.

Обновление памяти:

- Обновить `best2obs/log.md`.
- Обновить `best2obs/architecture/backend.md`.
- Если принято новое решение по admin channel или failure semantics, записать его в `best2obs/decisions/`.
- После production-code changes обновить Graphify.

## Шаг 10. Post-MVP MAX Media, Buttons И Contact

Назначение: после text-only MVP добавить MAX media upload flow, payment link button и optional contact button без обязательного переноса всех UX-фич.

Статус 2026-06-04: media upload flow и payment link button реализованы в MAX adapter/API slice; contact `request_contact` оставлен на later, потому что текущий scope не включал проверку contact hash.

В новом чате использовать общий промпт и добавить:

```text
Шаг 10: добавь post-MVP MAX media/buttons/contact. Первый MAX MVP уже text-only; этот шаг не нужен для запуска текстового MAX, но нужен для фото, link-button оплаты и optional contact button.
```

Действия:

- Реализовать MAX `send_media()` через upload flow:
  - `POST /uploads`;
  - загрузка файла на выданный URL;
  - отправка attachment с `token`;
  - retry/backoff на `attachment.not.ready`.
- Подключить автофото к `ChannelClient.send_media()`.
- Добавить inline keyboard link-button для payment link, если это безопасно в текущем payment flow; до этого MAX payment link остается обычным текстом.
- Не запускать реальную оплату без отдельного явного запроса; проверять только создание/формат ссылки или fake flow.
- Optional: добавить `request_contact` button только если пользователь явно выбрал этот MVP scope; иначе оставить текстовый ввод телефона.
- Добавить fallback: если MAX media недоступно, клиент получает понятный текст, а system log фиксирует failure.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
```

Запустить focused smoke на тестовом MAX-боте для media/button, если есть тестовый токен. После DB-mutating checks выполнить cleanup + fresh sync.

Definition of Done:

- Фото беседок/бани можно отправить в MAX.
- Payment link может уходить link-button; текстовый fallback сохраняется.
- Contact button либо реализован и проверен, либо явно оставлен на later с записью в roadmap.
- Telegram media path не сломан.

Обновление памяти:

- Обновить `best2obs/log.md`.
- Обновить `best2obs/architecture/api.md` и `best2obs/architecture/backend.md`.
- Если contact button оставлен на later, обновить roadmap.
- После production-code changes обновить Graphify.

## Шаг 11. MAX Runbook, Env И Checks

Назначение: подготовить production env, reverse proxy, webhook registration procedure и status checks для MAX.

Статус 2026-06-04: Step 11 подготовлен как operations/docs + safe script slice. `production-env-checklist.md` и `production-runbook.md` описывают MAX env, reverse proxy/HTTPS, manual registration и rollback; `scripts/register_max_webhook.py` добавлен с dry-run по умолчанию. Webhook не зарегистрирован, `POST /subscriptions` не вызывался, launch gate не выполнялся.

В новом чате использовать общий промпт и добавить:

```text
Шаг 11: обнови MAX runbook/env/checks. Подготовь production env, reverse proxy и webhook registration procedure, но не регистрируй webhook без отдельного явного запроса.
```

Действия:

- Обновить `best2obs/operations/production-env-checklist.md` MAX-полями:
  - `MAX_BOT_TOKEN`;
  - `MAX_API_BASE_URL=https://platform-api.max.ru`;
  - `MAX_WEBHOOK_ENABLED=true` для production;
  - `MAX_WEBHOOK_PATH=/webhooks/max`;
  - `MAX_WEBHOOK_URL=https://.../webhooks/max`;
  - `MAX_WEBHOOK_SECRET`;
  - `MAX_MODE=webhook`;
  - `CLIENT_CHANNELS=telegram,max` для режима рядом с Telegram.
- Обновить `best2obs/operations/production-runbook.md`:
  - reverse proxy на публичный HTTPS `443`;
  - trusted TLS certificate;
  - internal endpoint не открыт наружу напрямую;
  - порядок проверки `scripts/max_status.py`;
  - ручная команда `scripts/register_max_webhook.py`;
  - rollback/unsubscribe procedure;
  - запрет long polling в production.
- Добавить или обновить `scripts/register_max_webhook.py` с `--dry-run`, если возможно.
- Запустить безопасные checks только если они не регистрируют webhook.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\max_status.py
```

Definition of Done:

- Production env checklist знает MAX values.
- Runbook объясняет reverse proxy, webhook registration и rollback.
- `max_status.py` проверяет `GET /me` и subscriptions без утечки токена.
- Webhook не зарегистрирован, если пользователь не дал отдельный явный запрос.
- Перед реальной registration в следующем launch/ops scope нужно отдельно подтвердить, что внутренний MAX webhook runner фактически стартует и reverse proxy ведет на живой endpoint; Step 11 это не включает.

Обновление памяти:

- Обновить `best2obs/log.md`.
- Обновить `best2obs/index.md`, если добавлены новые runbook/check pages.
- Обновить `best2obs/architecture/api.md`, если production MAX webhook procedure стала стабильной.
- После production-code changes обновить Graphify; после wiki-only изменений Graphify не трогать.

## Шаг 12. MAX Launch Gate

Назначение: финальная проверка, что Telegram не сломан, MAX webhook active, smoke clean, память обновлена.

В новом чате использовать общий промпт и добавить:

```text
Шаг 12: проведи MAX launch gate. Telegram должен остаться рабочим, MAX webhook должен быть active, smoke clean, log updated. Не делай реальные платежи без отдельного подтверждения.
```

Действия:

- Проверить Telegram baseline:

```powershell
.\.venv\Scripts\python.exe scripts\telegram_status.py
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
.\.venv\Scripts\python.exe scripts\live_health_report.py
```

- Проверить MAX status:

```powershell
.\.venv\Scripts\python.exe scripts\max_status.py
```

- Убедиться, что production MAX использует webhook, а не long polling.
- Убедиться, что `GET /subscriptions` показывает ожидаемый webhook URL.
- До `scripts/register_max_webhook.py --apply` отдельно подтвердить, что MAX webhook runner подключен к production runtime или запущен отдельным service; Step 11 оставил registration только dry-run/manual.
- Провести MAX text smoke.
- Провести MAX media/button smoke только если post-MVP Шаг 10 уже был явно включен в текущий launch scope.
- Проверить duplicate safety webhook event.
- Проверить, что admin notifications MVP приходят в Telegram.
- Запустить релевантный automated regression gate, достаточный для затронутых зон.
- Если создавались тестовые записи или DB-mutating smoke, выполнить cleanup + fresh sync.

Definition of Done:

- Telegram API/status clean.
- Telegram клиентский путь не сломан.
- MAX webhook active и смотрит на правильный HTTPS URL.
- MAX text smoke clean.
- MAX media/button smoke clean только если post-MVP media/buttons включены в текущий launch scope.
- Long polling выключен в production.
- Admin notifications MVP в Telegram.
- `best2obs/log.md` обновлен финальной MAX launch gate записью.

Обновление памяти:

- Обновить `best2obs/log.md` с финальным launch gate summary.
- Обновить `best2obs/architecture/` и `best2obs/operations/`, если фактический production setup отличается от плана.
- Для каждого blocker создать или обновить `best2obs/bugs/`.
- После production-code changes обновить Graphify.

## После MAX MVP

Следующие работы не блокируют первый MAX MVP, если Шаги 1-12 закрыты:

- полноценный MAX-only admin channel;
- расширенная observability/queue для MAX inbound, если `webhook_events(provider='max')` окажется недостаточно для production-диагностики;
- MAX contact button с валидацией contact hash;
- MAX voice/audio download adapter;
- richer callback flows и `message_callback`;
- расширение `live_health_report.py` MAX subscription/webhook checks;
- отдельные e2e fixtures для MAX webhook retry/duplicates.
