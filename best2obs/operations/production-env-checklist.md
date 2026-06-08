# Production Env Checklist

Назначение: чеклист серверного `.env` перед MVP-релизом `best2`.

Источники правды: `.env.example`, `app/core/config.py`, [[architecture/auth]], [[architecture/api]], [[roadmap/release-context-window-steps]] и [[roadmap/max-context-window-steps]]. Секреты не записывать в git, wiki или чат; в этом файле фиксируются только имена переменных, ожидаемые режимы и признаки заполненности.

## Где хранить

- Серверный env хранить вне репозитория, например `/etc/best2/best2.env`.
- `systemd` должен читать его через `EnvironmentFile=/etc/best2/best2.env`.
- Локальный `.env` в репозитории не считать production-ready даже если `safe_summary()` выглядит рабочим.
- Не коммитить `.env`, токены, webhook-secret, ключи оплаты, DB-пароль и admin chat id.

## Обязательные production values

| Переменная | Production value / проверка | Заметка |
| --- | --- | --- |
| `APP_ENV` | `production` | Включает production-guard для YooKassa webhook secret. |
| `APP_DEBUG` | `false` | Не печатать лишнюю диагностику в production. |
| `APP_TIMEZONE` | `Europe/Moscow` | Используется для дат, TTL, sync freshness. |
| `SESSION_TTL_HOURS` | `72` или осознанно выбранное значение | Должно совпадать с ожидаемым временем жизни диалога. |
| `HOLD_TTL_MINUTES` | `30` или осознанно выбранное значение | Клиентский резерв слота до оплаты. |
| `HANDOFF_TTL_MINUTES` | `60` или осознанно выбранное значение | Срок живого handoff-состояния. |
| `MESSAGE_SUMMARY_ENABLED` | `true` | Включает retention/summary старых сообщений. |
| `MESSAGE_SUMMARY_AFTER_HOURS` | `48` | Release target: хранить подробные сообщения до 48 часов. |
| `MESSAGE_SUMMARY_INTERVAL_SECONDS` | `3600` или осознанно выбранное значение | Частота фонового summary loop. |
| `MESSAGE_SUMMARY_BATCH_CONVERSATIONS` | `20` или осознанно выбранное значение | Размер batch для фонового summary. |
| `HTTP_TRUST_ENV` | `false` | Не подхватывать случайные proxy env для HTTP-клиентов. |
| `LOG_LEVEL` | `INFO` | Для production без шумного debug. |

## PostgreSQL

| Переменная | Production value / проверка | Заметка |
| --- | --- | --- |
| `DB_HOST` | заполнен серверным host | Не использовать случайный local host. |
| `DB_PORT` | `5432` если провайдер не требует другого | Beget managed PostgreSQL обычно `5432`. |
| `DB_NAME` | заполнен production DB name | Проверить, что это именно база `best2`. |
| `DB_USER` | заполнен production user | Должен иметь права на нужные таблицы. |
| `DB_PASSWORD` | non-empty | Секрет, не печатать. |
| `DB_CHARSET` | `utf8` или значение из текущего окружения | В `config.py` default `utf8`, в `.env.example` указан `utf8mb4`; для PostgreSQL ключ фактически не основной. |
| `DB_SSLMODE` | `verify-full` / `verify-ca` по серверному сертификату | Не снижать SSL без отдельного решения. |
| `DB_SSLROOTCERT` | путь к CA-файлу, доступному process user | Например `~/.postgresql/root.crt` или абсолютный путь. |
| `DB_TARGET_SESSION_ATTRS` | `read-write` | Защита от случайного read-only replica. |
| `DB_CONNECT_TIMEOUT` | `15` или осознанно выбранное значение | Должно быть достаточно для managed DB. |
| `DB_POOL_ENABLED` | `true` | Production должен использовать pool. |
| `DB_POOL_MIN` | `1` | Минимум соединений. |
| `DB_POOL_MAX` | `5` или осознанно выбранное значение | Не завышать без проверки лимитов DB. |

## Telegram

| Переменная | Production value / проверка | Заметка |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | non-empty | Секрет, не печатать. |
| `TELEGRAM_WEBHOOK_URL` | пусто | Код сейчас работает через polling, не Telegram webhook mode. |
| `ADMIN_TELEGRAM_CHAT_ID` | заполнен реальным admin chat id | Нужен для handoff, оплат, ошибок YCLIENTS/AI и refund notices. |

Перед стартом polling `scripts/telegram_status.py` должен показывать пустой `webhook_url`; иначе polling может не получать updates.

## MAX client channel

Эти поля являются production target для MAX-срезов из [[roadmap/max-context-window-steps]]. Config/runtime support уже есть, но сам факт заполненных переменных не равен launch gate: webhook не регистрировать и не открывать клиентский MAX production-трафик, пока отдельным шагом не подтверждено, что внутренний MAX webhook runner запущен, reverse proxy ведет на него, а `scripts/max_status.py` видит ожидаемую подписку.

| Переменная | Production value / проверка | Заметка |
| --- | --- | --- |
| `MAX_BOT_TOKEN` | non-empty, когда включен MAX | Секрет, не печатать. |
| `MAX_API_BASE_URL` | `https://platform-api.max.ru` | Не передавать token в query string. |
| `MAX_MODE` | `webhook` в production, `polling` только dev/test | Нельзя одновременно polling и webhook для одного MAX-бота. |
| `MAX_WEBHOOK_ENABLED` | `true` для production MAX webhook | Не включать до готового HTTPS endpoint, secret и подтвержденного startup MAX runner. |
| `MAX_WEBHOOK_HOST` | `127.0.0.1` за reverse proxy | `0.0.0.0` допустим только с firewall; внутренний порт не должен торчать наружу напрямую. |
| `MAX_WEBHOOK_PORT` | `8089` или выбранный локальный порт | Должен совпадать с reverse proxy `proxy_pass`. |
| `MAX_WEBHOOK_PATH` | `/webhooks/max` | Должен совпадать с reverse proxy и registration script. |
| `MAX_WEBHOOK_URL` | public HTTPS URL с path `/webhooks/max`, без query/fragment и без явного порта | Требуется публичный `443` и trusted TLS certificate. |
| `MAX_WEBHOOK_SECRET` | non-empty для production webhook, 5-256 символов `[A-Za-z0-9_-]` | Передается в MAX subscription и проверяется через `X-Max-Bot-Api-Secret`. |
| `MAX_WEBHOOK_MAX_BODY_BYTES` | `32768` или меньше/равно proxy body limit | Proxy body limit не должен быть больше application limit без причины. |
| `CLIENT_CHANNELS` | `telegram,max` для режима рядом с Telegram | Telegram остается рабочим клиентским каналом. |

Step 10 уже добавил MAX media upload и link-button для payment URL, а 2026-06-05 parity slice добавил первый MAX voice/audio adapter с fallback. Contact `request_contact` остается later. Для production env это значит: медиа/кнопки проверяются smoke-ами, voice нужно подтвердить реальным MAX payload sample, а contact не является blocker текущего запуска.

## AI / Voice

| Переменная | Production value / проверка | Заметка |
| --- | --- | --- |
| `AI_PROVIDER` | `openrouter` или осознанно выбранный provider | Текущий основной путь - OpenAI-compatible client. |
| `OPENROUTER_API_KEY` | non-empty при `AI_PROVIDER=openrouter` | Секрет, не печатать. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Default в `.env.example` и `config.py`. |
| `OPENAI_API_KEY` | non-empty только если нужен OpenAI provider | Не обязателен для OpenRouter-only режима. |
| `OPENAI_MODEL` | `anthropic/claude-sonnet-4` или актуально выбранная модель | Зафиксировать осознанно перед релизом. |
| `OPENAI_TEMPERATURE` | `0.2` | Текущий стабильный режим. |
| `OPENAI_MAX_TOKENS` | `700` | Текущий лимит ответа. |
| `VOICE_TRANSCRIPTION_ENABLED` | `true` или осознанно `false` | Если voice smoke входит в релиз, должно быть `true`. |
| `VOICE_TRANSCRIPTION_PROVIDER` | `openrouter` или выбранный provider | Проверить ключи provider. |
| `VOICE_TRANSCRIPTION_MODEL` | `openai/whisper-large-v3` | Текущий `.env.example`. |
| `VOICE_TRANSCRIPTION_LANGUAGE` | `ru` | Русская транскрипция. |
| `VOICE_TRANSCRIPTION_MAX_SECONDS` | `120` | Ограничение на длину voice. |

## YCLIENTS

| Переменная | Production value / проверка | Заметка |
| --- | --- | --- |
| `YCLIENTS_BASE_URL` | `https://api.yclients.com/api/v1` | Default API endpoint. |
| `YCLIENTS_PARTNER_TOKEN` | non-empty | Секрет, не печатать. |
| `YCLIENTS_USER_TOKEN` | non-empty | Секрет, не печатать. |
| `YCLIENTS_COMPANY_ID` | non-empty | ID production company. |
| `YCLIENTS_SYNC_ENABLED` | `true` | Release target: локальный cache должен обновляться фоновым loop. |
| `YCLIENTS_SYNC_INTERVAL_SECONDS` | `5` или осознанно выбранное значение | `.env.example` использует `5`; если переменную опустить, `config.py` default будет `60`. |
| `YCLIENTS_SYNC_DAYS_BACK` | `1` | Окно sync назад. |
| `YCLIENTS_SYNC_DAYS_FORWARD` | `60` | Окно sync вперед. |

После старта `scripts/yclients_sync_status.py --strict` должен быть fresh, `last_error=None`, `records_seen` больше нуля.

## YooKassa / предоплата

| Переменная | Production value / проверка | Заметка |
| --- | --- | --- |
| `PAYMENT_PROVIDER` | `yookassa` | Иначе payment runner пропускает YooKassa sync. |
| `PAYMENT_SHOP_ID` | non-empty | Секретная платежная конфигурация. |
| `PAYMENT_SECRET_KEY` | non-empty | Секрет, не печатать. |
| `PAYMENT_SUCCESS_URL` | production URL | Куда клиент возвращается после оплаты. |
| `PAYMENT_FAIL_URL` | production URL | Куда клиент возвращается при отмене/ошибке. |
| `PREPAYMENT_MODE` | `percent` | Release target: production предоплата считается процентом. |
| `PREPAYMENT_PERCENT` | `50` | Release target: 50%. |
| `PREPAYMENT_AMOUNT_RUB` | не управляет production-суммой при `PREPAYMENT_MODE=percent` | Может оставаться заполненным, но не должен использоваться как production сумма. |
| `PAYMENT_STATUS_SYNC_ENABLED` | `true` | Fallback polling статусов оплаты. |
| `PAYMENT_STATUS_SYNC_INTERVAL_SECONDS` | `60` или осознанно выбранное значение | Не ставить слишком редко перед release smoke. |

## YooKassa webhook

| Переменная | Production value / проверка | Заметка |
| --- | --- | --- |
| `YOOKASSA_WEBHOOK_ENABLED` | `true` | Release target: webhook runner стартует вместе с `main.py`. |
| `YOOKASSA_WEBHOOK_HOST` | `127.0.0.1` за reverse proxy, либо `0.0.0.0` только с firewall | Внутренний порт не должен быть открыт наружу напрямую. |
| `YOOKASSA_WEBHOOK_PORT` | `8088` или выбранный локальный порт | Reverse proxy должен вести на этот порт. |
| `YOOKASSA_WEBHOOK_PATH` | `/webhooks/yookassa` | `register_yookassa_webhook.py` требует этот path в public URL. |
| `YOOKASSA_WEBHOOK_SECRET` | non-empty | Обязателен при `APP_ENV=production`; проверяется через `X-Webhook-Secret` или query `secret`. |
| `YOOKASSA_WEBHOOK_MAX_BODY_BYTES` | `32768` или меньше/равно proxy body limit | Proxy limit не должен быть больше application limit без причины. |
| `YOOKASSA_WEBHOOK_URL` | public HTTPS URL с path `/webhooks/yookassa` | Если proxy не добавляет `X-Webhook-Secret`, URL должен включать query `?secret=...` вне git. |

Production endpoint должен быть доступен по HTTPS, а внутренний `8088` не должен быть открыт публично напрямую.

## Проверка safe summary

Локально на Windows:

```powershell
@'
from app.core.config import get_settings
s = get_settings()
print(s.safe_summary())
print({
    "admin_chat_configured": bool(s.admin_telegram_chat_id),
    "yookassa_webhook_secret_configured": bool(s.yookassa_webhook_secret),
    "yookassa_webhook_url_configured": bool(s.yookassa_webhook_url),
    "max_bot_configured": bool(s.max_bot_token),
    "max_webhook_secret_configured": bool(s.max_webhook_secret),
    "max_webhook_url_configured": bool(s.max_webhook_url),
})
'@ | .\.venv\Scripts\python.exe -
```

На сервере перед ручными проверками:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python - <<'PY'
from app.core.config import get_settings
s = get_settings()
print(s.safe_summary())
print({
    "admin_chat_configured": bool(s.admin_telegram_chat_id),
    "yookassa_webhook_secret_configured": bool(s.yookassa_webhook_secret),
    "yookassa_webhook_url_configured": bool(s.yookassa_webhook_url),
    "max_bot_configured": bool(s.max_bot_token),
    "max_webhook_secret_configured": bool(s.max_webhook_secret),
    "max_webhook_url_configured": bool(s.max_webhook_url),
})
PY
```

Эта проверка показывает только безопасную сводку и boolean-признаки секретов. Она не доказывает, что server env production-ready: значения нужно сверить вручную по чеклисту выше.

## Stop conditions

- Любой production secret оказался записан в git/wiki/chat.
- `APP_ENV` не `production` на сервере.
- `PREPAYMENT_MODE` не `percent` или `PREPAYMENT_PERCENT` не `50`.
- `YOOKASSA_WEBHOOK_ENABLED=true`, но `YOOKASSA_WEBHOOK_SECRET` пустой.
- `YOOKASSA_WEBHOOK_URL` не HTTPS или path не `/webhooks/yookassa`.
- `ADMIN_TELEGRAM_CHAT_ID` пустой.
- Telegram `webhook_url` не пустой перед polling release.
- YCLIENTS strict-status stale после повторного sync и есть `last_error`.
- Для production MAX: `MAX_MODE` не `webhook`, `MAX_WEBHOOK_SECRET` пустой/невалидный, `MAX_WEBHOOK_URL` не HTTPS `/webhooks/max`, содержит query/fragment/явный порт, или тот же MAX-бот имеет активный polling.
- Для production MAX: reverse proxy не настроен на public HTTPS `443`, внутренний `MAX_WEBHOOK_PORT` открыт наружу напрямую, или `GET /subscriptions` показывает чужой/устаревший webhook URL.
- Для production MAX launch: webhook registration еще не выполнен отдельным явным шагом или внутренний MAX webhook runner фактически не стартует.
