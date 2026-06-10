# 2026-06-10 - MAX subscription still points to old domain

## Status

Open until the MAX webhook subscription is moved from the old domain to the new domain.

## Symptom

After deploying the new server for `https://max.ermantgz.ru`, the public MAX webhook health endpoint returns HTTP 200, but the MAX bot does not answer live messages.

## Finding

Read-only `scripts/max_status.py` shows:

- `subscriptions_count=1`
- subscription URL: `https://max.killrealp2.ru/webhooks/max`
- update types: `message_created`, `bot_started`

So MAX still sends live updates to the old server URL. The new endpoint is healthy but not yet subscribed.

## Required fix

On the new server:

1. Confirm `/opt/admin_niz2/.env` uses:
   - `MAX_WEBHOOK_URL=https://max.ermantgz.ru/webhooks/max`
   - `MAX_WEBHOOK_ENABLED=true`
   - `MAX_MODE=webhook`
2. Confirm public health:
   - `curl -i https://max.ermantgz.ru/webhooks/max`
3. Run:
   - `.venv/bin/python scripts/register_max_webhook.py --dry-run`
4. Run real apply only with explicit operator approval:
   - `.venv/bin/python scripts/register_max_webhook.py --apply`
5. Recheck:
   - `.venv/bin/python scripts/max_status.py`

Expected result: subscription URL becomes `https://max.ermantgz.ru/webhooks/max`.

## Related checks

Local fake checks are green for:

- `scripts/max_api_client_smoke.py`
- `scripts/max_inbound_normalization_smoke.py`
- `scripts/max_outbound_text_smoke.py`

These cover MAX typing action, inbound normalization, outbound text, and the fake voice/audio path. Live voice still needs a real MAX voice payload after subscription migration.
