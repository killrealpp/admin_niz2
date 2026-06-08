# Production Runbook

Назначение: инструкция запуска, остановки и диагностики production `best2` на сервере с `systemd`.

Production-код этим runbook не меняется. Все секреты хранятся вне git, см. [[operations/production-env-checklist]].

## Базовые пути

Рекомендуемые server paths:

- код: `/opt/best2`;
- venv: `/opt/best2/.venv`;
- env file: `/etc/best2/best2.env`;
- systemd unit: `/etc/systemd/system/best2.service`;
- logs: `journalctl -u best2`.

Если выбран другой путь, заменить его во всех командах и зафиксировать в log.

## Pre-start checklist

Перед первым стартом или релизным restart:

- release freeze из [[roadmap/release-context-window-steps]] соблюден: не начинать новый refactor до launch gate;
- server env сверено по [[operations/production-env-checklist]];
- `.env`/секреты не лежат в git;
- dependencies установлены в `/opt/best2/.venv`;
- DB миграции применены штатным способом проекта;
- Telegram Bot API отвечает, `webhook_url` пустой;
- если включается MAX, `scripts/max_status.py` должен пройти без печати токена, а production MAX должен быть в webhook mode, не polling;
- YCLIENTS credentials рабочие, sync может получить записи;
- YooKassa credentials и webhook URL готовы, если webhook включается на этом шаге;
- нет второго `main.py`.

Базовая проверка кода перед server rollout:

```bash
cd /opt/best2
./.venv/bin/python -m compileall app scripts
./.venv/bin/python scripts/lint_best2info.py
./.venv/bin/python scripts/validate_yclients_map.py
```

## Проверить server env

Не печатать env целиком. Загружать env и смотреть только safe summary:

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

Ожидаемый production смысл:

- `app_env='production'`;
- `http_trust_env=False`;
- `telegram_configured=True`;
- `yclients_configured=True`;
- `payment_provider='yookassa'`;
- `payment_configured=True`;
- `prepayment_mode='percent'`;
- `prepayment_percent=50`;
- `yookassa_webhook_enabled=True`, если webhook уже должен быть активен;
- boolean-признаки admin chat, webhook secret и webhook URL равны `True`.
- Для MAX при подготовке production: `CLIENT_CHANNELS=telegram,max`, `MAX_MODE=webhook`, `MAX_WEBHOOK_ENABLED=true`, `MAX_WEBHOOK_HOST=127.0.0.1` за proxy, `MAX_WEBHOOK_PORT=8089` или выбранный внутренний порт, `MAX_WEBHOOK_URL` public HTTPS `/webhooks/max` без query/fragment/явного порта, `MAX_WEBHOOK_SECRET` заполнен и валиден для MAX subscription. Не считать это launch gate, пока webhook не зарегистрирован отдельным подтвержденным шагом и `scripts/max_status.py` не видит ожидаемую subscription.

## Развернуть код

Один раз при подготовке сервера:

```bash
sudo mkdir -p /opt/best2 /etc/best2
sudo chown -R best2:best2 /opt/best2
cd /opt/best2
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

Env file создать вручную вне git:

```bash
sudo install -o root -g best2 -m 0640 /path/to/prepared-best2.env /etc/best2/best2.env
```

Миграции/инициализацию БД выполнять только осознанно и по production env:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/init_db.py
./.venv/bin/python scripts/test_db.py
```

`scripts/test_db.py` создает и удаляет smoke user `test_smoke_user`; это допустимый DB smoke, но все равно писать результат в log.

## systemd unit

Пример `/etc/systemd/system/best2.service`:

```ini
[Unit]
Description=best2 Telegram booking bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=best2
Group=best2
WorkingDirectory=/opt/best2
EnvironmentFile=/etc/best2/best2.env
ExecStart=/opt/best2/.venv/bin/python /opt/best2/main.py
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Применить unit:

```bash
sudo systemctl daemon-reload
sudo systemctl enable best2
```

## Запустить один `main.py`

Перед стартом:

```bash
pgrep -af "python.*main.py" || true
systemctl status best2 --no-pager
```

Если уже есть живой `main.py`, сначала понять, кто его запустил. Не держать одновременно ручной polling и `systemd`.

Старт:

```bash
sudo systemctl start best2
sudo systemctl status best2 --no-pager
journalctl -u best2 -n 100 --no-pager
```

Через 1-2 минуты:

```bash
pgrep -af "python.*main.py"
journalctl -u best2 -n 150 --no-pager
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/telegram_status.py
./.venv/bin/python scripts/yclients_sync_status.py --strict
./.venv/bin/python scripts/live_health_report.py
```

Ожидается один process `main.py`, сообщения о старте Telegram polling, YCLIENTS loop и payment status loop. Если YooKassa webhook включен, должен быть log о `YooKassa webhook server started`. Если MAX production webhook включен, должен быть log о старте MAX webhook channel/listener.

## Проверить Telegram API

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/telegram_status.py
```

OK:

- `username` совпадает с production bot;
- `webhook_url` пустой, потому что бот работает polling mode;
- `pending_update_count` не растет бесконтрольно.

Если `webhook_url` не пустой, не открывать пользователей: polling может не получать updates. Сначала очистить Telegram webhook штатным способом и повторить `telegram_status.py`.

## Проверить MAX status и mode

MAX добавляется рядом с Telegram. Admin notifications MVP остаются в Telegram.

Безопасная status-проверка не регистрирует webhook и не вызывает `POST /subscriptions`:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/max_status.py
```

OK:

- `GET /me` отвечает по `https://platform-api.max.ru`;
- `GET /subscriptions` показывает ожидаемый webhook state;
- token не печатается в output или logs.

Если `MAX_BOT_TOKEN` пустой, скрипт должен завершиться `status='skipped'`. Это нормально для серверов, где MAX еще не включен.

Dev polling:

- допустим только для локального/dev smoke;
- не запускать при `APP_ENV=production` или `MAX_MODE=webhook`;
- не запускать, если у того же MAX-бота уже активен webhook subscription.

### MAX reverse proxy / HTTPS

Production MAX webhook должен быть доступен только как public HTTPS `https://DOMAIN/webhooks/max` на внешнем `443`. В URL не указывать порт, query или fragment. TLS-сертификат должен быть от доверенного CA, с корректным CN/SAN и полной chain.

Внутренний listener должен быть закрыт от внешнего интернета. Рекомендуемый env:

```bash
MAX_WEBHOOK_ENABLED=true
MAX_MODE=webhook
MAX_WEBHOOK_HOST=127.0.0.1
MAX_WEBHOOK_PORT=8089
MAX_WEBHOOK_PATH=/webhooks/max
MAX_WEBHOOK_URL=https://DOMAIN/webhooks/max
```

Пример Nginx location:

```nginx
location = /webhooks/max {
    proxy_pass http://127.0.0.1:8089/webhooks/max;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 35s;
    client_max_body_size 32k;
}
```

Проверки до registration:

```bash
curl -i https://DOMAIN/webhooks/max
ss -ltnp | grep 8089 || true
```

OK для GET: HTTP 200 и JSON `service: max-webhook`. Внутренний порт `8089` должен слушать только `127.0.0.1:8089` либо быть закрыт firewall. С 2026-06-07 `main.py` умеет стартовать MAX webhook runner через общий runtime при `CLIENT_CHANNELS=telegram,max`, `MAX_MODE=webhook`, `MAX_WEBHOOK_ENABLED=true` и `MAX_WEBHOOK_SECRET`; перед регистрацией все равно отдельно подтвердить, что production runtime действительно запущен и proxy ведет на живой listener.

### MAX webhook registration

Сначала всегда dry-run:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/register_max_webhook.py --dry-run
```

Dry-run должен показать:

- `calls_max_api=false`;
- `method=POST`;
- `path=/subscriptions`;
- `url=https://DOMAIN/webhooks/max`;
- `update_types=["message_created", "bot_started"]`;
- `secret_configured=true`;
- `token_configured=true`.

Реальную регистрацию выполнять только после отдельного явного подтверждения на launch/ops шаге:

```bash
./.venv/bin/python scripts/register_max_webhook.py --apply
./.venv/bin/python scripts/max_status.py
```

Эта команда делает `POST /subscriptions` с body `url`, `update_types`, `secret`; token уходит только в `Authorization` header. После регистрации `scripts/max_status.py` должен показать ожидаемый URL. Не запускать `scripts/max_dev_polling_smoke.py` для этого же бота, пока webhook subscription активна.

### MAX rollback / unsubscribe

Rollback нужен, если webhook URL ошибочный, listener не отвечает 200, MAX retries сыпятся в journal, или нужно вернуться к dev polling для диагностики.

Сначала dry-run:

```bash
./.venv/bin/python scripts/register_max_webhook.py --unsubscribe --dry-run
```

Реальную отписку выполнять только после отдельного явного подтверждения:

```bash
./.venv/bin/python scripts/register_max_webhook.py --unsubscribe --apply
./.venv/bin/python scripts/max_status.py
```

После rollback:

- `GET /subscriptions` не должен показывать удаленный URL;
- `MAX_WEBHOOK_ENABLED` можно оставить для будущего запуска только если listener больше не принимает внешний трафик, иначе выключить и перезапустить service;
- dev polling разрешен только вне production и только когда active webhook subscription отсутствует.

Текущий MAX scope после 2026-06-05 parity slice: проверить текстовый smoke, fake media/button smoke и MAX voice fallback/transcription smoke. Contact `request_contact` не входит в launch scope без отдельного запроса; реальный MAX voice payload нужно подтвердить live smoke-ом.

## Проверить YCLIENTS sync

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/yclients_sync_status.py --strict
```

OK:

- `fresh=True`;
- `last_error=None`;
- `records_seen` больше нуля;
- `age_seconds` меньше `max_age_seconds`.

Если stale:

```bash
./.venv/bin/python scripts/sync_yclients_records.py --once
./.venv/bin/python scripts/yclients_sync_status.py --strict
journalctl -u best2 -n 150 --no-pager | grep -i yclients || true
```

Если после повторного sync `last_error` сохраняется, считать это infra/integration blocker, а не поводом менять бизнес-логику.

## Проверить YooKassa webhook

Application hardening smoke без внешних side effects:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/yookassa_webhook_hardening_smoke.py
./.venv/bin/python scripts/yookassa_status.py
```

Reverse proxy должен давать public HTTPS endpoint:

```bash
curl -i https://DOMAIN/webhooks/yookassa
```

OK для GET: HTTP 200 и JSON с `service: yookassa-webhook`.

Перед регистрацией проверить env:

- `YOOKASSA_WEBHOOK_ENABLED=true`;
- `YOOKASSA_WEBHOOK_SECRET` non-empty;
- `YOOKASSA_WEBHOOK_URL` public HTTPS URL с path `/webhooks/yookassa`;
- если proxy не добавляет `X-Webhook-Secret`, в registered URL должен быть query `?secret=...` вне git;
- локальный порт `8088` не открыт наружу напрямую.

Сначала всегда dry-run:

```bash
./.venv/bin/python scripts/register_yookassa_webhook.py --dry-run
```

Dry-run должен показать:

- `calls_yookassa_api=false`;
- `method=POST`;
- `path=/webhooks`;
- `events=["payment.succeeded", "payment.canceled"]`;
- `payment_configured=true`;
- `webhook_enabled=true`;
- `webhook_secret_configured=true`;
- `url` без раскрытия query-secret.

Реальную регистрацию выполнять только на production-сервере после отдельного явного подтверждения:

```bash
./.venv/bin/python scripts/register_yookassa_webhook.py --apply
./.venv/bin/python scripts/yookassa_status.py
```

OK: зарегистрированы события `payment.succeeded` и `payment.canceled`, `journalctl -u best2` без webhook startup/processing errors.

## Проверить DB и hygiene

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/live_health_report.py
./.venv/bin/python scripts/db_status.py
./.venv/bin/python scripts/live_db_hygiene_audit.py --limit 20
```

`live_health_report.py` read-only: проверяет DB connectivity, freshness YCLIENTS, runtime counts, active holds, pending payments, paid notification gaps, `journal_missing`/`yclients_create_error`, pending `refund_required` и последние system logs. Exit 0 означает, что blocker-ов нет; warnings требуют внимания, но не всегда блокируют live production. `db_status.py` печатает host/db/user и count таблиц. `live_db_hygiene_audit.py` read-only и должен завершиться exit 0 с пустыми проблемными списками.

## Остановить процесс

Штатно:

```bash
sudo systemctl stop best2
sudo systemctl status best2 --no-pager
pgrep -af "python.*main.py" || true
```

Если `main.py` остался жив после stop, сначала проверить parent/unit:

```bash
ps -fp PID
```

Ручной `kill` использовать только после подтверждения, что это лишний процесс `best2`, а не другой Python job.

## Stale sync

Симптомы:

- `scripts/yclients_sync_status.py --strict` exit 1;
- `fresh=False`;
- `last_error` заполнен;
- в journal есть `YCLIENTS records sync failed`.

Действия:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/sync_yclients_records.py --once
./.venv/bin/python scripts/yclients_sync_status.py --strict
journalctl -u best2 -n 200 --no-pager | grep -i yclients || true
```

Если ручной sync OK, подождать один interval и повторить strict-status. Если ручной sync падает, проверить токены, `YCLIENTS_COMPANY_ID`, сеть и ответ API. Не запускать regression/live smoke до fresh sync.

## DB timeout / connection failures

Симптомы:

- `scripts/test_db.py` или `scripts/db_status.py` падает;
- journal показывает timeout, SSL или pool errors;
- бот не отвечает после старта.

Действия:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/test_db.py
./.venv/bin/python scripts/db_status.py
journalctl -u best2 -n 200 --no-pager | grep -Ei "db|database|pool|timeout|ssl|connection" || true
```

Проверить:

- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`;
- `DB_SSLMODE` и доступность `DB_SSLROOTCERT` для user `best2`;
- лимиты managed PostgreSQL и `DB_POOL_MAX`;
- сетевой доступ с сервера к DB host.

Если проблема похожа на transient, повторить диагностику. Не выполнять `clear_db.py` как реакцию на timeout.

## Paid-but-journal-pending

Симптомы:

- клиент получил `Оплата поступила`, но финальное подтверждение не пришло;
- `payments.status='paid'`, но `payments.payment_notified_at IS NULL`;
- у booking нет `yclients_record_id`;
- в `system_logs` есть `payment_paid_journal_pending`;
- у booking заполнен `yclients_create_error`.

Первичная диагностика:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/sync_payment_statuses.py
./.venv/bin/python scripts/yclients_sync_status.py --strict
./.venv/bin/python scripts/live_db_hygiene_audit.py --limit 20
journalctl -u best2 -n 250 --no-pager | grep -Ei "payment_paid_journal_pending|yclients_create|payment|webhook" || true
```

Ожидаемое поведение: `sync_payment_statuses.py` вызывает retry статусов оплаты и `create_missing_yclients_records`. Если YCLIENTS восстановился, запись должна создаться, затем клиент получит финальное подтверждение, а `payment_notified_at` заполнится.

Если retry не помогает:

- не создавать дубль оплаты и не создавать вторую бронь автоматически;
- проверить `yclients_create_error` и доступность услуги/ресурса в YCLIENTS;
- вручную сверить слот в YCLIENTS;
- если запись нужно создать вручную, зафиксировать это в log и убедиться, что клиент/admin уведомлены;
- если деньги пришли, а бронь невозможно закрепить, это blocker для ручного решения и потенциального возврата.

## Refund required

Симптомы:

- `system_logs.event_type='refund_required'`;
- `live_db_hygiene_audit.py` показывает `refund_required_without_admin_notified_at`;
- отмена paid booking подпадает под правила возврата.

Действия:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/live_db_hygiene_audit.py --limit 20
journalctl -u best2 -n 200 --no-pager | grep -i refund || true
```

Проверить, что admin notification дошел в `ADMIN_TELEGRAM_CHAT_ID`. Если не дошел, руками передать admin данные брони и отметить проблему в [[bugs/current-known-issues]].

## Очистить тестовые записи YCLIENTS

Скрипт по умолчанию dry-run. Сначала всегда смотреть candidates:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/cleanup_yclients_test_records.py --phone 79990000000
```

Другие селекторы:

```bash
./.venv/bin/python scripts/cleanup_yclients_test_records.py --external-id 123456789
./.venv/bin/python scripts/cleanup_yclients_test_records.py --name-contains "TEST"
./.venv/bin/python scripts/cleanup_yclients_test_records.py --external-id-prefix local_regression_
```

Удалять только после визуальной сверки списка:

```bash
./.venv/bin/python scripts/cleanup_yclients_test_records.py --phone 79990000000 --apply
./.venv/bin/python scripts/sync_yclients_records.py --once
./.venv/bin/python scripts/yclients_sync_status.py --strict
```

`--all-bot-bookings --apply` не использовать на production без отдельного явного решения.

## Cleanup локальной БД после тестов

До открытия реальных пользователей, после DB-mutating smoke/regression можно выполнить общий cleanup из release plan:

```bash
cd /opt/best2
set -a
source /etc/best2/best2.env
set +a
./.venv/bin/python scripts/clear_db.py
./.venv/bin/python scripts/sync_yclients_records.py --once
./.venv/bin/python scripts/yclients_sync_status.py --strict
./.venv/bin/python scripts/live_db_hygiene_audit.py --limit 20
```

После go-live `scripts/clear_db.py` не запускать без отдельного явного решения: он чистит runtime-таблицы и может удалить реальные диалоги/брони.

## Минимальный post-start report

После каждого production restart записать в [[log]]:

- дату/время и причину restart;
- git revision или dirty-tree snapshot;
- `systemctl status best2` summary;
- `telegram_status.py`: bot username, empty `webhook_url`, pending count;
- `yclients_sync_status.py --strict`: `fresh`, `records_seen`, `last_error`;
- `live_health_report.py`: `status`, blockers, warnings;
- `live_db_hygiene_audit.py --limit 20`: clean или список blocker;
- webhook status/registration, если трогали YooKassa;
- MAX status/subscription summary, если MAX включен или проверялся;
- известные residual risks.
