# 2026-06-08 - Server SSH/HTTPS blocker for MAX production webhook

## Status

Resolved for MAX launch; SSH hardening remains.

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

2026-06-08 later maintenance recheck:

- Local private-key ACL was tightened so Windows OpenSSH no longer rejects the key file as too open.
- A fresh SSH repeat on port `2222` still failed intermittently: some attempts timed out during SSH banner exchange, others reached authentication and were denied. This blocked a current repeat of server-side MAX media fake smokes from the workstation.
- Public HTTPS/MAX launch state remains resolved from the earlier deploy; this is now a maintenance-access hardening issue, not a MAX webhook/media blocker.

2026-06-08 deploy-pull recheck after commit `6062725`:

- Public MAX webhook health from the workstation is green: `https://max.killrealp2.ru/webhooks/max` returns HTTP 200 with `service=max-webhook`.
- One repeat GET timed out, then the next GET returned HTTP 200; this should be treated as an intermittent public health symptom until server logs/nginx upstream timing can be inspected over SSH. `HEAD` returns the known `501 Unsupported method ('HEAD')`.
- `max_status.py` shows one active subscription for `https://max.killrealp2.ru/webhooks/max` with update types `message_created` and `bot_started`; `telegram_status.py` is OK with an empty Telegram webhook and pending updates `0`.
- SSH to `45.147.179.48` on `22` and `2222` reaches TCP, but maintenance login is not usable from Codex. Attempts either time out during SSH banner exchange or return `Permission denied (publickey,password)` for the local `best2_deploy_ed25519` key.
- Impact: commit `6062725` is pushed to GitHub, but `/opt/admin_niz2` could not be pulled/restarted by Codex. The server likely still runs the previous deployed code until an operator restores key auth or runs the deploy commands manually.

2026-06-08 webhook-path recheck after local full audit:

- DNS is correct: `max.killrealp2.ru` resolves to `45.147.179.48`; TCP `80` and `443` are reachable.
- `http://max.killrealp2.ru/webhooks/max` returns `301` to HTTPS.
- `https://max.killrealp2.ru/` returns nginx `404` quickly, so the HTTPS listener itself is alive.
- Exact `https://max.killrealp2.ru/webhooks/max` times out from the workstation, while `https://max.killrealp2.ru/webhooks/max/` reaches the app and returns JSON `{"ok": false, "error": "not_found"}`. Since the active MAX subscription URL is the exact no-slash path, this is a production delivery risk until checked on the server.
- `https://max.killrealp2.ru/webhooks/yookassa` returns nginx `404`, so the YooKassa webhook path is not proxied to the internal runner yet.

## Impact

The original blocker prevented Codex from uploading/configuring the app. It was resolved by using temporary key-based SSH on port `2222` and by configuring the existing cloned project under `/opt/admin_niz2`.

Step 12 MAX Launch Gate is now completed for the MAX production webhook slice: `best2.service` is active, `https://max.killrealp2.ru/webhooks/max` returns HTTP 200, and MAX subscriptions show one active subscription for `message_created` and `bot_started`.

## Likely Causes To Check On Server/Provider Panel

- `sshd` not running, stuck, firewalled after TCP accept, or bound behind a broken proxy/filter.
- SSH allowed only from a provider console/VPN/IP allowlist different from the current client route.
- nginx has an existing location/proxy for `/webhooks/max` pointing to a dead upstream.
- HTTPS listener/firewall/nginx SSL config is half-created or hanging during TLS handling.

## Needed Fix

Remaining cleanup:

1. keep or remove temporary SSH port `2222` after a stable maintenance access policy is chosen;
2. confirm password SSH is disabled as intended after no more emergency access is needed;
3. keep `fail2ban` active;
4. later harden `best2.service` graceful shutdown so a normal `systemctl restart` does not log `Client channel stopped unexpectedly: telegram`.
5. check exact nginx locations for `/webhooks/max` and `/webhooks/yookassa`; expected server-local probes are `curl -i http://127.0.0.1:8089/webhooks/max` -> `200 service=max-webhook` and `curl -i http://127.0.0.1:8088/webhooks/yookassa` -> `200 service=yookassa-webhook`.
