# 2026-06-08 - Server SSH/HTTPS blocker for MAX production webhook

## Status

Open.

## Context

MAX production launch needs a public HTTPS endpoint:

- `https://max.killrealp2.ru/webhooks/max`
- nginx reverse proxy on external 443
- internal best2 MAX webhook runner on `127.0.0.1:8089/webhooks/max`
- active MAX subscription registered only after endpoint verification

DNS is already propagated: `max.killrealp2.ru` resolves to `45.147.179.48`.

## Symptoms

- TCP port `22` is reachable, but SSH does not send a protocol banner and times out before authentication.
- `http://max.killrealp2.ru/` returns `301` from `nginx/1.24.0 (Ubuntu)` to HTTPS.
- `http://max.killrealp2.ru/webhooks/max` hangs until timeout.
- `https://max.killrealp2.ru/` and `https://max.killrealp2.ru/webhooks/max` hang until timeout.

2026-06-08 recheck:

- TCP ports `22`, `80` and `443` are reachable.
- SSH still fails before authentication: Paramiko receives a connection reset before the SSH banner, and OpenSSH/`ssh-keyscan` time out.
- `http://max.killrealp2.ru/` now returns HTTP 200 from nginx with a static page.
- HTTPS still times out; `https://max.killrealp2.ru/webhooks/max` is still not a valid MAX webhook endpoint.

## Impact

Codex cannot upload `/opt/best2`, create `/etc/best2/best2.env`, install dependencies, configure nginx/certbot/systemd, start the MAX webhook runner, or safely run `register_max_webhook.py --apply`.

Step 12 MAX Launch Gate remains open. MAX subscriptions remain `0`.

## Likely Causes To Check On Server/Provider Panel

- `sshd` not running, stuck, firewalled after TCP accept, or bound behind a broken proxy/filter.
- SSH allowed only from a provider console/VPN/IP allowlist different from the current client route.
- nginx has an existing location/proxy for `/webhooks/max` pointing to a dead upstream.
- HTTPS listener/firewall/nginx SSL config is half-created or hanging during TLS handling.

## Needed Fix

Restore working SSH or provide a provider web console/alternate SSH port. After access works, continue with:

1. deploy current best2 to `/opt/best2`;
2. create `/etc/best2/best2.env` from the current local env with production MAX webhook settings;
3. install venv dependencies;
4. configure nginx HTTPS 443 for `max.killrealp2.ru`;
5. start `best2.service`;
6. verify `curl -i https://max.killrealp2.ru/webhooks/max` returns HTTP 200 with `service=max-webhook`;
7. run `scripts/register_max_webhook.py --dry-run`;
8. run `scripts/register_max_webhook.py --apply` only after the endpoint is green.
