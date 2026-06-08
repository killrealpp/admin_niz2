# API / Integrations

## 2026-06-07 MAX webhook runtime wiring

- MAX production webhook intake is now wired into `main.py` through `app/bot/runtime.py`: when `CLIENT_CHANNELS` includes `max`, `MAX_MODE=webhook`, `MAX_WEBHOOK_ENABLED=true` and `MAX_WEBHOOK_SECRET` is configured, the runtime starts `app/bot/max_webhook_runner.py` with `make_max_webhook_event_processor()`.
- This wiring does not register the webhook. Runtime startup still performs no `POST /subscriptions` and no `DELETE /subscriptions`; `scripts/register_max_webhook.py` remains the manual helper and dry-run is the default.
- The production integration gate remains outside code: public HTTPS `MAX_WEBHOOK_URL` on external 443, trusted TLS, reverse proxy to the internal MAX webhook runner path, a real `MAX_WEBHOOK_SECRET`, explicit operator permission for `--apply`, expected update types `message_created`/`bot_started`, and `scripts/max_status.py` showing the active subscription.
- Local/dev testing continues to use MAX long polling only with `MAX_MODE=polling` and `MAX_WEBHOOK_ENABLED=false`; polling and webhook must not be active for the same bot at the same time.

## 2026-06-05 MAX parity API additions

- `MaxApiClient` now covers the MAX API calls needed for local parity: `POST /chats/{chatId}/actions` for typing, `GET /messages/{messageId}` for full message lookup, and bounded download of audio URLs. Bot auth remains header-only through `Authorization`; foreign download URLs do not receive the bot token.
- MAX typing is sent as `{"action": "typing_on"}` to `/chats/{chatId}/actions` when the delivery target has `chat_id`. Missing `chat_id` is a debug-level no-op, not a client-facing failure.
- MAX voice/audio processing uses `GET /messages/{messageId}` only when the initial update does not contain enough attachment data. The adapter extracts a downloadable audio URL from known attachment fields, enforces duration/size/time limits, and reuses the shared transcription provider. If the payload shape is not downloadable, the client receives a fallback text and the raw shape remains available in logs/raw payloads for the next live sample.
- MAX outbound message formatting remains conservative: `format="html"` is sent only when outbound options explicitly request `parse_mode="html"`. The adapter does not globally enable HTML for all MAX text.
- Webhook registration is unchanged: no automatic subscription calls exist in runtime. `scripts/register_max_webhook.py` remains manual and dry-run by default; real `POST /subscriptions` or `DELETE /subscriptions` still requires a separate explicit `--apply` request.

## 2026-06-04 MAX production runbook/check procedure

- Step 11 formalized the MAX production operations boundary in [[operations/production-env-checklist]] and [[operations/production-runbook]]: public MAX webhook must be `https://DOMAIN/webhooks/max` on external `443`, with trusted TLS, no explicit port/query/fragment, and a reverse proxy to the internal MAX webhook runner port.
- Added `scripts/register_max_webhook.py` as a manual helper. Its default mode is dry-run (`calls_max_api=false`); real `POST /subscriptions` registration or `DELETE /subscriptions?url=...` rollback requires an explicit `--apply` run and was not executed in Step 11.
- The registration payload follows MAX API: `url`, `update_types` (`message_created`, `bot_started` by default) and `secret`; auth remains header-only via `Authorization`, and the script validates `MAX_WEBHOOK_URL`/`MAX_WEBHOOK_SECRET` before any apply call.
- `scripts/max_status.py` remains the safe read-only status check for `GET /me` and `GET /subscriptions` without token output. Production launch gate must verify that subscriptions show the expected HTTPS URL and that long polling is not active for the same bot.
- Operational blocker before real registration: `app/bot/max_webhook_runner.py` currently exists as a runner/processor boundary, but Step 11 did not wire/start it from `main.py` or register a webhook. The launch/ops step must confirm the internal runner is actually live before `--apply`.

## 2026-06-04 MAX media/upload/button API slice

- `app/integrations/max_client.py::MaxApiClient.send_message()` now accepts optional `attachments`, `text_format`, `notify` and `disable_link_preview` fields while keeping the existing target rule: `POST /messages` with either `user_id` or `chat_id` query params.
- `MaxApiClient.create_upload(upload_type=...)` wraps `POST /uploads?type=image|video|audio|file`; `upload_file(path, upload_type=...)` uploads the local file to the URL returned by MAX and extracts the attachment payload token for subsequent `POST /messages`.
- Platform API calls still use header-only auth (`Authorization: <MAX_BOT_TOKEN>`), keep the token out of URL/query params and redact it from MAX error text. The upload URL itself is used as returned by MAX and the no-secret smoke verifies that the bot token is not inserted into that URL.
- MAX inline payment buttons are sent as `attachments` with `type='inline_keyboard'` and a `link` button. The payment URL remains in the message text as fallback; no real YooKassa payment or live MAX request is made by tests.
- This slice still does not call `POST /subscriptions`, does not register webhook, does not add `request_contact`/contact hash validation, and does not implement voice/audio download.
- Smoke coverage: `scripts/max_media_buttons_smoke.py` checks fake `/uploads`, file upload, media attachment send, `attachment.not.ready` retry, link-button payload shape, media fallback logging and shared MAX auto-media routing.

## 2026-06-04 MAX outbound text API slice

- `app/integrations/max_client.py::MaxApiClient.send_message()` now covers the text-only outbound MVP call: `POST /messages` with either `user_id` or `chat_id` in query params and JSON body `{"text": ...}`.
- Authentication remains header-only: `Authorization: <MAX_BOT_TOKEN>`. The token is not placed in URL/query params and `_safe_response_text()` redacts it from MAX error bodies.
- The MAX text limit is enforced before live requests: a single API payload above `4000` characters raises `MaxApiError`; `MaxChannelClient` is responsible for splitting ordinary outbound replies into valid chunks.
- This slice does not add MAX upload/media, inline keyboards, contact buttons, callback answers, webhook registration or `POST /subscriptions`. It also does not perform live MAX calls in smoke tests.
- Smoke coverage: `scripts/max_outbound_text_smoke.py` checks fake `POST /messages` URL/query/body/auth, target selection, split/guard behavior, token redaction and the shared normalized inbound path. Existing `scripts/max_api_client_smoke.py` remains green for read/status/polling API methods.

## 2026-06-04 MAX webhook runner slice

- Добавлен `app/bot/max_webhook_runner.py` для production MAX webhook endpoint без регистрации webhook. Приложение по-прежнему не вызывает `POST /subscriptions`; регистрация остается отдельным будущим/manual шагом.
- Endpoint принимает только `MAX_WEBHOOK_PATH` (`/webhooks/max` по умолчанию), проверяет header `X-Max-Bot-Api-Secret`, обязательный `Content-Length`, `MAX_WEBHOOK_MAX_BODY_BYTES`, UTF-8 JSON и JSON object. Неверный path возвращает `404`, неверный secret `403`, bad JSON/body-size ошибки - `400/413`.
- Для production/prod запуск требует `MAX_WEBHOOK_SECRET`; runner также требует `MAX_MODE=webhook`, чтобы не смешивать webhook и polling для одного MAX-бота.
- Duplicate safety реализована до обработки через `webhook_events(provider='max')`: `event_type` берется из `update_type/type/event_type`, stable key - из event/update/id, scoped message id или canonical `sha256` payload hash. Повтор с тем же ключом возвращает быстрый `200 OK` с `duplicate=true` и не запускает вторую обработку.
- Валидный новый event после durable dedup кладется в in-memory queue, поэтому HTTP response не ждет AI/DB/YCLIENTS/dialog processing. Реальная MAX inbound normalization/outbound delivery не подключалась в этом срезе.
- Smoke: `python scripts/max_webhook_runner_smoke.py`.

## 2026-06-04 MAX dev polling API slice

- `MaxApiClient` теперь имеет `get_updates(marker=None, limit=100, timeout=30, types=None)` для dev/test `GET /updates`. Метод использует тот же безопасный `_request()` слой, передает token только через `Authorization`, кладет polling-параметры в query без token, ограничивает `limit` диапазоном `1..1000` и `timeout` диапазоном `0..90`.
- `scripts/max_dev_polling_smoke.py` перед polling выполняет read-only MAX status gate (`GET /me`, `GET /subscriptions`) и печатает только безопасный summary. При пустом `MAX_BOT_TOKEN` smoke завершается `status='skipped'`; при production/webhook-mode/webhook subscriptions возвращает blocker.
- Long polling остается только dev/test инструментом. Production MAX path по-прежнему должен идти через webhook; этот срез не регистрирует webhook, не вызывает `POST /subscriptions`, не отправляет `POST /messages` и не делает реальные платежи.

## 2026-06-04 MAX API client/status slice

- Добавлен `app/integrations/max_client.py`: `MaxApiClient` использует `https://platform-api.max.ru` из `MAX_API_BASE_URL` и передает `MAX_BOT_TOKEN` только в header `Authorization: <token>`, без query string.
- Реализованы безопасные read-only методы `get_me()` и `get_subscriptions()` для Step 4 MAX status checks. Клиент имеет timeout, retry для GET, уважает `429 Retry-After`, делает базовый backoff на transient network/5xx и редактирует токен из error body, если он вдруг попал в ответ.
- Добавлен `scripts/max_status.py`: проверяет `GET /me` и `GET /subscriptions`, печатает только безопасные поля бота и подписок, а при пустом `MAX_BOT_TOKEN` завершает проверку понятным `status='skipped'` без утечки секретов.
- Добавлен `scripts/max_api_client_smoke.py` с fake HTTP client: проверяет header-only auth, отсутствие токена в URL, retry по `429 Retry-After` и понятную ошибку при пустом токене.
- MAX webhook registration, dev polling, inbound normalization, outbound text и реальные платежи в этом срезе не подключались.

## 2026-06-04 MAX API/Webhook baseline target

- MAX клиентский канал добавляется рядом с Telegram, без копирования `message_handler.py`.
- API base URL: `https://platform-api.max.ru`; bot token передается только в header `Authorization: <token>`.
- Первый MVP использует text scope: `GET /me`, `GET /subscriptions`, dev-only `GET /updates`, `POST /messages` для обычного текста и payment link обычным текстом. Step 10 уже добавил MAX media upload и inline link-button как post-MVP adapter slice.
- Production MAX должен работать через HTTPS webhook `/webhooks/max` за reverse proxy на внешнем `443`, с проверкой `X-Max-Bot-Api-Secret`.
- MAX webhook registration должен быть ручной командой `scripts/register_max_webhook.py`; приложение не регистрирует webhook автоматически при старте.
- Duplicate safety для MAX webhook использует существующую `webhook_events` с `provider='max'`.
- Contact-button и voice/audio download adapter не входят в первый MVP и остаются later integration scope.

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
