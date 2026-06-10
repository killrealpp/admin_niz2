# Deploy best2 to a new server for max.ermantgz.ru

This runbook is for moving `best2` to a fresh Ubuntu server with the public webhook domain:

```text
https://max.ermantgz.ru
```

It does not store secrets. Put real tokens only into `/etc/best2/best2.env` on the server.

## What changes with the new domain

Update production env from the old domain to the new one:

```env
MAX_WEBHOOK_URL=https://max.ermantgz.ru/webhooks/max
YOOKASSA_WEBHOOK_URL=https://max.ermantgz.ru/webhooks/yookassa?secret=<YOOKASSA_WEBHOOK_SECRET>
```

Update nginx `server_name`:

```nginx
server_name max.ermantgz.ru;
```

If MAX currently has an active subscription to the old URL, MAX will keep sending updates to that old URL until the subscription is changed. For a changed URL:

1. Start the new server and verify `https://max.ermantgz.ru/webhooks/max` returns HTTP 200.
2. Run `scripts/register_max_webhook.py --dry-run`.
3. Run real `--apply` only after explicit operator approval.

For YooKassa, HTTP notification URL is configured manually in the YooKassa dashboard. If the URL changes, update it there to:

```text
https://max.ermantgz.ru/webhooks/yookassa?secret=<YOOKASSA_WEBHOOK_SECRET>
```

## 1. DNS

Create an A record:

```text
max.ermantgz.ru -> NEW_SERVER_IP
```

Wait until the domain resolves to the new IP:

```bash
getent hosts max.ermantgz.ru
```

## 2. Base packages

```bash
apt update
apt upgrade -y
apt install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx curl wget ca-certificates ufw
```

## 3. Firewall

If SSH is on port `22`:

```bash
ufw allow 22/tcp
ufw allow 'Nginx Full'
ufw enable
ufw status
```

If SSH is on a custom port, allow that port before enabling UFW.

## 4. App user and directories

Recommended path for this project is `/opt/admin_niz2`, because the current production server already uses it.

```bash
adduser --system --group --home /opt/admin_niz2 best2
mkdir -p /opt/admin_niz2 /etc/best2
chown -R best2:best2 /opt/admin_niz2
```

## 5. Clone the repo

Replace `<REPO_URL>` with the real repository URL.

```bash
sudo -u best2 git clone <REPO_URL> /opt/admin_niz2
cd /opt/admin_niz2
```

## 6. Python environment

```bash
sudo -u best2 python3 -m venv /opt/admin_niz2/.venv
sudo -u best2 /opt/admin_niz2/.venv/bin/python -m pip install --upgrade pip
sudo -u best2 /opt/admin_niz2/.venv/bin/pip install -r /opt/admin_niz2/requirements.txt
```

## 7. Beget PostgreSQL CA certificate

Use an absolute path so systemd does not depend on `~` expansion:

```bash
wget -O /etc/ssl/certs/beget-cloud-ca.crt https://beget.com/cloud-ca.crt
chmod 0644 /etc/ssl/certs/beget-cloud-ca.crt
```

Production env should contain:

```env
DB_SSLROOTCERT=/etc/ssl/certs/beget-cloud-ca.crt
```

## 8. Production env

Create the env file:

```bash
nano /etc/best2/best2.env
```

Minimum production shape:

```env
APP_ENV=production
APP_DEBUG=false
APP_TIMEZONE=Europe/Moscow
CLIENT_CHANNELS=telegram,max

DB_HOST=<db-host>
DB_PORT=5432
DB_NAME=<db-name>
DB_USER=<db-user>
DB_PASSWORD=<db-password>
DB_SSLMODE=verify-full
DB_SSLROOTCERT=/etc/ssl/certs/beget-cloud-ca.crt
DB_TARGET_SESSION_ATTRS=read-write
DB_CONNECT_TIMEOUT=15

TELEGRAM_BOT_TOKEN=<telegram-token>
TELEGRAM_WEBHOOK_URL=

AI_PROVIDER=openrouter
OPENROUTER_API_KEY=<openrouter-key>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=anthropic/claude-sonnet-4
OPENAI_TEMPERATURE=0.2
OPENAI_MAX_TOKENS=700

YCLIENTS_BASE_URL=https://api.yclients.com/api/v1
YCLIENTS_PARTNER_TOKEN=<yclients-partner-token>
YCLIENTS_USER_TOKEN=<yclients-user-token>
YCLIENTS_COMPANY_ID=<yclients-company-id>
YCLIENTS_SYNC_ENABLED=true
YCLIENTS_SYNC_INTERVAL_SECONDS=60
YCLIENTS_SYNC_DAYS_BACK=1
YCLIENTS_SYNC_DAYS_FORWARD=60

MAX_BOT_TOKEN=<max-token>
MAX_WEBHOOK_SECRET=<max-webhook-secret>
MAX_WEBHOOK_URL=https://max.ermantgz.ru/webhooks/max
MAX_WEBHOOK_ENABLED=true
MAX_WEBHOOK_HOST=127.0.0.1
MAX_WEBHOOK_PORT=8089
MAX_WEBHOOK_PATH=/webhooks/max
MAX_MODE=webhook
MAX_SEND_RELATED_MEDIA=true

PAYMENT_PROVIDER=yookassa
PAYMENT_SHOP_ID=<yookassa-shop-id>
PAYMENT_SECRET_KEY=<yookassa-secret-key>
PREPAYMENT_MODE=percent
PREPAYMENT_PERCENT=50
PREPAYMENT_AMOUNT_RUB=2000
PAYMENT_STATUS_SYNC_ENABLED=true
PAYMENT_STATUS_SYNC_INTERVAL_SECONDS=10

YOOKASSA_WEBHOOK_ENABLED=true
YOOKASSA_WEBHOOK_HOST=127.0.0.1
YOOKASSA_WEBHOOK_PORT=8088
YOOKASSA_WEBHOOK_PATH=/webhooks/yookassa
YOOKASSA_WEBHOOK_SECRET=<random-secret>
YOOKASSA_WEBHOOK_URL=https://max.ermantgz.ru/webhooks/yookassa?secret=<same-random-secret>

ADMIN_TELEGRAM_CHAT_ID=<admin-chat-id>
LOG_LEVEL=INFO
```

Secure it:

```bash
chown root:best2 /etc/best2/best2.env
chmod 640 /etc/best2/best2.env
```

## 9. Systemd

Create `/etc/systemd/system/best2.service`:

```ini
[Unit]
Description=best2 Telegram and MAX bot runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=best2
Group=best2
WorkingDirectory=/opt/admin_niz2
EnvironmentFile=/etc/best2/best2.env
ExecStart=/opt/admin_niz2/.venv/bin/python /opt/admin_niz2/main.py
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Do not start it yet if the old production bot is still running with the same Telegram token.

## 10. Nginx and TLS

Create `/etc/nginx/sites-available/best2.conf` with HTTP only first:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name max.ermantgz.ru;

    location / {
        return 404;
    }
}
```

Enable it:

```bash
ln -s /etc/nginx/sites-available/best2.conf /etc/nginx/sites-enabled/best2.conf
nginx -t
systemctl reload nginx
```

Issue a certificate:

```bash
certbot --nginx -d max.ermantgz.ru
```

Then use this HTTPS server block:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name max.ermantgz.ru;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name max.ermantgz.ru;

    ssl_certificate /etc/letsencrypt/live/max.ermantgz.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/max.ermantgz.ru/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    client_max_body_size 64k;

    location = /webhooks/max {
        proxy_pass http://127.0.0.1:8089/webhooks/max;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 35s;
    }

    location = /webhooks/yookassa {
        proxy_pass http://127.0.0.1:8088/webhooks/yookassa;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 35s;
    }

    location / {
        return 404;
    }
}
```

Reload:

```bash
nginx -t
systemctl reload nginx
```

## 11. Preflight before start

```bash
cd /opt/admin_niz2
set -a
source /etc/best2/best2.env
set +a

.venv/bin/python -m compileall app scripts
.venv/bin/python scripts/db_status.py
.venv/bin/python scripts/yclients_sync_status.py --strict
.venv/bin/python scripts/telegram_status.py
.venv/bin/python scripts/max_status.py
.venv/bin/python scripts/yookassa_status.py
```

If the database is empty and tables are missing:

```bash
.venv/bin/python scripts/init_db.py
```

## 12. Cutover

Stop the old runtime before starting the new one, otherwise Telegram long polling can conflict:

```bash
systemctl stop best2.service
```

On the new server:

```bash
systemctl daemon-reload
systemctl enable --now best2.service
systemctl status best2.service --no-pager
journalctl -u best2.service -n 100 --no-pager
```

Verify local listeners:

```bash
ss -ltnp | grep -E '8088|8089'
```

Verify public endpoints:

```bash
curl -i https://max.ermantgz.ru/webhooks/max
curl -i https://max.ermantgz.ru/webhooks/yookassa
```

## 13. Release readiness

```bash
cd /opt/admin_niz2
set -a
source /etc/best2/best2.env
set +a

.venv/bin/python scripts/release_readiness_report.py --limit 5
```

For a temporary 1 RUB payment smoke, use this only during the controlled test:

```env
PREPAYMENT_MODE=fixed
PREPAYMENT_AMOUNT_RUB=1
```

Then run:

```bash
.venv/bin/python scripts/release_readiness_report.py --allow-fixed-test-prepayment --limit 5
```

After the test, restore:

```env
PREPAYMENT_MODE=percent
PREPAYMENT_PERCENT=50
PREPAYMENT_AMOUNT_RUB=2000
```
