# 2026-06-08 - YooKassa payment enable blockers

## Status

Open for production deployment. Code safety helpers are local/committed, but live payment enablement is still blocked by credentials/connectivity and server proxy setup.

## Findings

- Payment code already supports YooKassa payment links through `create_payment_link_for_holds()` after booking confirmation.
- The current production MAX launch had deliberately disabled real YooKassa runtime actions: `PAYMENT_PROVIDER=disabled`, payment status sync disabled and YooKassa webhook disabled.
- Local `.env` was updated to the intended payment mode (`PREPAYMENT_MODE=percent`, `PREPAYMENT_PERCENT=50`, non-empty webhook secret, bot webhook URL), but server `/opt/admin_niz2/.env` must be updated separately by the operator.
- Live payment creation produced a failed `payments` row with YooKassa `401 invalid_credentials`, so the server `PAYMENT_SHOP_ID` or `PAYMENT_SECRET_KEY` is wrong/invalid for the configured shop.
- Read-only `scripts/yookassa_status.py` attempted `GET /webhooks` and hit an SSL handshake timeout from the workstation. This did not create a payment and did not register a webhook, but server-side connectivity still needs to be checked.
- Public `https://max.killrealp2.ru/webhooks/yookassa` currently returns nginx `404`, so nginx does not yet proxy the YooKassa path to the internal webhook runner.

## Local Fixes

- `scripts/register_yookassa_webhook.py` is dry-run by default and requires `--apply` for real `POST /webhooks`.
- `scripts/yookassa_status.py` was added for read-only YooKassa webhook/status checks with secret redaction.
- Payment-status replies now skip external YooKassa sync when a local payment is already `paid`, avoiding slow/transient external calls before answering paid users.

## Needed For Production

- Server env should set `PAYMENT_PROVIDER=yookassa`.
- Production prepayment should use `PREPAYMENT_MODE=percent` and `PREPAYMENT_PERCENT=50`, not local `PREPAYMENT_AMOUNT_RUB=1`.
- Server env needs non-empty `YOOKASSA_WEBHOOK_SECRET`.
- Public URL should be `https://max.killrealp2.ru/webhooks/yookassa?secret=...` or another trusted HTTPS domain/path that matches `YOOKASSA_WEBHOOK_PATH=/webhooks/yookassa`.
- nginx must proxy `/webhooks/yookassa` to the internal YooKassa runner port (`127.0.0.1:8088` by current convention).
- `PAYMENT_STATUS_SYNC_ENABLED=true` should be enabled as a fallback even after webhook registration.
- Run `scripts/register_yookassa_webhook.py --dry-run` first; real `--apply` needs a separate explicit production confirmation.

## Verification

- `scripts/yookassa_webhook_hardening_smoke.py` passed locally.
- `scripts/register_yookassa_webhook.py --dry-run --url https://max.killrealp2.ru/webhooks/yookassa?secret=placeholder` passed and did not call YooKassa API.
- `scripts/register_yookassa_webhook.py --dry-run` passes locally with the current redacted URL and does not call YooKassa API.
- `scripts/local_regression_suite.py --group payments` passed after paid-state sync stabilization.
