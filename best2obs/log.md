# Project Log

## 2026-06-08 - MAX contextual photos widened and YooKassa payment enablement prepared locally

- User reported a second live MAX wording: after the gazebo discussion, "а покажете их?" still answered through the LLM fallback ("нет фотографий беседок") instead of deterministic media routing.
- Widened `contextual_photo_reply()` in `app/services/dialog/info_flow.py`: pronoun photo requests now resolve to gazebo photos when recent history contains either an assistant gazebo-options answer or a user's previous gazebo question. `scripts/dialog_contextual_photo_smoke.py` now covers both "покажете их?" and "а покажете их?", including user-only gazebo history.
- Prepared YooKassa operations without creating a real payment or registering webhooks: `scripts/register_yookassa_webhook.py` now defaults to dry-run and requires `--apply` for real `POST /webhooks`; `scripts/yookassa_status.py` lists redacted webhook/status data with read-only API calls.
- Stabilized paid payment replies: `message_handler_flow_glue.py` and `post_booking_flow.py` no longer call external YooKassa sync before answering when the local conversation already has a `paid` payment row. Pending payments still use sync.
- Safe checks passed: `compileall app scripts`, `dialog_contextual_photo_smoke.py`, `max_media_buttons_smoke.py`, `max_outbound_text_smoke.py`, `yookassa_webhook_hardening_smoke.py`, `register_yookassa_webhook.py --dry-run --url https://max.killrealp2.ru/webhooks/yookassa?secret=placeholder`, `local_regression_suite.py --case "paid booking payment question is deterministic"`, and `local_regression_suite.py --group payments`.
- Read-only `yookassa_status.py` hit an SSL handshake timeout to YooKassa from the local workstation. No payment was created and no webhook was registered; this remains a production enablement blocker until server-side connectivity is checked.
- Graphify update was attempted after code changes; it refreshed artifacts but again reported node-count protection (`220` vs `221`) and refused the final overwrite. No force overwrite was used.
- Production deployment/restart is still pending because current SSH maintenance access is blocked/flaky. Details: [[bugs/2026-06-08-max-webhook-media-background-task]], [[bugs/2026-06-08-yookassa-payment-enable-blockers]], [[bugs/2026-06-08-server-ssh-https-blocker]].

## 2026-06-08 - MAX contextual gazebo photo follow-up fixed locally

- User reported a live MAX case: after asking which gazebos are available, the follow-up "покажете их?" was treated as part of the current bathhouse draft/confirmation and returned the bathhouse booking summary instead of gazebo photos.
- Fixed locally by adding `contextual_photo_reply()` in `app/services/dialog/info_flow.py`. It detects contextual photo requests like "покажете их?" and, when the recent assistant history listed gazebo options, routes the message through the existing explicit gazebo photo path.
- Wired the same guard before `awaiting_confirmation` side replies in `app/services/message_handler.py`, so an active bathhouse confirmation state does not swallow a gazebo photo follow-up.
- Added `scripts/dialog_contextual_photo_smoke.py`; it covers the exact "gazebo list -> покажете их?" scenario, verifies the `awaiting_confirmation` wrapper path, and checks that gazebo media paths are selected.
- Local verification passed through the project venv: `compileall app scripts`, `dialog_contextual_photo_smoke.py`, `dialog_identity_smoke.py`, `max_media_buttons_smoke.py`, `max_outbound_text_smoke.py`, and `local_regression_suite.py --group media`.
- Graphify update was attempted after the code change; it refreshed graph artifacts but again reported node-count protection (`311` vs `312`) and refused the final overwrite. No force overwrite was used.
- Production deployment/restart is still pending because the current SSH maintenance path to the server is blocked/flaky. Details: [[bugs/2026-06-08-max-webhook-media-background-task]], [[bugs/2026-06-08-server-ssh-https-blocker]].

## 2026-06-08 - MAX webhook photo delivery bug fixed locally

- Reproduced the user's MAX symptom from code flow: the bot could send "сейчас отправлю фото" text from the shared dialog, but production MAX webhook processing used `asyncio.run()` while related media was scheduled as a background task. The temporary event loop closed before the media task could upload/send photos.
- A second live MAX failure was found from DB logs after the user tested "покажешь баню?": `system_logs.event_type='max_media_delivery_failed'`, image `banya.jpg`, error `MAX upload did not return attachment token`. Safe live upload check confirmed MAX returns `payload_keys=photos`, `photos_count=1`, `has_token=False`; the old parser incorrectly required a top-level token.
- Fixed the webhook lifecycle locally: `process_client_message()` now supports `await_related_media`, and `process_max_webhook_event()` enables it so MAX webhook worker processing waits for related media before closing its loop. The HTTP webhook handler still returns `200` quickly because processing already happens through the runner queue.
- Fixed MAX upload parsing locally: `MaxApiClient.upload_file()` accepts `photos` payloads, nested token payloads and upload URL token fallbacks.
- Added MAX outbound text sanitization so accidental `Telegram`/`телеграм` mentions are replaced before a client-facing MAX send. Also made runtime/system/response prompts channel-neutral: "client chat" instead of "Telegram".
- Added deterministic bot identity handling: "как тебя зовут" now answers "Меня зовут Любовь..." before calling the LLM, preventing the model from inventing "Бест".
- Added regression coverage to `scripts/max_media_buttons_smoke.py` for webhook related-media delivery and MAX `photos` upload payload, to `scripts/max_outbound_text_smoke.py` for MAX Telegram-mention sanitization, and to `scripts/dialog_identity_smoke.py` for the name answer.
- Local verification passed: compileall, `max_media_buttons_smoke.py`, `max_outbound_text_smoke.py`, `dialog_identity_smoke.py`, `max_inbound_normalization_smoke.py`, `max_webhook_runner_smoke.py`, `channel_contract_smoke.py`, `local_regression_suite.py --group media`, and read-only/safe live checks (`max_status.py` subscriptions `1`; MAX upload-only check for `banya.jpg` OK). No live user message or payment was sent during the upload check.
- Graphify update was attempted after code changes. The graph tool refused the final overwrite twice because of node-count mismatch protection (`234` vs `235`, then `169` vs `170`); no force overwrite was used.
- Production deployment is still pending because current SSH access to `45.147.179.48` is blocked/flaky: both `2222` and `22` timed out during banner exchange on the latest recheck. Details: [[bugs/2026-06-08-max-webhook-media-background-task]], [[bugs/2026-06-08-server-ssh-https-blocker]].

## 2026-06-08 - Reusable MAX/Telegram and server-access playbooks

- Created [[prompts/multi-channel-bot-integration-skill]] as a reusable AI instruction for future projects that need Telegram/MAX or other multi-channel entry/exit parity around one shared dialog core.
- Created [[operations/ai-remote-server-access-playbook]] as a reusable SSH/nginx/systemd/HTTPS access guide for safely giving an AI operator temporary access to a remote Linux server without sending passwords through chat.
- Rechecked MAX media/photo behavior through safe fake smokes. Local `scripts/max_media_buttons_smoke.py`, `scripts/max_outbound_text_smoke.py`, and `scripts/max_api_client_smoke.py` passed on this turn; the same server-side fake smokes had passed after the production deploy. A current repeat over SSH was blocked by the known flaky server SSH path (`2222` banner timeout / key auth denial), not by MAX media code. These checks verify adapter media/buttons/upload request shape without sending unsolicited live media to users.

## 2026-06-08 - MAX production webhook launched on server

- Production deployment completed on the remote server under `/opt/admin_niz2`.
- Access was restored through temporary key-based SSH on port `2222`; regular port `22` stayed flaky under SSH noise, so `2222` remains as the current maintenance access path. `fail2ban` was restarted and is active again.
- Server `.env` was adjusted for safe production runtime without printing secrets: `APP_ENV=production`, `CLIENT_CHANNELS=telegram,max`, `MAX_MODE=webhook`, `MAX_WEBHOOK_ENABLED=true`, `MAX_WEBHOOK_HOST=127.0.0.1`, `MAX_WEBHOOK_PORT=8089`, `MAX_WEBHOOK_PATH=/webhooks/max`, `MAX_SEND_RELATED_MEDIA=true`. Real YooKassa runtime actions were disabled for this launch: `PAYMENT_PROVIDER=disabled`, `PAYMENT_STATUS_SYNC_ENABLED=false`, `YOOKASSA_WEBHOOK_ENABLED=false`.
- Beget CA was installed at `/root/.postgresql/root.crt`; server dependencies were installed in `/opt/admin_niz2/.venv`.
- Server preflight passed: `compileall app scripts`, `db_status.py`, `max_status.py`, `telegram_status.py`, `register_max_webhook.py --dry-run`, YCLIENTS one-shot sync (`seen=133`, `upserted=133`), strict sync status, `live_health_report.py`, and `live_db_hygiene_audit.py --limit 20`.
- `best2.service` was created and enabled. It is active, starts Telegram polling and the MAX webhook runner, and listens internally on `127.0.0.1:8089`.
- nginx was configured with `/etc/nginx/sites-available/best2-max.conf` for `max.killrealp2.ru`, proxying `/webhooks/max` to `127.0.0.1:8089`. Let's Encrypt certificate was issued successfully for `max.killrealp2.ru`; certbot reports expiry `2026-09-06` and scheduled renewal.
- Public endpoint verification passed from outside the server: `https://max.killrealp2.ru/webhooks/max` returns HTTP `200` with `{"ok": true, "service": "max-webhook"}`.
- MAX webhook registration was applied after the green endpoint. `scripts/register_max_webhook.py --apply` returned `success=true`; final `scripts/max_status.py` shows `subscriptions_count=1` for `https://max.killrealp2.ru/webhooks/max` with update types `message_created` and `bot_started`.
- Final post-launch checks passed: `best2.service` active/enabled, Telegram status OK with webhook empty and pending `0`, MAX status OK with active subscription, live health `status=ok`, hygiene clean, YCLIENTS fresh.
- Residual operational note: `systemctl restart best2.service` logs a transient `Client channel stopped unexpectedly: telegram` during SIGTERM because the runtime treats graceful Telegram polling stop as a channel exit. The service restarts and remains healthy, but graceful shutdown handling should be hardened later.

## 2026-06-08 - SSH key exists locally but transport still blocked

- Local key files `best2_deploy_ed25519` and `best2_deploy_ed25519.pub` exist under the user's `.ssh` directory.
- Codex tried key-based SSH on `45.147.179.48:22`; the key loaded locally, but the connection still failed before an SSH session/banner was established (`No existing session`), so this is still transport/server-side, not password/key authentication.
- Codex also tried `45.147.179.48:2222`; the port is not reachable/listening externally yet.
- Next step remains server-console repair: ensure the public key is in `/root/.ssh/authorized_keys`, configure SSH to listen on `2222`, account for Ubuntu `ssh.socket` if enabled, and allowlist Codex IP `83.149.70.79`.

## 2026-06-08 - SSH still blocked after allowlist attempt

- Rechecked external access after the user asked to verify again. Codex external IP remains `83.149.70.79`.
- TCP `22` and `443` are reachable, but `ssh-keyscan -p 22` still times out before receiving an SSH banner, so Codex still cannot administer the server directly.
- `http://max.killrealp2.ru/` no longer serves the full n8n UI; it now returns HTTP `404` from nginx/upstream. HTTPS `https://max.killrealp2.ru/webhooks/max` still times out.
- Recommended next step is to configure an alternate temporary SSH listener on `2222`, allow it for Codex IP `83.149.70.79`, and keep the existing `22` listener untouched.

## 2026-06-08 - Server console output analyzed for MAX deploy

- User provided server console output from `/opt/admin_niz2`.
- `ssh.service` is active and listening on `0.0.0.0:22`/`[::]:22`, but the server is under heavy SSH noise: `fail2ban` shows thousands of failed attempts and multiple banned IPs, and the logs show repeated preauth closes. Codex's current external IP is `83.149.70.79`, matching recent `sshd` log entries that closed before authentication.
- `nginx -T` shows only an existing `server_name n8n.ermantgz.ru` block proxying to `localhost:5679`; there is no dedicated `max.killrealp2.ru` server block yet. Public HTTP for `max.killrealp2.ru` therefore falls through to the existing n8n/default site.
- Server ports currently show nginx on `80`/`443`, docker proxy on `8080`, and no listener on `8088`/`8089`; best2 MAX webhook runner is not running yet.
- `/opt/admin_niz2/.env` permissions were tightened manually with `chmod 600 .env`.
- Next safe path: temporarily allowlist Codex IP or otherwise restore SSH access, then configure `/opt/admin_niz2` service and a separate nginx HTTPS server block for `max.killrealp2.ru` proxying `/webhooks/max` to `127.0.0.1:8089`.

## 2026-06-08 - MAX production deploy SSH recheck after manual server setup

- User manually cloned/prepared the project on the server under `/opt/admin_niz2` and created `/opt/admin_niz2/.env`.
- External recheck still cannot establish SSH from Codex: TCP `22` is reachable, but `ssh-keyscan` times out before receiving an SSH banner. Codex still cannot run commands on the server directly.
- Public HTTP for `max.killrealp2.ru` currently serves an n8n UI page through `nginx/1.24.0 (Ubuntu)`. This means the domain is already routed to an existing nginx/n8n site.
- HTTPS still times out, and `https://max.killrealp2.ru/webhooks/max` is not reachable. MAX webhook registration remains unsafe until nginx HTTPS 443 and the best2 webhook runner are verified.
- No server changes were made by Codex, no MAX webhook registration was performed, and no subscription/payment mutation was performed.

## 2026-06-08 - MAX production deploy recheck still blocked by SSH

- Rechecked the server after the user reported it should be working. DNS still resolves `max.killrealp2.ru` to `45.147.179.48`.
- TCP ports `22`, `80` and `443` are reachable from the workstation, but SSH is still not usable: Paramiko gets a connection reset before the SSH protocol banner, and OpenSSH/`ssh-keyscan` also time out before authentication. This is still not a password failure.
- Web status changed slightly: `http://max.killrealp2.ru/` now returns HTTP 200 from `nginx/1.24.0 (Ubuntu)` with a static page, but HTTPS still times out and the production MAX endpoint `https://max.killrealp2.ru/webhooks/max` is not reachable.
- Safe bot checks remain OK: `scripts/max_status.py` reports MAX bot `id524706834883_bot` and `subscriptions_count=0`; `scripts/register_max_webhook.py --dry-run` passes with `calls_max_api=false`, URL `https://max.killrealp2.ru/webhooks/max`, update types `message_created`/`bot_started`; `scripts/telegram_status.py` reports Telegram webhook empty and pending updates `0`.
- No code was uploaded to the server, no nginx/systemd changes were made, no MAX webhook registration was performed, no `POST /subscriptions`/`DELETE /subscriptions` was called, and no YooKassa payment action was performed.

## 2026-06-08 - MAX production deploy attempt blocked by server access

- DNS for `max.killrealp2.ru` is propagated and resolves to `45.147.179.48` from local DNS plus public `1.1.1.1` and `8.8.8.8`.
- Server preflight from the workstation found port `22` reachable at TCP level, but SSH never sends a protocol banner and times out before authentication. This blocks code upload and nginx/systemd configuration from Codex.
- Public HTTP currently reaches `nginx/1.24.0 (Ubuntu)` and `/` returns `301` to HTTPS, but `http://max.killrealp2.ru/webhooks/max` hangs until timeout. HTTPS requests to `/` and `/webhooks/max` also time out. This means the public MAX webhook endpoint is not ready.
- Safe local checks remain green: `compileall app scripts`, `max_media_buttons_smoke.py`, `max_api_client_smoke.py`, `max_inbound_normalization_smoke.py`, `telegram_status.py`, `max_status.py`, `live_health_report.py`, `db_status.py`, and `live_db_hygiene_audit.py --limit 20`.
- YCLIENTS strict freshness was stale during the check, then refreshed safely with `scripts/sync_yclients_records.py --once`: `seen=133`, `upserted=133`; final strict status fresh and health `status=ok`.
- Local `.env` had an empty `MAX_WEBHOOK_SECRET`, so a valid URL-safe secret was generated locally and `MAX_WEBHOOK_URL=https://max.killrealp2.ru/webhooks/max`, `MAX_WEBHOOK_ENABLED=true`, `MAX_MODE=webhook` were set. `scripts/register_max_webhook.py --dry-run` now passes with `calls_max_api=false`, `update_types=['message_created', 'bot_started']`.
- No MAX webhook registration was performed, no `POST /subscriptions`/`DELETE /subscriptions` was called, and no real YooKassa payment was performed. MAX subscriptions remain `0`.
- Blocker recorded in [[bugs/2026-06-08-server-ssh-https-blocker]].

## 2026-06-08 - MAX production data discussion and media recheck

- User confirmed intent to run production on a remote server with nginx, can provide SSH/password access and asked whether to use IP vs domain. Current recommendation remains domain + trusted HTTPS 443 because MAX webhook requirements validate HTTPS, trusted CA chain and domain CN/SAN match.
- Safe checks were run without webhook registration, without `POST /subscriptions`/`DELETE /subscriptions`, and without real YooKassa payments.
- MAX/photo/media verification passed: `scripts/max_media_buttons_smoke.py` OK and `scripts/local_regression_suite.py --group media` OK. Covered explicit gazebo photos, general gazebo photo request, bathhouse/house photos, related media selection and payment/link-button adapter smoke.
- Other checks passed: `compileall app scripts`, `max_api_client_smoke.py`, `max_inbound_normalization_smoke.py`, `max_outbound_text_smoke.py`, `max_runtime_smoke.py`, `channel_contract_smoke.py`, `channel_notifications_smoke.py`.
- Live read-only statuses passed: `scripts/telegram_status.py` OK (`@fnsmvsvmpvpovbot`, webhook empty, pending `0`), `scripts/max_status.py` OK (`id524706834883_bot`, subscriptions `0`), `scripts/live_db_hygiene_audit.py --limit 20` clean.
- YCLIENTS cache was stale at first, then safely refreshed with `scripts/sync_yclients_records.py --once`: `seen=132`, `upserted=132`; strict status fresh and final `scripts/live_health_report.py` returned `status=ok`, blockers/warnings empty.
- Local `.env` already contains `MAX_WEBHOOK_SECRET`; it was not overwritten. Production launch still needs final server env values, nginx reverse proxy, public domain URL and explicit `register_max_webhook.py --apply` only after the endpoint is live.

## 2026-06-07 - MAX runtime parity and local dual-channel runner

- Implemented the requested MAX parity runtime slice in `best2` only. `main.py` still delegates to `app/bot/runtime.py`, and the runtime now owns background services once per process while Telegram polling is just one channel runner.
- `app/bot/telegram_bot.py` now exposes `create_bot()` and can run polling with `manage_background_services=False`, so the shared runtime can start Telegram without duplicating YCLIENTS/payment/retention/YooKassa loops. Direct Telegram-only startup remains backward-compatible with background services enabled.
- `app/bot/runtime.py` now validates MAX config before starting background tasks, starts shared background services once, supports local MAX polling, and supports production `MAX_MODE=webhook` by starting `start_max_webhook_server(event_processor=make_max_webhook_event_processor())` when `CLIENT_CHANNELS` includes `max`, `MAX_WEBHOOK_ENABLED=true` and `MAX_WEBHOOK_SECRET` is set.
- Safety boundaries held: no MAX webhook was registered, no `POST /subscriptions` or `DELETE /subscriptions` was called, no real YooKassa payment was performed, and Telegram remains the admin-notification channel for MVP.
- Refreshed YCLIENTS safely with `scripts/sync_yclients_records.py --once`: final successful status `records_seen=143`, `records_upserted=143`, fresh. One YCLIENTS attempt had a transient remote-host-reset warning and then retried successfully.
- Verification was green:
  - `python -m compileall app scripts`
  - `scripts/db_status.py`
  - `scripts/yclients_sync_status.py --strict`
  - `scripts/telegram_status.py`
  - `scripts/max_status.py`
  - `scripts/live_health_report.py`
  - `scripts/live_db_hygiene_audit.py --limit 20`
  - `scripts/max_api_client_smoke.py`
  - `scripts/max_inbound_normalization_smoke.py`
  - `scripts/max_outbound_text_smoke.py`
  - `scripts/max_media_buttons_smoke.py`
  - `scripts/channel_contract_smoke.py`
  - `scripts/channel_notifications_smoke.py`
  - `scripts/max_runtime_smoke.py`
  - `scripts/max_webhook_runner_smoke.py`
  - `scripts/local_regression_suite.py --group media --group fresh`
  - `scripts/local_regression_suite.py --group services`
  - `scripts/local_regression_suite.py --group post_booking`
  - `scripts/local_regression_suite.py --group payments`
- Observations from checks: one first `max_status.py` retry window hit an SSL handshake timeout to `platform-api.max.ru`, and the final repeat was OK with bot `id524706834883_bot` and `subscriptions_count=0`. One health run during long regressions was blocked only because the 10-minute YCLIENTS freshness window expired; after sync, final `live_health_report.py` was `status=ok`, blockers/warnings empty.
- Started a local hidden dual-channel runner for manual paired smoke: CPython PID `13284`, stdout `runtime_logs/main_telegram_max_20260607_2054.out.log`, stderr `runtime_logs/main_telegram_max_20260607_2054.err.log`. Temporary env: `CLIENT_CHANNELS=telegram,max`, `MAX_MODE=polling`, `MAX_WEBHOOK_ENABLED=false`, `MAX_SEND_RELATED_MEDIA=true`, `PAYMENT_PROVIDER=disabled`, `PAYMENT_STATUS_SYNC_ENABLED=false`, `YOOKASSA_WEBHOOK_ENABLED=false`. Startup log confirmed Telegram polling for `@fnsmvsvmpvpovbot` and MAX polling ready for `id524706834883_bot` with `send_media=True`.
- Found and fixed a runtime supervision bug during that live startup: if one channel runner returned normally while the other kept running, `asyncio.gather()` could leave a half-live process. `_run_channel_runners()` is now fail-fast for multi-channel mode: when any channel exits, the other channel is cancelled and the process exits for supervisor/local restart. `scripts/max_runtime_smoke.py` now covers this behavior, and `compileall app scripts` plus `scripts/max_runtime_smoke.py` passed after the fix.
- The old PID `13284` was stopped after Telegram polling hit a transient `ServerDisconnectedError`. A fresh runner attempt with `YCLIENTS_SYNC_ENABLED=false` exited correctly because local Python DNS could not resolve `api.telegram.org` (`socket.gaierror 11001`); subsequent minimal Python `socket.getaddrinfo()` also failed for `api.telegram.org` and `platform-api.max.ru` while the DB host still resolved. `Resolve-DnsName api.telegram.org` started returning an IP after `ipconfig /flushdns`, but Python/aiohttp still failed. Current state: no live local `main.py` runner is active; manual paired smoke is blocked by local DNS/network, not by MAX code.
- Graphify was updated after code changes with `best2graph/update_graph.ps1`; final report updated `graph.json`, `graph.html`, `GRAPH_REPORT.md` and `GRAPH_TREE.html`.
- Step 12 MAX Launch Gate remains open, not complete: production still needs public HTTPS `MAX_WEBHOOK_URL`, `MAX_WEBHOOK_SECRET`, reverse proxy on external 443 to the internal MAX webhook runner, confirmation that the webhook runner is live in production, an explicit request to run `scripts/register_max_webhook.py --apply`, expected update types `message_created` and `bot_started`, and an active MAX subscription visible in `scripts/max_status.py`.

## 2026-06-05 - Local best2 bot processes stopped

- Stopped the local `best2` runtime processes by operator request: previous MAX/Telegram manual-test runner `main.py` PID `26216` and an additional `main.py` process PID `22868` were terminated or already gone by the time of stop.
- Follow-up process scan found no remaining Python `main.py` / MAX dev polling processes for `best2`. Telegram and MAX local polling are currently offline until `main.py` or a dev runner is started again.
- No production code, `.env`, webhook subscription, MAX registration or payment action was changed.

## 2026-06-05 - MAX Telegram parity completion plan saved

- Created [[roadmap/max-telegram-parity-completion-plan]] as the remaining work plan to make MAX behavior match Telegram as a true second client entry/exit point.
- The plan defines parity as equal dialog meaning/state/output across Telegram and MAX, with platform UI differences allowed only where MAX itself differs.
- Remaining phases: manual local paired smoke on current `CLIENT_CHANNELS=telegram,max` runner, live MAX voice payload confirmation, targeted adapter fixes from smoke, automated parity coverage, runtime ownership cleanup so background loops are not Telegram-owned, production MAX webhook runtime, launch gate, and rollback.
- No production code, webhook registration, subscription mutation or real payment action was performed in this planning step.

## 2026-06-05 - MAX parity implementation slice

- Implemented the requested MAX parity plan without registering a webhook, without calling `POST /subscriptions`/`DELETE /subscriptions`, and without real YooKassa payments. MAX now stays a channel adapter/runtime around the shared `process_client_message()` / `handle_incoming()` path; `message_handler.py` was not forked.
- MAX UX parity changes:
  - `MaxApiClient.send_chat_action()` uses `POST /chats/{chatId}/actions`, and `MaxChannelClient.send_typing()` sends `typing_on` when `chat_id` is available.
  - Telegram `/start` and MAX `bot_started` now share `START_WELCOME_TEXT`; MAX `bot_started` sends the static welcome directly and does not enter the DB/dialog questionnaire path.
  - `voice_transcription_service.transcribe_audio_bytes()` is the shared provider-agnostic transcription helper; Telegram voice reuses it, and MAX audio/voice updates try to fetch full message data, download an audio URL and transcribe. If MAX payload is unsupported, transcription is disabled, provider key is missing, duration is too long or no downloadable URL exists, MAX replies with a clear fallback instead of silently ignoring the event.
  - MAX non-audio attachments now receive an explicit "text or voice" fallback, not a misleading voice-processing error.
  - MAX outbound formatting remains opt-in: HTML format is only sent when outbound options request `parse_mode="html"`.
- Local runtime changes: `main.py` now delegates to `app/bot/runtime.py`; `CLIENT_CHANNELS=telegram,max` starts Telegram polling and MAX dev polling together only when `MAX_MODE=polling`, `MAX_WEBHOOK_ENABLED=false`, `MAX_BOT_TOKEN` is configured, app env is not production, and the MAX bot has no active webhook subscriptions. `scripts/max_dev_live_polling.py` now reuses the shared MAX polling loop and keeps payments disabled unless explicitly allowed.
- Verification:
  - `compileall app scripts` OK.
  - MAX/channel smokes OK: `max_api_client_smoke.py`, `max_inbound_normalization_smoke.py`, `max_outbound_text_smoke.py`, `max_media_buttons_smoke.py`, `channel_contract_smoke.py`, `channel_notifications_smoke.py`, `max_runtime_smoke.py`, `max_webhook_runner_smoke.py`.
  - Regression groups OK: `services`, `media+fresh`, `post_booking`, `payments`; `local_regression_suite.py --list-cases` OK. `payments` is slow on the deterministic paid-payment question check (~192s) but passed.
  - Status checks OK after one-shot YCLIENTS sync: `db_status.py`, `yclients_sync_status.py --strict`, `live_health_report.py`, `live_db_hygiene_audit.py --limit 20`, `max_status.py`, `telegram_status.py`.
  - MAX read-only status: bot `id524706834883_bot`, subscriptions `0`. Telegram status: `@fnsmvsvmpvpovbot`, webhook empty, pending updates `0`.
  - Safe polling smoke with temporary `MAX_MODE=polling` returned `status='skipped'` because there were no MAX updates, not because of a blocker.
  - `register_max_webhook.py --url https://example.com/webhooks/max --secret placeholder-secret` ran dry-run only with `calls_max_api=false`.
  - Short live startup smoke for `main.py` with temporary `CLIENT_CHANNELS=telegram,max`, `MAX_MODE=polling`, `MAX_WEBHOOK_ENABLED=false`, `MAX_SEND_RELATED_MEDIA=true`, `PAYMENT_PROVIDER=disabled`, `PAYMENT_STATUS_SYNC_ENABLED=false`, `YOOKASSA_WEBHOOK_ENABLED=false` reached Telegram polling and MAX polling `ready`, then was stopped.
- Database after checks is healthy: `live_health_report.py` status `ok`, blockers/warnings empty, active holds `0`, pending payments `0`, YCLIENTS `records_seen=141`, `records_upserted=141`, fresh. Runtime data was not globally truncated because hygiene was clean and `clear_db.py` would delete all users/conversations/bookings.
- Graphify update was run after code changes. It completed extraction/reclustering work but warned that the new graph had 333 nodes while existing `graph.json` had 335 and refused final overwrite without `force=True`; no force update was attempted.
- After the checks a local background runner was started for manual Telegram/MAX testing: CPython PID `26216`, log `runtime_logs/main_max_parity_live.out.log`. Temporary process env: `CLIENT_CHANNELS=telegram,max`, `MAX_MODE=polling`, `MAX_WEBHOOK_ENABLED=false`, `MAX_SEND_RELATED_MEDIA=true`, `PAYMENT_PROVIDER=disabled`, `PAYMENT_STATUS_SYNC_ENABLED=false`, `YOOKASSA_WEBHOOK_ENABLED=false`, `YCLIENTS_SYNC_ENABLED=false`. Startup log confirms Telegram polling and MAX polling `ready`.
- Step 12 MAX Launch Gate is still not fully complete: there is still no production HTTPS MAX webhook URL, no active MAX webhook subscription, and no confirmed production webhook runner behind reverse proxy 443.

## 2026-06-05 - MAX parity root-cause recheck

- Rechecked the user's report that MAX mechanics feel worse than Telegram using project memory, Graphify and direct code inspection. Production code was not changed.
- Graphify query for Telegram/MAX entry-exit parity mostly returned `scripts/max_dev_live_polling.py`, so the graph was not sufficient for the full cross-channel comparison; raw code inspection was used as source of truth.
- Operational status is green: `scripts/max_status.py` OK with bot `id524706834883_bot`, subscriptions `0`; `scripts/telegram_status.py` OK with webhook empty and pending `0`; `scripts/live_health_report.py` OK with fresh YCLIENTS cache (`records_seen=138`); compile and MAX/channel smokes OK.
- Root cause is adapter/runtime parity, not a forked dialog core. MAX text `message_created` goes through `process_client_message()` and shared `handle_incoming()`, but Telegram has extra UX paths around it:
  - Telegram `/start` is a direct static `message.answer()` and does not enter the DB/dialog path; MAX `bot_started` is normalized to `/start` and processed as a normal dialog message.
  - Telegram voice goes through `on_voice()`, transcription and `normalize_telegram_voice_message()`; MAX normalizer ignores `message_created` without text, so voice/audio/attachment-only MAX events do not reach transcription or the dialog.
  - Telegram typing is implemented in `TelegramChannelClient.send_typing()`; `MaxChannelClient.send_typing()` is currently a no-op, so MAX cannot show "typing" from this code path.
  - Telegram text/media calls pass reply/source message options; MAX live polling passes no analogous options.
  - `scripts/max_dev_live_polling.py` defaults to `send_media=False`; Step 10 MAX media exists in the adapter, but the current local runner suppresses related media unless started with `--send-media`.
  - `main.py` starts only Telegram polling; local dual-channel testing currently requires separate Telegram `main.py` plus MAX dev polling processes.
- No MAX webhook registration, subscription POST/DELETE, production webhook, or real YooKassa payment actions were performed.

## 2026-06-05 - MAX/Telegram live parity diagnosis

- Investigated the user's report that MAX UX is worse than Telegram during local live testing.
- Runtime state corrected for local testing: MAX dev polling remains alive (launcher PID `10964`, child PID `11900`), and Telegram `main.py` is now also running (launcher PID `25904`, child PID `23100`) with safe temporary overrides `CLIENT_CHANNELS=telegram,max`, `PAYMENT_PROVIDER=disabled`, `PAYMENT_STATUS_SYNC_ENABLED=false`, `YOOKASSA_WEBHOOK_ENABLED=false`.
- Verified Telegram startup log: polling started for `@fnsmvsvmpvpovbot`, YooKassa webhook server disabled, payment status sync disabled, YCLIENTS sync loop running.
- MAX local smoke is not silent anymore: polling processed `bot_started` and text `message_created` updates; DB now has one MAX user, one MAX conversation and 16 MAX messages from the live smoke. Recent MAX dialog is using the shared booking path and reached `current_step=time`.
- Health after starting both runtimes: `scripts/live_health_report.py` returned `status=ok`, no blockers/warnings; YCLIENTS cache fresh with 138 records.
- Found real parity gaps, recorded in `best2obs/bugs/current-known-issues.md`: `MaxChannelClient.send_typing()` is currently a no-op despite live MAX `POST /chats/9386682/actions` with `typing_on` returning success; MAX voice/audio is not implemented because `max_router.normalize_max_update()` ignores message updates without text; `main.py` remains Telegram-only, so local dual-channel runtime currently requires two processes.
- No MAX webhook registration, subscription POST/DELETE, production webhook, or real YooKassa payment actions were performed.

## 2026-06-05 - MAX local live polling recheck

- Re-ran safe local/MAX checks while `scripts/max_dev_live_polling.py` was still running. No production code changes were made.
- `compileall app scripts`: OK. `scripts/db_status.py`: OK against `kifloquomirab.beget.app/default_db`; expected tables exist; runtime tables remain empty; YCLIENTS cache tables have 138 records/busy intervals.
- `scripts/telegram_status.py`: OK (`@fnsmvsvmpvpovbot`, webhook empty, pending `0`). `scripts/max_status.py`: OK (`id524706834883_bot`, subscriptions `0`).
- First `scripts/yclients_sync_status.py --strict` was stale by the 10-minute launch-check threshold (`age_seconds=656`, max `600`), so `scripts/sync_yclients_records.py --once` was run safely and refreshed cache to `seen=138`, `upserted=138`; strict status then became fresh (`age_seconds=67`).
- `scripts/live_health_report.py`: `status=ok`, no blockers/warnings. `scripts/live_db_hygiene_audit.py --limit 20`: clean. Extra DB channel count: no users/conversations by channel, `messages=0`, `system_logs=0`, `webhook_events=0`.
- Local MAX polling runner is alive (launcher PID `10964`, child PID `11900`). Output log reached cycle `28` with `updates_count=0`, `processed_count=0`; stderr log only contains the PowerShell CLIXML header. Live MAX smoke is still waiting for a real message to the MAX bot.
- No MAX webhook registration, subscription POST/DELETE, production webhook, or real YooKassa payment actions were performed.

## 2026-06-05 - MAX local live polling started

- Implemented the local MAX launch plan without production webhook registration, without `POST /subscriptions`, without `DELETE /subscriptions`, without production-code changes and without real YooKassa payments.
- Preflight: `compileall app scripts` OK; `scripts/db_status.py` OK against `kifloquomirab.beget.app/default_db`; Telegram status OK (`@fnsmvsvmpvpovbot`, webhook empty, pending `0`); MAX status OK (`id524706834883_bot`, subscriptions `0`).
- YCLIENTS strict status was stale (`age_seconds=1036`), so `scripts/sync_yclients_records.py --once` was run safely and refreshed cache to `seen=138`, `upserted=138`; repeated strict status fresh and `scripts/live_health_report.py` returned `status=ok`; `scripts/live_db_hygiene_audit.py --limit 20` clean.
- Started `scripts/max_dev_live_polling.py` as a hidden local process with temporary env overrides `MAX_MODE=polling`, `MAX_WEBHOOK_ENABLED=false`, `CLIENT_CHANNELS=telegram,max`. Runner status: `ready`, bot `id524706834883_bot`, `existing_updates_skipped=0`, marker `3134`, `real_payments_enabled=False`, `send_media=False`.
- Active runner processes observed: venv launcher PID `10964` and child CPython PID `11900`. Output log: `%TEMP%\best2-max-live-20260605-145943.out.log`; error log currently only has PowerShell CLIXML header/no runner error.
- 70-second watch window after start saw polling cycles with `updates_count=0`, `processed_count=0`; live MAX smoke is waiting for a user message in MAX and is not yet completed.

## 2026-06-05 - New PostgreSQL DB restored and initialized

- Re-ran the Beget certificate setup using the Windows equivalent of `mkdir -p ~/.postgresql && wget https://beget.com/cloud-ca.crt --output-document ~/.postgresql/root.crt && chmod 0600 ~/.postgresql/root.crt`: `C:\Users\kaisa\.postgresql\root.crt` was downloaded from the official Beget URL and verified with SHA256 `1F7F0A9C5FA2B715860BFA4C95C6ADD04479EFDF9001B11D9A238FC4F68DD2CB`.
- After the fresh CA download, PostgreSQL SSLRequest to `kifloquomirab.beget.app:5432` and direct IP `159.194.235.48:5432` returned `S`, and `scripts/db_status.py` reached the DB with `DB_SSLMODE=verify-full`.
- Applied the schema to the new DB with `scripts/init_db.py`; migration `app/db/migrations/001_init.sql` completed successfully for `kifloquomirab.beget.app/default_db`.
- Verified schema and empty runtime tables with `scripts/db_status.py`: expected tables exist (`users`, `conversations`, `messages`, `conversation_summaries`, `slot_holds`, `bookings`, `payments`, `yclients_sync_state`, `yclients_records`, `resource_busy_intervals`, `system_logs`, `waitlist_requests`, `webhook_events`).
- Refilled YCLIENTS cache with `scripts/sync_yclients_records.py --once`: `seen=137`, `upserted=137`; `scripts/yclients_sync_status.py --strict` fresh (`age_seconds=66`, `last_error=None`).
- Health checks green: `compileall app scripts` OK, `scripts/telegram_status.py` OK (`@fnsmvsvmpvpovbot`, webhook empty, pending `0`), `scripts/max_status.py` OK (`id524706834883_bot`, subscriptions `0`), `scripts/live_health_report.py` status `ok` with no blockers/warnings, `scripts/live_db_hygiene_audit.py --limit 20` clean.

## 2026-06-05 - PostgreSQL allowlist note and local route diagnosis

- User clarified that Beget external access was opened as `0.0.0.0/0`.
- Rechecked config without printing secrets: effective DB target is `kifloquomirab.beget.app:5432`, `DB_NAME=default_db`, `DB_USER=cloud_user`, `DB_SSLMODE=verify-full`, password configured.
- Tested the `c-kifloquomirab.beget.app` variant from Beget-style examples; it does not resolve for this DB, so the current technical domain remains the only resolving endpoint observed locally.
- Local route diagnosis showed `Test-NetConnection kifloquomirab.beget.app -Port 5432` using source `10.0.85.2` on `outline-tap0`, while external IP detection changed from the earlier `46.28.66.18` to `37.221.211.187`. If `0.0.0.0/0` is actually applied, the source IP should not matter; if Beget does not apply/accept the broad rule, the changing VPN exit IP can explain persistent blocking.
- Direct IP connection with temporary `DB_HOST=159.194.235.48` and `DB_SSLMODE=require` still timed out, so hostname verification is not the current blocker.
- Current next diagnostic step: retry after disabling VPN/tunnel or adding the currently detected public IP explicitly in Beget, then rerun `scripts/db_status.py` and `scripts/init_db.py`.

## 2026-06-05 - PostgreSQL certificate checked, access still blocked

- Investigated whether the new Beget PostgreSQL connection failure is certificate-related.
- Local `~/.postgresql/root.crt` existed but did not match the official Beget CA from `https://beget.com/cloud-ca.crt`; the old file was backed up and `root.crt` was replaced with the official Beget CA.
- Retest after CA update still fails with the same `timeout expired` under `DB_SSLMODE=verify-full`; raw PostgreSQL SSLRequest to `kifloquomirab.beget.app:5432` and direct IP `159.194.235.48:5432` still gets no response before TLS/certificate validation can begin.
- Temporary checks with `DB_SSLMODE=require` and `DB_SSLMODE=disable` also timed out before authentication. This means the current blocker is not the certificate itself; the server/proxy is accepting TCP but not allowing/responding to PostgreSQL protocol startup from this environment.
- Current external client IP detected for allowlist checks: `46.28.66.18`. Beget PostgreSQL external access/allowlist should be checked for this IP or a suitable subnet before retrying `scripts/db_status.py` and `scripts/init_db.py`.

## 2026-06-05 - New PostgreSQL target corrected but schema init blocked

- User replaced the Beget DB target and asked to recreate the previous schema. No production code changes were made.
- Fixed local `.env` DB host formatting: `DB_HOST` had been set to `kifloquomirab.beget.app:5432`, while the app passes `DB_PORT` separately. It is now `DB_HOST=kifloquomirab.beget.app` with `DB_PORT=5432`.
- New DNS/TCP target: `kifloquomirab.beget.app -> 159.194.235.48`; `Test-NetConnection ... -Port 5432` reports `TcpTestSucceeded=True`.
- PostgreSQL still does not complete protocol startup: raw SSLRequest to both hostname and direct IP times out; `scripts/db_status.py` fails after 3 attempts with `timeout expired` under `DB_SSLMODE=verify-full`; a temporary `DB_SSLMODE=disable` check also times out.
- `scripts/init_db.py` was attempted after the host fix and failed before applying SQL with the same connection timeout. Therefore tables were not created yet.
- The intended schema source is `app/db/migrations/001_init.sql`, applied by `scripts/init_db.py`; it contains `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... IF NOT EXISTS` statements for the expected best2 tables and indexes.

## 2026-06-05 - PostgreSQL latest recheck still blocked

- Rechecked DB connectivity again on user request. No production code or `.env` changes were made.
- DNS still resolves `luecahalemas.beget.app` to `95.214.62.243`; `Test-NetConnection luecahalemas.beget.app -Port 5432` still reports `TcpTestSucceeded=True`.
- Raw PostgreSQL SSLRequest to both `luecahalemas.beget.app:5432` and direct IP `95.214.62.243:5432` still gets no response before timeout.
- `scripts/db_status.py` with temporary `DB_POOL_ENABLED=false` and `DB_CONNECT_TIMEOUT=8` still fails after 3 attempts with `psycopg2.OperationalError ... timeout expired`.
- Result: DB is still not normal. DB-dependent YCLIENTS strict/live health/hygiene checks remain blocked at the base PostgreSQL connection step.

## 2026-06-05 - PostgreSQL additional recheck still blocked

- Rechecked DB connectivity once more on user request. No production code or `.env` changes were made.
- DNS still resolves `luecahalemas.beget.app` to `95.214.62.243`; `Test-NetConnection luecahalemas.beget.app -Port 5432` still reports `TcpTestSucceeded=True`.
- Raw PostgreSQL SSLRequest to both hostname and direct IP still gets no response before timeout.
- `scripts/db_status.py` with temporary `DB_POOL_ENABLED=false` and `DB_CONNECT_TIMEOUT=8` still fails after 3 attempts with `timeout expired` under `DB_SSLMODE=verify-full`.
- Result: DB-dependent YCLIENTS/live health/hygiene checks remain blocked by the base PostgreSQL connection failure.

## 2026-06-05 - PostgreSQL repeat recheck still blocked

- Rechecked DB connectivity again after the previous Beget top-up check. No production code or `.env` changes were made.
- `Test-NetConnection luecahalemas.beget.app -Port 5432` still reports `TcpTestSucceeded=True` and resolves to `95.214.62.243`.
- Raw PostgreSQL SSLRequest to both `luecahalemas.beget.app:5432` and direct IP `95.214.62.243:5432` still gets no response before timeout.
- `scripts/db_status.py` with temporary `DB_POOL_ENABLED=false` and `DB_CONNECT_TIMEOUT=8` still fails after 3 attempts with `timeout expired` under the normal `DB_SSLMODE=verify-full`.
- Extra diagnostic with temporary `DB_SSLMODE=disable` also fails after 3 attempts with the same timeout, so the symptom is not limited to SSL negotiation/certificate verification.
- Result: DB remains the launch/local live-test blocker. DB-dependent YCLIENTS strict/live health/hygiene checks were not rerun because the base PostgreSQL connection still fails.

## 2026-06-05 - PostgreSQL recheck after Beget top-up still blocked

- Rechecked DB connectivity after the user topped up Beget. No production code or `.env` changes were made.
- `Test-NetConnection luecahalemas.beget.app -Port 5432` still resolves to `95.214.62.243` and reports `TcpTestSucceeded=True`.
- Raw PostgreSQL SSLRequest to both `luecahalemas.beget.app:5432` and direct IP `95.214.62.243:5432` still times out before receiving the expected `S`/`N` byte, so the failure remains before DB authentication, DNS hostname verification and certificate validation.
- `scripts/db_status.py` with temporary `DB_POOL_ENABLED=false` and `DB_CONNECT_TIMEOUT=8` still fails after 3 attempts with `psycopg2.OperationalError: connection to server at "luecahalemas.beget.app" (95.214.62.243), port 5432 failed: timeout expired`.
- Result: DB is still not normal from the local app environment. DB-dependent YCLIENTS strict/live health/hygiene checks were not rerun because they would fail at the same first connection step.

## 2026-06-05 - PostgreSQL recheck still blocked

- Rechecked DB connectivity for `best2` after the MAX local runner work. No production code or `.env` changes were made.
- `Test-NetConnection luecahalemas.beget.app -Port 5432` still shows `TcpTestSucceeded=True` and resolves to `95.214.62.243`, so TCP reachability exists.
- Raw PostgreSQL SSLRequest still times out before receiving `S`/`N` from both hostname and direct IP `95.214.62.243`. This is still before DB auth and before certificate validation.
- `scripts/db_status.py` with temporary `DB_POOL_ENABLED=false` and `DB_CONNECT_TIMEOUT=8` failed with `psycopg2.OperationalError: connection to server at "luecahalemas.beget.app" (95.214.62.243), port 5432 failed: timeout expired`.
- Result: DB is not normal yet. YCLIENTS strict/health/hygiene checks were not re-run because DB connectivity is still the first blocker and those checks would fail on the same connection step.

## 2026-06-05 - MAX local live polling runner prepared

- Added `scripts/max_dev_live_polling.py` as a dev-only local MAX live test entrypoint. It is not imported by `main.py`, does not register webhook, does not call `POST /subscriptions`, and refuses to run in `APP_ENV=production/prod`, when `MAX_WEBHOOK_ENABLED=true`, when `MAX_MODE` is not `polling`, or when `GET /subscriptions` returns any active subscriptions.
- The live runner uses `GET /updates` for `message_created`/`bot_started`, normalizes events through the existing MAX router, processes them through the shared `process_client_message()` path, and sends real MAX replies through `MaxChannelClient`. It defaults to text-only related delivery (`--send-media` is required for media) and disables YooKassa provider inside the process unless `--allow-real-payments` is explicitly passed.
- Added a startup DB preflight (`SELECT 1`) before polling so the runner does not answer MAX users with a generic error while PostgreSQL is unreachable. The preflight uses one short direct connection attempt and does not print secrets.
- Verification: `python -m compileall app scripts` OK; `scripts/max_status.py` OK with bot `id524706834883_bot`, subscriptions `0`; `scripts/max_outbound_text_smoke.py` OK; `scripts/max_webhook_runner_smoke.py` OK. With current `.env` (`MAX_MODE=webhook`), both `scripts/max_dev_polling_smoke.py` and `scripts/max_dev_live_polling.py --cycles 1 --timeout 0` correctly stop before polling. With temporary `MAX_MODE=polling`, the new live runner stops at DB preflight because PostgreSQL still times out.
- PostgreSQL diagnosis detail: raw TCP connect to `luecahalemas.beget.app:5432` and `95.214.62.243:5432` succeeds, but a direct PostgreSQL SSLRequest receives no response until timeout for both hostname and IP. This points to a network/hosting PostgreSQL frontend issue before authentication, not a MAX issue.
- To test locally after DB recovery: run with temporary/local env `MAX_MODE=polling`, `MAX_WEBHOOK_ENABLED=false`, no MAX subscriptions, then start `scripts/max_dev_live_polling.py`; keep `--allow-real-payments` off for safe local tests.
- Graphify updated via `best2graph/update_graph.ps1` after adding the script: incremental scan saw `1 code / 36 docs / 12 images changed`; final graph has `82 nodes`, `93 edges`, `22 communities`.

## 2026-06-05 - MAX token status checked, DB blocker returned

- Continued strictly in the `best2` project. No `bitrix-tg` files were read or used. Production code and `.env` were not edited.
- Rechecked current official MAX docs at `https://dev.max.ru/docs` and `https://dev.max.ru/docs-api`: token must be sent via `Authorization`, not query params; API base is `https://platform-api.max.ru`; production event delivery should use Webhook, not Long Polling; `POST /subscriptions` requires HTTPS endpoint on external `443`, trusted TLS, optional/recommended `secret` delivered as `X-Max-Bot-Api-Secret`, and expected quick `200 OK`; Long Polling remains dev/test only and must not be mixed with an active Webhook subscription.
- Local safe env summary now sees `MAX_BOT_TOKEN` configured, `MAX_API_BASE_URL=https://platform-api.max.ru`, `MAX_MODE=webhook`, `MAX_WEBHOOK_ENABLED=False`, no `MAX_WEBHOOK_URL/SECRET`, `CLIENT_CHANNELS=telegram`, `HTTP_TRUST_ENV=False`.
- MAX read-only status is OK: `scripts/max_status.py` successfully called `GET /me` and `GET /subscriptions` without printing the token. Bot summary: `user_id=292662610`, name `Максима Горького Русалка`, username `id524706834883_bot`, `is_bot=True`, subscriptions count `0`.
- Safe checks OK: `python -m compileall app scripts`; Telegram baseline `@fnsmvsvmpvpovbot` with empty `webhook_url` and `pending_update_count=0`; `scripts/register_max_webhook.py --dry-run --url https://example.com/webhooks/max --secret abcde` returned `calls_max_api=false` and `token_configured=true`; fake/local MAX smokes `max_api_client_smoke.py`, `max_outbound_text_smoke.py`, `max_inbound_normalization_smoke.py`, `max_webhook_runner_smoke.py`, `max_media_buttons_smoke.py`, `channel_contract_smoke.py`, `channel_notifications_smoke.py` OK.
- `scripts/max_dev_polling_smoke.py` correctly stopped with blocker `MAX polling smoke requires MAX_MODE=polling`, which matches the current docs/runbook boundary for webhook-mode. No `GET /updates` smoke was run in this mode.
- Full end-to-end bot health is blocked by PostgreSQL connectivity, not by MAX: `scripts/yclients_sync_status.py --strict`, `scripts/live_health_report.py`, `scripts/db_status.py` with `DB_POOL_ENABLED=false`/short timeout all failed with `psycopg2.OperationalError: connection to server at "luecahalemas.beget.app" (95.214.62.243), port 5432 failed: timeout expired`. `Test-NetConnection luecahalemas.beget.app -Port 5432` still shows `TcpTestSucceeded=True`, so the TCP port is reachable but PostgreSQL handshake from the app does not complete.
- Full MAX launch gate remains open: no active webhook subscription, no production `MAX_WEBHOOK_URL/SECRET`, `CLIENT_CHANNELS` not yet `telegram,max`, MAX webhook runner is not confirmed live behind HTTPS `443`, and `scripts/register_max_webhook.py --apply` was not requested or run.

## 2026-06-04 - MAX Step 12 safe preflight partial

- Проведен безопасный preflight-срез Step 12 из [[roadmap/max-context-window-steps]] без MAX production данных. Step 12 не закрыт как launch gate: MAX webhook не зарегистрирован, `POST /subscriptions` и `DELETE /subscriptions` не вызывались, live MAX calls не выполнялись, реальные YooKassa-платежи не создавались, production-код не менялся.
- Safe env summary: локальное окружение `APP_ENV=local`, `telegram_configured=True`, `CLIENT_CHANNELS=telegram`, `max_configured=False`, `MAX_MODE=webhook`, `MAX_WEBHOOK_ENABLED=False`, `MAX_WEBHOOK_URL/SECRET` не настроены, YCLIENTS и YooKassa config заполнены. Рабочее дерево остается dirty; чужие изменения не откатывались.
- Checks OK: `python -m compileall app scripts`; `scripts/telegram_status.py` (`@fnsmvsvmpvpovbot`, `webhook_url=''`, `pending_update_count=0`); `scripts/yclients_sync_status.py --strict` fresh (`age_seconds=93`, `records_seen=128`, `last_error=None`); `scripts/live_health_report.py` status `ok` без blockers/warnings; `scripts/live_db_hygiene_audit.py --limit 20` clean.
- MAX safe checks: `scripts/max_status.py` safe skip because `MAX_BOT_TOKEN` is not configured; `scripts/register_max_webhook.py --dry-run --url https://example.com/webhooks/max --secret abcde` returned `calls_max_api=false`, `method=POST`, `path=/subscriptions`, update types `message_created, bot_started`; `scripts/max_dev_polling_smoke.py` safe skip because token is absent.
- MAX fake/local smokes OK: `max_api_client_smoke.py`, `max_inbound_normalization_smoke.py`, `max_webhook_runner_smoke.py`, `max_outbound_text_smoke.py`, `max_media_buttons_smoke.py`, `channel_contract_smoke.py`, `channel_notifications_smoke.py`.
- Blockers for full Step 12 Launch Gate: need real `MAX_BOT_TOKEN`, production `MAX_WEBHOOK_URL`, valid `MAX_WEBHOOK_SECRET`, `CLIENT_CHANNELS=telegram,max`, `MAX_WEBHOOK_ENABLED=true`, confirmed HTTPS reverse proxy on external `443` to the internal `/webhooks/max` listener, confirmed MAX webhook runner/process actually starts with a processor, explicit permission to run `scripts/register_max_webhook.py --apply`, and `GET /subscriptions` must show the expected active webhook URL. No new code bug was found, so `best2obs/bugs/` was not updated.

## 2026-06-04 - MAX Step 11 runbook/env/checks

- Completed Step 11 from [[roadmap/max-context-window-steps]] as an operations/docs + safe-script slice. No MAX webhook was registered, no `POST /subscriptions` or live MAX delivery call was made, no YooKassa payment was created, and launch gate was not started.
- Updated [[operations/production-env-checklist]]: MAX production target now includes `MAX_BOT_TOKEN`, `MAX_API_BASE_URL`, `MAX_MODE=webhook`, `MAX_WEBHOOK_ENABLED`, `MAX_WEBHOOK_HOST/PORT/PATH/URL/SECRET/MAX_BODY_BYTES` and `CLIENT_CHANNELS=telegram,max`; stop conditions now cover invalid URL/secret, public exposure of the internal MAX port and stale/foreign MAX webhook subscriptions.
- Updated [[operations/production-runbook]] with MAX reverse proxy/HTTPS requirements, Nginx example for `/webhooks/max`, internal endpoint checks, status check order, dry-run registration procedure, future explicit `--apply` command, rollback/unsubscribe procedure and the production long-polling ban. The runbook explicitly notes the current launch blocker: Step 11 does not wire/start the MAX webhook runner from `main.py`; before real registration an explicit launch/ops scope must confirm the internal runner is live.
- Added `scripts/register_max_webhook.py`: default dry-run prints a safe plan with `calls_max_api=false`; real registration uses `POST /subscriptions` only with explicit `--apply`, and rollback uses `DELETE /subscriptions?url=...` only with explicit `--unsubscribe --apply`. The script validates HTTPS URL/path/no explicit port/no query and MAX secret format before any apply call.
- Updated [[architecture/api]], [[roadmap/max-context-window-steps]] and [[index]] with the stable Step 11 procedure and residual launch-gate boundary. `scripts/max_status.py` remains the safe read-only `GET /me` + `GET /subscriptions` check.
- Checks: `.\.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts\register_max_webhook.py --dry-run --url https://example.com/webhooks/max --secret abcde` OK with `calls_max_api=false`; `scripts\register_max_webhook.py --unsubscribe --dry-run --url https://example.com/webhooks/max --secret abcde` OK with `calls_max_api=false`; `scripts\max_status.py` safe skip because `MAX_BOT_TOKEN` is not configured. `git diff --check` on touched tracked wiki files is clean apart from expected LF/CRLF warnings.
- Graphify updated via `best2graph/update_graph.ps1` after adding the new script: incremental scan saw `1 code / 36 docs / 12 images changed`; final graph after reclustering has `73 nodes`, `76 edges`, `21 communities`. Control query finds `scripts/register_max_webhook.py`, `_call_max_subscription_api()`, `_validate_webhook_url()` and `_validate_secret()`.

## 2026-06-04 - MAX Step 10 post-MVP media/buttons/contact

- Completed the explicit Step 10 code slice from [[roadmap/max-context-window-steps]] for MAX media upload and payment link buttons without registering MAX webhook, without calling `POST /subscriptions`, without live MAX calls by default and without real payment smokes.
- `app/integrations/max_client.py` now supports `POST /messages` with optional attachments/format/notify flags, `POST /uploads` creation and file upload to the returned URL. The bot token still goes only in the `Authorization` header for platform API calls and is not placed in URLs/query params.
- `app/bot/max_channel_client.py` now implements `send_media()` through the MAX upload flow: upload each local image/file, send media attachments with upload `token`, retry `attachment.not.ready`, and fallback to a client text plus `system_logs.event_type='max_media_delivery_failed'` if media delivery fails.
- `app/bot/max_message_processor.py` now lets normalized MAX messages use the shared related-media routing (`process_client_message(..., send_related_media=True)`), so explicit and auto photo paths can reach MAX through `ChannelClient.send_media()` instead of a MAX-specific dialog fork.
- MAX payment links preserve the ordinary text fallback and can also get an inline keyboard `link` button when `MaxChannelClient.send_text()` sees a payment/prepayment text containing an HTTP link, or when a caller passes explicit link-button options. Telegram text/media/payment paths were not changed.
- Contact request button was intentionally left for later: Step 10 did not add `request_contact` or contact-hash validation; roadmap now records this as a later slice.
- Added `scripts/max_media_buttons_smoke.py`: no-secret/no-DB fake smoke for `/uploads`, upload URL use, MAX media send attachments, `attachment.not.ready` retry, payment link button format, media fallback logging and normalized MAX auto-media routing.
- Checks: `.\.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts\max_media_buttons_smoke.py` OK; `scripts\max_outbound_text_smoke.py` OK; `scripts\max_api_client_smoke.py` OK; `scripts\max_inbound_normalization_smoke.py` OK; `scripts\max_webhook_runner_smoke.py` OK; `scripts\channel_contract_smoke.py` OK; `scripts\channel_notifications_smoke.py` OK; `scripts\max_dev_polling_smoke.py` safe skip because `MAX_BOT_TOKEN` is not configured; `scripts\local_regression_suite.py --group media --group payments` OK.
- After the DB-mutating regression: `clear_db.py` OK, `sync_yclients_records.py --once` OK (`seen=128/upserted=128`), `yclients_sync_status.py --strict` fresh (`age_seconds=113`, `records_seen=128`) and `live_db_hygiene_audit.py --limit 20` clean. `git diff --check` on touched Step 10 files is clean apart from expected LF/CRLF warnings on existing wiki files.
- Graphify updated via `best2graph/update_graph.ps1`: incremental scan saw `5 code / 36 docs / 12 images changed`; final graph after reclustering has `180 nodes`, `446 edges`, `24 communities`. Control query finds `MaxApiClient.upload_file()`, `create_upload()`, `MaxChannelClient.send_media()`, `_send_message_with_attachment_retry()`, payment link button smoke and `max_media_buttons_smoke.py`.

## 2026-06-04 - MAX Step 9 user notifications by channel

- Completed Step 9 from [[roadmap/max-context-window-steps]]: client payment/hold/reminder/waitlist notifications now route through `NotificationRouter` by the user's stored channel. Admin notifications remain Telegram-only for the MVP; MAX webhook registration, `POST /subscriptions`, media/buttons/contact/voice and real payment smokes were not added.
- Added `app/bot/client_notification_router.py` to build a client notification router with Telegram delivery when an aiogram bot is available and MAX text delivery when `MAX_BOT_TOKEN` is configured. This does not start MAX polling/webhook and does not call live MAX APIs by itself.
- Added `app/services/client_notification_service.py`: shared `DeliveryTarget` construction from `user_channel` + `user_external_id`, `send_client_text_notification()` dispatch through `NotificationRouter`, and `system_logs` event `client_notification_delivery_failed` for missing/unknown/failing channel. Failed delivery returns `delivered=False` and callers do not mark the notification as delivered.
- Updated `app/services/payment_status_runner.py`: auto-resent payment links, paid payment notifications, paid-without-booking notices, journal-pending paid notices, expired-hold notices and booking reminders use the client router for text delivery. Telegram paid-booking media remains Telegram-only and is sent after the text for Telegram targets; MAX MVP receives only the ordinary text.
- Updated `app/services/waitlist_service.py`: waitlist match notifications use `NotificationRouter` and mark `waitlist_requests.status='notified'` only after successful delivery.
- Updated repository contracts so notification rows include `user_channel`: `payments_repo.list_paid_unnotified()`, `slot_holds_repo.list_expired_unnotified()` and `waitlist_repo.list_active_due()`. `bookings_repo.list_due_reminders()` already returned `user_channel`.
- Added `scripts/channel_notifications_smoke.py`: no-secret/no-DB fake-router smoke for Telegram reminder delivery, MAX reminder delivery, waitlist Telegram/MAX delivery, unknown channel logging without delivered marks and adapter failure logging without delivered marks.
- Checks: `.\.venv\Scripts\python.exe -m compileall app scripts` OK; `.\.venv\Scripts\python.exe scripts\channel_notifications_smoke.py` OK; `channel_contract_smoke.py` OK; `max_outbound_text_smoke.py` OK; `max_api_client_smoke.py` OK; `max_inbound_normalization_smoke.py` OK; `max_webhook_runner_smoke.py` OK; `max_dev_polling_smoke.py` OK with safe skip because `MAX_BOT_TOKEN` is not configured; `local_regression_suite.py --group payments --group waitlist --group reminder` OK. After DB-mutating regression, `clear_db.py` OK, `sync_yclients_records.py --once` OK (`seen=128/upserted=128`), strict sync fresh and `live_db_hygiene_audit.py --limit 20` clean.
- `git diff --check` on touched Step 9 files is clean apart from expected LF/CRLF warnings on existing Windows-tracked files. Graphify updated via `best2graph/update_graph.ps1`: incremental scan saw `8 code / 36 docs / 12 images changed`; final graph after reclustering has `214 nodes`, `471 edges`, `26 communities`. Control query finds `send_client_text_notification()`, `notify_paid_payments_once()`, `notify_booking_reminders_once()`, `notify_expired_holds_once()`, `notify_waitlist_matches()` and the router builder.
- Telegram client notification text/order stays behavior-preserving for text sends; admin notifications are still direct Telegram. MAX users can receive these client notifications only as text through `MaxChannelClient`; MAX polling remains dev/test-only and the MAX webhook runner is still not wired into `main.py` / `telegram_bot.py`.

## 2026-06-04 - MAX Step 8 outbound text

- Completed Step 8 from [[roadmap/max-context-window-steps]]: added MAX outbound text for the text-only MVP without registering a webhook, without calling `POST /subscriptions`, without live MAX calls in tests, without media/buttons/contact/voice, without real payments and without changing Telegram delivery.
- `app/integrations/max_client.py` now has `send_message(text, user_id=None, chat_id=None)` for `POST /messages`. It sends the bot token only in the `Authorization` header, keeps the token out of the URL/query params, uses `user_id` or `chat_id` query params, sends JSON body `{"text": ...}`, guards MAX text at `4000` characters and redacts the token from error text.
- Added `app/bot/max_channel_client.py`: `MaxChannelClient.send_text()` implements the `ChannelClient` text path over `MaxApiClient`. It chooses `chat_id` when `DeliveryTarget.chat_id` is present, otherwise uses `DeliveryTarget.external_id` as `user_id`, and splits long text into MAX-sized chunks. `send_typing()` is a no-op and `send_media()` logs a text-only MVP skip instead of adding media support.
- Added `app/bot/max_message_processor.py`: `process_max_update()` normalizes MAX updates, builds `DeliveryTarget` and calls the shared `process_client_message(..., send_related_media=False)`. `process_max_webhook_event()` / `make_max_webhook_event_processor()` provide a safe event-processor hook for the existing webhook runner, but this step still does not connect the webhook runner to `main.py`/`telegram_bot.py` and does not register webhook subscriptions.
- Added `scripts/max_outbound_text_smoke.py`: no-secret fake HTTP/adapter smoke checks `POST /messages` URL/query/body/auth, `chat_id` vs `user_id` target selection, 4000-character split/guard, token redaction and the normalized MAX inbound path into the shared processor via a fake `handle_incoming()`.
- Checks: `.\.venv\Scripts\python.exe -m compileall app scripts` OK; `.\.venv\Scripts\python.exe scripts\max_outbound_text_smoke.py` OK (`max_outbound_text_smoke=ok`); `.\.venv\Scripts\python.exe scripts\max_api_client_smoke.py` OK; `.\.venv\Scripts\python.exe scripts\max_inbound_normalization_smoke.py` OK; `.\.venv\Scripts\python.exe scripts\max_webhook_runner_smoke.py` OK; `.\.venv\Scripts\python.exe scripts\max_dev_polling_smoke.py` OK with safe skip because `MAX_BOT_TOKEN` is not configured; `git diff --check -- app/integrations/max_client.py app/bot/max_channel_client.py app/bot/max_message_processor.py scripts/max_outbound_text_smoke.py` OK.
- Graphify updated via `best2graph/update_graph.ps1`: incremental scan saw `4 code / 36 docs / 12 images changed`; final graph after reclustering has `125 nodes`, `229 edges`, `23 communities`. Control query finds `MaxChannelClient`, `send_message()`, `split_max_text()`, `process_max_update()` and `max_outbound_text_smoke.py`.
- Telegram behavior was not changed in this step: `TelegramChannelClient`, Telegram normalization, Telegram polling/runtime and `message_handler.py` were not edited. Admin notifications remain Telegram for MVP. MAX polling remains dev/test-only and production MAX remains webhook-oriented.

## 2026-06-04 - MAX Step 7 inbound normalization

- Completed Step 7 from [[roadmap/max-context-window-steps]]: added MAX inbound normalization without registering a webhook, without calling `POST /subscriptions`, without connecting MAX outbound text, without changing Telegram normalization and without real payments.
- Added `app/bot/max_router.py`: `normalize_max_update(update) -> IncomingMessage | None` handles MVP `message_created` text events and `bot_started` events. Normalized messages keep `channel='max'`, `external_user_id`, `user_name`, `message_time` and `raw_payload` with `update_type`, `timestamp`, `chat_id`, `message_id`, optional `payload` and the original MAX update copy.
- `message_created` accepts text from common MAX shapes (`message.body.text`, string `body`, nested `message_created`, root `text`) and ignores non-text or userless events safely. `bot_started` becomes `/start` or `/start <payload>` and keeps the deeplink payload in `raw_payload["payload"]`.
- `app/bot/max_polling_runner.py::normalize_max_text_update()` now reuses `normalize_max_update()` and remains a text-only wrapper returning `(IncomingMessage, DeliveryTarget)` for the Step 5 dev polling smoke. It still ignores `bot_started` for polling text smoke and still does not send `POST /messages`.
- Added `scripts/max_inbound_normalization_smoke.py`: local no-secret payload-shape smoke for `message_created`, nested `message_created`, `bot_started`, ignored unknown/non-text events and polling-wrapper compatibility.
- Checks: `.\.venv\Scripts\python.exe -m compileall app scripts` OK; `.\.venv\Scripts\python.exe scripts\max_inbound_normalization_smoke.py` OK (`max_inbound_normalization_smoke=ok`); `.\.venv\Scripts\python.exe scripts\max_webhook_runner_smoke.py` OK (`max_webhook_runner_smoke=ok`); `.\.venv\Scripts\python.exe scripts\max_dev_polling_smoke.py` OK with safe skip because `MAX_BOT_TOKEN` is not configured; `git diff --check -- app/bot/max_router.py app/bot/max_polling_runner.py scripts/max_inbound_normalization_smoke.py` OK.
- Graphify updated via `best2graph/update_graph.ps1`: incremental scan saw `3 code / 36 docs / 12 images changed`; final graph after reclustering has `115 nodes`, `228 edges`, `22 communities`. Control query finds `normalize_max_update()`, `max_router.py`, `normalize_max_text_update()` and `max_inbound_normalization_smoke.py`.
- Telegram behavior was not changed: `app/bot/router.py`, `app/bot/telegram_bot.py`, `app/bot/client_message_processor.py` and `app/services/message_handler.py` were not edited in this step. MAX webhook runner remains unconnected to `main.py`/`telegram_bot.py`; webhook was not registered and MAX outbound text remains a later step.

## 2026-06-04 - MAX Step 6 webhook runner

- Выполнен Шаг 6 из [[roadmap/max-context-window-steps]]: добавлен MAX webhook runner/endpoint без регистрации webhook, без `POST /subscriptions`, без production-start подключения по умолчанию, без outbound MAX text, без inbound normalization Step 7 и без реальных платежей.
- Добавлен `app/bot/max_webhook_runner.py`: lightweight HTTP runner принимает только `MAX_WEBHOOK_PATH` (`/webhooks/max` по умолчанию), проверяет `X-Max-Bot-Api-Secret`, `Content-Length`, `MAX_WEBHOOK_MAX_BODY_BYTES`, UTF-8 JSON и то, что payload является JSON object. Для production/prod server fail-fast требует `MAX_WEBHOOK_SECRET`; запуск разрешен только при `MAX_MODE=webhook` и `MAX_WEBHOOK_ENABLED=true`.
- Endpoint делает durable duplicate gate до фоновой обработки через существующую `webhook_events`: `provider='max'`, `event_type` из `update_type/type/event_type`, `provider_object_id` как стабильный MAX event key (`event/update/id`, scoped message id или canonical `sha256`). Дубликат возвращает быстрый `200 OK` с `duplicate=true` и не попадает в очередь повторно.
- Валидный новый event кладется в in-memory queue и HTTP response возвращается сразу после validation + dedup + enqueue; обработчик очереди вызывает опциональный `event_processor`. Если processor не передан, event логируется как accepted without processor и остается в `webhook_events` без `processed_at`, чтобы не имитировать фактическую dialog-обработку до следующих шагов.
- `app/core/config.py` и `.env.example` расширены MAX webhook runtime-полями `MAX_WEBHOOK_HOST`, `MAX_WEBHOOK_PORT`, `MAX_WEBHOOK_MAX_BODY_BYTES` поверх уже существующих `MAX_WEBHOOK_ENABLED/PATH/URL/SECRET/MODE`.
- Добавлен `scripts/max_webhook_runner_smoke.py`: fake in-memory `webhook_events` проверяет production-secret fail-fast, path validation, secret mismatch, bad JSON, JSON-array rejection, body-size limit, duplicate event и quick accept при медленном processor.
- Проверки: `.\.venv\Scripts\python.exe -m compileall app scripts` OK; `.\.venv\Scripts\python.exe scripts\max_webhook_runner_smoke.py` OK (`max_webhook_runner_smoke=ok`); `git diff --check -- app/bot/max_webhook_runner.py app/core/config.py .env.example scripts/max_webhook_runner_smoke.py` OK только с ожидаемыми LF/CRLF warnings для уже dirty tracked files.
- Graphify обновлен через `best2graph/update_graph.ps1`: incremental scan увидел `3 code / 36 docs / 12 images changed`, итоговая карта после reclustering `116 nodes`, `164 edges`, `23 communities`. Контрольный query находит `max_webhook_runner.py`, `stable_max_event_key()` и `max_webhook_runner_smoke.py`.
- Telegram behavior не менялось: `telegram_bot.py`, `client_message_processor.py` и `message_handler.py` в этом шаге не редактировались; admin notifications MVP остаются Telegram; MAX polling не включался и webhook не регистрировался.

## 2026-06-04 - MAX Step 5 dev polling smoke

- Выполнен Шаг 5 из [[roadmap/max-context-window-steps]]: добавлен dev/test-only MAX polling smoke/runtime без подключения polling к production start, без webhook registration, без MAX outbound text как production-функции и без реальных платежей.
- `app/integrations/max_client.py` расширен минимальным безопасным `get_updates(marker, limit, timeout, types)` для `GET /updates`: токен по-прежнему передается только через `Authorization` header, параметры polling идут как query params без token, `limit` ограничен `1..1000`, `timeout` `0..90`, GET retry/429 logic переиспользует существующий `_request()`.
- Добавлен `app/bot/max_polling_runner.py`: `run_max_dev_polling_smoke()` делает read-only `GET /me` + `GET /subscriptions`, блокирует polling при `APP_ENV=production`, `MAX_WEBHOOK_ENABLED=true`, `MAX_MODE != polling` или наличии webhook subscriptions, затем делает `GET /updates` только для `message_created`.
- В этом срезе MAX text update прогоняется через общий путь `IncomingMessage(channel='max') -> process_client_message() -> handle_incoming()`, но доставка ответа намеренно dry-run: `DryRunMaxChannelClient` только захватывает reply/typing/media counts и не отправляет `POST /messages`. Для smoke `process_client_message(..., send_related_media=False)` отключает post-reply media routing, чтобы не помечать авто-медиа как отправленное без реальной MAX-доставки. Реальный MAX outbound text остается следующим отдельным шагом, не смешанным с polling smoke.
- Добавлен `scripts/max_dev_polling_smoke.py`: локальный CLI печатает безопасный summary без token и без текста клиента/ответа. При пустом `MAX_BOT_TOKEN` локальный результат: `{'base_url': 'https://platform-api.max.ru', 'app_env': 'local', 'max_mode': 'webhook', 'max_webhook_enabled': False, 'status': 'skipped', 'reason': 'MAX_BOT_TOKEN is not configured', 'max_configured': False}`.
- `scripts/max_api_client_smoke.py` расширен fake-проверкой `get_updates()`: header-only auth, отсутствие token в URL и корректные `marker/limit/timeout/types`.
- Проверки: `.\.venv\Scripts\python.exe -m compileall app scripts` OK; `.\.venv\Scripts\python.exe scripts\max_api_client_smoke.py` OK (`max_api_client_smoke=ok`); `.\.venv\Scripts\python.exe scripts\max_status.py` OK со skip из-за отсутствующего `MAX_BOT_TOKEN`; `.\.venv\Scripts\python.exe scripts\max_dev_polling_smoke.py` OK со skip по той же причине; inline `max_polling_normalizer_sanity=ok`; `git diff --check -- app/integrations/max_client.py app/bot/max_polling_runner.py scripts/max_api_client_smoke.py scripts/max_dev_polling_smoke.py` OK.
- Graphify обновлен через `best2graph/update_graph.ps1`: финальный повтор после processor-флага прошел без warning, incremental scan увидел `2 code / 36 docs / 12 images changed`, итоговая карта `107 nodes`, `192 edges`, `22 communities`; контрольный query находит `run_max_dev_polling_smoke()`, `get_updates()`, `max_dev_polling_smoke.py` и `send_related_media` flag в `process_client_message()`.
- Telegram behavior не менялось: `app/bot/telegram_bot.py`, `app/bot/client_message_processor.py` и `app/services/message_handler.py` в этом шаге не редактировались; admin notifications MVP остаются Telegram.

## 2026-06-04 - MAX Step 4 API client and status scripts

- Выполнен Шаг 4 из [[roadmap/max-context-window-steps]]: добавлен безопасный read-only MAX API слой без подключения runtime MAX, без webhook registration, без dev polling, без outbound/inbound MAX и без реальных платежей.
- Добавлен `app/integrations/max_client.py`: `MaxApiClient` использует `MAX_API_BASE_URL` (`https://platform-api.max.ru` по умолчанию), передает `MAX_BOT_TOKEN` только в header `Authorization: <token>`, реализует `get_me()` и `get_subscriptions()`, timeout, retry для GET, обработку `429 Retry-After`, backoff для transient network/5xx и redaction токена из error body.
- Добавлен `scripts/max_status.py`: проверяет `GET /me` и `GET /subscriptions`, печатает только безопасные поля бота/подписок и при пустом `MAX_BOT_TOKEN` завершается понятным skip. Локальный результат: `{'status': 'skipped', 'reason': 'MAX_BOT_TOKEN is not configured', 'base_url': 'https://platform-api.max.ru', 'max_configured': False}`.
- Добавлен `scripts/max_api_client_smoke.py`: fake HTTP smoke проверяет header-only auth, отсутствие токена в URL, retry по `429 Retry-After` и понятную ошибку при пустом токене.
- Проверки: `.\.venv\Scripts\python.exe -m compileall app scripts` OK; `.\.venv\Scripts\python.exe scripts\max_api_client_smoke.py` OK (`max_api_client_smoke=ok`); `.\.venv\Scripts\python.exe scripts\max_status.py` OK со skip из-за отсутствующего `MAX_BOT_TOKEN`.
- Обновлен [[architecture/api]]: зафиксирован фактический MAX API client/status slice и границы среза. Telegram behavior не менялся: `telegram_bot.py`, `client_message_processor.py` и `message_handler.py` в этом шаге не редактировались.
- Graphify обновлен через `best2graph/update_graph.ps1`: incremental scan увидел `3 code / 36 docs / 12 images changed`, итоговая карта после reclustering `101 nodes`, `150 edges`, `22 communities`. Контрольный query находит `MaxApiClient`, `get_me()`, `get_subscriptions()`, `max_status.py` и `max_api_client_smoke.py`.

## 2026-06-04 - MAX Step 3 Telegram behavior-preserving extraction

- Выполнен Шаг 3 из [[roadmap/max-context-window-steps]]: Telegram processing path вынесен без подключения MAX runtime. `app/bot/client_message_processor.py` теперь владеет общим клиентским путем `IncomingMessage -> per-user lock -> asyncio.to_thread(handle_incoming) -> ChannelClient reply -> media routing -> error fallback`.
- Добавлен `app/bot/telegram_channel_client.py`: `TelegramChannelClient` реализует `ChannelClient` поверх текущего `aiogram.Bot`. Для входящих Telegram сообщений он сохраняет прежнюю семантику доставки: основной ответ идет как `message.reply(...)` через опцию `reply_to_message`, а media note/photo/media group после ответа идут как `message.answer...` через `source_message`.
- `app/bot/telegram_bot.py` оставлен Telegram adapter/runtime: `/start`, `/status`, text/caption/voice handlers, voice transcription, dispatcher, polling, YCLIENTS sync loop, payment status loop, message retention loop и YooKassa webhook server остаются в нем. Фоновые loops и admin notifications на этом срезе остаются Telegram-first.
- MAX-функции в этом шаге не добавлялись: нет `MaxApiClient`, MAX polling, MAX webhook, MAX outbound, webhook registration или реальных платежей. `message_handler.py` не копировался и не форкался.
- Проверки: `.\.venv\Scripts\python.exe -m compileall app scripts` OK; `.\.venv\Scripts\python.exe scripts\local_regression_suite.py --list-cases` OK.
- Graphify обновлен через `best2graph/update_graph.ps1`: incremental scan увидел `3 code / 36 docs / 12 images changed`, итоговая карта после reclustering `103 nodes`, `153 edges`, `22 communities`. Контрольный query теперь находит `TelegramChannelClient`, `process_client_message()`, `_process_incoming_with_lock()`, media routing и `telegram_bot.py::run_polling()`.

## 2026-06-04 - MAX Step 2 transport contract

- Выполнен Шаг 2 из [[roadmap/max-context-window-steps]]: введен пассивный transport contract для будущих каналов без подключения MAX runtime и без изменения Telegram behavior. `handle_incoming()` и `app/bot/telegram_bot.py` не менялись; Telegram polling/output остается прежним.
- Добавлены channel constants: `CHANNEL_MAX = "max"` и `SUPPORTED_CLIENT_CHANNELS` в `app/core/constants.py`; `CHANNEL_TELEGRAM` сохранен на прежнем месте для совместимости существующих импортов.
- Добавлены новые contract-модули: `app/bot/channel_types.py` (`DeliveryTarget`, `OutboundMessage`), `app/bot/channel_client.py` (`ChannelClient` Protocol) и `app/bot/notification_router.py` (`NotificationRouter`, `NotificationDeliveryError`). Router пока только dispatch-ит по зарегистрированному channel client и явно падает на неизвестном канале; существующие Telegram отправки к нему еще не подключены.
- `app/core/config.py` и `.env.example` расширены MAX/client-channel полями: `CLIENT_CHANNELS`, `MAX_BOT_TOKEN`, `MAX_API_BASE_URL`, `MAX_WEBHOOK_ENABLED`, `MAX_WEBHOOK_PATH`, `MAX_WEBHOOK_URL`, `MAX_WEBHOOK_SECRET`, `MAX_MODE`. `safe_summary()` показывает только безопасные флаги (`client_channels`, `max_configured`, `max_mode`, `max_webhook_enabled`) без токена/secret.
- Добавлен `scripts/channel_contract_smoke.py`: fake `ChannelClient` проверяет `DeliveryTarget.address`, `OutboundMessage.media_paths`, `NotificationRouter.send_text/send()` и ошибку `NotificationDeliveryError` для неизвестного канала.
- Проверки: `python -m compileall app scripts` OK; `scripts/channel_contract_smoke.py` OK (`channel_contract_smoke=ok`); inline import/settings sanity-check OK (`channels=('telegram','max')`, `max_api_base_url='https://platform-api.max.ru'`, local `client_channels='telegram'`, `max_configured=False`). `git diff --check` по измененным файлам exit 0 с ожидаемыми LF/CRLF warnings.
- Graphify обновлен через `best2graph/update_graph.ps1`: incremental scan увидел `6 code / 36 docs / 12 images changed`, итоговая карта `111 nodes`, `175 edges`, `26 communities`. Query по transport contract находит `DeliveryTarget`, `OutboundMessage`, `NotificationRouter`, `ChannelClient` и `channel_contract_smoke.py`.
- Обновлены [[architecture/backend]] и [[roadmap/max-channel-entry-exit-plan]] под фактический status Шага 2. Следующий безопасный MAX шаг - Шаг 3 Telegram behavior-preserving extraction: вынести общий processing path и `TelegramChannelClient`, не добавляя MAX runtime-функции.

## 2026-06-04 - MAX Step 1 inventory and freeze

- Выполнен Шаг 1 из [[roadmap/max-context-window-steps]]: MAX inventory/freeze. Production-code не менялся; webhook registration, MAX polling, реальные платежи и Graphify update не запускались. Graphify query по Telegram-bound точкам был выполнен первым, но отдал слабую semantic-выдачу по knowledge nodes, поэтому дальше использованы read-only `rg` и открытие конкретных runtime/config файлов.
- Подтверждены текущие Telegram-bound точки: `main.py` напрямую запускает `app.bot.telegram_bot.run_bot()`. `app/bot/telegram_bot.py` владеет Telegram polling, `/start`, `/status`, text/caption/voice handlers, per-user lock, typing action, `message.reply()/answer()`, автофото через `FSInputFile`/`MediaGroupBuilder`, а также стартует YCLIENTS sync loop, payment status loop, message retention loop и YooKassa webhook server.
- Входной шов уже есть, но только для Telegram: `app/bot/router.py` нормализует Telegram payload в `IncomingMessage(channel='telegram', external_user_id, user_name, text, message_time, raw_payload)`, а `normalize_incoming()` пока оставлен как future adapter и для не-Telegram каналов бросает `NotImplementedError`.
- Background/output остаются `aiogram.Bot`-bound: `payment_status_runner.py` отправляет client payment/expired-hold/reminder/journal-pending notifications и admin events через `bot.send_message/send_photo/send_media_group`; `waitlist_service.py` принимает `Bot` и шлет waitlist match по `row["user_external_id"]`; `yclients_sync_runner.py` вызывает waitlist notifications через переданный Telegram bot; `yookassa_webhook_runner.py` после webhook вызывает `notify_paid_payments_once(bot)`; `admin_telegram_service.py` жестко использует `ADMIN_TELEGRAM_CHAT_ID`; `voice_transcription_service.py` скачивает voice через Telegram Bot API. Это будущий scope для `ChannelClient`/`NotificationRouter`, но admin notifications на MAX MVP остаются в Telegram.
- Env/config inventory: `app/core/constants.py` содержит только `CHANNEL_TELEGRAM`; `app/core/config.py` не читает MAX-настройки; `.env.example` сейчас содержит только `MAX_BOT_TOKEN` и `MAX_WEBHOOK_SECRET`. Для Шага 2 не хватает зафиксированных contract fields: `CHANNEL_MAX`, `CLIENT_CHANNELS`, `MAX_API_BASE_URL`, `MAX_WEBHOOK_ENABLED`, `MAX_WEBHOOK_PATH`, `MAX_WEBHOOK_URL`, `MAX_MODE`, а также `DeliveryTarget`, `OutboundMessage`, `ChannelClient` и `NotificationRouter`.
- DB readiness подтверждена на уровне кода: `users_repo` ищет/создает пользователей по `(channel, external_id)`, `conversations_repo.create()` сохраняет `channel`, а `webhook_events_repo.create_if_new()` уже имеет conflict-key `(provider, event_type, provider_object_id)` и может быть переиспользован для `provider='max'` со стабильным MAX event key.
- Dirty tree inventory: рабочее дерево уже большое и не является чистым baseline. Группы изменений: production-code refactor/hardening (`app/db/connection.py`, `app/services/*`, новые dialog helpers), tests/scripts (`scripts/local_regression_suite.py`, `scripts/dialog_context_suite.py`, `scripts/live_health_report.py`), `best2info`, `best2obs`, `best2graph/graphify-out`, root `graphify-out/cache`. Отдельно есть untracked новые flow/wiki файлы из предыдущих срезов. `git diff --name-status --diff-filter=D` не показал tracked deletions; `git diff` выводит только ожидаемые LF/CRLF warnings.
- Freeze зафиксирован: до закрытия Шага 2 transport contract и Шага 3 Telegram behavior-preserving extraction не начинать MAX feature work, который требует копии `message_handler.py` или параллельного MAX-ядра. Следующий безопасный шаг по MAX - [[roadmap/max-context-window-steps]] Шаг 2 Transport Contract.

## 2026-06-04 - MAX text-only MVP plan clarified

- Уточнен MAX MVP scope по новому плану: MAX добавляется рядом с Telegram, общий путь остается `IncomingMessage -> handle_incoming() -> reply`, первый MVP ограничен текстом и обычной ссылкой оплаты текстом. MAX media, link-button оплаты, contact-button и voice/audio adapter вынесены в post-MVP срезы.
- Обновлены [[decisions/2026-06-04-max-mvp-channel-decisions]], [[roadmap/max-context-window-steps]] и [[roadmap/max-channel-entry-exit-plan]]: первые live-проверки идут через dev-only polling, production MAX идет через HTTPS webhook, webhook registration остается ручным, duplicate safety переиспользует `webhook_events(provider='max')`.
- Обновлены planned-секции [[architecture/api]], [[architecture/backend]], [[operations/production-env-checklist]] и [[operations/production-runbook]]: MAX env/config contract, `platform-api.max.ru`, `Authorization` header, `/webhooks/max`, `X-Max-Bot-Api-Secret`, `CLIENT_CHANNELS=telegram,max`, запрет production polling и MAX status/runbook checks.
- Wiki-only изменение: production-code не менялся, реальные webhook registration/платежи не запускались, тесты и Graphify не запускались.

## 2026-06-04 - MAX context-window rollout route

- Создан [[roadmap/max-context-window-steps]]: операционный маршрут внедрения MAX по одному контекстному окну. Каждый из 12 шагов содержит стартовый prompt, действия, Definition of Done и правило обновления памяти.
- [[roadmap/max-channel-entry-exit-plan]] оставлен архитектурной основой; новый файл не заменяет архитектурный план, а задает порядок выполнения: inventory/freeze, transport contract, Telegram extraction, MAX client/status, dev polling smoke, webhook runner, inbound normalization, outbound text, user notifications, media/buttons/contact, runbook/env/checks, launch gate.
- Зафиксированы решения в [[decisions/2026-06-04-max-mvp-channel-decisions]]: MAX добавляется рядом с Telegram, Telegram остается рабочим клиентским каналом на время внедрения, admin notifications на MVP остаются в Telegram.
- `best2obs/index.md` обновлен ссылкой на новый MAX route и decision. Изменение wiki-only: production-code не менялся, production tests не запускались, Graphify не обновлялся.

## 2026-06-04 - MAX channel entry/exit architecture plan

- Изучена официальная документация MAX для чат-ботов, API, создания бота, webhook/subscriptions, сообщений, updates, media upload, кнопок, deep links и legal/requirements pages.
- Создан roadmap [[roadmap/max-channel-entry-exit-plan]]: целевой срез — не копировать `message_handler.py` под MAX, а выделить transport entry/exit points вокруг уже существующего `IncomingMessage -> handle_incoming() -> reply` ядра.
- Текущий вывод по архитектуре: БД уже channel-aware (`users.channel`, `external_id`, `conversations.channel`), но runtime/output еще Telegram-bound: `main.py -> telegram_bot.run_bot()`, `payment_status_runner`, `waitlist_service`, `admin_telegram_service`, voice/media используют `aiogram.Bot`.
- План фиксирует новые точки: `ChannelClient`, `NotificationRouter`, `client_message_processor`, `MaxApiClient`, `max_router`, `max_webhook_runner`, dev-only `max_polling_runner`, `max_status.py` и `register_max_webhook.py`. Production MAX должен идти через HTTPS webhook, long polling только для dev/test.
- `best2obs/index.md` обновлен ссылкой на новый roadmap. Production-code не менялся.

## 2026-06-04 - reference/unavailable flow extraction and regression guard

- Выполнен первый post-MVP refactor slice из плана dialog coordinator: создан `app/services/dialog/reference_flow.py`. В него вынесены pure route/helpers для same-date/same-time reference patch, запроса ближайших свободных дат после `last_unavailable`, alternative-service reply после недоступного слота и повтора той же недоступной даты. `message_handler_flow_glue.py` оставляет единый assistant commit через локальный `commit_route_result()` и thin callback adapters; route helpers сами не пишут assistant message.
- Добавлен внутренний `RouteResult` для reference routes: `reply/status/current_step/next_step/form_data/intent`. Полная route-table/priority схема пока не вводилась: порядок поведения сохранен, а текущий срез только делает reference/unavailable ветки видимее и тестируемее.
- Red-first regression добавлен в `scripts/local_regression_suite.py`: `services	second service same reference unavailable keeps current service`. До фикса он падал: paid gazebo -> новая bathhouse same-day -> same-time reference unavailable сохранял `service_type=gazebo` и отвечал про «Беседка». После фикса `preserve_current_service_for_reference()` из `reference_flow.py` сохраняет текущую bathhouse draft-услугу для reference-фраз без явного нового service request; `last_unavailable.service_type` остается `bathhouse`, ответ говорит про «Баня».
- Перед срезом baseline: `compileall app scripts` OK, `local_regression_suite.py --list-cases` OK, `dialog_context_suite.py` сначала поймал устаревший assert на старую банную фразу `3, 4, 5, 6 и 7`; expectation обновлен под текущий package-table UX, после чего context 19/19 OK. `dialog_edge_suite.py` первый запуск не уложился в 180s без assert-fail, повтор с большим таймаутом 15/15 OK; `dialog_stress_suite.py` 13/13 OK.
- Verification после среза: `python -m compileall app scripts` OK; named red-first case OK; `local_regression_suite.py --group post_booking --group services --group gazebo --group dates --group time` exit 0; `dialog_context_suite.py` 19/19 OK; `dialog_stress_suite.py` 13/13 OK. `git diff --check` exit 0 с ожидаемыми LF/CRLF warnings. `--list-cases` теперь показывает 201 непустой case-line; новая строка находится в группе `services`, текущий dirty baseline уже отличался от старой записи про 199.
- После DB-mutating checks выполнены `scripts/clear_db.py`, `scripts/sync_yclients_records.py --once` (`seen=125`, `upserted=125`), `scripts/yclients_sync_status.py --strict` fresh (`records_seen=125`, `last_error=None`), `scripts/live_db_hygiene_audit.py --limit 20` clean и `scripts/live_health_report.py` `status=ok`, blockers/warnings пустые, runtime tables чистые.
- Graphify обновлен через `best2graph/update_graph.ps1`: incremental scan увидел 5 code / 36 docs / 12 images changed, финальная карта `638 nodes`, `2868 edges`, `34 communities`. Query по `reference_flow.py` находит `RouteResult`, callback dataclasses, `same_booking_reference_patch()`, `free_dates_after_unavailable_route()`, `unavailable_alternatives_route()` и glue adapters.

## 2026-06-04 - live dialog fix: bathhouse period text, PM period parsing and gazebo capacity replacement

- Закрыт срочный live-пакет из ручного диалога 2026-06-04. Симптомы: банный date-only ответ с пакетами был слишком плотным и непонятным; фраза `мы приеду с 12 дня до 8 вечера` могла превратиться в период до `08:00 следующего дня`; фраза `могу заменить 6 беседку, нас просто человек 30 придет, и 6 беседка не подойдет` уходила в ближайшие свободные даты/`75 дней` вместо подбора подходящих беседок на уже известную дату/период.
- Исправления: `time_parsing.time_period_patch()` сохраняет маркеры `дня/вечера/ночи` при разборе периода и не считает `ч` внутри `человек` единицей часов; битый guard `на <N> часов` восстановлен в UTF-8. `bathhouse_period_options_reply()` теперь даёт пошаговый текст с таблицей пакетов 3-7 часов, будни/пт-вс ценами и примерами периода. В `message_handler_flow_glue.py` добавлен ранний `_impl_gazebo_capacity_change_request()` до semantic preflight: активная беседка + просьба заменить/не подходит + новое число гостей очищает старую беседку, сохраняет дату/время/длительность, проверяет свободные подходящие варианты и не уходит в `75 дней`.
- Regression: `python -m compileall app scripts` OK; targeted cases OK: `people range is not parsed as time`, `afternoon time words parse as PM`, `bathhouse date-only reply explains packages`, `gazebo variant change for large group offers suitable`. Первый связанный прогон `local_regression_suite.py --group time --group gazebo --group services` поймал regression `на 15-17 человек` -> time-period; после исправления guard-а повторный связанный прогон завершился `exit=0`.
- После DB-mutating regression выполнены `scripts/clear_db.py`, `scripts/sync_yclients_records.py --once` (`seen=126`, `upserted=126`), `scripts/yclients_sync_status.py --strict` fresh (`records_seen=126`, `last_error=None`), `scripts/live_db_hygiene_audit.py --limit 20` clean и `scripts/live_health_report.py` `status=ok`, blockers/warnings пустые, runtime tables чистые. `git diff --check` exit 0 с ожидаемыми LF/CRLF warnings.
- Graphify обновлён через `best2graph/update_graph.ps1`: incremental scan увидел 5 code / 36 docs / 12 images changed, финальная карта компактная (`443 nodes`, `1801 edges`, `27 communities`). Query по свежему helper-у всё ещё отдаёт слабую семантическую выдачу по `best2info/objects/gazebos.md`, но сам graph update завершился успешно.

## 2026-06-04 - compact full check and 3-scenario regression

- Выполнена компактная проверка проекта по запросу пользователя; production-code не менялся, Graphify не обновлялся. Baseline: `python -m compileall -q app scripts` OK, `scripts/test_db.py` OK (`user_id=3`, `conversation_id=3`, `message_id=160`), `scripts/lint_best2info.py` OK (`files=15`, `links_checked=15`, `price_checks=ok`) с прежними NOTE про ответы `уточним по факту`, `scripts/validate_yclients_map.py` OK (`checked_configured_pairs=29`, `live_book_services=29`, `unmapped_live_services=none`), `git diff --check` exit 0 с ожидаемыми LF/CRLF warnings.
- Первый `scripts/yclients_sync_status.py --strict` показал stale cache без ошибки (`age_seconds=928`, `records_seen=126`, `last_error=None`), после штатного `scripts/sync_yclients_records.py --once` YCLIENTS fresh (`seen=126`, `upserted=126`). Telegram API живой (`@fnsmvsvmpvpovbot`, webhook пустой, pending `0`). `scripts/live_health_report.py` до сценариев и после cleanup вернул `status=ok`, blockers/warnings пустые.
- Ровно 3 fake-AI сценария из `scripts/local_regression_suite.py` прошли OK: `gazebo date+guests first message checks availability`, `phone completion yes creates hold not second confirmation`, `bathhouse blocks 500 without unavailable alternatives`. После DB-mutating regression выполнены `scripts/clear_db.py`, повторный YCLIENTS sync/status и `scripts/live_db_hygiene_audit.py --limit 20`; финальный runtime чистый (`users/conversations/messages/slot_holds/bookings/payments/system_logs=0`), `yclients_records=126`, `resource_busy_intervals=126`, hygiene clean.
- Остаток по release route не изменился: следующий существенный шаг - [[roadmap/release-context-window-steps]] Step 6 server/systemd, но он требует отдельного server target/access и подтвержденного production env; далее Step 7 YooKassa webhook, Step 8 automated regression, Step 9 manual Telegram smoke, Step 10 controlled payment smoke, Step 11 launch gate, Step 12 first-day monitoring.

## 2026-06-04 - release minimal health report and server deploy boundary

- Выполнен Шаг 5 из [[roadmap/release-context-window-steps]]: добавлен read-only `scripts/live_health_report.py` для компактной pre/post-start диагностики. Скрипт не делает cleanup, sync, webhook calls или writes: открывает DB-сессию в read-only режиме и печатает JSON report со статусом `ok/blocker`.
- Health report проверяет: DB connectivity и safe DB identity, YCLIENTS sync freshness, counts runtime-таблиц, active holds, pending payments, paid payments без client notification marker, paid bookings без admin notification marker, bookings со статусом `journal_missing` или `yclients_create_error`, pending `refund_required`, последние system errors/logs. Exit 0 означает отсутствие blocker-ов; active holds/pending payments и recent system errors вынесены как warnings.
- `best2obs/operations/production-runbook.md` обновлен: `scripts/live_health_report.py` добавлен в post-start проверки через 1-2 минуты, DB/hygiene раздел и минимальный post-start report. Production business logic не менялась.
- Проверки Шага 5: `python -m compileall scripts\live_health_report.py` OK. Первый запуск `scripts/live_health_report.py` корректно вернул blocker из-за stale YCLIENTS (`fresh=False`, `age_seconds=1227`, `last_success_at=2026-06-04T08:17:46.094017+03:00`, `records_seen=126`, `last_error=None`). После штатного `scripts/sync_yclients_records.py --once` OK (`seen=126`, `upserted=126`) повторный `scripts/yclients_sync_status.py --strict` fresh (`age_seconds=62`, `records_seen=126`, `last_error=None`), а `scripts/live_health_report.py` завершился `status=ok`, blockers/warnings пустые.
- Финальный local health snapshot после sync сначала был: `users=1`, `conversations=1`, `messages=136`, `conversation_summaries=0`, `slot_holds=0`, `bookings=0`, `payments=0`, `waitlist_requests=0`, `system_logs=2`, `yclients_sync_state=1`, `yclients_records=127`, `resource_busy_intervals=127`, `webhook_events=0`; active holds/pending payments/paid notification gaps/journal errors/refund_required = `0`. Повторный report в 08:44 тоже `status=ok`, но `messages` вырос до `158`; read-only метаданные последних строк показывают пары `user/assistant` в conversation `1` за 08:42-08:44. Локальный `python main.py` не запущен, Telegram API живой (`@fnsmvsvmpvpovbot`, webhook пустой, pending `0`), значит DB, вероятно, пишет другой live/runtime экземпляр или внешний процесс. Это не вызвано `live_health_report.py`, но важно перед server/systemd шагом: не поднимать второй polling-процесс, пока не понятен текущий writer.
- После добавления script-кода выполнен `best2graph/update_graph.ps1`; query находит `scripts/live_health_report.py` и его helper-функции. Наблюдение: incremental Graphify снова сильно компактный (`78 nodes`, `197 edges` до reclustering, `23 communities`), но новый diagnostic slice присутствует.
- Шаг 6 [[roadmap/release-context-window-steps]] фактически не завершен: в локальном репозитории/памяти нет явного SSH/server target или deploy-конфига, а текущая среда Windows не является production-сервером с `/opt/best2` и `systemd`. Поэтому код не размещался на сервере, `/etc/best2/best2.env` не создавался, `systemctl start best2` не выполнялся, `journalctl` не проверялся. Для закрытия Шага 6 нужен отдельный server target/access и подтверждение production env; runbook уже содержит команды, включая новый `scripts/live_health_report.py`.

## 2026-06-04 - release production env checklist and runbook

- Выполнены Шаги 3-4 из [[roadmap/release-context-window-steps]]: создан production env checklist и production runbook. Production-code не менялся; изменения wiki-only: новые страницы [[operations/production-env-checklist]], [[operations/production-runbook]], ссылки в [[index]] и эта запись log. Graphify не обновлялся, потому что код не менялся.
- Для Шага 3 сверены `.env.example`, `app/core/config.py`, [[architecture/auth]] и [[architecture/api]]. В чеклисте зафиксированы production targets: `APP_ENV=production`, `APP_DEBUG=false`, `PREPAYMENT_MODE=percent`, `PREPAYMENT_PERCENT=50`, `YCLIENTS_SYNC_ENABLED=true`, `MESSAGE_SUMMARY_ENABLED=true`, `MESSAGE_SUMMARY_AFTER_HOURS=48`, `HTTP_TRUST_ENV=false`, `YOOKASSA_WEBHOOK_ENABLED=true`, non-empty `YOOKASSA_WEBHOOK_SECRET`, public HTTPS `YOOKASSA_WEBHOOK_URL` с path `/webhooks/yookassa`, заполненный `ADMIN_TELEGRAM_CHAT_ID`. Отдельно отмечено, что `PREPAYMENT_AMOUNT_RUB` не должен управлять production-суммой при `PREPAYMENT_MODE=percent`.
- Локальная проверка `get_settings().safe_summary()` выполнена только как sanity-check формы конфига, не как production-валидация. Текущий local summary: `app_env=local`, `db_host=luecahalemas.beget.app`, `db_name=default_db`, `db_sslmode=verify-full`, `ai_provider=openrouter`, `openai_model=anthropic/claude-sonnet-4`, `http_trust_env=False`, `voice_transcription_enabled=True`, `telegram_configured=True`, `openrouter_configured=True`, `yclients_configured=True`, `payment_provider=yookassa`, `payment_configured=True`, `prepayment_mode=fixed`, `prepayment_amount_rub=1`, `prepayment_percent=50`, `yookassa_webhook_enabled=True`.
- Для Шага 4 создан runbook с разделами: pre-start checklist, проверка `.env`, deploy/venv/init DB, пример `systemd` unit, старт ровно одного `main.py`, проверки Telegram API/YCLIENTS/YooKassa webhook/DB hygiene, остановка процесса, stale sync, DB timeout, paid-but-journal-pending, refund_required, cleanup тестовых записей YCLIENTS и cleanup локальной БД после тестов. Runbook намеренно не ссылается на будущий `scripts/live_health_report.py`, кроме пометки, что Шаг 5 должен добавить эту команду.

## 2026-06-04 - release local baseline gate

- Выполнен Шаг 2 из [[roadmap/release-context-window-steps]]: local baseline gate перед server/release действиями. Production-code не менялся; изменяется только этот log.
- Команды и результаты: `python -m compileall app scripts` OK; `scripts/test_db.py` OK (`OK user_id=2 conversation_id=2 message_id=113`, smoke сам очищает `test_smoke_user`); `scripts/lint_best2info.py` OK (`files=15`, `links_checked=15`, `price_checks=ok`) с прежними NOTE про ответы `уточним по факту`; `scripts/validate_yclients_map.py` OK (`checked_configured_pairs=29`, `live_book_services=29`, `unmapped_live_services=none`, aliases without direct service: `summer_gazebo`, `gazebo_bathhouse`).
- Первый `scripts/yclients_sync_status.py --strict` был stale, но без ошибки: `fresh=False`, `age_seconds=38206`, `last_success_at=2026-06-03T21:39:47.997176+03:00`, `records_seen=128`, `records_upserted=128`, `last_error=None`. По правилу шага выполнен `scripts/sync_yclients_records.py --once`: YCLIENTS HTTP 200, `seen=126`, `upserted=126`, window `-1/+60 days`.
- Повторный strict-status свежий: `fresh=True`, `age_seconds=54`, `last_success_at=2026-06-04T08:17:46.094017+03:00`, `records_seen=126`, `records_upserted=126`, `last_error=None`.
- `git diff --check` exit 0; новых whitespace/blocker проблем нет. Остались ожидаемые LF/CRLF warnings по уже dirty файлам production-code, `best2info`, `best2obs` и scripts.

## 2026-06-04 - release inventory and freeze

- Выполнен Шаг 1 из [[roadmap/release-context-window-steps]]: release inventory и freeze. Production-code не менялся; выполнены read-only команды `git status --short`, `git diff --stat`, `git diff --name-status`, `git status --porcelain=v1 -- graphify-out best2graph\graphify-out`, `git diff --name-status --diff-filter=D`, `git ls-files --deleted`.
- Dirty tree разложен по группам. Production-code: изменены `app/db/connection.py`, ряд `app/services/...`, `app/services/message_handler.py`; новые файлы `app/services/bathhouse_pricing.py`, `app/services/dialog/bathhouse_flow.py`, `app/services/dialog/message_handler_flow_glue.py`. Tests/scripts: `scripts/dialog_context_suite.py`, `scripts/local_regression_suite.py`. `best2info`: index/runtime и страницы бани/цен. `best2obs`: architecture, bugs, index, log, roadmap, testing pages, плюс новые roadmap-файлы `project-hardening-master-plan.md` и `release-context-window-steps.md`. `best2graph`: рабочая Graphify-карта в `best2graph/graphify-out`. Root cache/generated: tracked `graphify-out/cache/semantic/...`, `graphify-out/cache/stat-index.json` и набор untracked AST/semantic cache-файлов.
- `git diff --stat` на момент inventory: 35 tracked files changed, `13470 insertions(+), 35298 deletions(-)`. Большая часть удалений относится к перестроенному `best2graph/graphify-out/graph.json` и переразложенному `message_handler.py`; это уже существующее dirty-состояние до Шага 1, не новая правка этого шага. Git также печатает ожидаемые LF/CRLF warnings для ряда файлов.
- Неожиданных tracked deletions не найдено: `git diff --name-status --diff-filter=D` не вернул удаленных файлов, `git ls-files --deleted` пустой. Root `graphify-out/cache` остается generated-шумом и не включается в релиз без отдельной сверки.
- Release freeze зафиксирован: до Шага 10 не начинать новый refactor `message_handler.py`, AI-speed оптимизации или large test-suite decomposition, если они не блокируют smoke. Релизный scope = боевой MVP на сервере с `systemd`, не full hardening.

## 2026-06-04 - created release context-window step plan

- Создан отдельный wiki-файл [[roadmap/release-context-window-steps]]: боевой MVP-релиз `best2` разбит на 12 шагов, каждый рассчитан на один новый чат/контекстное окно. Для каждого шага указаны стартовый prompt, действия, команды и Definition of Done.
- План фиксирует выбранный релизный порог: боевой MVP на сервере с `systemd`, без обязательного большого refactor до запуска. Последовательность: release inventory, local baseline, production env checklist, runbook, health report, server/systemd, YooKassa webhook, automated regression, manual Telegram smoke, controlled payment smoke, launch gate, first-day monitoring.
- Обновлён [[index]] со ссылкой на новый roadmap. Production-код не менялся; Graphify не обновлялся, потому что это wiki-only изменение.

## 2026-06-03 - completed Priority 1 local stabilization

- Операционный запуск восстановлен локально. До запуска среди Python-процессов не было `main.py`; `scripts/test_db.py` OK, Telegram API живой (`@fnsmvsvmpvpovbot`, webhook пустой, pending updates `0`), первый `yclients_sync_status.py --strict` был stale (`age_seconds=2068`, `records_seen=125`). Выполнен `scripts/sync_yclients_records.py --once` (`seen=125`, `upserted=125`), затем запущен один локальный `main.py` hidden-фоном. Корректный Windows-запуск требует quoting пути `main.py`, потому что workspace лежит в `Рабочий стол`.
- Через 1+ минуту после старта polling был жив: launcher PID `7488`, child CPython PID `21632`, `Telegram polling started`, `Run polling for bot @fnsmvsvmpvpovbot`. Telegram API оставался живым, YCLIENTS strict-status fresh (`last_success_at=2026-06-03T19:32:55+03:00`, `records_seen=126`). Реальный `/status` через Telegram transport нельзя отправить самому себе Bot API без user-originated сообщения; handler зарегистрирован в `telegram_bot.py`, а транспорт/polling проверены отдельно.
- Во время runtime smoke найден и закрыт инфраструктурный баг DB pool: `message_retention_runner` на старте упал с `psycopg2.pool.PoolError: trying to put unkeyed connection`. Причина - lazy-init race глобального `ThreadedConnectionPool` между background loops и возврат connection не обязательно в тот же pool object. `app/db/connection.py` теперь защищает pool init `Lock`, возвращает connection в тот же pool object и ретраит transient `PoolError` на checkout. Smoke после правки зелёный: compile конкретного файла, retention `asyncio.to_thread(summarize_and_delete_old_messages_once)` => `{'conversations': 0, 'messages': 0}`, 16 concurrent checkout через 8 workers => все `1`.
- Lightweight baseline зелёный: `compileall app scripts`, `lint_best2info.py`, `validate_yclients_map.py`, `git diff --check` только с обычными CRLF warnings. `local_regression_suite.py --list-cases` показывает 199 cases.
- Незавершённый glue-boundary `message_handler.py -> app/services/dialog/message_handler_flow_glue.py` подтверждён полным targeted regression без новых refactor-правок: `local_regression_suite.py --group fresh --group services`, `--group post_booking --group payments`, `--group cancel --group reschedule`, `--group prices --group time --group upsell --group media`; `dialog_context_suite.py` 19/19, `dialog_edge_suite.py` 15/15, `dialog_stress_suite.py` 13/13. Наблюдение прежнее: на AI semantic ветках остаются `dialog_timing_slow`, функционально сценарии зелёные.
- После DB-mutating regression выполнены `clear_db.py`, `sync_yclients_records.py --once` (`seen=127`, `upserted=127`), `yclients_sync_status.py --strict` fresh и `live_db_hygiene_audit.py --limit 20` clean.
- Dirty tree разложен на группы без отката неизвестных пользовательских изменений: production-код (`app/services/...` плюс новый `app/db/connection.py` фикс), tests/scripts, `best2info`, `best2obs`, рабочая карта `best2graph`, root `graphify-out/cache`. Root `graphify-out/cache` уже был generated-шумом до текущего захода; после `best2graph/update_graph.ps1` удалены только 5 новых текущих untracked AST-cache хвостов, pre-existing root-cache изменения оставлены. `best2graph/update_graph.ps1` выполнен после code-slice; карта не doc-only и query находит `message_handler.py`, `message_handler_flow_glue.py`, `new_booking_flow.py` (штатный incremental сейчас даёт `398 nodes`, `1517 edges`, `35 communities`, но нужный кодовый срез присутствует).
- После первой финальной попытки runtime DB показала 1 live conversation / 6 messages от Telegram external_id `865839042` за `20:02-20:03` и один `human_handoff` log. Для чистого post-regression baseline текущий `main.py` был остановлен, `clear_db.py` повторён, затем `sync_yclients_records.py --once` (`seen=127`, `upserted=127`) и hygiene снова clean. Финальный локальный `main.py` запущен hidden-фоном: launcher PID `8972`, child CPython PID `17436`; через 75 секунд процесс жив, Telegram API живой, pending `0`, YCLIENTS strict fresh (`last_success_at=2026-06-03T20:13:56+03:00`, `records_seen=127`), runtime tables чистые (`users/conversations/messages/system_logs=0`). Runtime log без stderr и без DB-pool `PoolError`.

## 2026-06-03 - read-only current status check after unfinished refactor chat

- По запросу на текущий статус production-код не менялся. Сейчас постоянный Telegram polling не запущен: среди Python-процессов нет `main.py`, поэтому бот не забирает новые сообщения. Telegram API при этом живой: `@fnsmvsvmpvpovbot`, webhook пустой, pending updates `0`.
- БД доступна: `scripts/test_db.py` OK. YCLIENTS-cache сейчас stale: `scripts/yclients_sync_status.py --strict` вернул `fresh=False`, `age_seconds=1144`, `last_success_at=2026-06-03T18:54:42.052958+03:00`, `records_seen=125`, `last_error=None`.
- Lightweight baseline по текущему коду зелёный: `compileall app scripts`, `lint_best2info.py`, `validate_yclients_map.py`, `git diff --check` только с обычными CRLF warnings. `local_regression_suite.py --list-cases` работает (`199` cases, `exit=0`).
- Важно: рабочее дерево ушло дальше последней аккуратной записи памяти. `message_handler.py` теперь в основном состоит из wrappers, которые импортируют `_impl_*` из нового `app/services/dialog/message_handler_flow_glue.py`; сам `handle_incoming()` делегирует в `_impl_handle_incoming()`. Graphify query видит `message_handler_flow_glue.py`, `new_booking_flow.py` и `message_handler.py`. Этот большой glue-extraction срез не описан в предыдущем log как завершённый и не был подтверждён здесь полным DB-mutating regression.

## 2026-06-03 - checked live dialog availability and restarted local bot

- По запросу на проверку крайнего диалога `scripts/inspect_last_dialog.py` вернул `no conversations`: в текущей `best2` БД нет `users/conversations/messages`. Это ожидаемо совпадает с недавними DB cleanup-прогонами через `scripts/clear_db.py`; восстановить последний live-dialog из `best2` runtime-таблиц сейчас нельзя. `best3_*` таблицы заполнены, но последний `best3` conversation старый (`2026-05-29`) и не является свежим источником для текущего `best2` анализа.
- Найдено операционное состояние: DB smoke зелёный, Telegram API живой (`@fnsmvsvmpvpovbot`, webhook пустой, pending updates `0`), но постоянный `main.py` до проверки не был запущен, поэтому новые best2-диалоги не попадали бы в БД, а фоновые loops не поддерживали бы YCLIENTS freshness. Первый `yclients_sync_status.py --strict` был stale (`age_seconds=1256`, `records_seen=123`).
- Выполнен manual `scripts/sync_yclients_records.py --once` (`seen=125`, `upserted=125`), затем запущен один локальный `main.py` hidden-фоном (`Start-Process`, launcher PID `19748`, child PID `14116`). Через цикл фонового sync strict-status свежий: `last_success_at=2026-06-03T18:30:33+03:00`, `records_seen=125`, `last_error=None`. Baseline без production-правок зелёный: `test_db.py`, `compileall app scripts`, `lint_best2info.py`, `validate_yclients_map.py`.

## 2026-06-03 - started Phase 3 fresh/new-booking helper extraction

- Продолжена работа после Phase 2 registry runner: следующий срез [[roadmap/project-hardening-master-plan]] / Фаза 3 сделан behavior-preserving, без изменения внешнего routing order. `app/services/dialog/new_booking_flow.py` получил pure helper-логику fresh/new booking: `wants_additional_booking()`, `starts_new_booking_request()`, `generic_new_booking_request()`, `context_service_for_generic_new_booking()`, `fresh_booking_form_data_for_text()`, `fresh_start_immediate_reply()` и `fresh_booking_patch_from_ai()`.
- `app/services/message_handler.py` оставляет прежние `_...` wrappers для совместимости старых call sites/monkeypatch и остаётся владельцем side effects: DB writes, assistant commit, payment/YCLIENTS operations, callback wiring. Размер handler уменьшен примерно `5936 -> 5837` строк; `handle_incoming()` остался на том же routing-пути.
- Baseline: `test_db.py` OK; первый `yclients_sync_status.py --strict` был stale (`age_seconds=852`, `records_seen=120`), после `sync_yclients_records.py --once` fresh. `compileall app scripts`, `lint_best2info.py`, `validate_yclients_map.py`, `git diff --check` OK (только обычные CRLF warnings).
- Regression: combined `local_regression_suite.py --group fresh --group services --group post_booking --group payments` упёрся в timeout около 5 минут без диагностического вывода, поэтому после cleanup/sync группы прогнаны отдельно и все зелёные: `fresh`, `services`, `post_booking`, `payments`. Широкие guards тоже зелёные: `dialog_context_suite.py` 19/19, `dialog_edge_suite.py` 15/15, `dialog_stress_suite.py` 13/13. Наблюдение прежнее: на AI semantic ветках остаются `dialog_timing_slow`, функционально сценарии проходят.
- После DB-mutating прогонов выполнены `clear_db.py`, `sync_yclients_records.py --once` (`seen=121`, `upserted=121`), `yclients_sync_status.py --strict` fresh и `live_db_hygiene_audit.py --limit 20` clean.
- Graphify: штатный `.\best2graph\update_graph.ps1` снова схлопнул incremental карту до `540/541 nodes` и выдал safety warning. Карта восстановлена временным full extract без `--no-cluster`, затем артефакты перенесены в `best2graph/graphify-out`: финально `1800 nodes`, `7458 edges`, `84 communities`; query находит `new_booking_flow.py`, `fresh_start_immediate_reply()` и `message_handler.py`. Root `graphify-out/cache` очищен от новых generated хвостов текущего прогона; pre-existing 13 untracked AST cache-файлов оставлены.

## 2026-06-03 - completed Phase 2 registry-driven regression runner

- Фаза 2 из [[roadmap/project-hardening-master-plan]] дозакрыта без изменения production-модулей: `scripts/local_regression_suite.py` теперь ведёт все 199 существующих checks через единый `REGRESSION_CASES` registry в прежнем порядке старого `main()`. Длинный ручной dispatch `run("group", ...)` заменён на один проход по выбранным `RegressionCase`; `--group` фильтрует тот же source of truth, `--case "exact name"` запускает named checks, `--list-cases` выходит до lock/cleanup/DB.
- Registry получил лёгкую защиту: `_build_cases_by_name()` падает на duplicate case names и unknown groups, группы сверяются с `TEST_GROUPS`, `--group` остаётся с argparse choices. Порядок `--list-cases` стабилен: порядок `TEST_GROUPS`, затем порядок регистрации внутри группы. Fake AI остаётся default; real AI теперь включается только явным `--real-ai`, старый env-toggle `BEST2_REGRESSION_REAL_AI` больше не используется.
- Baseline перед правкой: системный `python` не имел зависимостей (`pydantic` missing), поэтому проверки повторены через `.venv`; `compileall app scripts` OK, `test_db.py` OK. Первый `yclients_sync_status.py --strict` был stale (`age_seconds=833`, `records_seen=120`, `last_error=None`), после `sync_yclients_records.py --once` строгий статус fresh.
- Runner checks зелёные: `--list-cases`; `--case "bathhouse pool included info during form"`; `--case "payment reply uses 30 minute ttl and refund note"`; multi-case representatives `second booking resets slot fields`, `free dates lookup after no availability`, `reschedule selects service after list`, `paid cancel asks confirmation`; `--group services`; `--group prices --group time`; `--group payments --group post_booking`.
- После DB-mutating checks выполнены `clear_db.py`, `sync_yclients_records.py --once` (`seen=120`, `upserted=120`), `yclients_sync_status.py --strict` fresh и `live_db_hygiene_audit.py --limit 20` clean. Финальные проверки: `compileall app scripts` OK, `git diff --check` OK с обычными CRLF warnings.
- Graphify обновлялся по workflow: первый `.\best2graph\update_graph.ps1` снова схлопнул incremental graph до `293 nodes`, затем карта восстановлена временным full extract (`111 code files`) и перенесена обратно в `best2graph/graphify-out`; финально `1846 nodes`, `7535 edges`, `84 communities`, query находит `RegressionCase` в `scripts/local_regression_suite.py`. Root `graphify-out/cache` возвращён к ожидаемому состоянию: 11 новых generated cache-файлов удалены, 2 tracked root-cache файла восстановлены, pre-existing 13 untracked AST-файлов оставлены.

## 2026-06-03 - implemented Phase 2 single-case regression runner slice

- По [[roadmap/project-hardening-master-plan]] начата Фаза 2: `scripts/local_regression_suite.py` получил `RegressionCase`, named registry, CLI `--case`, `--list-cases`, `--fake-ai` и `--real-ai`. Fake AI остаётся поведением по умолчанию; real AI включается только явным флагом или старым `BEST2_REGRESSION_REAL_AI`.
- В registry перенесён первый набор частых live-cases: `bathhouse date-only reply explains packages`, `bathhouse pool included info during form`, `bathhouse blocks 500 without unavailable alternatives`, `bathhouse 500 follow-up manual admin`, `start available services lists all primary options`, `bathhouse ten hour price formula`, `coal price is known`, `until midnight uses existing start`, `payment reply uses 30 minute ttl and refund note`. Старый `--group` сохранён и использует registry для перенесённых сценариев.
- Проверки зелёные: baseline `test_db.py`, `compileall app scripts`, `lint_best2info.py`, `validate_yclients_map.py`, `git diff --check` с обычными CRLF warnings; `local_regression_suite.py --list-cases`; `--case "bathhouse pool included info during form"`; `--case "bathhouse 500 follow-up manual admin" --fake-ai`; `--case "bathhouse ten hour price formula"`; `--group services`.
- После DB-mutating проверок выполнены `clear_db.py`, `sync_yclients_records.py --once` (`seen=120`, `upserted=120`), `yclients_sync_status.py --strict` fresh и `live_db_hygiene_audit.py --limit 20` clean. Первый `.\best2graph\update_graph.ps1` снова дал неполный incremental graph (`289 nodes`), поэтому карта восстановлена через временный full extract и перенесена обратно в `best2graph/graphify-out`: финально `1844 nodes`, `7675 edges`, `84 communities`, query находит `RegressionCase` в `scripts/local_regression_suite.py`. Root `graphify-out/cache` после побочного шума возвращён к исходному состоянию: новые generated cache-файлы удалены, pre-existing 13 untracked AST-файлов оставлены.

## 2026-06-03 - created project hardening master plan

- Создан отдельный подробный roadmap [[roadmap/project-hardening-master-plan]] по улучшению минусов проекта: cleanup/discipline для dirty tree и Graphify, single-scenario regression runner, дальнейшее уменьшение `message_handler.py`, разделение `local_regression_suite.py`, ускорение AI/info веток, укрепление PostgreSQL/YCLIENTS/YooKassa, runbook production-запуска, observability и source-of-truth hygiene.
- План рассчитан на новый чат: сначала читать `index/log/master-plan`, затем делать baseline/status, затем начинать с Фазы 2 - single-scenario runner с fake AI по умолчанию. Production-код не менялся, Graphify не обновлялся, потому что изменялась только wiki.

## 2026-06-03 - checked bathhouse live scenarios one by one

- По запросу пользователя отдельно проверены сценарии из последнего чата без реального LLM-провайдера: импортированы конкретные regression-функции, `message_handler.call_ai` заменён на fake `AIResponse(intent="other", action="ask_next_question")`, поэтому реальных AI-запросов/расхода на LLM не было.
- Зелёные одиночные проверки: `bathhouse date-only reply explains packages`, `bathhouse pool included info during form`, `bathhouse blocks 500 without unavailable alternatives`, `bathhouse 500 follow-up manual admin`. Ответы подтвердили цены пакетов 3-7ч, прямое `бассейн входит в бронь`, отказ на 500 гостей без `баня не свободна/не нашла`, и follow-up без повторного вопроса количества гостей.
- После DB-mutating проверки восстановлен чистый baseline: `clear_db.py`, `sync_yclients_records.py --once` (`seen=120`, `upserted=120`), `yclients_sync_status.py --strict` fresh, `live_db_hygiene_audit.py --limit 20` clean. Production-код не менялся.

## 2026-06-03 - resumed Graphify/cache cleanup after bathhouse follow-up

- Продолжение после обрыва: production-код в этом заходе не менялся. Реальная проблема была в обслуживании Graphify, а не в банной логике: incremental update временно схлопнул `best2graph` до doc-only карты, а восстановительная попытка через root `graphify update .` насорила в `graphify-out/cache`.
- Корневой generated-cache приведён в порядок: 2 tracked root-cache файла восстановлены к `HEAD`, 88 новых untracked root-cache хвостов удалены, 13 pre-existing untracked AST cache-файлов оставлены как были. Рабочая карта остаётся в `best2graph/graphify-out/`.
- Проверки после продолжения: `compileall app scripts` OK; первый `local_regression_suite.py --group services --group prices --group time` упал на transient `psycopg2.OperationalError: SSL error: unexpected eof while reading`, повторный прогон прошёл OK; `git diff --check` OK с обычными CRLF warnings.
- После DB-mutating проверок восстановлен чистый baseline: `clear_db.py`, затем `sync_yclients_records.py --once` (`seen=120`, `upserted=120`), `yclients_sync_status.py --strict` fresh, `live_db_hygiene_audit.py --limit 20` clean. Graphify query по bathhouse pool/huge-group снова находит `bathhouse_flow.py`, `info_flow.py` и `message_handler.py`; текущая карта: `1842 nodes`, `7671 edges`, `86 communities`.

## 2026-06-03 - fixed bathhouse live UX follow-up

- Закрыт следующий live UX-пакет по бане: prompt пакетов теперь показывает цены `3ч 6 300/7 950 ₽` ... `7ч 14 700/18 550 ₽`, ориентир `2 100 ₽/час` в будни и `2 650 ₽/час` в пт-вс, а после 7 часов `+1 500 ₽/час`.
- Active bathhouse info-flow получил прямой deterministic ответ на `бассейн вместе идет?`: `Да, это баня с бассейном, бассейн входит в бронь`, затем возвращает текущий вопрос анкеты. Ответ идёт до generic capacity-copy.
- Capacity guard для бани больше не вызывает `alternative_services_for_unavailable_date()` при отказе по вместимости. Для `500` гостей бот говорит, что баня автоматически оформляется до 15 человек, стандартного авто-варианта на такое количество нет, крупнейшие обычные варианты сильно меньше, нужен ручной/admin сценарий. `last_capacity_rejection` сохраняет отклонённое количество, а follow-up `а что подходит на 500 человек?` отвечает по сути без повторного `Сколько примерно гостей?`.
- Добавлены regression guards: `bathhouse pool included info during form`, `bathhouse blocks 500 without unavailable alternatives`, `bathhouse 500 follow-up manual admin`; `bathhouse date-only reply explains packages` расширен проверками цен пакетов.
- Проверки: `compileall app scripts` OK; `lint_best2info.py` OK; `validate_yclients_map.py` OK; `local_regression_suite.py --group services --group prices --group time` OK; `dialog_context_suite.py` 19/19 OK; `dialog_edge_suite.py` 15/15 OK; `dialog_stress_suite.py` 13/13 OK; `git diff --check` OK с обычными CRLF warnings. При stress был один transient `Database pool init failed attempt=1`, suite завершился зелёным.
- Graphify обновлён и восстановлен полным кодовым сканом: `1842 nodes`, `7671 edges`, `86 communities`.

## 2026-06-03 - planned bathhouse live UX follow-up

- Production-код не менялся. По ручному Telegram smoke после банных правок выделен новый открытый пакет UX-регрессий: в prompt пакетов бани нужно показывать цены/часовой ориентир, вопрос `бассейн вместе идет?` должен получать прямой ответ `да, это баня с бассейном`, отказ на `500` гостей не должен дописывать `баня не свободна`, а follow-up `что подходит на 500 человек?` должен отвечать про отсутствие стандартного авто-варианта и ручной/admin сценарий.
- Зафиксировано в [[bugs/current-known-issues]], [[roadmap/dialog-regression-scenarios]] и [[roadmap/pre-launch]]. Кодовые точки для следующего захода: `app/services/dialog/bathhouse_flow.py::bathhouse_period_options_reply`, `app/services/message_handler.py::_capacity_info_reply`, `app/services/message_handler.py::_bathhouse_capacity_mismatch_reply`, `app/services/dialog/availability_flow.py::alternative_services_for_unavailable_date`, regression coverage in `scripts/local_regression_suite.py` / `scripts/dialog_context_suite.py`.

## 2026-06-03 - fixed bathhouse dialog regressions

- Закрыт live-пакет по бане: date-only/nearest-free вопросы при уже выбранной дате больше не обещают точную свободность без времени и длительности, а объясняют пакеты `3, 4, 5, 6 и 7` часов, доплату `+1 500 ₽/час` после 7 часов и просят время + длительность/период.
- Фраза `я хочу поменять время` в активной анкете бани без нового времени очищает старые `time/duration`, возвращает шаг `time` и просит новый период; open-ended default `до утра` больше не применяется к `bathhouse`, только к gazebo-flow.
- Баня на 8+ часов оформляется автоматически: `app/services/bathhouse_pricing.py` выбирает 7-часовой YCLIENTS package нужного дня недели, а локальные hold/booking/availability используют фактическую длительность. Цена считается как цена 7ч пакета + `1 500 ₽ × каждый час сверх 7`; payment/base-price и price replies используют общий helper.
- Active bathhouse info-flow получил deterministic ответы: про алкоголь/напитки отвечает `можно аккуратно`, `без стекла у бассейна`, порядок и безопасность; complaint на `почему говоришь, что баня отдельно бронируется` отвечает `Вы правы, баню уже оформляем; это баня с бассейном` и возвращается к текущему вопросу анкеты. Фраза про отдельную бронь оставлена для кейса добавления бани к беседке, но не внутри активной анкеты бани.
- Обновлены `best2info/objects/bathhouse.md`, `best2info/prices/bathhouse.md`, `best2info/runtime.md`, regression-сценарии в `local_regression_suite.py` и live-135 expectation в `dialog_context_suite.py`.
- Проверки: `compileall app scripts` OK; `lint_best2info.py` OK; `validate_yclients_map.py` OK; `local_regression_suite.py --group services --group prices --group time` OK; `dialog_context_suite.py` 19/19 OK; `dialog_edge_suite.py` 15/15 OK; `dialog_stress_suite.py` 13/13 OK; `git diff --check` OK с обычными CRLF warnings.
- Graphify обновлён через `.\best2graph\update_graph.ps1`: `741 nodes`, `3558 edges`, `41 communities`; query по bathhouse extended duration находит `bathhouse_pricing.py`, `availability_service.py`, `price_info.py`, `payment_service.py` и `yclients_record_service.py`.
- После DB-mutating проверок выполнены `scripts/clear_db.py` и `scripts/sync_yclients_records.py --once`: свежий YCLIENTS-cache `seen=120`, `upserted=120`; `yclients_sync_status.py --strict` fresh, `live_db_hygiene_audit.py --limit 20` clean.

## 2026-06-03 - prepared clean Telegram/YCLIENTS test baseline

- Перед ручными Telegram-тестами выполнена операционная чистка без изменения production-кода: штатный dry-run/apply `scripts/cleanup_yclients_test_records.py --all-bot-bookings --apply` удалил 1 активную бот-запись из YCLIENTS-журнала (`booking_id=138`, `yclients_record_id=1751957826`), после чего локальная БД очищена через `scripts/clear_db.py`.
- После очистки восстановлен актуальный локальный календарь: `scripts/sync_yclients_records.py --once` вернул свежий кэш YCLIENTS (`seen=119`, `upserted=119`, окно `-1/+60` дней); `scripts/yclients_sync_status.py --strict` fresh, `scripts/live_db_hygiene_audit.py --limit 20` clean, `cleanup_yclients_test_records.py --all-bot-bookings` показывает `Candidates: 0`.
- Проверки поведения перед финальной очисткой зелёные: `compileall app scripts`, `lint_best2info.py`, `validate_yclients_map.py`, `test_db.py`, `dialog_context_suite.py` 19/19, `dialog_edge_suite.py` 15/15, `dialog_stress_suite.py` 13/13. Наблюдение сохраняется прежним: на AI semantic ветках есть `dialog_timing_slow`, но функционально сценарии проходят.
- Финальное состояние БД для ручных тестов: `users=0`, `conversations=0`, `messages=0`, `conversation_summaries=0`, `bookings=0`, `slot_holds=0`, `payments=0`, `system_logs=0`, `waitlist_requests=0`, `webhook_events=0`; справочный кэш занятости оставлен: `yclients_records=119`, `resource_busy_intervals=119`, `yclients_sync_state=1`.

## 2026-06-02 - completed info-flow Phase 3 and reserve/payment fixes

- Завершён Phase 3 из [[roadmap/large-file-decomposition-plan]] / [[roadmap/message-handler-refactor]]: `app/services/dialog/info_flow.py` теперь владеет info-question helpers (`looks_like_info_question`, deterministic/common info, active-booking reference info, `answer_info_during_form`, reply/next-question guards), а `message_handler.py` оставляет тонкие wrappers и callback-builders. Это behavior-preserving срез: persistence, side effects и routing ownership остаются в handler.
- Дореализован пакет из плана "знания, время, резерв и оплата": обновлены knowledge/price тексты по бане `3-7` часов + `1 500 ₽/час` после 7 часов, уголь `3 кг — 270 ₽`; price helper считает баню на 10 часов как 7ч пакет + 3 доп. часа.
- Time/correction flow теперь понимает `4 или 5 вечера` как ранний понятный старт `16:00`, не превращает диапазоны гостей `15-17 человек` во время, а `до 12 ночи` при известном старте `16:00` даёт `duration=8`, не `time=04:00`.
- Резерв переведён на 30 минут (`HOLD_TTL_MINUTES=30` в `.env.example`, production/user-facing texts берут TTL из settings). Payment text добавляет правило возврата предоплаты при отмене не позднее 7 дней.
- Для active unpaid hold правка даты/времени/длительности отменяет старый hold, помечает старую pending payment как `superseded`, создаёт новый hold/payment link и не запускает paid reschedule-flow. Payment runner получил auto-resend свежих ссылок на 10-й и 20-й минуте активного резерва; late paid superseded link не создаёт booking автоматически и уходит в manual-review/admin path.
- Проверки: `compileall app scripts`, `lint_best2info.py`, `validate_yclients_map.py`, `test_db.py`, `dialog_context_suite.py` 19/19, `dialog_edge_suite.py` 15/15, `dialog_stress_suite.py` 13/13, `local_regression_suite.py --group prices --group time --group payments --group post_booking`, отдельно `--group services`, отдельно `--group upsell`, `git diff --check` OK. Combined `local_regression_suite.py --group services --group prices --group upsell --group post_booking` был остановлен по timeout около 5 минут без диагностического вывода; покрывающие группы после этого прошли отдельно. Graphify обновлён: `671 nodes`, `3119 edges`, `30 communities`.

## 2026-06-02 - paused during message_handler Phase 3 info-flow extraction

- Работа остановлена по просьбе пользователя во время Phase 3 из [[roadmap/large-file-decomposition-plan]] / [[roadmap/message-handler-refactor]]: начат behavior-preserving вынос info-flow из `app/services/message_handler.py` в новый `app/services/dialog/info_flow.py`.
- До правок baseline был зелёный: `.venv\Scripts\python.exe -m compileall app scripts`, `scripts/lint_best2info.py`, `scripts/validate_yclients_map.py`, `scripts/test_db.py`, `scripts/dialog_context_suite.py` 19/19, `scripts/dialog_edge_suite.py` 15/15, `scripts/dialog_stress_suite.py` 13/13.
- Текущее незавершённое состояние кода: добавлен `app/services/dialog/info_flow.py` с `InfoQuestionCallbacks`, `InfoFlowCallbacks`, `ActiveBookingInfoCallbacks` и перенесёнными реализациями `looks_like_info_question`, `deterministic_info_reply`, `active_booking_reference_info_reply`, `append_current_service_question`, `answer_info_during_form`, `reply_already_asks`, `should_append_next_question_after_info`.
- В `app/services/message_handler.py` уже добавлены импорты из `info_flow.py`, callback-builders `_info_question_callbacks()`, `_info_flow_callbacks()`, `_active_booking_info_callbacks()`, а wrappers `_deterministic_info_reply()`, `_active_booking_reference_info_reply()`, `_append_current_service_question()` уже переключены на новый модуль.
- На момент остановки ещё НЕ закончено: wrappers `_looks_like_info_question()`, `_answer_info_during_form()`, `_reply_already_asks()`, `_should_append_next_question_after_info()` всё ещё имеют старые тела в `message_handler.py`; импортированные aliases `_reply_already_asks_impl` и `_should_append_next_question_after_info_impl` пока не используются. Нужно аккуратно завершить wiring или удалить лишние aliases после решения.
- После частичных правок проверки НЕ запускались и Graphify НЕ обновлялся. Следующий заход начать с осмотра diff, затем либо завершить wiring тонкими wrappers, либо откатить незавершённый срез только если явно решено. После завершения обязательно прогнать `compileall`, targeted info suites (`dialog_context_suite.py`, `dialog_edge_suite.py`, `dialog_stress_suite.py`, `local_regression_suite.py --group services --group prices --group upsell --group post_booking`), затем `git diff --check` и `.\best2graph\update_graph.ps1`.

## 2026-06-02 - implemented large-file decomposition Phase 2 new booking flow

- Реализован Phase 2 из [[roadmap/large-file-decomposition-plan]]: fresh/stale/new-booking orchestration вынесен из `app/services/message_handler.py` в `app/services/dialog/new_booking_flow.py`. Новый модуль возвращает `NewBookingFlowResult` с `reply`, `status`, `intent`, `current_step`, `next_step`, `form_data`; handler по-прежнему владеет записью сообщений, `conversations_repo.update_after_message()` и DB commits.
- Перенесены ветки stale form choice, `нет` + новая заявка в одном сообщении, новая услуга поверх старого draft, новая заявка поверх reserved/payment context, fresh-start с сохранением только `client_name`/`phone`, а также AI-assisted fresh-start reset. Context-only stale reset возвращает `reply=None`, после чего handler применяет update и продолжает routing.
- На Phase 2 regression найден и закрыт целевой red: после stale reset фраза `нет` + новая баня могла сбросить старую анкету, но потерять service из текущего сообщения и уйти в список услуг. Исправлено использованием fresh form builder для текста текущего сообщения; сценарий `stale no plus new bath request processes same message` снова обрабатывает баню/дату/время в том же сообщении.
- Обновлен `scripts/dialog_stress_suite.py`: два upsell stress expectations приведены к уже закрепленному UX из `local_regression_suite.py --group upsell` - после позитивного выбора допов бот остается на `upsell_items` и переходит дальше после последующего `нет`.
- Проверки: baseline `compileall app scripts`, `lint_best2info.py`, `validate_yclients_map.py`, `git diff --check` OK; `scripts/test_db.py` OK; `dialog_context_suite.py` 19/19 OK; `dialog_edge_suite.py` 15/15 OK; `dialog_stress_suite.py` 13/13 OK после обновления expectation; `local_regression_suite.py --group fresh --group services --group post_booking --group payments` OK. Graphify обновлен полным ресканом после сброса generated manifest; query находит `new_booking_flow.py` (`1759 nodes`, `7271 edges`, `72 communities`).

## 2026-06-02 - implemented large-file decomposition Phase 1 commit boundary

- Реализован первый срез [[roadmap/large-file-decomposition-plan]] для `app/services/message_handler.py`: добавлен единый `_commit_assistant_response()` и локальный `commit_reply()` внутри `handle_incoming`. Повторяющиеся пары `messages_repo.create(sender=SENDER_ASSISTANT)` + `conversations_repo.update_after_message()` заменены на единый helper без изменения порядка routing.
- Особые случаи сохранены: seed `form_data` при новом разговоре и stale-context update без ответа остаются прямыми `conversations_repo.update_after_message`; финальный AI/fallback путь сохраняет `_persist_user_profile()` через `before_update`, то есть телефон пользователя пишется после assistant message и до update conversation, как раньше.
- Результат среза: `message_handler.py` сократился до `6351` строк; прямые assistant-message commits централизованы в helper, а оставшиеся `messages_repo.create` в handler относятся к входящему user message или самому helper.
- Проверки: `.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts/lint_best2info.py` OK; `scripts/validate_yclients_map.py` OK. `scripts/dialog_context_suite.py` и `scripts/test_db.py` не стартовали из-за внешнего PostgreSQL timeout к `95.214.62.243:5432`; `Test-NetConnection` при этом видит TCP порт открытым. Полный Phase 1 regression (`context/edge/stress`, `local_regression_suite.py --group payments --group post_booking --group fresh`) нужно повторить после восстановления DB-соединения.
- Graphify обновлен после кода; после сброса generated manifest выполнен полный перескан `107 code` файлов. Итоговая карта рабочая, query находит `message_handler.py`: `1745 nodes`, `7207 edges`, `70 communities` после recluster.

## 2026-06-02 - readiness baseline before next task

- По запросу готовности к следующему этапу проверен текущий baseline без изменений production-кода. Рабочее дерево уже содержит незакоммиченные изменения предыдущего пакета 2026-06-02: `message_handler.py`, `price_info.py`, `local_regression_suite.py`, `best2obs/*` и обновленный Graphify.
- Легкие проверки прошли: `.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts/lint_best2info.py` OK; `scripts/validate_yclients_map.py` OK; `scripts/test_db.py` OK; `scripts/live_db_hygiene_audit.py --limit 20` clean.
- Первый `scripts/yclients_sync_status.py --strict` был stale (`age_seconds=1061`, порог `600`, `records_seen=117`, `last_error=None`). Выполнен `scripts/sync_yclients_records.py --once`: `seen=117`, `upserted=117`; повторный strict fresh (`age_seconds=46`, `records_seen=117`, `last_error=None`).
- Текущее операционное состояние БД после smoke не является чистым manual-test baseline: `users=1`, `conversations=1`, `messages=42`, `slot_holds=1`, `bookings=0`, `yclients_records=117`, `resource_busy_intervals=117`. Перед чистым ручным Telegram smoke снова выполнить `scripts/clear_db.py`, затем `scripts/sync_yclients_records.py --once` и `scripts/yclients_sync_status.py --strict`.
- Вывод по этапу: можно переходить к следующей задаче только после свежего полного regression/context/edge/stress baseline на текущем dirty tree; для refactor первым срезом остается Phase 1 `message_handler.py`: Commit/Result Boundary из [[roadmap/large-file-decomposition-plan]].

## 2026-06-02 - fixed live services list, upsell info, late hookah price and voice smoke

- Закрыт live-пакет по стартовому списку услуг, info-вопросам на шаге допов и late addon+price: `че можно?` без выбранной услуги теперь deterministic перечисляет обычные/летние беседки, крытую беседку, тёплую беседку, баню с бассейном и гостевой дом, оставаясь на `service_type`.
- Info-вопросы на активном `upsell_items` отвечают по факту и возвращают к допам без перехода к телефону: без выбранных допов follow-up `Что подготовить для вас? Если ничего не нужно, напишите «нет».`, с уже выбранным кальяном follow-up `Если хотите добавить что-то ещё...`; выбранные допы не теряются. Если в одном сообщении есть телефон и info-вопрос, телефон теперь сохраняется.
- Late-фраза `а я бы хотел добавить калик в допы, цена изменится?` на `awaiting_confirmation` или поздних шагах сначала сохраняет `кальян`, отвечает ценой `Кальян — 1 500 ₽...` и возвращает актуальную confirmation-сводку с `Допы: кальян`, без `Допы: не нужны`. Price-helper также понимает `калик/калян/кальянчик`.
- Дополнительно закрыт edge-риск: post-booking вопрос про погоду больше не уходит в AI-текст, который мог упомянуть предоплату при `payment_paid`; deterministic ответ не меняет бронь и не предлагает действия.
- Голосовые проверены отдельно: локальный конфиг `VOICE_TRANSCRIPTION_ENABLED=True`, provider `openrouter`, model `openai/whisper-large-v3`, OpenRouter key present, `HTTP_TRUST_ENV=False`; реальный smoke через `_transcribe_audio()` на временном WAV с русской TTS-фразой вернул `Хочу забронировать беседку на 30 июня`; fake Telegram voice path сохранил `content_type=voice`, `voice_duration=5`, и long-duration guard вернул `Voice message is too long`.
- Regression coverage: добавлены `start available services lists all primary options`, `upsell parking info returns to empty addons`, `upsell parking info keeps selected addon`, `late kalik price adds addon to confirmation`.
- Проверки: `.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts/local_regression_suite.py --group services` OK; `scripts/local_regression_suite.py --group upsell` OK; `scripts/local_regression_suite.py --group upsell --group prices --group post_booking` OK; `scripts/dialog_context_suite.py` 19/19 OK; `scripts/dialog_edge_suite.py` 15/15 OK. Первый combined `services+upsell` запуск упёрся в timeout/lock и был повторен группами отдельно. Graphify обновлён (`476 nodes`, `2316 edges` после recluster).

## 2026-06-02 - improved positive upsell follow-up before continuing form

- По live-ручному тесту после фразы `калик один` изменен UX шага допов: позитивный выбор теперь отвечает `Хорошо, кальян добавим ✅`, но не прыгает сразу к телефону/следующему полю. Бот остается на `upsell_items` и пишет: `Если хотите добавить что-то ещё, напишите. Если больше ничего не нужно, напишите «нет», и продолжим по анкете.`
- При последующем `нет` выбранные допы сохраняются и анкета идет дальше к следующему обязательному полю или confirmation. Повторный позитивный выбор допов объединяется с уже выбранными позициями, поэтому `кальян` затем `и лед` дает `Допы: кальян, лед`, а не перезаписывает список.
- Технически добавлены `_merge_selected_upsells()` и `_upsell_followup_reply()` в `message_handler.py`; active `current_step/next_step='upsell_items'` теперь имеет приоритет над `next_question(form_data)`, чтобы `нет` после уже сохраненного допа не трактовалось как `Допы: не нужны`.
- Regression обновлен: `positive addon survives later negative`, `soft upsell accept after push`, `first mangal set selection`, `positive upsell asks for more then continues`, `mixed addon price and selection saves items`. Проверки: `compileall app scripts` OK; `local_regression_suite.py --group upsell` OK; `dialog_edge_suite.py` 15/15 OK; `dialog_context_suite.py` 19/19 OK. Первый параллельный запуск context-suite уперся в regression lock от edge-suite и был повторен отдельно успешно. Graphify обновлен (`450 nodes`, `2201 edges` после recluster).
- После regression-прогонов БД снова очищена через `scripts/clear_db.py` и заново наполнена из YCLIENTS: `sync_yclients_records.py --once --days-back 1 --days-forward 60` дал `seen=121`, `upserted=121`; финально `users=0`, `conversations=0`, `messages=0`, `bookings=0`, `yclients_records=121`, `resource_busy_intervals=121`, strict sync fresh, `live_db_hygiene_audit.py --limit 20` clean.

## 2026-06-02 - prepared clean DB state for manual Telegram test

- Перед ручным тестированием выполнена операционная очистка локальной БД через `scripts/clear_db.py`: `users`, `conversations`, `messages`, `conversation_summaries`, `slot_holds`, `bookings`, `yclients_records`, `resource_busy_intervals`, `yclients_sync_state` и `system_logs` сброшены до `0`. Перед reset в БД было `users=4`, `conversations=4`, `messages=137`, `yclients_records=132`; `scripts/test_db.py` прошел и создал пробную строку, поэтому очистка выполнялась после проверки соединения.
- Таблица записей заново наполнена из YCLIENTS командой `scripts/sync_yclients_records.py --once --days-back 1 --days-forward 60`: `seen=121`, `upserted=121`. Финальный `scripts/yclients_sync_status.py --strict` свежий (`records_seen=121`, `records_upserted=121`, `last_error=None`), `scripts/live_db_hygiene_audit.py --limit 20` чистый.
- Production-код не менялся. Состояние для ручного теста: `users=0`, `conversations=0`, `messages=0`, `slot_holds=0`, `bookings=0`, `yclients_records=121`, `resource_busy_intervals=121`.

## 2026-06-01 - fixed live 19:09 post-booking/photo/confirmation regressions

- Продолжен пакет из прошлого чата по live-диалогу 01.06.2026 19:09-19:16: после оплаченной беседки вопрос `а что еще можно забронить?` теперь определяет текущую услугу по активным броням из БД через `active_user_bookings()`, а `form_data.service_type` использует только как fallback. Если в `form_data` осталась старая баня, клиент всё равно получает `Кроме вашей беседки...`, а не `Помимо бани...`.
- Дополнительно закреплено, что `current_booking_question` всегда отвечает canonical summary из БД/holds, а не свободным `reply_to_user` от AI. Это закрыло найденный при продолжении красный context-сценарий: `а у меня сейчас есть брони?` больше не может сказать `Пока не вижу активных броней`, если локальная paid booking видна в БД.
- Explicit-photo flow расширен на общий запрос `а беседки покажете?`: ответ перечисляет конкретные беседки, чтобы `media_for_client_message()` выбрал реальные `besedka*.jpg`, а не только текст "отправлю фото".
- На `awaiting_confirmation` живой отказ `я перехотел, давай нет` закрывает ещё не созданный черновик, очищает slot-поля, сохраняет имя/телефон и возвращает шаг `service_type`.
- Проверки: `.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts/dialog_context_suite.py` 19/19 OK; `scripts/dialog_edge_suite.py` 15/15 OK; `scripts/local_regression_suite.py --group post_booking --group media --group fresh` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `.\best2graph\update_graph.ps1` обновил Graphify (`561 nodes`, `2698 edges` после recluster). Во время stress были ожидаемые `AIProviderUnavailable`/402 в semantic preflight, но deterministic/degraded paths прошли, suite завершился 13/13.

## 2026-06-01 - fixed post-booking startup/regression after latest changes

- Диагностика запуска: `.venv\Scripts\python.exe -m compileall app scripts main.py` OK, `scripts/test_db.py` OK, короткий запуск `.venv\Scripts\python.exe main.py` не упал за 20 секунд и ушел в polling; исходная жалоба "проект не запускается" как стартовый crash не воспроизвелась после фикса.
- Найден реальный regression в post-booking/current-booking слое: `dialog_stress_suite.py` краснел на сценариях текущих броней/отмены, когда paid booking текущего разговора мог пропасть из ответа из-за временно stale/missing YCLIENTS-cache row. `active_user_bookings()` теперь досоединяет paid локальные брони текущего разговора в статусах `created_in_yclients`/`journal_missing`, чтобы summary/cancel/reschedule не говорили "ничего не вижу" по оплаченной локальной записи.
- Дополнительно закрыт плавающий ответ после отмены: `post_booking_flow.plain_ack_after_closed_booking()` теперь deterministic считает `ок`/`окей` спокойным ack после закрытой брони и возвращает текст про новую бронь, не отдавая это AI fallback-у.
- Проверки: `compileall app scripts main.py` OK; `dialog_stress_suite.py` 13/13 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_context_suite.py` 17/17 OK; `local_regression_suite.py --group post_booking --group cancel --group payments` OK; `scripts/test_db.py` OK; `scripts/live_db_hygiene_audit.py --limit 20` clean; `scripts/lint_best2info.py` OK; `.\best2graph\update_graph.ps1` обновил Graphify (`49 nodes`, `58 edges` после recluster).

## 2026-06-01 - implemented state/text consistency hardening package

- Реализован пакет [[roadmap/state-text-consistency-hardening-plan]] без большого разбора `message_handler.py`: `handle_incoming` делает semantic preflight для активных клиентских диалогов через текущий `AIResponse`, переиспользует результат в основной AI-ветке, а недоступность AI пишет `system_logs.event_type='ai_semantic_degraded'` и уходит в существующий safe fallback/deterministic path.
- Добавлен state/text consistency guard для критичных ответов по допам: если generated/AI текст говорит `кальян добавлен`, но canonical `form_data.upsell_items` не содержит `кальян`, или summary говорит `Допы: не нужны` при другом state, backend пересобирает ответ из canonical state и пишет `state_text_consistency_rebuilt`.
- Доработаны допы: `кальянчик`, `кальяна`, `калик один`, `ничего кроме кальяна`, `уберите все`, `уберите все, кальян оставьте`; `добавьте` работает как contextual accept после последнего upsell prompt. Positive addon survives later negative закреплен сценарием `кальян -> имя -> телефон -> нет`.
- Cancel/refund: клиентский текст теперь явно говорит `7 дней или больше`; regression покрывает 6/7/8 дней, multi-booking cancel с refund event только для paid+refundable позиции, idempotent `refund_required` по booking id и admin notification drain всех pending logs с `admin_notified_at`.
- Добавлен read-only `scripts/live_db_hygiene_audit.py`: проверяет orphan `bot_booking` intervals, paid/cancelled refundable bookings без `refund_required`, paid payments без `payment_notified_at`, regression waitlist rows и `refund_required` без `admin_notified_at`. Текущий audit чистый; известный archived local test paid booking #1 исключается по явной archive-пометке.
- Проверки: `.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts/local_regression_suite.py --group upsell` OK; `--group cancel` OK; `--group post_booking --group payments` OK; `scripts/dialog_context_suite.py` 17/17 OK; `scripts/dialog_edge_suite.py` 14/14 OK; `scripts/dialog_stress_suite.py` 13/13 OK; `scripts/live_db_hygiene_audit.py --limit 20` clean; `.\best2graph\update_graph.ps1` обновил Graphify (`547 nodes`, `3466 edges` до recluster). Наблюдение: из-за обязательного semantic preflight в активных deterministic ветках context/edge/stress чаще печатают `dialog_timing_slow`, функционально сценарии зеленые.

## 2026-06-01 - planned state/text consistency hardening package

- По пользовательскому плану и после перечитывания `best2obs/index.md`, `log.md`, `bugs/current-known-issues.md`, `architecture/backend.md`, `decisions/2026-05-27-dialog-state-policy.md` и `roadmap/pre-launch.md` зафиксирован новый roadmap [[roadmap/state-text-consistency-hardening-plan]].
- Scope: закрыть риски 1-6 без production-правок сейчас: AI-first semantic pass для входящих клиентских сообщений, state/text consistency guard перед важными ответами, расширение upsell-сценариев, cancel/refund boundary по 7 дням, admin refund notification hygiene и read-only live DB audit после regression.
- Пункт 7 отложен: большой разбор `message_handler.py` не делать до зеленого сценарного пакета. Код бота и тесты не запускались/не менялись.

## 2026-06-01 - live Telegram kalik addon and refundable cancel admin notice

- По последнему live-чату 16:48-16:57 подтверждены два нюанса: `Калик` на шаге допов получил текст `Кальян добавлен`, но не был надежно сохранен deterministic parser-ом, поэтому после телефона бот снова спросил допы, а второй отказ перезаписал сводку на `Допы: не нужны`; отмена брони в этом чате была за 3 дня до 4 июня, поэтому клиентский текст про невозврат аванса был корректным, но для отмен за 7+ дней не хватало отдельного админ-уведомления о возврате.
- Исправлено: `form_patches.upsell_items_patch()` распознает разговорные алиасы кальяна `калик/калян/калиан`; после первого выбора допа дальнейшие шаги ведут к подтверждению с `Допы: кальян`, без повторного вопроса допов. `cancel_flow` при отмене оплаченной брони в refundable window пишет `system_logs.event_type='refund_required'`, а `payment_status_runner.notify_admin_about_refund_requests()` отправляет админу текст `Требуется вернуть предоплату клиенту...` и помечает лог `admin_notified_at`.
- Regression coverage: добавлены `kalik addon survives to confirmation`, проверка `refund_required` system log в `paid cancel refund window text and admin refund log`, и `refund required notifies admin` с fake bot.
- Проверки: `.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts/local_regression_suite.py --group upsell` OK; `scripts/local_regression_suite.py --group cancel` OK; `scripts/dialog_edge_suite.py` 14/14 OK; `.\best2graph\update_graph.ps1` обновил Graphify-карту (`539 nodes`, `3366 edges` до recluster).

## 2026-06-01 - restored PostgreSQL root certificate for verify-full

- Восстановлен локальный `C:\Users\kaisa\.postgresql\root.crt` из TLS-цепочки PostgreSQL `luecahalemas.beget.app`: leaf `luecahalemas.beget.app`, intermediate `beget.app Intermediate Authority`, root `Beget Cloud Services Root Authority`.
- Штатный `DB_SSLMODE=verify-full` снова проходит: `scripts/test_db.py` OK, `scripts/db_status.py` читает таблицы. После `scripts/sync_yclients_records.py --once` статус `scripts/yclients_sync_status.py --strict` fresh (`records_seen=124`, `last_error=None`). Production-код не менялся.

## 2026-06-01 - planned large-file decomposition roadmap

- Без изменения production-кода создан [[roadmap/large-file-decomposition-plan]]: будущий план разгрузки `app/services/message_handler.py` и `scripts/local_regression_suite.py`, с опорой на текущую память и Graphify-карту.
- План фиксирует порядок безопасных slices: baseline, commit/result boundary, fresh/stale/new-booking flow, info-flow, reference/unavailable flow, media glue, затем разделение regression suite на `scripts/regression/*`.
- `best2obs/index.md` получил ссылку на новый roadmap-файл. Код бота и тесты не запускались/не менялись.

## 2026-06-01 - live Telegram guest/options, upsell selection and post-booking context fixes

- По live-чату 11:45-11:52 разобраны три сбоя: фраза `нас будет 30 человек, какая беседка подойдет` могла показать варианты и всё равно повторно спросить гостей; ответ `давайте первый набор` после прайса допов не распознавался как выбор мангального набора №1 и возвращал старый вопрос по допам/свободности; post-booking вопрос после забронированной беседки `что еще можно забронировать` отвечал `Помимо бани...`, потому что текст не учитывал текущую активную услугу.
- Исправлено в диалоговом backend: добавлен shortcut `_gazebo_guest_options_shortcut`, который принимает guest-count внутри вопроса о подборе беседки, сохраняет `guests_count` и переводит на выбор подходящего варианта без второго вопроса; `upsell_items_patch` теперь понимает `первый/второй/малый набор`, `№1/№2`, цены 500/1000 как явный выбор мангального набора; `_available_services_reply` стал service-aware и для активной беседки пишет `Кроме вашей беседки...`.
- Regression coverage: `dialog_context_suite.py` расширен до 17 сценариев живым кейсом `нас будет 30 человек, какая беседка подойдет`; `local_regression_suite.py --group upsell` покрывает `давайте первый набор`; context live-135 проверяет, что после оплаченной беседки ответ на `можно еще что нибудь забронировать?` не говорит `помимо бани`.
- Проверки текущего продолжения: `.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts/dialog_context_suite.py` 17/17 OK; `scripts/local_regression_suite.py --group upsell` OK; `scripts/local_regression_suite.py --group post_booking` OK; `scripts/dialog_edge_suite.py` 14/14 OK; `scripts/dialog_stress_suite.py` 13/13 OK; `scripts/lint_best2info.py` OK.

## 2026-06-01 - best2info graph-aware retrieval, percent prepayment and bathhouse cleanup

- Реализован пакет из плана стабильного тестового запуска: `best2info/index.md` переписан как карта клиентской базы знаний с явными источниками истины, алиасами для retrieval и правилом "если точного факта нет, бот не придумывает".
- `app/services/knowledge_service.py` теперь читает `best2info/**/*.md` как маленький граф: парсит заголовки и `[[wikilinks]]`, всегда добавляет `runtime.md`, выбирает релевантные страницы по текущему scoring и расширяет выборку 1-hop исходящими/входящими ссылками. Keyword/token scoring остался fallback-слоем.
- Добавлен `scripts/lint_best2info.py`: проверяет broken wikilinks, orphan pages, базовые цены и скидочные цены беседок против `config/services_map.yaml`, фиксированные пакеты бани/дома, цену теплой беседки и факты без точной цены, где ответ должен быть "уточним по факту". Прогон: `OK best2info lint: files=15, links_checked=15, price_checks=ok`.
- Настройки предоплаты расширены: `PREPAYMENT_MODE=fixed|percent`, `PREPAYMENT_AMOUNT_RUB`, `PREPAYMENT_PERCENT=50`. Локальный тестовый режим закреплен как `PREPAYMENT_MODE=fixed`, `PREPAYMENT_AMOUNT_RUB=1`; production-цель перед реальным запуском - `PREPAYMENT_MODE=percent`, `PREPAYMENT_PERCENT=50`.
- `payment_service` умеет считать percent-mode от цены основной услуги/пакета по `services_map`, для беседок учитывает скидку 50% ПН-ЧТ, допы в аванс не включает. Текстовые ответы о цене/предоплате используют тот же режим.
- Выполнен безопасный cleanup тестовой бани `2026-06-30 12:00-16:00`: `bookings.id=1` переведен в `cancelled` с архивной пометкой в `yclients_create_error`, `resource_busy_intervals.source='bot_booking'/source_record_id='1'` удален, `payments.id=2` оставлен `paid` и получил `payment_notified_at`, чтобы не отправлять старое уведомление. В `system_logs` записано событие `manual_cleanup_test_bathhouse_2026_06_30`.
- Во время regression-прогона найден и закрыт test-isolation баг: waitlist-тест подхватывал существующую live-строку `waitlist_requests.id=35` из общей БД. Строка восстановлена в `active` без `notified_at`, а тест теперь подменяет `waitlist_repo.list_active_due` и обрабатывает только созданные test waitlist ids.
- Проверки по пакету: `python -m compileall app scripts` OK; `scripts/lint_best2info.py` OK; `scripts/validate_yclients_map.py` OK; `scripts/yookassa_webhook_hardening_smoke.py` OK; все группы `scripts/local_regression_suite.py` прошли в 3 блоках; `dialog_context_suite.py` 16/16, `dialog_edge_suite.py` 14/14, `dialog_stress_suite.py` 13/13, `dialog_regression_smoke.py` OK после свежего YCLIENTS sync. На текущем продолжении дополнительно повторены `compileall` и `lint_best2info.py`.
- Финальный status в продолжении: первый `yclients_sync_status.py --strict` был stale только по возрасту (`age_seconds=1120`, `last_error=None`), затем `sync_yclients_records.py --once` прошел `seen=122/upserted=122`; повторный strict fresh (`age_seconds=47`, `records_seen=122`, `last_error=None`).
- Дополнительно после wiki-обновлений пройден узкий regression `scripts/local_regression_suite.py --group prices --group waitlist`: OK, включая ответы с предоплатой `1 ₽`, graph-aware retrieval smoke и waitlist relevance. Live `waitlist_requests.id=35` после прогона остался `active`, `notified_at=NULL`.

## 2026-06-01 - pre-live диагностика фонов, тестовая предоплата и upsell-тексты

- По запросу перечитаны `best2obs/index.md` и `best2obs/log.md`, затем проверены `best2info`, фоновые runner'ы, текущий `.env`, свежесть YCLIENTS-cache и последние live-сообщения/платежи.
- На момент диагностики `best2info/` работал как клиентская markdown-wiki/граф Obsidian с token/keyword retrieval без runtime-обхода связей; позднее в этот же день retrieval обновлен до 1-hop graph-aware режима, см. верхнюю запись.
- Фоновые процессы на момент проверки не запущены: `Get-Process python` вернул `NO_PYTHON_PROCESSES`. При запуске `main.py` должны стартовать `run_yclients_sync_loop`, `run_payment_status_loop`, `run_message_retention_loop` и локальный `start_yookassa_webhook_server`; `telegram_status.py` показал webhook пустой и `pending_update_count=0`.
- YCLIENTS-cache свежий: `scripts/yclients_sync_status.py --strict` OK (`fresh=True`, `age_seconds=59`, `records_seen=122`, `last_error=None`). DB доступна: `messages=151`, `conversation_summaries=0`, `slot_holds=4`, `bookings=2`, `yclients_records=128`, `resource_busy_intervals=130`.
- Найден источник расхождения "в YCLIENTS свободно, бот пишет занято" по бане на 30 июня: локальная paid-заявка `bookings.id=1` на `2026-06-30 12:00`, 4 часа, имеет `yclients_record_id=NULL` и `yclients_create_error` с HTTP 422 `Услуга недоступна в выбранное время`; при этом в `resource_busy_intervals` остался `bot_booking` interval `2026-06-30 12:00-16:00`, поэтому локальная availability может блокировать слот, которого нет в журнале YCLIENTS.
- Локальный `.env` переведен в тестовый режим `PREPAYMENT_AMOUNT_RUB=1`; новый Python process подтвердил `get_settings().prepayment_amount_rub == 1`. Уже созданная ранее ссылка `payments.id=58` остается на `2000.00 RUB`, потому что сумма уже сохранена в YooKassa/БД.
- Улучшены service-specific upsell-тексты в `booking_form_service._upsell_question()` и `dialog/form_patches.upsell_sales_messages()`: отдельные формулировки для бани, беседки, тёплой беседки и дома; логика выбора/отказа от допов не менялась.
- Проверки после текстовых правок: `.venv\Scripts\python.exe -m compileall app scripts` OK; `scripts/local_regression_suite.py --group upsell` OK. Наблюдение прежнее: отдельный сценарий `generic ok after upsell info does not accept items` дал `dialog_timing_slow` на AI semantic, функционально зелёный.

## 2026-06-01 - полный сценарный аудит текущих изменений

- Перед проверкой прочитаны `best2obs/index.md`, `best2obs/log.md`, сценарные чеклисты и `testing/dialog-test-matrix.md`. Production-код в ходе этого аудита не менялся; существующее грязное дерево оставлено как текущие изменения проекта.
- Проверки сценариев прошли зелёными: `.venv\Scripts\python.exe -m compileall app scripts` OK; `local_regression_suite.py` пройден тремя блоками (`fresh/dates/gazebo/services/time/prices/upsell`, `payments/post_booking/cancel/reschedule`, `media/waitlist/handoff/reminder`) OK; `dialog_context_suite.py` 16/16 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK.
- Найден операционный нюанс: первый `dialog_regression_smoke.py` упал до диалога с `No free gazebo date found for smoke test`, потому что локальный YCLIENTS-cache был stale (`age_seconds=34651`, `max_age_seconds=600`, `last_error=None`). Выполнен `scripts/sync_yclients_records.py --once`: `seen=123`, `upserted=123`; повторный `yclients_sync_status.py --strict` OK (`fresh=True`, `records_seen=123`, `last_error=None`).
- После sync `scripts/dialog_regression_smoke.py` прошёл OK: smoke нашёл свободную беседку, защитил `давай беседку номер 2` от записи `guests_count=2`, создал fake-payment на `2000.00 ₽` и оставил hold активным без booking до оплаты.
- Дополнительные безопасные проверки: `scripts/validate_yclients_map.py` OK (`checked_configured_pairs=29`, `unmapped_live_services=none`), `scripts/test_db.py` OK, `scripts/yookassa_webhook_hardening_smoke.py` OK, `scripts/yclients_smoke.py` OK. `scripts/yookassa_smoke.py` не запускался, потому что он создаёт реальную внешнюю ссылку.
- Наблюдение: в regression/context/edge/stress всё ещё встречаются `dialog_timing_slow` на AI/availability ветках, функционально сценарии зелёные. Это остаётся UX/performance-направлением, не текущей регрессией корректности.

## 2026-05-31 - закрыт pre-live fallback/proxy/smoke пакет

- Реализован общий capacity guard в `message_handler.py`: все normal/fallback/AI-unavailable пути теперь вызывают `_capacity_mismatch_reply()`, который проверяет сначала беседки, затем баню. Баня с `guests_count > 15` очищает `guests_count` и не переходит к `event_format`.
- Уточнён parser формата события: `др` считается днём рождения только как отдельное слово; `день рождения`, `днюха`, `юбилей` сохранены. `просто посидеть с друзьями` остаётся `компания друзей`.
- Добавлена явная proxy-политика `HTTP_TRUST_ENV=false`: настройка есть в `.env.example`, локальном `.env` и `Settings`; OpenAI/OpenRouter, YCLIENTS, YooKassa и voice transcription создают `DefaultHttpxClient`/`httpx.Client` с `trust_env=settings.http_trust_env`. One-shot YCLIENTS sync прошёл без `NO_PROXY` и без `socks4` error.
- Локальный `.env` переведён с `PREPAYMENT_AMOUNT_RUB=1` на `2000`; smoke fake-payment тоже проверяет `2000.00 ₽`.
- В ходе smoke найден и закрыт дополнительный state bug: на шаге `guests_count` фраза `давай беседку номер 2` сохраняла `guests_count=2`. Добавлен guard `_explicit_gazebo_variant_reference()` и smoke-check `gazebo number selection does not become guest count`.
- Проверки после финальной правки: `.venv\Scripts\python.exe -m compileall app scripts` OK; все 4 listed chunks `scripts/local_regression_suite.py` OK; `scripts/dialog_context_suite.py` 16/16 OK; `scripts/dialog_edge_suite.py` 14/14 OK; `scripts/dialog_stress_suite.py` 13/13 OK; `scripts/sync_yclients_records.py --once` OK (`seen=129`, `upserted=129`); `scripts/yclients_sync_status.py --strict` OK (`fresh=True`, `records_seen=129`, `last_error=None`); `scripts/dialog_regression_smoke.py` OK.

## 2026-05-31 - диагностика best2 без правок production-кода

- Перед проверкой прочитаны `best2obs/index.md` и `best2obs/log.md`; production-код не менялся. Рабочее дерево уже было грязным: изменения в `app/services/*`, `scripts/local_regression_suite.py`, `scripts/dialog_context_suite.py`, `best2info/*` и `best2obs/*` оставлены как пользовательские/существующие.
- `compileall app scripts` прошёл OK. Полный grouped-прогон `local_regression_suite.py` за один запуск упёрся в 10-минутный timeout, поэтому проверка была разбита на части.
- Split `local_regression_suite.py --group dates --group services --group upsell --group waitlist --group payments --group post_booking` завершился `EXIT=1`: `bathhouse blocks large group` упал. Бот на `40` гостей в анкете бани перешёл к `event_format` и сохранил `guests_count=40`, вместо того чтобы заблокировать баню больше 15 гостей.
- `dialog_context_suite.py` подтвердил проблему: 15/16, падает `Баня на 40 гостей блокируется до шага формата`. `dialog_edge_suite.py` прошёл 14/14, `dialog_stress_suite.py` прошёл 13/13.
- Найден операционный фактор: системный Windows proxy отдаёт `http/https=socks4://127.0.0.1:10808`; `httpx 0.28.1` падает на таком proxy. Из-за этого OpenAI/OpenRouter и YCLIENTS-вызовы логируют `ValueError: Unknown scheme for proxy URL URL('socks4://127.0.0.1:10808')`, а диалог чаще уходит в fallback. Именно fallback-путь сейчас не проверяет bathhouse capacity так же, как normal path.
- Первый `scripts/yclients_sync_status.py --strict` был красным: stale sync (`age_seconds=88145`) и `last_error` про `socks4`. Временная команда `$env:NO_PROXY='*'; scripts/sync_yclients_records.py --once` успешно обновила локальный журнал (`seen=129`, `upserted=129`), повторный strict-status OK (`fresh=True`, `records_seen=129`, `last_error=None`).
- Подтвержден старый конфигурационный риск: `.env` всё ещё содержит `PREPAYMENT_AMOUNT_RUB=1`, тогда как `.env.example` держит `2000`; live-ссылки YooKassa останутся на 1 ₽ до изменения env и перезапуска.
- Выводы занесены в [[bugs/current-known-issues]] и [[roadmap/pre-launch]]. Следующий безопасный fix scope: добавить bathhouse capacity guard в fallback/AI-unavailable path и/или availability trigger на `guests_count` для bathhouse; затем повторить `compileall`, профильные regression-группы и context-suite.

## 2026-05-30 - закрыт live-пакет waitlist/context/confirmation

- Реализован safe waitlist gate без новой таблицы: используется существующая `waitlist_requests`, но перед уведомлением теперь проверяются `active` status, будущая дата, отсутствие уже закрывающей брони/hold, отсутствие отказа в последних сообщениях и свежая доступность после sync. Неактуальные запросы закрываются как `closed`, отправленные остаются `notified`.
- Закрыты новые live-регрессии диалога: баня больше 15 гостей блокируется и предлагает просторную беседку; `на 30 число/на 30-е/на 30` берёт месяц из свежего контекста текущей анкеты или `last_unavailable`; `нет` на финальном подтверждении больше не меняет допы, а переводит в flow изменения заявки; `ну окей` после info-вопроса на шаге допов не выбирает допы без явного выбора.
- Добавлены regression/context проверки: `bathhouse blocks large group`, `contextual day number keeps discussed month`, `confirmation no is not upsell correction`, `generic ok after upsell info does not accept items`, `waitlist notifies only relevant requests`, а также 2 context-сценария в `dialog_context_suite.py`.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group dates`, `--group services`, `--group upsell`, `--group waitlist`, `--group post_booking`, `--group gazebo`, `--group payments` OK; `dialog_context_suite.py` 16/16 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK. Первый `yclients_sync_status.py --strict` был красным из-за stale sync и `SSL error: unexpected eof while reading`; после `sync_yclients_records.py --once` строгий статус OK (`records_seen=127`, `last_error=None`).

## 2026-05-30 - закрыты live-30.05 price/common-info, upsell, book_times и media сбои

- Разобран свежий live-диалог после чистой базы: `сколько будет стоить?` ошибочно попадало в ответ про детей из-за substring `дет` внутри `будет`; первый `не` на допах закрывал допы сразу; баня `30 июня 12:00-16:00` проходила локальный hold/payment, но YCLIENTS после оплаты возвращал 422; `30 челове` не фильтровало беседки по вместимости; summary двух броней отправлял фото бани без Беседки №1; `просто посидеть с друзьями` могло стать `день рождения`.
- Исправлено без смены публичных API/БД: common-info children matcher стал словоформенным; добавлен semantic `classify_upsell_reply()` с двухкасательным отказом; для `bathhouse/house` фиксированные пакеты сверяют выбранный старт с YCLIENTS `book_times` до hold/payment; guests parser принимает обрезанное `челов*`; media selection берёт беседку из `service_variant/hold_yclients_service_id/yclients_service_id` и booking-list text.
- По важному замечанию про “не хардкодить”: добавлен semantic price route. Если AI понял свободную фразу как `price_question`, backend считает цену по `services_map` даже без слов `цена/стоить/сколько`; deterministic слой остаётся только safety guard против ложных веток.
- Добавлены/обновлены regression checks: `price question with budet is not children info`, `AI semantic price question without price keywords`, `bare ne first upsell gets soft push`, `fixed service rejects missing yclients book time`, `fixed service yclients unavailable does not claim free`, `truncated people word extracts guests`, `friends hangout event format not birthday`, расширен `gazebo media selection`.
- Проверки: `.venv\Scripts\python.exe -m compileall app scripts` OK; `local_regression_suite.py --group prices --group upsell --group services --group gazebo --group media --group payments` OK; после semantic-price правки `local_regression_suite.py --group prices` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; `sync_yclients_records.py` one-shot и `yclients_sync_status.py --strict` OK (`records_seen=126`, `last_error=None`).
- Бот не запускался. Live paid-but-journal-pending запись бани с YCLIENTS 422 не ремонтировалась без отдельной команды.

## 2026-05-30 - подготовлена чистая база best2 перед live-тестами

- Перед новым ручным тестированием удалены 2 явные тестовые записи, созданные из Telegram-бота в YCLIENTS: `1741815435` (Беседка, 29 мая 2026, 15:00, телефон `+79099667655`, имя `Ирина`) и `1741778379` (Беседка, 19 июня 2026, 12:00, телефон `+79968533502`, имя `Заменим На Ivan`). Удаление выполнено через `scripts/cleanup_yclients_test_records.py --apply`; результат `Deleted: 2, failed: 0`.
- Локальная база best2 очищена через `scripts/clear_db.py`: `users`, `conversations`, `messages`, `conversation_summaries`, `slot_holds`, `bookings`, `payments`, `waitlist_requests`, `system_logs`, `webhook_events` теперь по `0`.
- Таблицы журнала заново наполнены из YCLIENTS через `scripts/sync_yclients_records.py --once --days-back 1 --days-forward 60`: `seen=126`, `upserted=126`; `scripts/yclients_sync_status.py --strict` показал fresh sync, `last_error=None`.
- Подготовка проекта проверена без запуска бота: `python -m compileall app scripts` OK; активных `python`-процессов перед очисткой не найдено.

## 2026-05-29 - закрыт live-19:02 сбой последующей брони беседки после старого draft бани

- По live-цепочке `а какие беседки есть` -> `хочу добвить отдельной бронью` найден повторяющийся класс ошибок последующих броней: старый draft бани с неподходящей длительностью мог перехватить новую фразу и вернуть ошибку про 12 часов бани вместо старта отдельной беседки.
- Исправлено точечно: generic new-booking detector теперь понимает `отдельной/отдельную бронью`, `добавить/добвить отдельной`, а service-exists route больше не перехватывает сообщения с явной датой/периодом или same-date/same-time reference.
- Вопрос `а какие беседки есть` получил deterministic ответ со списком типов беседок и сохраняет `last_discussed_service_type=gazebo`, не меняя текущий draft. Следующая фраза `хочу добвить отдельной бронью` стартует чистую беседку с сохранением только контакта.
- Post-booking вопрос про комаров теперь отвечает deterministic текстом из базы до AI-классификатора: обработка раз в неделю, природная территория, лучше взять репеллент.
- Формулировка по бане уточнена: это не произвольная почасовая услуга; в YCLIENTS заведены фиксированные пакеты 3, 4, 5, 6 или 7 часов.
- Добавлены regression checks: `gazebo info then separate booking ignores old bath draft`, `mosquito question after booking bypasses AI`; обновлены существующие duration-тексты.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group services --group prices` OK; `local_regression_suite.py --group fresh --group post_booking --group payments --group time` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK.

## 2026-05-29 - зафиксирован план безопасного уменьшения message_handler

- После сценарной диагностики разобран размер `app/services/message_handler.py`: файл около 5.7k строк, главный `handle_incoming` около 2k строк маршрутизации и сохранения состояния.
- Вывод: повторяющиеся live-нюансы возникают на границах flow, где старый draft/new booking/info/availability/hold пересекаются в одном координаторе. Уменьшать файл нужно не большим rewrite, а короткими behavior-preserving разрезами под зелёными suites.
- Создан [[roadmap/message-handler-refactor]]: сначала единый helper сохранения `FlowResult`, затем stale/new-booking flow, info-flow, same-reference/unavailable UX и только после этого явный route table.
- `best2` production-код не менялся; обновлены только `best2obs` roadmap/index/backend notes.

## 2026-05-29 - сценарная диагностика best2 после фиксов live-14:29

- Проведён повторный сценарный прогон best2 без запуска Telegram-бота: `compileall app scripts` OK; после one-shot `sync_yclients_records.py --once` strict YCLIENTS был fresh (`records_seen=125`, `last_error=None`).
- `dialog_context_suite.py` прошёл 14/14: дата/гости, same-date/same-time, оплаченная беседка -> новая баня, active gazebo info inside bath draft, confirmation summary and two-gazebo queue держат контекст.
- `dialog_edge_suite.py` прошёл 14/14: summary/off-topic внутри анкеты, phone+info, confirmation side questions, cancel-flow, reschedule-flow и post-booking off-topic не портят состояние.
- `dialog_regression_smoke.py` прошёл OK; основные grouped regression-зоны прошли: `fresh/payments/post_booking/services/time/upsell` OK и `dates/gazebo/prices/media/waitlist/handoff/cancel/reschedule/reminder` OK.
- Первый `dialog_stress_suite.py` прогон дал 12/13: live-like сценарий `баньку тем же днем что и беседка` -> `и часы как там же` попал в ветку недоступности бани, где основные `date/time/duration` очищаются в пользу `last_unavailable`. После полной cleanup regression-fixtures повторный stress прошёл 13/13. Вывод: same-reference логика умеет копировать контекст, но unavailable-slot branch остаётся UX-risk, потому что клиент может увидеть это как потерю контекста.
- Замер по ощущениям live: функционально suites зелёные, но многие сложные ветки идут через AI/availability и дают `dialog_timing_slow` примерно 6-19 секунд. Это не ломает состояние, но объясняет ощущение, что бот иногда "троит"; следующий фокус — быстрее short-circuit frequent info/off-topic/summary paths и отдельно покрыть unavailable same-reference branch.

## 2026-05-29 - best3 full best2obs parity and safe tools milestone

- In `../best3`, full documented `best2obs` scenario-id coverage is now enforced by `scripts/best2obs_scenario_runner.py --all`: `STD-001..009`, `CTX-001..022`, `EDGE-001..014`, `STR-001..013`, `REG-001..014`.
- This is not a copy of the old `best2` `message_handler.py`: `best3` keeps the AI-orchestrator model and adds backend safe tools for current draft, media/photos, waitlist, payment/current-booking checks and non-destructive cancel/reschedule proposals.
- The raw `# best2info` leak class is closed in `best3`: questions like "what are we booking" now route to backend state through `show_current_draft`, and `answer_info` strips wiki/index metadata before replying.
- Verification in `best3`: 49 unit tests OK; compile OK; `table_prefix_guard.py` OK; `core_parity_scenarios.py` OK; `best2obs_scenario_runner.py --all` OK; `shadow_compare.py` OK; live-AI smoke for current draft/media/cancel/reschedule OK; guarded smoke/payment/expired/webhook and final `test_pilot_checklist.py` OK.
- `best2` production code was not changed. During the final guard, unrelated active best2 regression processes and one stale idle DB transaction were stopped so row-count safety could measure `best3` cleanly.

## 2026-05-29 - закрыты live-14:29 stale-context, `не` на допах, soft-confirm и фиксированные блоки бани

- По новому live-чату разобраны 4 сбоя: явная новая заявка бани после старого draft сначала показывала stale-checkpoint вместо обработки сообщения; ответ `не` на вопрос допов не принимался как отказ; `ну вроде да` не подтверждало готовую заявку; баня могла уйти в произвольные 12 часов `09:00-21:00`, после чего оплата проходила локально, но YCLIENTS не создавал запись.
- Исправлено точечно без большого рефакторинга `message_handler.py`: подробная новая заявка поверх старой анкеты стартует чистый draft с сохранением только контакта; `нет + новая заявка` в одном сообщении обрабатывается сразу, без повторного вопроса; короткое `не/no/нет спасибо` считается финальным отказом от допов; мягкие подтверждения вроде `ну вроде да` принимаются в confirmation-flow.
- Для услуг с фиксированными блоками длительности добавлена backend-валидация в availability: баня больше не принимается как произвольная почасовая бронь. Если клиент пишет `с 9 утра до 21 ночи`, бот сохраняет дату/время, сбрасывает только длительность и просит выбрать доступный блок 3, 4, 5, 6 или 7 часов.
- Live-заявка `booking_id=1096` не ремонтировалась: локально она дошла до paid, но YCLIENTS вернул `422 service unavailable at chosen time` именно из-за недопустимого 12-часового блока. Новый код не должен создавать такую заявку заново без выбора допустимой длительности.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group fresh`, `--group time`, `--group upsell`, `--group post_booking`, `--group services` OK; payment-сценарии прошли через основной вывод + отдельный subset 5/5 OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; stress-сценарии прошли split-run 13/13 OK. Полный монолитный stress-прогон один раз упал на transient PostgreSQL SSL/runner-lock, но те же сценарии прошли при раздельном запуске.
- После `scripts/sync_yclients_records.py --once` строгий `scripts/yclients_sync_status.py --strict` OK: `records_seen=125`, `records_upserted=125`, `last_error=None`. Бот не запускался.

## 2026-05-29 - диагностирована причина платежей YooKassa на 1 рубль

- Найден конфигурационный источник: в локальном `.env` установлено `PREPAYMENT_AMOUNT_RUB=1`, а `payment_service.calculate_prepayment_amount()` умножает это значение на количество броней и передает его в YooKassa как `amount.value`.
- Проверка БД read-only: все 7 локальных платежей `payments` за 2026-05-28..2026-05-29 имеют `amount=1.00 RUB` (4 paid, 3 canceled).
- Проверка YooKassa read-only: последние 30 платежей текущего магазина тоже `1.00 RUB` и все имеют booking-bot metadata, то есть это живые ссылки бота, а не только `scripts/yookassa_smoke.py`.
- Дополнительная QR/СБП-проверка: `/me` YooKassa показывает включенный `sbp`, но `YooKassaClient.create_payment()` не передает `payment_method_data.type=sbp`, поэтому бот создает обычную ссылку на общую форму YooMoney; последние успешные платежи прошли как `tinkoff_bank`/`sberbank`, а canceled имеют `expired_on_confirmation`.
- Production-код не менялся. Вывод записан в [[bugs/current-known-issues]]; для исправления нужно отдельно изменить `.env` на целевую сумму и перезапустить бот. Если нужна именно QR/СБП-ссылка, нужно изменить интеграцию на `payment_method_data.type=sbp` или добавить настройку платежного метода. Если нужна предоплата 50%, требуется отдельная бизнес-логика вместо фиксированной суммы.

## 2026-05-29 - best3 live chat bathhouse alias fix

- In `../best3`, latest Telegram pilot chat exposed a live-AI alias mismatch: AI returned `service_type=sauna` for `баньку`, backend rejected it, and the draft stayed empty.
- Fixed in `../best3`: `sauna/banya/bath/банька/баньку/баньке` normalize to `bathhouse`; greeting fallback no longer says `уточню у администратора`; `greeting_bath_short` is now part of `agent_smoke.py --all-scenarios`.
- Verification in `best3`: 41 unit tests OK; compile OK; prefix guard OK; core/shadow OK; full pre-pilot checklist OK; bot restarted in safe test mode. `best2` production code was not changed.

## 2026-05-29 - best3 YooKassa webhook and pilot gate

- In `../best3`, added the local YooKassa webhook runner/service with secret validation, max body size, `best3_webhook_events` persistence and duplicate-safe `payment.succeeded` finalization.
- Added `../best3/app/services/notification_service.py` for client assistant notification messages and admin system logs deduped by `payment_notified_at`, `admin_notified_at` and `expired_notified_at`.
- Added `../best3/scripts/yookassa_webhook_smoke.py` and `../best3/scripts/test_pilot_checklist.py`; final checklist passed after active best2 background suites stopped mutating old row counts.
- Verification in `best3`: 37 unit tests OK, compile OK, SQL prefix guard OK, core/shadow OK, strict YCLIENTS OK after sync, agent smoke OK, fake paid finalization OK, expired hold smoke OK, YooKassa webhook smoke OK.
- `best2` production code was not changed.

## 2026-05-29 - закрыты live-13:07 ошибки времени, fake payment и новой заявки

- По новому live-чату разобраны 3 сбоя: `с 9 утра до 21 ночи, если что можно на дольше остаться?` превращалось в `09:00-08:00` на 23 часа; `а ты можешь сделать будто бы я оплатил?` могло уйти в проверку оплаты и показать `Оплата получена`; `приступим к следующуей заявке?` во время active hold распознавалось как доп `лед`.
- Исправлено точечно: явный период времени теперь защищён helper-ом `has_explicit_time_period()` и не проигрывает AI-guess про "подольше"; fake-payment формулировки обрабатываются как отказ от ручной имитации оплаты без смены статуса hold; upsell parser ищет короткие допы вроде `лед` по границам слова, а generic next-booking фразы поверх active hold запускают чистую новую анкету с сохранением только имени/телефона.
- Добавлены regression checks в `scripts/local_regression_suite.py`: `gazebo explicit period with longer question keeps end time`, `fake payment request does not mark paid`, `next application while hold starts blank not ice`.
- Проверки: `python -m compileall app scripts` OK; `local_regression_suite.py --group fresh --group payments --group time` OK; профиль `--group services --group gazebo --group upsell --group post_booking --group payments --group time --group fresh` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; после `sync_yclients_records.py --once` строгий `yclients_sync_status.py --strict` OK (`seen=125`, `upserted=125`, `last_error=None`).
- Бот не запускался; был выполнен только one-shot sync YCLIENTS-cache для свежего strict-статуса.

## 2026-05-29 - best3 safe paid finalization и expired hold cleanup

- В `../best3` добавлен safe paid-finalization режим: `YCLIENTS_RECORD_MODE=fake` позволяет проверить paid payment -> local booking -> fake YCLIENTS record -> busy interval без внешнего создания записи в YCLIENTS.
- Добавлены `../best3/scripts/payment_finalize_smoke.py`, `../best3/scripts/cleanup_expired_holds.py`, `../best3/scripts/expired_holds_smoke.py`.
- Expired hold cleanup переводит просроченные active holds в `expired`, отмечает `expired_notified_at` и пишет событие в `best3_system_logs`.
- Проверки `best3`: `unittest discover -s tests` 30 tests OK; `compileall app scripts tests` OK; `table_prefix_guard.py` OK; `core_parity_scenarios.py` OK; `shadow_compare.py` OK; expanded smoke/fake finalization/expired hold smoke через DB guard OK.
- Наблюдение: во время одного guard-прогона `best2.messages` выросла на 2 строки из-за параллельной live-активности `best2`; повторные guard-прогоны игнорировали только `messages`, остальные production-таблицы `best2` не менялись. `best2` production-код не менялся.

## 2026-05-29 - best3 добавил backend understanding и DB safety guard

- В `../best3` добавлен `state.understanding` для agent prompt: current task, missing fields, readiness, active holds, latest payment status, active bookings и safe next actions. Это делает состояние явным для AI.
- В `best3` добавлены backend-understanding overrides: вопрос про оплату/предоплату идёт через `get_payment_status`; явная смена услуги вроде `а я же хочу баньку` принудительно патчит новый `service_type`; policy считает readiness после service-switch cleanup.
- Добавлен безопасный fake payment provider для smoke, чтобы проверять hold/payment link без реального YooKassa вызова.
- Добавлен `../best3/scripts/db_safety_guard.py`: row-count snapshot production-таблиц `best2` до/после команды. Прогон `agent_smoke.py --all-scenarios --safe-payments` и `sync_yclients_records.py --once` подтвердили, что `best2` таблицы не изменились.
- Проверки `best3`: `unittest discover -s tests` 28 tests OK; `compileall app scripts tests` OK; `table_prefix_guard.py` OK; `core_parity_scenarios.py` OK; `shadow_compare.py` OK; strict YCLIENTS OK; расширенный smoke OK.
- `best2` production-код не менялся.

## 2026-05-29 - best3 получил собственную LLM Wiki

- В `../best3` создан `best3obs/` как отдельный markdown/Obsidian-граф по образцу `best2obs`: index/log, architecture, roadmap, testing, bugs, decisions, prompts и daily.
- В корень `best3` добавлен `AGENTS.md`: будущие задачи по `best3` должны начинаться с чтения `best3obs/index.md` и `best3obs/log.md`, а значимые выводы должны сохраняться в wiki.
- Дополнительно улучшены `best3` smoke/shadow инструменты: `agent_smoke.py --json` показывает agent/policy/tool/draft outcome, `shadow_compare.py` поддерживает multi-turn outcome scenarios.
- Проверки `best3`: `unittest discover -s tests` 24 tests OK; `compileall app scripts tests` OK; `table_prefix_guard.py` OK; `shadow_compare.py` OK; `sync_yclients_records.py` OK; fallback `agent_smoke.py --json` OK.

## 2026-05-29 - best3 core parity перенесён как agent-first правила и сценарии

- В `../best3` внедрён core-parity слой по выбранному scope: новая бронь, info-вопросы, availability, hold/payment safety, paid/current-booking поведение и ключевые live-нюансы `best2`, но без копирования большого `best2` `message_handler.py`.
- Добавлены deterministic stub/shadow сценарии `scripts/core_parity_scenarios.py` и `scripts/shadow_compare.py`: сравниваются outcome (`action`, `draft_patch`, payment/hold intent), а не буквальный текст ответа.
- Усилены `best3` agent/policy/tools: natural date/guest/time parsing, mixed `answer_info + draft_patch`, service switch cleanup (`а я же хочу баньку`), upsell vague accept/refusal, name correction, safe `abort_draft`, payment/current-booking routing, active/expired hold guards.
- Payment слой `best3` закреплён идемпотентностью pending-ссылки и запретом поздней конвертации истёкшего hold; paid `get_payment_status` показывает строку брони с датой/временем, если booking уже создан.
- Проверки `best3`: `unittest discover -s tests` 23 tests OK; `compileall app scripts tests` OK; `table_prefix_guard.py` OK; `core_parity_scenarios.py` OK; `shadow_compare.py` OK; `sync_yclients_records.py` + `yclients_sync_status.py --strict` fresh; real-AI `agent_smoke.py` OK на короткой цепочке без оплаты. Реальный Telegram bot не запускался.
- Baseline `best2`: `compileall app scripts` OK; `dialog_context_suite.py` 14/14 OK; профильный `local_regression_suite.py --group services --group gazebo --group upsell --group post_booking --group payments` OK.

## 2026-05-29 - добавлены paraphrase-регрессии против словарных костылей

- По просьбе проверить, что исправления не завязаны на одну конкретную фразу, расширены regression-сценарии batch-парафразами: гипотетические гости (`а если нас 10`, `для 10 человек`, `если будет 10 человек`), отказ от допов на месте (`возьмем/возьмём`, `разберемся`), исправление имени (`имя заменим/поменяем`, `замени имя`, `фио измени`) и post-booking цепочка про баню разными словами.
- Новый прогон поймал реальный общий недочёт: `фио измени на IVAN` не доходило до parser имени, потому что prefilter знал `имя`, но не `фио`. Исправлено в `app/services/dialog/form_corrections.py`; теперь `фио` работает в том же общем name-correction flow.
- Важный вывод: deterministic guards остаются как защита состояния, но теперь тестируются не как одно "магическое слово", а как класс смысловых формулировок. AI-route может понять свободную фразу, а backend проверяет, что результат безопасен для текущего draft/booking-state.
- Проверки: `python -m compileall app scripts` OK; `local_regression_suite.py --group post_booking` OK; профильный `local_regression_suite.py --group services --group gazebo --group upsell --group post_booking --group payments` завершился `EXIT=0`, `FAIL`/`Traceback`/`AssertionError` не найдены.
- Обновлены `best2obs/testing/dialog-test-matrix.md`, `best2obs/testing/scenario-run-2026-05-29.md`, `best2obs/roadmap/dialog-regression-scenarios.md`, `best2obs/bugs/current-known-issues.md`.
- Бот не запускался.

## 2026-05-29 - создан best3 agent-first baseline рядом с best2

- В соседней папке `../best3` создан чистый agent-first проект без форка старого `message_handler.py`: AI возвращает JSON action/patch, backend валидирует policy и выполняет только safe tools.
- Добавлена отдельная PostgreSQL-схема на уровне таблиц с префиксом `best3_`: users/conversations/messages/drafts/agent_runs/tool_calls/holds/bookings/payments/YCLIENTS-cache/waitlist/webhook/system_logs. Миграция `best3` применена, создано 16 таблиц `best3_*`; `best2` таблицы не изменялись.
- Реализованы v1-компоненты: Telegram polling, agent contract, policy validator, tool executor, draft validation, info retrieval из `best2info`, local availability по `best3_yclients_records`/`best3_resource_busy_intervals`, YooKassa payment link path, paid payment finalization skeleton и YCLIENTS record creation.
- Перенесена машинная карта `services_map.yaml`; первый `best3` YCLIENTS sync выполнен успешно: `seen=125`, `upserted=125`, strict fresh (`last_error=None`).
- Проверки `best3`: `compileall app scripts tests` OK, `unittest discover -s tests` OK, `scripts/table_prefix_guard.py` OK, fallback `scripts/agent_smoke.py` OK без реального AI-вызова. Реальный Telegram bot не запускался.

## 2026-05-29 - закрыты live-1953 контекстные сбои бани и подтверждения

- По последнему live-чату `conversation_id=1953` разобраны сбои: `имя заменим на IVAN` сохраняло лишние слова, `если бы нас было 10` отвечало по старым 20 гостям, `на месте возьмем` превращалось в базовый мангальный набор, после телефона могло быть второе подтверждение, paid notification не показывало дату/время, а post-booking вопрос про баню выдумывал русскую/финскую сауну и добавление к беседке.
- Исправлено точечно: parser имени чистит формы `заменим/замени/...` и сохраняет uppercase `IVAN`; guests parser понимает `нас было/было бы`; разговорный отказ `на месте возьмем/возьмём` оставляет `допы: не нужны`; post-booking bath reply стал deterministic и говорит только про баню с бассейном как отдельную бронь; follow-up `а ее как бронировать нужно?` отвечает по последней обсуждённой бане; generic `давайте начнем новую заявку` может использовать `last_discussed_service_type`, но стартует чистый draft; `а я же хочу баньку` чистит старые slot-поля; paid notification добавляет строку брони.
- Добавлены regression checks: `name correction replaces value after na`, `hypothetical guest count updates capacity question`, `on-site upsell refusal keeps no extras`, `phone completion yes creates hold not second confirmation`, `paid notification includes booking summary`, `bathhouse post-booking info then generic new request`, `service correction with zhe resets old form`.
- Проверка БД live-чата: booking `806` существует, `yclients_record_id=1741815435`, `payment_status=paid`, `status=created_in_yclients`, `admin_notified_at` заполнен. Текущий live-draft бани в БД не ремонтировался.
- `best2info` уточнён: баня с бассейном является отдельной бронью, не доп к беседке; цены описаны как фиксированные блоки длительности по дню недели. `best2info/index.md` получил wiki-ссылки, но кодовый retrieval по-прежнему работает по тексту файлов, не по графу Obsidian.
- Обновлены `best2obs/bugs/current-known-issues.md`, `best2obs/roadmap/dialog-regression-scenarios.md`, `best2obs/testing/dialog-test-matrix.md`, `best2obs/testing/scenarios/context-live.md`, `best2obs/testing/scenarios/broad-regression.md`, `best2obs/testing/scenario-run-2026-05-29.md`, `best2obs/architecture/backend.md`.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group services --group payments --group upsell` OK после нового confirmation/pronoun-follow-up теста; ранее на этой же ветке прошли полный `local_regression_suite.py`, `dialog_context_suite.py` 14/14, `dialog_edge_suite.py` 14/14, `dialog_stress_suite.py` 13/13 и `yclients_sync_status.py --strict` после ручного `sync_yclients_records.py --once`.
- Бот не запускался.

## 2026-05-29 - закрыты live-135 paid/expired hold нюансы новой бани

- По свежей live-цепочке Kirill найдены и закрыты 4 routing-сбоя: `а она уже активна, я вносил предоплату?` могло отвечать по старому expired hold; `давайте новую оформим, мне нужна баня` запускало отмену беседки; `денег нет... оплачу... подождете?` уходило в перенос; после expired hold `я и говорю давай ее же оформлю` теряло прежний слот и спрашивало дату заново.
- Исправлено точечно: cancel detector больше не считает `мне нужна баня` фразой `не нужна баня`; вопросы про внесённую предоплату идут в deterministic payment-status route; active hold получил guard для просьбы подождать оплату; expired hold можно восстановить по фразам `давайте/оформим эту же/ее же оформлю` с сохранением `service_type/date/time/duration`.
- Добавлены regression checks в `scripts/local_regression_suite.py`: `paid booking payment question is deterministic`, `new bath request does not cancel paid gazebo`, `payment delay does not start reschedule`, `resume same expired hold does not ask date`.
- Обновлены `best2obs/bugs/current-known-issues.md`, `best2obs/roadmap/dialog-regression-scenarios.md`, `best2obs/testing/dialog-test-matrix.md`, `best2obs/testing/scenarios/context-live.md`, `best2obs/testing/scenarios/broad-regression.md`.
- Проверки: `python -m compileall app scripts` OK; `local_regression_suite.py --group payments --group services` OK; полный `local_regression_suite.py` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; `dialog_regression_smoke.py` OK.
- После длинных прогонов `yclients_sync_status.py --strict` стал stale (`age_seconds=1350`); выполнен `scripts/sync_yclients_records.py --once`, финальный strict fresh (`age_seconds=53`, `records_seen=124`, `last_error=None`).
- Бот не запускался.

## 2026-05-29 - матрица тестов разложена на подветки для ручной проверки

- `best2obs/testing/dialog-test-matrix.md` оформлена как главная матрица-хаб: добавлены ветки Standard, Context/Live, Edge, Stress, Broad Regression, Run Report и Full Diagnostics.
- Созданы ручные чеклисты успешных сценариев: `best2obs/testing/scenarios/standard.md`, `context-live.md`, `edge.md`, `stress.md`, `broad-regression.md`.
- Все сценарии в новых чеклистах перенесены из успешного сценарного прогона 2026-05-29 и помечены авто-статусом `OK`; колонка `Ручная проверка` оставлена как `TODO`, чтобы владелец мог отметить результат вручную.
- Выполнен `scripts/sync_yclients_records.py --once`: `seen=125`, `upserted=125`; затем `scripts/yclients_sync_status.py --strict` fresh (`age_seconds=54`, `records_seen=125`, `last_error=None`).
- Полная очистка `users/messages/conversations` не выполнялась автоматически: предосмотр БД показал реальные локальные строки пользователей Евгения и Kirill, а также связанные `slot_holds` и `booking`; для полной очистки нужен явный отдельный confirm, потому что это затрагивает не только три таблицы.
- Бот не запускался.

## 2026-05-29 - сценарный прогон от стандартных до нестандартных случаев

- Проведён отдельный сценарный прогон в порядке усложнения: стандартный `dialog_regression_smoke.py`, затем `dialog_context_suite.py`, `dialog_edge_suite.py`, `dialog_stress_suite.py` и широкий `local_regression_suite.py`.
- Все сценарии прошли: `dialog_regression_smoke.py` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; полный `local_regression_suite.py` OK.
- Отчёт по сценариям сохранён в `best2obs/testing/scenario-run-2026-05-29.md`, ссылка добавлена в `best2obs/index.md`.
- Непрошедших сценариев нет. Наблюдения: в логах остаются `dialog_timing_slow` на AI semantic/post-booking ветках; после длинного прогона YCLIENTS-cache стал stale (`age_seconds=961`), после повторного `sync_yclients_records.py --once` финальный strict снова OK (`records_seen=125`, `last_error=None`).

## 2026-05-29 - полный диагностический прогон проекта

- Проведена полная диагностика проекта и тестов; подробный отчёт сохранён в `best2obs/testing/full-diagnostics-2026-05-29.md`, ссылка добавлена в `best2obs/index.md`.
- Операционно: БД доступна, Telegram API отвечает (`pending_update_count=0`), YCLIENTS-cache в начале был stale (`age_seconds=28528`), после `sync_yclients_records.py --once` финальный strict fresh (`records_seen=125`, `last_error=None`).
- Все основные suites зелёные: `compileall app scripts` OK; `test_db.py` OK; `yookassa_webhook_hardening_smoke.py` OK; `validate_yclients_map.py` OK; `yclients_smoke.py` OK; полный `local_regression_suite.py` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; `dialog_regression_smoke.py` OK.
- Во время диагностики починен legacy `dialog_regression_smoke.py`: cleanup теперь удаляет `waitlist_requests`, фиксированная дата обновлена на 2026-05-29, устаревшие text assertions приведены к текущим корректным ответам.
- Наблюдения: `validate_yclients_map.py` прошёл только после retry из-за transient SSL handshake timeout YCLIENTS; в suites остаются `dialog_timing_slow` около 5-9 секунд на AI semantic/post-booking ветках; реальный `yookassa_smoke.py` не запускался, потому что создаёт внешнюю платёжную ссылку.

## 2026-05-28 - расширена матрица диалоговых тестов новой пачкой

- Добавлены regression-сценарии: `число такое же как у беседки` для второй услуги, `а с детьми и собакой можно? парковка есть?` без активной анкеты, `а до утра можно отдыхать?` внутри draft беседки.
- Добавлен edge-сценарий `Без анкеты: дети, животные и парковка не стартуют бронь`; `dialog_edge_suite.py` теперь проходит 14/14.
- Новый same-date тест поймал баг route priority: фраза `число такое же как у беседки` ошибочно уходила в cross-service active-booking info reply и не переносила дату в текущую баню. Исправлено точечно: same-date/same-time reference больше не обрабатывается как info-ответ про активную бронь.
- Обновлена `best2obs/testing/dialog-test-matrix.md`: добавлены новые успешные сценарии и результаты точечного прогона.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group services --group prices --group time` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK.

## 2026-05-28 - создана матрица успешных диалоговых тестов

- Добавлен `best2obs/testing/dialog-test-matrix.md`: единая таблица успешных сценариев, их покрытия (`local_regression_suite.py`, `dialog_context_suite.py`, `dialog_edge_suite.py`, `dialog_stress_suite.py`) и статуса последнего прогона.
- В матрицу занесены зелёные сценарии последнего полного verification: live-135 post-booking/new-bath context, date/guests poison guards, two-gazebo queue, upsell, info-вопросы, cancel/reschedule, availability/pricing и media.
- Правило на будущее: каждый новый live-баг сначала заносить в matrix как `TODO/FAIL`, затем добавлять автотест, после фикса переводить в `OK` с указанием покрытия.

## 2026-05-28 - закрыт live-135 контекст второй брони после оплаченной беседки

- По live-цепочке `conversation_id=135` добавлены регрессии: после оплаченной беседки вопрос `можно еще что нибудь забронировать?` не должен возвращать старый `awaiting_confirmation`; `давайте еще баню на то же число что и беседка` должен стартовать новую баню с `date=2026-06-30` и шагом `time`; вопрос `а вообще норм беседка?` внутри анкеты бани должен отвечать по активной беседке и возвращать к бане.
- Исправлена граница post-booking/new-booking: информационный вопрос про доступные услуги в post-booking состоянии больше не использует старый booking-ready `form_data` для повторного confirmation, а явная новая бронь может сбросить старый confirmation-draft, если у клиента уже есть активная оплаченная бронь.
- Same-date reference расширен на формулировки `то же число`, `на то же число`, `число то же`, `число такое же`. При новой услуге backend берет только дату из активной брони указанной услуги и не переносит старые `service_type`, вариант, гостей, формат или допы.
- Для услуг, где duration нужен до availability, проверка свободности больше не стартует по одной дате без времени/длительности: после `баню на то же число` бот спрашивает время, а не дату повторно и не делает преждевременный availability-check.
- Info-вопросы с ссылкой на другую активную услугу теперь отвечают по активной брони этой услуги: если текущий draft — баня, а клиент спрашивает про беседку, бот показывает активную беседку и добавляет актуальный следующий вопрос бани, не меняя `service_type`.
- Дополнительно закрыты два flow-order edge cases, найденные полным suite: `да/да да` в активном reschedule/cancel-flow больше не перехватывается plain post-booking ack; cancel confirmation доверяет `booking_id/booking_ids`, уже сохраненным в `cancel_flow`, даже если локальная сверка журнала временно пометила запись `journal_missing`.
- Проверки: `compileall app scripts` OK; полный `scripts/local_regression_suite.py` OK; `scripts/dialog_context_suite.py` 14/14 OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK; `scripts/yclients_sync_status.py --strict` fresh (`records_seen=127`, `last_error=None`).

## 2026-05-28 - закрыт live-сбой upsell/confirmation/payment для conversation 135

- По живому чату Kirill `conversation_id=135` разобрана цепочка 19:35-19:45. Первый отказ от допов `нет` корректно включал мягкий второй заход, но ответ `ну давайте` не распознавался как согласие на только что предложенный "мангальный минимум": состояние требовало `upsell_items`, а backend ждал явное название допа. Добавлен contextual accept после upsell-push: если последний вопрос был про минимум, `ну давайте/давайте/ок давайте` сохраняет `базовый мангальный набор` и переводит к следующему шагу, не повторяя availability/upsell.
- Вопрос `а это хорошая беседка?` на `awaiting_confirmation` вскрыл routing bug: fresh-start/new-booking guard мог сработать до confirmation-flow, потому что в вопросе есть слово "беседка". Теперь fresh-start не прерывает `awaiting_confirmation`, а для вопроса о текущей выбранной беседке добавлен deterministic info-reply: бот отвечает про выбранный объект и оставляет подтверждение активным.
- Telegram обработчик теперь сериализует входящие text/voice сообщения одного пользователя через per-user `asyncio.Lock`. Это защищает от гонок, когда клиент быстро отправляет два сообщения подряд (`а комары?` и `а это хорошая беседка?`) и оба обработчика читают/пишут одно состояние параллельно.
- По оплате найдено: платеж YooKassa `payment_id=17` стал `paid`, локальный booking `213` был создан, но создание YCLIENTS-записи упало на transient SSL timeout. Runner откладывал paid-уведомление до готовности YCLIENTS, поэтому клиент не получил сообщение. Исправлено: retry создания YCLIENTS для paid booking теперь повторяется через 30 секунд, а клиенту один раз отправляется промежуточное `Оплата поступила, закрепляю запись в журнале`, если журнал ещё не готов.
- Найден дополнительный resource bug: при финализации paid hold локальный `resource_busy_intervals` мог вставиться на первую беседку из `services_map`, потому что newly-created booking не нёс `hold_yclients_service_id/hold_yclients_staff_id`. Теперь bookings-repo возвращает оба hold-id, finalize мержит их сразу, `_resolve_yclients_ids` учитывает staff id, а stale bot busy interval для booking перезаписывается.
- Живая заявка восстановлена вручную без включения бота: `scripts/sync_payment_statuses.py` создал YCLIENTS record `1741240914` для booking `213`; booking теперь `created_in_yclients`, ресурс `18201061/3828151` (`Беседка №4`), payment `17` остаётся `payment_notified_at=NULL`, чтобы после следующего запуска бот отправил финальное подтверждение клиенту.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group upsell --group gazebo --group payments` OK; `--group fresh --group dates --group prices --group time --group services --group post_booking --group cancel --group reschedule` OK; `--group media --group waitlist --group handoff --group reminder` OK; `scripts/dialog_context_suite.py` 13/13 OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Операционно: локальный Telegram bot process оставлен выключенным по просьбе; `main.py` процессов после проверки нет.

## 2026-05-28 - guest/date guard переведен с keyword-trigger на structural validation

- По замечанию, что `чел/человек/гостей/нас будет` не должны быть "мозгом" бота, переработан guard против poison-state `30 июня -> 30 гостей`. AI по-прежнему первым определяет смысл и может вернуть `guests_count` без слов-маркеров; backend теперь не ищет "магическое слово", а валидирует конфликт полей.
- Новое правило: AI-only `guests_count` отклоняется, если он совпадает с числом даты/номером беседки и не подтвержден текущим шагом `guests_count` или deterministic parser. Поэтому `на 30 июня` не становится `30 гостей`, `29 мая 6 беседка` не становится `6 гостей`, но `на 30 июня двадцать` принимается как 20 гостей, если AI так понял смысл.
- Удален старый core guard `_has_guest_count_signal` / `_guest_count_from_date_only`; вместо него добавлены `_ai_guest_count_conflicts_with_date_context` и `_ai_guest_count_conflicts_with_gazebo_variant`.
- `scripts/dialog_context_suite.py` расширен до 13 сценариев: добавлены проверки "AI-смысл без слов-маркеров гостей принимается" и "номер беседки из AI-patch не превращается в гостей".
- Тестовый harness `scripts/local_regression_suite.py` поправлен под текущую дату 2026-05-28: active hold fixtures теперь создают `expires_at` относительно реального времени и используют уникальный test resource id, иначе payment-regression падал не из-за диалога, а из-за протухшего/конфликтующего тестового hold.
- Проверки: `compileall app scripts` OK; `scripts/dialog_context_suite.py` 13/13 OK; `local_regression_suite.py --group gazebo --group dates --group prices --group upsell --group time --group fresh` OK; `--group services --group post_booking --group payments --group cancel --group reschedule` OK после harness-fix; `--group media --group waitlist --group handoff --group reminder` OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Перед live smoke `scripts/yclients_sync_status.py --strict` fresh (`age_seconds=101`, `records_seen=126`, `last_error=None`). Локальный Telegram polling перезапущен на новом коде для `@fnsmvsvmpvpovbot`; из-за локальной DNS-проблемы запуск выполнен с временным `DB_HOST=95.214.62.243`, `DB_SSLMODE=verify-ca`, `DB_POOL_ENABLED=false`, `.env` не менялся.

## 2026-05-28 - закрыт live-dialog с двумя беседками, скидками и ночным временем

- По последнему Telegram-чату найдено, что смешанное сообщение `нужно 2 беседки на 02.06 и 19.06, там есть мангал и угли?` уходило только в info-route: бот отвечал про мангал, но не закреплял намерение двух отдельных заявок. Добавлен deterministic route для `2/две беседки`: первая дата становится текущей заявкой, остальные даты сохраняются в `pending_additional_bookings`, клиенту сразу объясняется, что брони заполняются по очереди.
- Добавлен guard для второй даты из очереди: сообщение вроде `19.06 на 13` во время первой заявки больше не перезаписывает дату/время текущего черновика. Бот напоминает, что 19 июня запомнил как следующую отдельную бронь, и возвращает клиента к текущему шагу.
- Исправлен UX ночного интервала: `11:00` с default duration до утра теперь показывается как `с 11:00 до 08:00 следующего дня (21 час)` в confirmation, draft/booking summaries, holds, stale-form summary и availability replies. Это оставляет бизнес-логику `до 08:00`, но делает её понятной клиенту.
- Availability/gazebo option lists стали discount-aware: если дата беседки попадает на ПН-ЧТ, строки вариантов показывают базовую цену и цену со скидкой 50%. Обычный вопрос `сколько стоит?` для выбранной беседки на будний день тоже возвращает скидочную цену, а не только базу.
- Исправлен приоритет correction на `awaiting_confirmation`: команда `время тоже поменяй с 11 до 08` больше не перехватывается reserved-hold glue с ответом `не вижу активной предварительной заявки`; она остаётся в confirmation-flow, перепроверяет availability и возвращает обновлённую сводку.
- Summary detector расширен на фразы с опечатками вроде `активыне заявки`: бот показывает текущий черновик/активные брони, а не уходит в side-reply про вторую бронь.
- Добавлены context regression scenarios: sequential two-gazebo queue, pending second-date guard, weekday price discount in normal price question, awaiting-confirmation time correction plus typo summary.
- Проверки: `compileall app scripts` OK; `scripts/dialog_context_suite.py` 8/8 OK; `local_regression_suite.py --group gazebo --group prices --group time --group fresh --group upsell` OK; `--group payments --group post_booking --group cancel --group reschedule` OK; `--group services --group dates --group media --group waitlist --group handoff --group reminder` OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Перед live smoke `scripts/yclients_sync_status.py --strict` показал stale cache (`age_seconds=2611`), выполнен `scripts/sync_yclients_records.py --once`; повторный strict fresh (`age_seconds=90`, `records_seen=122`, `last_error=None`).

## 2026-05-28 - закрыт context/availability баг `на 30 июня нас будет 20`

- По новому live-сообщению найдено, что локальная YCLIENTS-cache после ручного sync знает свободные большие беседки на 30 июня для 20 гостей (`№1`, `№8`, `№3`, `Крытая`), поэтому ответ `на ближайшие 75 дней не нашла` был не проблемой таблицы, а проблемой порядка dialog-routing.
- Причина: дата+гости в одном сообщении могли попасть в раннюю ветку выбора беседки по пустому/старому `last_available_gazebo_variants`, минуя реальную availability-проверку. Дополнительно, если на выбранную дату свободны только маленькие беседки, executor не всегда добавлял ближайшие подходящие даты.
- Исправлено: first date+guests message теперь идёт в общий availability executor; при смене даты/гостей очищается `last_suggested_free_dates`; no-capacity для беседок показывает выбранную дату, объясняет ограничение вместимости и предлагает ближайшие подходящие даты вокруг выбранной даты.
- Исправлено контекстное подтверждение: `что мы подтверждаем?` без слова `бронь` теперь считается summary-вопросом и не запускает повторную availability-проверку, поэтому черновик на `awaiting_confirmation` не сбрасывается в `awaiting_new_date`.
- Добавлен `scripts/dialog_context_suite.py`: печатает transcript живых контекстных сценариев и проверяет, что бот помнит дату/гостей/выбранную беседку/шаг подтверждения.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group gazebo --group dates` OK; `--group fresh --group upsell --group time --group prices --group services` OK; `--group payments --group post_booking --group cancel --group reschedule` OK; `--group media --group waitlist --group handoff --group reminder` OK; `scripts/dialog_context_suite.py` 4/4 OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Перед live smoke `scripts/yclients_sync_status.py --strict` показал stale cache (`age_seconds=1676`), выполнен `scripts/sync_yclients_records.py --once`; повторный strict fresh (`age_seconds=81`, `records_seen=121`, `last_error=None`).

## 2026-05-28 - отказ от черновика брони получил ранний routing priority

- По live-сообщению `давай откажемся от брони` найден routing/state bug: фраза не попадала в cancel/abort intent, поэтому на шаге допов backend продолжал обычный booking flow и отвечал availability/upsell текстом.
- Причина не в ограничении `info/check_availability`, а в порядке маршрутизации: AI может понимать смысл, но backend должен до допов, availability и AI-текста валидировать команды отмены/abort текущего черновика.
- Расширен общий cancel detector и `_wants_abort_current_draft`: формулировки `откажемся/отказ от брони/заявки/оформления`, `бронь не нужна`, `не будем бронировать` теперь считаются отказом от текущей заявки.
- Добавлен ранний guard для неопределенного ответа на шаге времени: `ну че нибудь` больше не отдается AI на придумывание слота, а повторяет вопрос времени и оставляет `time/duration` пустыми.
- Добавлены regression/edge проверки: `abort current draft from upsell refusal` в `local_regression_suite.py` и edge-сценарий `Анкета: отказ от брони на шаге допов отменяет черновик`.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group fresh --group upsell` OK; `local_regression_suite.py --group post_booking --group cancel` OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.

## 2026-05-28 - best2info и жесткий intent routing для info/availability

- Создана отдельная клиентская wiki `best2info/`: `index.md`, `runtime.md`, страницы по объектам, ценам, допам, оплате, скидкам, локации, детям/животным и правилам отдыха. `best2obs` остается памятью разработки, `best2info` становится source of truth для клиентских информационных ответов.
- `app/services/knowledge_service.py` обновлен: `load_knowledge()` теперь дает короткий runtime-контекст, а `retrieve_client_knowledge()` выбирает релевантные markdown-разделы из `best2info` для info-вопросов. Legacy `app/knowledge` оставлен fallback, старые файлы не удалялись.
- Info-вопросы в активной анкете теперь отвечают через deterministic/retrieved knowledge, а проверка свободности остается backend-действием через локальную БД/YCLIENTS-cache. AI продолжает понимать смысл, но изменение состояния и availability валидирует backend.
- Закрыты live-регрессии чата 6093: `20 чел` распознается как `guests_count=20`; для 5 июня при 20 гостях бот не предлагает маленькие беседки как подходящие; уточнение `только эта свободна на 5 июня` не листает 16-20 июня; на 8 июня предлагаются подходящие №1/№8/№3; скидка для Беседки №1 на 8 июня 2026 считается как ПН-ЧТ 50%.
- Усилен state-safe patching анкеты: голое `18,00` на шаге времени принимается как `18:00`, короткое `на 5` после времени сохраняет duration=5, `встреча однокласников` сохраняет event_format, а переход к кальяну/допам не теряет `time`, `duration`, `event_format`.
- Уточнен парсер варианта беседки: дата `на 5 июня есть беседка` больше не выбирает `Беседка №5`, но переносная фраза `беседку на 8` по-прежнему может выбрать №8 в корректном контексте.
- Добавлены regression checks в `scripts/local_regression_suite.py` для live-чата 6093, `best2info` retrieval, скидок, предоплаты/кальяна/детей/парковки и сохранения состояния после допов.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group gazebo --group dates --group prices --group upsell --group time --group fresh` OK; `local_regression_suite.py --group services --group post_booking --group payments --group cancel --group reschedule` OK; `scripts/dialog_edge_suite.py` 12/12 OK; `scripts/dialog_stress_suite.py` 13/13 OK.

## 2026-05-28 - explicit photo reply вынесен в media_flow

- Продолжен следующий маленький behavior-preserving media-срез после direct free-dates.
- Добавлен `app/services/dialog/media_flow.py` с `explicit_photo_reply` и `ExplicitPhotoCallbacks`.
- `message_handler.py` сохранил wrapper `_explicit_photo_reply`, который прокидывает текущие parsers для service/variant, normalize aliases, services map и доступные варианты беседок.
- Клиентские тексты и условия explicit-photo не менялись: явный запрос фото по беседке/бане/дому по-прежнему обходит AI, проверяет наличие медиа через `media_for_client_message` и не требует даты.
- Проверки после media-среза: `compileall app scripts` OK; `local_regression_suite.py --group media --group gazebo --group dates` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py --group post_booking --group payments --group cancel --group reschedule` OK.
- Наблюдение: авто-подбор медиа по availability-ответам остался в `media_service.py`; текущий разрез вынес только dialog glue для explicit photo reply.

## 2026-05-28 - direct free-dates lookup вынесен в availability_flow

- Продолжен маленький behavior-preserving разрез `message_handler.py` после общего availability executor.
- Direct free-dates orchestration перенесён в `app/services/dialog/availability_flow.py` как `direct_free_dates_lookup` + `DirectFreeDatesLookupCallbacks`.
- `message_handler.py` оставляет wrapper `_direct_free_dates_lookup`, который прокидывает текущие callbacks для `_deterministic_patch`, `_next_free_dates_reply`, `_alternative_services_for_unavailable_date`, `check_availability` и сохранения monkeypatch-friendly entrypoints.
- Поведение не менялось: прямой запрос ближайших свободных дат по-прежнему берёт сервис из текста/текущей анкеты/`last_unavailable`, сбрасывает stale-flow, проверяет конкретную дату при наличии, иначе вызывает `_next_free_dates_reply`.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group dates --group gazebo --group waitlist` OK; `--group fresh --group services --group prices --group upsell` OK; `--group post_booking --group payments --group cancel --group reschedule` OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Наблюдение: slow timing остаётся на отдельных AI semantic ветках примерно 5-8 секунд; это старый UX/infra риск, не связанный с текущим разрезом.

## 2026-05-28 - awaiting-confirmation execution вынесен в confirmation_flow

- Продолжен следующий behavior-preserving разрез после reserved/hold handler.
- `handle_awaiting_confirmation` перенесен в `app/services/dialog/confirmation_flow.py` через `AwaitingConfirmationCallbacks`.
- Вынесены сценарии финального подтверждения: correction patch перед оплатой, смена слота с повторной проверкой availability, конфликт active hold, создание 10-минутного hold, создание/переиспользование payment link, отказ от подтверждения и side-question на этапе подтверждения.
- `message_handler.py` теперь только вызывает confirmation-flow, пишет assistant message и обновляет conversation state; side effects и wrappers остаются прокинутыми callbacks.
- `message_handler.py` уменьшился примерно до 4583 строк; `confirmation_flow.py` вырос до ~693 строк.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group payments --group post_booking --group cancel` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py --group reschedule` OK; `local_regression_suite.py --group fresh --group gazebo --group prices --group upsell` OK.
- Наблюдение: функционально все ключевые сценарии подтверждения/оплаты/отмены/переноса сохранились. В timing logs всё ещё встречаются медленные AI semantic ветки, но это не связано с текущим разрезом.

## 2026-05-28 - начат confirmation_flow и reserved/hold handler

- Продолжен behavior-preserving рефакторинг `message_handler.py` после пополнения OpenRouter tokens.
- Добавлен `app/services/dialog/confirmation_flow.py`.
- Вынесены confirmation/hold guards: `mentions_payment_status`, `wants_cancel_or_change_hold`, защита от ошибочного cancel/change при изменении имени/телефона/допов.
- Вынесен `awaiting_confirmation_side_reply`: info-вопрос на финальном подтверждении по-прежнему сначала отвечает deterministic knowledge, затем при необходимости использует AI через callback; клиентский текст не изменялся.
- Вынесены hold-summary helpers: название объекта резерва, сообщение об истекшем hold, поиск pending payment по hold ids и summary активных hold/booking.
- Вынесен `handle_reserved_hold_command` через `ReservedHoldCallbacks`: истекший резерв, повторная payment-ссылка, исправление деталей в резерве, cancel/reschedule с активными бронями и replacement-date flow теперь находятся в confirmation module, но side effects остаются callbacks из координатора.
- Вынесены `create_hold` и `create_booking_from_hold`; `message_handler.py` оставляет тонкие wrappers, чтобы сохранить трассировку и текущий контракт.
- `message_handler.py` уменьшился примерно до 4749 строк; `confirmation_flow.py` сейчас около 491 строки.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group payments --group post_booking --group cancel` OK; `local_regression_suite.py --group cancel --group reschedule` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py --group fresh --group gazebo --group services --group prices --group upsell` OK.
- Наблюдение: после пополнения tokens OpenRouter 402 в текущих прогонах не повторился; медленные AI-ветки всё ещё видны в timing logs, но функционально сценарии OK.

## 2026-05-28 - вынесены grouped/swap reschedule execution и availability_flow

- Продолжен аккуратный разрез `message_handler.py` без изменения AI-промптов и клиентской логики.
- Grouped/swap execution переноса вынесен в `app/services/dialog/reschedule_flow.py` через `execute_swap_reschedule` и `RescheduleExecutionCallbacks`: получение booking, удаление старой записи YCLIENTS, локальное обновление расписания, создание новой записи и восстановление при ошибке остаются под контролем callbacks из координатора.
- Добавлен `app/services/dialog/availability_flow.py`: туда вынесены deterministic helpers для availability-ответов, no-availability/waitlist, очистки слота, повторной даты, альтернатив на недоступную дату и поиска ближайших свободных дат через callbacks.
- `message_handler.py` оставлен координатором: он передает callbacks для `check_availability`, `_active_user_bookings` и side-effect операций, чтобы не менять источник свободности и тестовые monkeypatch.
- Исправлен порядок маршрутизации: явный запрос новой/дополнительной брони теперь обрабатывается до post-booking classifier, поэтому фраза `а можно еще беседку забронировать?` не уходит в старый post-booking сценарий.
- Добавлен синоним переноса `смест...`: фразы вроде `сместим баню на 26 июня` запускают перенос, а не новую анкету из-за слова `баня`.
- Добавлен deterministic short-circuit info-вопросов до тяжелого AI-вызова: известные вопросы по базе знаний/прайсу отвечают локально, а info-вопрос без активной анкеты больше не стартует бронь из-за слова услуги.
- Проверки: `compileall app scripts` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py --group fresh --group gazebo --group services --group prices --group upsell --group reschedule` OK; `local_regression_suite.py --group post_booking --group payments --group cancel` OK.
- Наблюдение: в stress-логах остаются OpenRouter 402 `Prompt tokens limit exceeded` на отдельных AI-ветках, но сценарии проходят за счет deterministic/fallback путей. Это отдельный infra/UX-риск: нужно пополнить/поднять лимит или еще сильнее сокращать router/post-booking prompts.

## 2026-05-27 - начат вынос reschedule_flow

- Добавлен `app/services/dialog/reschedule_flow.py`.
- Из `message_handler.py` вынесен первый behavior-preserving слой переноса: распознаватели `wants_reschedule/swap/multi`, options/confirmation тексты, swap assignment parsing, reference helpers `то же время/та же дата`, выбор брони для переноса, подготовка `form_data` для проверки свободности, фильтр вариантов беседок при переносе.
- Single reschedule execution тоже вынесен через `RescheduleExecutionCallbacks`: удаление старой YCLIENTS-записи, обновление booking/hold, создание новой YCLIENTS-записи, восстановление старой записи при ошибке и handoff при невозможности восстановления.
- Grouped/swap execution переноса пока намеренно оставлен в `message_handler.py`.
- Во время stress-suite пойман и исправлен рефакторинговый промах: `gazebo_capacity_by_title` используется не только reschedule-flow, но и обычным availability-ответом; добавлен alias из нового модуля обратно в `message_handler.py`.
- Проверки после helper-разреза: `compileall app scripts` OK; `local_regression_suite.py --group reschedule` OK; `--group post_booking --group cancel --group payments --group services` OK; `--group gazebo --group reschedule` OK; `scripts/dialog_stress_suite.py` 13/13 OK после фикса alias.
- Проверки после single execution-разреза: `compileall app scripts` OK; `local_regression_suite.py --group reschedule` OK; `--group gazebo --group post_booking --group payments --group cancel` OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Наблюдение: качество AI-диалога не менялось; длинные ответы в stress всё ещё приходятся на `ai.semantic` 4-10s.

## 2026-05-27 - вынесен cancel-flow execution

- Следующий безопасный разрез `message_handler.py` выполнен без изменения AI/prompts: исполнение отмены перенесено в `app/services/dialog/cancel_flow.py`.
- Добавлен `CancelFlowCallbacks`: модуль cancel-flow получает актуальные callbacks из `message_handler.py` для `active_user_bookings`, `delete_yclients_record_for_booking`, `bookings_repo`, `users_repo`, handoff и confirm-parsers.
- Старые `_start_cancel_booking_flow` и `_handle_cancel_booking_flow` в `message_handler.py` оставлены тонкими wrappers, поэтому monkeypatch/tracing вокруг удаления YCLIENTS и локальных операций сохранены.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group cancel` OK; `--group post_booking --group payments --group reschedule` OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Наблюдение: функционально cancel/post-booking/reschedule поведение не изменилось; stress-suite снова показывает отдельные медленные AI semantic ветки 5-13s, это остается UX-направлением, но не связано с разрезом.

## 2026-05-27 - начат безопасный вынос post_booking_flow

- Добавлен `app/services/dialog/post_booking_flow.py`.
- Из `message_handler.py` вынесены низкорисковые post-booking helpers: summary активных броней/hold-резервов, распознавание продолжения вопроса "и это всё?", waitlist-decline, простой ack после закрытой брони.
- Вынесен `payment_status_reply`, но через callbacks из `message_handler.py`, чтобы monkeypatch/tracing для `sync_payment_statuses` и `create_missing_yclients_records` не сломались.
- Вынесен safe wrapper post-booking classifier; настоящий AI-вызов по-прежнему идет через `message_handler.classify_post_booking_message`, поэтому качество/подмены AI не изменены.
- `message_handler.py` уменьшен примерно на 120 строк в этом разрезе; cancel/reschedule execution пока намеренно оставлен внутри координатора.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group post_booking` OK; `--group payments --group cancel` OK; `--group reschedule` OK; `--group fresh --group services --group prices --group upsell` OK; `dialog_stress_suite.py` 13/13 OK.
- Наблюдение: параллельный запуск двух `local_regression_suite.py` корректно остановился на lock-файле, это ожидаемая защита тестов.

## 2026-05-27 - hardened YooKassa webhook request handling

- Усилен локальный YooKassa webhook runner без изменения AI/dialog logic.
- Добавлен `YOOKASSA_WEBHOOK_MAX_BODY_BYTES` с дефолтом `32768`.
- В production (`APP_ENV=production/prod`) webhook теперь fail-fast требует `YOOKASSA_WEBHOOK_SECRET`.
- POST webhook проверяет путь, secret через constant-time compare, обязательный `Content-Length`, пустое/неполное/слишком большое тело и JSON-object payload.
- Добавлен smoke `scripts/yookassa_webhook_hardening_smoke.py`: проверяет health GET, запрет без secret, happy path через заглушки, лимит body и bad path.
- Проверки: `compileall app scripts` OK; `scripts/yookassa_webhook_hardening_smoke.py` OK; `scripts/local_regression_suite.py --group payments --group post_booking` OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- YCLIENTS sync перед проверкой был старше strict-лимита, потому что основной bot process не запущен; выполнен `scripts/sync_yclients_records.py --once`, после чего `scripts/yclients_sync_status.py --strict` OK.

## 2026-05-27 - production hardening holds/payment/sync

- В `slot_holds` добавлен `yclients_staff_id`; схема получила partial unique index `idx_slot_holds_unique_active_resource_day` для активного резерва одного ресурса на дату.
- `slot_holds_repo.create` теперь ставит transaction advisory lock, истекает старые holds через DB time и через savepoint превращает уникальный конфликт в `SlotHoldConflict`.
- Confirmation-flow при конфликте hold не создает ссылку оплаты, а просит выбрать другое время/дату и сохраняет waitlist-запрос.
- `payment_service.create_payment_link_for_holds` переведен на payment-intent flow: локальный pending payment с `hold_ids` коммитится до вызова ЮKassa; повторный запрос переиспользует активную pending-ссылку; provider failure сохраняет `failed`.
- `yclients_sync_service` разделен на `fetch_records` без DB transaction и короткий `apply_records`; runner и `scripts/sync_yclients_records.py --once` используют двухфазный путь.
- Retention изменен с 72 на 48 часов: `MESSAGE_SUMMARY_AFTER_HOURS=48` в config, `.env.example` и локальном `.env`.
- DB connection стал устойчивее к закрытым pooled connections: rollback пропускается, если connection уже закрыт, а checkout отбрасывает closed connection.
- Удалены runtime-артефакты `recovered_pyc/`.
- Проверки: `compileall app scripts` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py` группы `payments`, `post_booking`, `upsell`, `prices`, `fresh`, `gazebo`, `services`, `time`, `cancel`, `reschedule` OK; `scripts/sync_yclients_records.py --once` OK; `scripts/yclients_sync_status.py --strict` OK.
- Наблюдение: один длинный stress-сценарий занял около 36s, основной вклад `ai.semantic`; функционально OK, но скорость AI остается UX-риском.

## 2026-05-26 - создана project memory

- Создана структура Obsidian-памяти `best2obs/`.
- Добавлен `AGENTS.md` с правилами работы для будущих задач.
- Проведен первичный анализ проекта без изменения production-кода.
- Зафиксированы основные модули: Telegram adapter, AI orchestration, booking state machine, availability, YCLIENTS sync, ЮKassa payment flow, media/photo sending, voice transcription, message retention.
- Созданы стартовые страницы по архитектуре, рискам, pre-launch задачам и workflow-командам.

## 2026-05-26 - принят LLM Wiki подход

- Пользователь прислал идею LLM Wiki как паттерн долговременной базы знаний.
- Решено применять этот подход к `best2obs/`: wiki должна быть постоянным, накапливающимся артефактом, а не разовыми заметками.
- Обновлен `AGENTS.md`: добавлены слои Raw sources / Wiki / Schema и операции Ingest / Query / Lint.
- Добавлены страницы [[prompts/llm-wiki-method]] и [[decisions/2026-05-26-use-llm-wiki]].

## 2026-05-26 - самостоятельная проверка сценариев

- Выполнены быстрые технические проверки: compileall, validate_yclients_map, db_status.
- Прогнан точечный срез из 23 сценариев regression suite: все проверки OK.
- Полный `local_regression_suite.py` остановлен из-за зависания на `free_dates_lookup`; это записано как риск тестовой инфраструктуры.
- Подробный отчет: [[daily/2026-05-26-scenario-check]].

## 2026-05-26 - исправлены свежие сбои диалога

- Исправлен `stale_form_flow`: ответ "давайте" теперь продолжает старую анкету, а явный запрос новой услуги/свободных дат после паузы начинает чистый контекст с сохранением имени и телефона.
- Добавлен прямой маршрут для вопросов "какие ближайшие свободные даты..." в обычной анкете: backend идет в локальную таблицу записей через availability, а не просит клиента назвать дату.
- Вопросы о цене допов в контексте upsell теперь отвечают прайсом допов, а не базовой стоимостью бани/услуги.
- Информационные вопросы на финальном подтверждении больше не проходят через post-booking classifier.
- Post-booking больше не запускает синхронизацию ЮKassa/YCLIENTS на каждое сообщение, если у разговора нет локальных платежей.
- Добавлены регрессионные проверки для свежих кейсов и стабилизирован cleanup тестовых данных.

## 2026-05-26 - начат рефакторинг message_handler

- Создан пакет `app/services/dialog/`.
- Вынесены `formatting.py`, `price_info.py`, `stale_form.py`, `routing_guards.py`.
- `message_handler.py` пока остается главным координатором, но часть форматирования, цен/допов, stale-form и routing guard логики вынесена в отдельные модули.
- Поведение сохранено через старые приватные алиасы/обертки, чтобы не ломать существующие тесты и вызовы.
- Пройдены `compileall` и точечные регрессии по price/info, stale-form и free-dates.

## 2026-05-26 - продолжен рефакторинг message_handler

- Добавлен `app/services/dialog/booking_texts.py`: шаблоны handoff-ответа, подтверждения заявки, сводки hold/booking, ссылки оплаты и короткой строки брони.
- Добавлен `app/services/dialog/handoff.py`: проверка активного handoff, распознавание конфликтных сообщений и создание handoff-лога для команды.
- Удалены дублирующие реализации из `message_handler.py`; старые приватные имена сохранены как импортированные алиасы.
- Пройдены `compileall` и точечные регрессии: confirmation info, post-booking fallback, booking summary, shared phone, handoff/location, price/upsell, stale-form/free-dates.

## 2026-05-26 - исправлено наследование старой анкеты при новой услуге

- Исправлена политика fresh-start: простая фраза клиента вроде "хочу баню" теперь может начать новую анкету, если в текущей анкете была другая услуга.
- Старые поля `date`, `time`, `duration`, `guests_count`, `event_format`, `upsell_items`, `service_variant` не переносятся в новую услугу; имя и телефон сохраняются.
- Добавлен `app/services/dialog/fresh_start.py`, чтобы решение о сбросе анкеты было отдельной backend-политикой, а не рассеянными условиями внутри `message_handler.py`.
- Добавлена регрессия `plain new service request resets old form`.
- Пройдены `compileall` и точечные регрессии по second booking, stale-form, fresh free-dates и price/upsell.

## 2026-05-26 - вынесен контекст актуальных броней

- Добавлен `app/services/dialog/booking_context.py`.
- Из `message_handler.py` вынесены: получение активных броней пользователя, fallback на брони текущего conversation, сверка с `yclients_records`/busy intervals, фильтрация удаленных записей журнала, summary-контекст для AI.
- Это закрепляет правило: вопросы "какие у меня брони" и post-booking summary должны идти по актуальным данным таблиц/журнала, а не по старой `form_data`.
- Пройдены `compileall` и точечные регрессии: booking summary counts all bookings, post booking summary always uses db, shared phone, old user booking/summary, second booking reset, plain new service reset, stale free dates.

## 2026-05-26 - вынесены парсеры дат и времени

- Добавлен `app/services/dialog/date_parsing.py`: относительные даты, голые дни месяца, неоднозначные будни, даты в сегментах переноса и "с 25 на 26".
- Добавлен `app/services/dialog/time_parsing.py`: периоды "с 18 до 00", одиночное время, "до утра", дефолтная длительность беседки до 08:00, явная длительность и конфликт периода/длительности.
- `message_handler.py` использует эти функции через старые приватные алиасы, чтобы не ломать существующие тесты.
- Пройдены `compileall` и точечные регрессии по датам, переносам, длительности, open-ended беседкам, time correction и fresh-start.

## 2026-05-26 - вынесена чистая логика подбора беседок

- Добавлен `app/services/dialog/gazebo_options.py`.
- Вынесены: текст выбора беседки, нормализация названий, память о последних свободных вариантах, фильтр по вместимости, авто-выбор единственной свободной беседки, форматирование строки варианта, выбор конфигурации услуги.
- I/O-часть с `check_availability` и ближайшими датами пока оставлена в `message_handler.py`, чтобы не смешивать чистый подбор с доступом к БД.
- Пройдены `compileall` и точечные регрессии по беседкам: only available variants, capacity filter, date reply asks guests, next free dates by guests, single auto-select, no guessed variant, selected capacity known free list, reschedule preferences.

## 2026-05-26 - полный regression suite снова завис по времени

- После рефакторинга был запущен полный `scripts/local_regression_suite.py` с лимитом 15 минут.
- Прогон не завершился до таймаута; фоновых Python-процессов после остановки не осталось.
- Добавлена печать прогресса после каждого check в `local_regression_suite.py`, чтобы при ручном запуске было видно, где suite находится.
- Повторные запуски с лимитами 5 и 2 минуты тоже не завершились; в автоматическом tool timeout частичный stdout не виден, но в обычном терминале прогресс должен печататься.
- Вывод: текущий полный suite нужно дробить на группы или добавить per-test timeout. До этого опираться на точечные регрессии по затронутым зонам.

## 2026-05-26 - regression suite разбит на группы и исправлен semantic reschedule

- В `scripts/local_regression_suite.py` добавлен `--group`: `fresh`, `payments`, `post_booking`, `services`, `dates`, `time`, `gazebo`, `media`, `upsell`, `prices`, `waitlist`, `handoff`, `reschedule`, `cancel`, `reminder`.
- Прогресс по каждому check печатается сразу, поэтому долгие прогоны теперь диагностируются без ожидания конца всего suite.
- Найден и исправлен сбой: фраза вроде "давайте сместим баню на 26 июня" в post-booking могла стартовать новую анкету из-за service keyword раньше, чем AI-classifier успевал вернуть `change_type=reschedule`.
- Порядок маршрутизации в `message_handler.py` изменён: reserved-hold команды сохраняют приоритет, затем post-booking/AI change flow, и только потом fresh-start новой анкеты.
- Пройдены группы: `fresh`, `dates`, `prices`, `upsell`, `time`, `gazebo`, `media`, `payments`, `post_booking`, `services`, `waitlist`, `handoff`, `reminder`, `reschedule`, `cancel`.
- Полный suite без `--group` всё ещё может быть слишком долгим; для ежедневной проверки использовать группы.

## 2026-05-26 - вынесена детерминированная логика отмены

- Добавлен `app/services/dialog/cancel_flow.py`.
- Из `message_handler.py` вынесены: распознавание намерения отмены, отмена всех броней, выбор отменяемой брони по номеру/типу/дате/варианту, тексты подтверждения и успешной отмены.
- Исполнение отмены осталось в `message_handler.py`: удаление записи YCLIENTS, обновление booking status и handoff при технической ошибке.
- Усилен cleanup regression suite: после прерванных прогонов тестовые зависимости удаляются не только по заранее выбранным conversation id, но и через join по `local_regression_%`.
- В regression suite добавлена печать длительности каждого check: формат `OK [29.4s]: ...`.
- Проверки: `compileall app scripts`, `local_regression_suite.py --group dates`, `local_regression_suite.py --group cancel`; reschedule-проверки пройдены точечно по всем сценариям группы.
- Наблюдение: группа `reschedule` целиком может превышать 10 минут из-за тяжелых fixture/DB-проходов; логика зелёная, но тестовую инфраструктуру стоит дальше ускорять или дробить.

## 2026-05-26 - ускорен semantic-router и стабилизированы fallback-ответы

- Добавлен `app/services/dialog/semantic_router.py`: основной AI-проход теперь получает компактный router-context с картой услуг и текущей анкетой, а не всю базу знаний.
- Полная база знаний остается для настоящих info-ответов и post-booking classifier; обычные шаги анкеты должны делать меньше токенов и меньше задержек.
- Добавлен `app/services/dialog/performance.py` и трассировка `handle_incoming`: в логах видны `total_s`, `db.connect`, `db.work`, `ai.semantic`, `ai.response`, `ai.post_booking`, availability/payment/YCLIENTS/media этапы.
- Добавлен `app/services/dialog/response_builder.py`: готовые клиентские тексты возвращаются без второго AI-вызова, а внутренние инструкции не должны уходить клиенту.
- Исправлен опасный fallback: если AI-генератор возвращает служебную инструкцию вроде "Начни без приветствия..." или падает, backend заменяет ее безопасным шаблонным вопросом.
- `availability_service.check_availability` переведен на локальные таблицы `yclients_records`/`resource_busy_intervals` как источник свободности в диалоге; прямой live fallback в YCLIENTS убран из клиентского ответа.
- Исправлена формулировка для комбинированной заявки "беседка + баня": бот стартует с беседки и пишет, что баню оформим второй отдельной бронью после беседки.
- Проверки: `compileall app scripts`, группы `prices+upsell+time`, `fresh`, `dates`, `gazebo+media`, `services`, `cancel+reschedule`, `payments+post_booking+waitlist+handoff+reminder`.
- Наблюдение по скорости: после трассировки самые длинные локальные регрессии чаще упираются в `db.connect`/`db.work`; иногда `ai.post_booking` занимает 3-5 секунд.

## 2026-05-26 - исправлены свежие сбои по телефону, бане и контексту второй услуги

- Невалидный телефон теперь отвечает готовым клиентским шаблоном без AI, чтобы внутренние инструкции вроде "попроси клиента" не попадали в Telegram.
- Уведомление админу по новой заявке теперь показывает конкретный объект: например `Беседка №8 (Беседка)`, а не только общий тип услуги.
- Правило open-ended периода "до утра / как пойдет / посмотрим" обобщено на баню и дом: при старте в 12:00 длительность считается до 08:00 следующего утра.
- Фразы вроде "на то же время что и беседка" в анкете бани больше не переключают текущую услугу на беседку: backend берет время/длительность из активной брони беседки и сохраняет текущий `service_type`.
- Добавлен abort-flow для незавершенной анкеты: "не хочу бронировать ее / передумал / не надо" очищает черновик, но сохраняет имя и телефон; оплаченные брони этим не отменяются.
- Добавлен connection pool PostgreSQL (`DB_POOL_ENABLED`, `DB_POOL_MIN`, `DB_POOL_MAX`), потому что трассировка показала заметные задержки на `db.connect` к удаленной БД.
- Добавлены регрессии: client-safe phone, admin object title, bathhouse open-ended until morning, second service same-time reference, abort current draft.
- Проверки: `.venv\Scripts\python.exe -m compileall app scripts`; `local_regression_suite.py` по группам `fresh+time+services+post_booking` и затем `dates+gazebo+media+waitlist+handoff+prices+upsell+payments+cancel+reschedule+reminder` - все OK.
- Наблюдение: `local_regression_suite.py` нельзя запускать параллельно двумя процессами, потому что cleanup использует общий префикс `local_regression_%` и процессы могут удалять данные друг друга.

## 2026-05-27 - стабилизированы формат анкеты, info-вопросы и правило аванса

- Исправлено принятие `event_format`: AI может заполнить формат с опечаткой клиента вроде "просто отдыз", но не может выдумать формат, если текущий шаг другой.
- Info-вопросы больше не должны добавлять старый вопрос анкеты: цена решетки на шаге допов остается на допах и не возвращает вопрос про формат.
- Добавлен reference-resolver для "та же дата / тот же день" по аналогии с "то же время": вторая услуга сохраняет свой `service_type`, а дату/время берет из актуальной брони.
- Тексты отмены оплаченной брони теперь учитывают правило 7 дней: за 7+ дней аванс можно вернуть по правилам отмены, ближе к дате аванс не возвращается.
- Добавлена память решений: [[decisions/2026-05-27-dialog-state-policy]] и [[roadmap/dialog-regression-scenarios]].
- Добавлены регрессии: event format typo, addon price during upsell, same date reference, brooms info without form, cancel refund window.
- Завершена проверка плана: прошли `compileall app scripts`, группы `post_booking+reschedule`, затем `fresh+dates+gazebo+media+prices+upsell+time+payments+services+waitlist+handoff+reminder+cancel`.
- Отполирован текст успешной отмены: строка про аванс теперь начинается с заглавной буквы в финальном клиентском сообщении.

## 2026-05-27 - продолжен рефакторинг message_handler

- Добавлен `app/services/dialog/form_patches.py`.
- Из `message_handler.py` вынесены чистые patch-парсеры анкеты: тип услуги, вариант беседки, телефон, формат отдыха, допы, гости, имя, reference-фразы "та же дата/то же время" и нормализация service aliases.
- Добавлен `app/services/dialog/form_corrections.py`.
- Из `message_handler.py` вынесены распознавание исправления имени и текст подтверждения исправленных полей.
- Старые приватные имена в `message_handler.py` сохранены как импортированные алиасы, поэтому существующие тесты и внутренние вызовы продолжают работать.
- Размер `message_handler.py` уменьшен до 5672 строк; следующий крупный кандидат на вынос - `reschedule_flow` и availability-ответы.
- Проверки: `compileall app scripts`; regression groups `fresh`, `prices`, `upsell`, `services`, `time`, `dates`, `post_booking`, `reschedule`; затем `fresh`, `prices`, `upsell`, `reschedule` после второго выноса.
- Дополнительно после выноса service/variant-парсеров пройдены группы `gazebo`, `media`, `payments`, `waitlist`, `handoff`, `reminder`, `cancel`.

## 2026-05-27 - исправлены живые сбои "подешевле" и неформальный отказ от допов

- По последнему живому диалогу найдено: таблица `messages` и semantic-router работают, но backend guards были слишком узкими и не принимали живые ответы клиента как смысловые ответы на текущий шаг.
- Фраза `а мне нужно что нибудь подешелве` на выборе беседки теперь распознается как просьба помочь с бюджетным вариантом. Backend берёт уже проверенные свободные варианты из локальной БД/`form_data`, фильтрует по вместимости и цене и не повторяет весь список.
- Неформальные отказы от допов (`неа`, `нте`, `нет же говорю`, `ytn`) теперь считаются отказом по смыслу. Первый отказ запускает второй мягкий продающий заход, второй отказ закрывает допы как `["не нужны"]`.
- Вопрос имени в анкете заменён на более нейтральный `На какое имя записать бронь?`, чтобы повторная бронь не выглядела так, будто бот забыл клиента.
- Semantic-router и системный промпт усилены: сначала определять крупную ветку (`info`, `check_availability`, `booking_form`, `post_booking`, `other`), а затем backend валидирует факты, доступность и состояние.
- Добавлены регрессии: `gazebo budget preference filters cheapest`, `gazebo budget preference during choice`, `informal upsell no uses two-touch flow`.
- Проверки: `compileall app scripts`; группы `gazebo`, `upsell`, затем `fresh+services+prices`, затем `time+payments+post_booking+waitlist+handoff+media+cancel+reschedule+reminder` - все OK.

## 2026-05-27 - добавлен stress-suite нестандартных диалогов

- Добавлен `scripts/dialog_stress_suite.py`: отдельный диагностический suite с живыми кривыми формулировками клиента, печатью USER/BOT transcript и проверкой state-инвариантов.
- Stress-suite сначала нашел реальные слабые места: `по чем/решотка`, `3й беседки`, `баню убери, беседку не трогай`, `сдвинем на денек позже`, `тем же днем`, `как там же, без изменений`, `забей, не оформляем`.
- Исправлены guards и patch-парсеры в `price_info.py`, `form_patches.py`, `cancel_flow.py`, `media_service.py`, `message_handler.py`.
- Новые проверенные сценарии: бюджетный подбор, два касания допов, цена допов без автодобавления, вторая услуга со ссылкой на прошлую бронь, список броней нестандартной фразой, выборочная отмена, перенос живой фразой, info без анкеты, abort черновика, явный запрос фото.
- Проверки: `compileall app scripts`; `scripts/dialog_stress_suite.py` - 10/10 OK; затем затронутые группы `prices+upsell+media+post_booking+cancel+reschedule+services` - все OK.
- После всех фиксов дополнительно пройден полный grouped suite: `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - все OK.
- Наблюдение: функционально сценарии прошли, но отдельные AI-ветки остаются медленными. В логах встречались ответы 8-15 секунд на cancel/reschedule и info/post-booking сценарии. Иногда AI всё ещё возвращает внутреннюю инструкцию, но guard/fallback перехватывает это и клиенту уходит безопасный текст.

## 2026-05-27 - исправлены info-вопросы внутри активной анкеты

- По живому диалогу найден сбой: во время анкеты бани вопрос `а если нас будет 30 человек` мог переключить ответ в контекст беседок и затем дважды повторить вопрос времени.
- Изменено правило info-сообщений: если semantic-router определил `answer_info`, backend не применяет `service_type/date/time/duration/guests_count` из AI как изменение анкеты. Информационный вопрос теперь отвечает в текущем контексте, а состояние анкеты меняется только на настоящих ответах клиента.
- Добавлен контекстный ответ по вместимости: для бани на 30 человек бот объясняет, что баня не лучший основной формат для такой компании, предлагает Беседку №1/тёплую беседку и сохраняет текущую услугу `bathhouse`.
- Добавлен pause-flow для фраз вроде `ну хз, я позже вам напишу`: бот сохраняет черновик и не добавляет следующий вопрос анкеты.
- Усилен дедупликатор продолжения анкеты: если ответ уже содержит вопрос про время или длительность, `Продолжим оформление` не добавляется повторно.
- Добавлены регрессии: `info during bath form keeps service context`, `later pause during form does not repeat question`; `scripts/dialog_stress_suite.py` расширен до 11 сценариев.
- Проверки: `compileall app scripts`; группы `fresh+prices`; `scripts/dialog_stress_suite.py` - 11/11 OK; группы `services+upsell+gazebo+post_booking+reschedule+media`; полный grouped suite `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - все OK.

## 2026-05-27 - добиты живые ошибки по выбору беседки, допам и отмене

- Добавлены защиты для сценария `29 мая 6 беседка`: если клиент выбрал конкретную беседку без количества гостей, backend сначала спрашивает гостей и проверяет вместимость, а не переходит ко времени.
- Фраза `а если нас будет 15 человек` теперь рассматривается как обновление `guests_count`; бот не должен повторно спрашивать количество гостей.
- Номер беседки в фразах вроде `хорошо, 4 беседка` не должен парситься как время `04:00`.
- Вопрос `А какие цены на допы` должен сразу отвечать прайсом допов, не зависать на "сейчас расскажу" и не сохраняться как `client_name`.
- Подтверждение `дя` добавлено в confirm-flow как допустимая опечатка `да`.
- После успешной отмены простое `окей/спасибо` больше не должно запускать текст "бронь зафиксирована".
- Добавлены regression checks: `forced gazebo variant asks guests before time`, `gazebo capacity question sets guests and skips repeat`, `gazebo variant change is not parsed as time`, `addon prices plural question replies immediately`, `paid cancel typo dya confirms`, `ack after cancel does not say booking fixed`.
- `scripts/dialog_stress_suite.py` расширен сценарием с выбором беседки, изменением гостей, вопросом о допах и отменой через `дя`.
- Проверки: `compileall app scripts` прошел. Повторный stress/regression запуск был заблокирован внешним PostgreSQL timeout: один прямой коннект после восстановления прошел за ~1 секунду, но затем новые процессы снова получали `timeout expired` на `luecahalemas.beget.app:5432`. TCP-порт доступен, SSL-варианты дают тот же timeout, поэтому тесты нужно повторить после стабилизации БД.

## 2026-05-27 - БД восстановилась, нестандартные тесты пройдены

- `scripts/db_status.py` успешно прочитал БД: таблицы `users`, `conversations`, `messages`, `slot_holds`, `bookings`, `yclients_records`, `resource_busy_intervals` доступны.
- Пройден `scripts/dialog_stress_suite.py`: 12/12 OK.
- В stress-suite проверены нестандартные живые сценарии: бюджетный подбор беседки с опечаткой, два касания допов с живыми отказами, вопрос цены допов без автодобавления, вторая услуга со ссылкой на дату/время беседки, странный вопрос "что на мне висит", выборочная отмена, перенос "на денек позже", info-вопросы без анкеты, abort черновика, явный запрос фото, принудительный выбор беседки без гостей, `дя` как подтверждение отмены.
- Пройдены затронутые regression-группы: `gazebo`, `upsell`, `prices`, `cancel`, `post_booking`, `services`, `reschedule`, `fresh` - все checks OK.
- Наблюдение по скорости: функционально тесты прошли, но отдельные AI-ветки всё ещё дают 4-7 секунд (`ai.semantic`/`ai.post_booking`). Это не блокер для релиза, но остается направлением оптимизации.

## 2026-05-27 - закрыт план по последним сценариям, hold и актуальности записей

- Исправлен парсинг живых фраз: `15-17 человек/гостей/чел` больше не превращается во время, а сохраняется как количество гостей с верхней границей для проверки вместимости; `в 3 часа дня`, `к 3 дня`, `в 3 чиса дня` распознаются как `15:00`; `с 3 дня до 11 ночи` дает период `15:00-23:00`.
- Для больших компаний усилен подбор беседок: при `20+` гостях `Беседка №1` ранжируется первой как комфортный просторный вариант, дальше идут остальные подходящие свободные варианты по вместимости/цене.
- Проверка свободности использует локальные `yclients_records`/`resource_busy_intervals`, но теперь учитывает свежесть sync-state; после YCLIENTS sync и создания/удаления записей очищается availability-cache, чтобы бот не отвечал старыми данными.
- Резерв оплаты стал строгим: после 10 минут hold переводится в `expired`, клиент получает сообщение о снятии резерва, повторная ссылка не создается поверх активного hold, поздняя оплата по старой ссылке не подтверждает бронь автоматически.
- Готовые ответы по цене и допам обогащены данными из базы знаний: прайс беседок без выбранного варианта показывает таблицу, вопросы цены допов остаются на шаге допов и не добавляют товар автоматически, upsell-сообщения получили несколько продающих вариантов с эмодзи.
- Добавлен `scripts/cleanup_yclients_test_records.py`: сначала dry-run кандидатов, затем удаление только bot-created/Telegram-created тестовых записей по явным признакам. По текущей чистке найдены и удалены 2 тестовые записи Telegram с телефоном `+79968533502`; финальный dry-run `--all-bot-bookings` показывает 0 кандидатов.
- После чистки выполнен YCLIENTS sync: локальная таблица записей обновлена, `records_seen=121`, `last_error=None`.
- Проверки: `compileall app scripts`; `scripts/dialog_stress_suite.py` - 12/12 OK; полный grouped suite `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - все checks OK; targeted groups `time+gazebo+payments`, `prices+upsell` - OK.
- Остаточный риск: отдельные AI-ветки в тестах всё ещё могут занимать 8-20 секунд на сложных info/post-booking/cancel/reschedule сценариях. Функционально сценарии проходят, но оптимизация скорости остается следующим UX-направлением.

## 2026-05-27 - подготовлена чистая БД для нового live-теста

- По просьбе очищен диалоговый слой: `users`, `conversations`, `messages`.
- Из-за FK-зависимостей также очищены связанные локальные сущности тестового диалога: `conversation_summaries`, `slot_holds`, `payments`, `bookings`, `waitlist_requests`, `system_logs`.
- Таблицы YCLIENTS-кеша не очищались полностью: `yclients_records` и `resource_busy_intervals` сохранены как источник свободности.
- После очистки обнаружены старые локальные интервалы `resource_busy_intervals.source='bot_booking'`, которые могли ложно блокировать свободность; удалено 54 таких интервала. Остались только интервалы `source='yclients'`.
- Выполнен YCLIENTS sync перед тестом: `records_seen=121`, `records_upserted=121`, `last_error=None`.
- Финальные счетчики для старта теста: `users=0`, `conversations=0`, `messages=0`, `slot_holds=0`, `payments=0`, `bookings=0`, `waitlist_requests=0`; `resource_busy_intervals=127` только из YCLIENTS, `yclients_records=126`.

## 2026-05-27 - исправлена память черновика после возврата от дома к беседке

- По live-чату найден новый класс сбоя: клиент сначала обсуждал беседку на 20 гостей на 2 июня, потом спросил гостевой дом на ту же дату, затем вернулся фразой `лан давайте беседку же выбираю перую беседку`. Бот мог ошибочно стартовать "вторую бронь", забыть дату/гостей и повторно спросить уже выбранную беседку.
- Добавлен guard продолжения текущего черновика при смене услуги обратно к ранее обсуждаемой: дата, гости, время, длительность и доступные варианты восстанавливаются из текущего `form_data`/`last_unavailable`, если клиент явно продолжает тот же сценарий, а не начинает новую бронь.
- Расширено распознавание варианта беседки: опечатки `перую`, `перву`, `первой` трактуются как `Беседка №1`, если контекст уже про выбор беседки.
- Добавлен draft-summary для вопросов вроде `а первая бронь какая?`: если оплаченной брони еще нет, бот не противоречит себе, а показывает текущую собираемую заявку и следующий недостающий шаг.
- Если гостевой дом/баня/теплая беседка недоступны на выбранную дату, бот теперь предлагает альтернативные свободные услуги на эту же дату, прежде всего подходящие беседки по вместимости, а не только пишет waitlist.
- Фраза `у нас просто праздник` после недоступного дома теперь используется как повод предложить альтернативы на ту же дату, а не снова просить дату.
- `ну нет`, `да нет` и близкие живые отказы добавлены в upsell negative parser: первый отказ по допам снова запускает мягкий продающий повтор, второй закрывает допы.
- Вопрос про длительность/часы в контексте беседки теперь не уходит в цену гостевого дома: готовый ответ объясняет, что у беседок стоимость зависит от конкретного объекта/периода, а не от "доплаты за каждый час".
- Шаблон подтверждения заявки обновлен: финальный вопрос теперь явный `Всё верно? Подтверждаете бронь?`, с прежней структурой и эмодзи.
- База знаний проверена через `load_knowledge()`: загружается `client_runtime.md`, ключевые факты про комаров/обработку, веники/штраф, предоплату, допы, парковку и адрес присутствуют.
- Проверки: `compileall app scripts`; полный grouped suite `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - все checks OK; `scripts/dialog_stress_suite.py` - 12/12 OK.

## 2026-05-27 - проведен senior project review

- Проведен обзор структуры, wiki, core services, DB schema, YCLIENTS/ЮKassa integrations, regression scripts и текущих known issues без изменения production-кода.
- Итоговая оценка проекта: 7/10. Сильные стороны: рабочая доменная модель, много регрессий, принцип "AI понимает, backend валидирует", LLM Wiki, fallback от внутренних AI-инструкций.
- Главные найденные риски: `message_handler.py` около 6000 строк; нет DB-level атомарности active hold; платеж ЮKassa создается внутри открытой transaction; YCLIENTS sync держит transaction во время сетевой загрузки; regression scripts нельзя запускать параллельно; webhook требует production-обвязки.
- Проверки: `compileall app scripts` - OK; `scripts/db_status.py` - OK; `scripts/local_regression_suite.py --group fresh --group payments` - OK; `scripts/validate_yclients_map.py` получил timeout 124s; `scripts/dialog_stress_suite.py` функционально дошел до конца, но cleanup упал из-за параллельного запуска с local regression, после чего штатный `_cleanup()` выполнен успешно.
- Подробный отчет: [[daily/2026-05-27-project-review]].

## 2026-05-27 - исправлены duration, mixed-upsell и диагностика sync

- Добавлена нормализация `duration` в `booking_form_service.merge_form_data` и `dialog/time_parsing.py`: строки вроде `8 часов`, `8 ч`, `8.5 часа` приводятся к числу часов, некорректные строки очищаются.
- Парсер времени теперь понимает свободную фразу `после обеда, к 3 дня и до 11 ночи` как `15:00` и длительность `8`.
- Mixed upsell-сообщение вида `а вода и лед сколько стоят? если можно, добавьте воду и лед` теперь одновременно отвечает по цене и сохраняет выбранные допы.
- Runtime-база знаний `app/knowledge/client_runtime.md` дополнена фактами про детей, животных, парковку, вместимость “впритык” и свои стулья/лавки.
- Добавлен `scripts/yclients_sync_status.py` для диагностики свежести YCLIENTS sync-state.
- `local_regression_suite.py` и `dialog_stress_suite.py` получили lock-файл, чтобы параллельные прогоны не ломали cleanup друг друга.
- Проверено: `compileall app scripts` - OK; `scripts/db_status.py` - OK; `scripts/sync_yclients_records.py --once` - OK; `scripts/yclients_sync_status.py --strict` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; `local_regression_suite.py --group time --group upsell --group prices` - OK; `local_regression_suite.py --group gazebo --group services --group post_booking --group cancel --group reschedule --group fresh --group payments` - OK.
- YCLIENTS sync после тестов свежий: `records_seen=122`, `records_upserted=122`, `last_error=None`.

## 2026-05-28 - продолжен разрез message_handler: swap-reschedule и availability execution

- `message_handler.py` уменьшен до ~4492 строк без изменения внешнего поведения.
- В `app/services/dialog/reschedule_flow.py` вынесены grouped/swap reschedule orchestration helpers: `start_swap_reschedule_flow`, `handle_swap_reschedule_flow`, `prepare_swap_reschedule`; `message_handler.py` оставил тонкие wrappers через `SwapRescheduleCallbacks`.
- В `reschedule_flow.py` также вынесен подбор новой беседки при переносе: `reschedule_gazebo_change_options_reply`.
- В `app/services/dialog/availability_flow.py` добавлен общий `execute_availability_check` с callbacks: одна точка для проверки локальной свободности, альтернатив, waitlist/no-availability и стандартного availability reply.
- Основная AI-ветка, fallback при недоступности AI и общий exception fallback теперь используют единый availability executor; fast-entry availability тоже переведен на него без waitlist side-effect.
- Проверки после разрезов: `compileall app scripts` - OK; `local_regression_suite.py --group reschedule` - OK; `local_regression_suite.py --group fresh --group gazebo --group waitlist --group services` - OK; `local_regression_suite.py --group prices --group upsell --group payments --group post_booking --group cancel --group reschedule` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; `local_regression_suite.py --group dates --group media --group time --group handoff --group reminder` - OK.
- Наблюдение: slow timing остался только на отдельных AI semantic ветках примерно 5-8 секунд; это не новая регрессия от рефакторинга.

## 2026-05-28 - разобран live-чат после теста Telegram

- По последнему live-чату найдено несколько user-facing ошибок, важнее дальнейшего рефакторинга: баня была предложена только с 6 августа, хотя текущая локальная availability-таблица после свежего sync показывает свободность 28 мая, 29 мая, 1 июня и дальше; вероятный класс бага - stale/free-dates glue, где старые `date`/`last_unavailable`/`last_suggested_free_dates` сдвигают старт поиска после явного `начнем новую`.
- В локальной таблице `resource_busy_intervals` обнаружены 46 `bot_booking` интервалов для бани 24 июня; это не объясняет августовский ответ напрямую, но нарушает ожидание чистой availability-таблицы после live-подготовки.
- Подтверждены диалоговые баги: бюджетный подбор беседки задает два вопроса в одном ответе; mixed selection+info (`четвертую / а с детьми можно?`) не закрепляет выбранную беседку; `я же говорил 10` после вопроса о гостях может парситься как время; короткий ack после pause возвращает upsell-вопрос.
- Решение на ближайший шаг: временно остановить behavior-preserving refactor и сначала закрыть эти живые регрессии с точечными regression/stress сценариями.

## 2026-05-28 - исправлены live-dialog баги перед продолжением рефакторинга

- Закрыт риск `начнем новую / какие ближайшие свободные даты для бани?`: ветка `awaiting_new_date`/`last_unavailable` больше не перехватывает явный запрос новой анкеты, direct free-dates запускается с чистого контекста и ищет от текущей даты.
- Бюджетный подбор беседки без выбранной даты стал deterministic: для `10 челов / что дешевле` бот сохраняет `guests_count=10`, показывает недорогие подходящие варианты как ориентир по цене и задаёт один следующий вопрос - дату для проверки журнала. Без выбранной даты он больше не пишет `из свободных`.
- Mixed selection+info исправлен: фраза `четвертую / а с детьми можно?` в контексте беседок сохраняет `Беседка №4`, отвечает по детям из базы знаний и задаёт следующий один вопрос по анкете.
- Expected-step parsing усилен: если текущий/следующий шаг явно `guests_count`, фразы вроде `я же говорил 10` обновляют гостей и не превращаются в `10:00`/длительность до утра.
- После pause-flow короткий ack вроде `кайф` больше не возвращает клиента к upsell-вопросу; бот оставляет черновик на паузе.
- Regression cleanup теперь удаляет orphan `resource_busy_intervals.source='bot_booking'`, не связанные с локальными bookings. После прогона orphan-интервалов 0, в `resource_busy_intervals` остался только `source='yclients'`.
- Выполнен ручной `scripts/sync_yclients_records.py --once`; `scripts/yclients_sync_status.py --strict` свежий (`records_seen=120`, `last_error=None`). Текущая проверка бани: 28 мая, 29 мая и 1 июня свободны; 30 мая закрыта записью.
- Проверки: `compileall app scripts`; regression groups `dates`, `gazebo`, `time`, `fresh`, `upsell+prices+services`, `post_booking+payments+cancel+reschedule`; `scripts/dialog_stress_suite.py` - 13/13 OK.

## 2026-05-28 - проведены сценарные тесты live-диалога и переноса

- Прогнан полный `scripts/local_regression_suite.py` после live-фиксов: все checks OK, включая payments/post_booking/services/dates/time/gazebo/media/upsell/prices/waitlist/handoff/reschedule/cancel/reminder.
- Прогнан `scripts/dialog_stress_suite.py`: 13/13 OK. В сценариях проверены живые отказы от допов, цены допов, вторая услуга с той же датой/временем, сводка броней, выборочная отмена, перенос `сдвинем баню на денек позже, часы те же`, info-вопросы, abort черновика, фото и подтверждение с опечаткой `Дя`.
- После дополнительного ручного сценария найден и закрыт stale-form edge case: если старая анкета уже протухла, сообщение `начнем новую / какие ближайшие свободные даты для бани?` больше не показывает checkpoint старой анкеты, а сразу делает fresh direct free-dates lookup с сохранением контакта.
- Добавлен regression `old form new free dates skips stale choice`; после правки прошли `compileall`, `local_regression_suite.py --group fresh --group dates --group time` и отдельный `--group reschedule`.
- Ручной сценарий после свежего YCLIENTS sync:
  - `начнем новую / какие ближайшие свободные даты для бани?` -> ближайшие даты: 28 мая, 29 мая, 31 мая, 1 июня, 3 июня; старый август не подтягивается.
  - `а беседки на какие даты есть?` -> ближайшие даты беседок с вариантами: 28 мая, 29 мая, 30 мая, 31 мая, 1 июня.
  - `10 челов / что дешевле` -> сохраняет 10 гостей, показывает недорогие подходящие варианты как ориентир по цене и спрашивает одну дату.
  - `четвертую / а с детьми можно?` -> сохраняет `Беседка №4`, отвечает по детям и спрашивает дату.
  - `я же говорил 10` на шаге времени -> подтверждает 10 гостей и не парсит `10` как `10:00`.
  - `позже напишу` + `кайф` -> оставляет черновик на паузе без возврата к upsell.
- Ручной перенос: оплаченная баня 25 июня, `сдвинем баню на денек позже, часы те же` -> бот предлагает перенос на 26 июня 18:00 на 6 часов; `да` -> бронь обновлена на 26 июня, `reschedule_flow` очищен.
- Важное наблюдение: пока гонялись длинные проверки, `yclients_sync_status.py --strict` стал stale (`age_seconds > 600`), и direct lookup мог давать неверную картину свободности. После `scripts/sync_yclients_records.py --once` ответы по ближайшим датам стали корректными. Для production критично держать один постоянный `main.py` с включенным YCLIENTS sync loop и мониторить freshness.
- Остаточный UX-риск: functional tests зелёные, но в regression/stress остаются `dialog_timing_slow` на отдельных AI/availability ветках примерно 3-10 секунд; это не новая регрессия, но перед релизом нужно продолжать ускорять частые deterministic маршруты и следить за sync latency.
## 2026-05-28 - закрыты новые live-dialog нюансы перед возвратом к refactor

- Вопросы вида `а че у меня по брони, которую я хотел забронировать` теперь не отвечают только "активных броней нет", если оформленной брони/hold еще нет, но есть черновик заявки. Backend сначала проверяет активные bookings и holds, затем показывает draft-summary и следующий недостающий шаг.
- Vague follow-up `ну че нибудь` на шаге времени больше не принимает AI-догадку как время/длительность: если клиент не дал явного времени или ссылки на прошлую бронь, состояние остается на `time`.
- Эмоциональный разговорный мат без жалобы (`бля будем зажигать`) больше не запускает handoff. Handoff остается для жалоб, возврата денег, агрессии в адрес компании/бота и явной просьбы подключить человека.
- Ссылки на время прошлой брони для второй услуги (`часы как там же`, `то же время`) считаются явным time-сигналом: backend подтягивает время/длительность из локальных активных броней, но сохраняет текущую услугу новой анкеты.
- Для услуг, где нужна длительность до availability, backend теперь спрашивает длительность только после известного времени, чтобы не перескакивать с `time` на `duration` при неопределенных фразах.
- Проверки: `compileall app scripts`; `local_regression_suite.py --group services`; `--group post_booking --group handoff --group fresh --group time`; `--group dates`; `--group gazebo`; `--group services --group prices --group upsell`; `--group payments`; `--group cancel`; `--group reschedule`; `--group media --group waitlist --group reminder`; `scripts/dialog_stress_suite.py` - 13/13 OK после фикса same-time edge case.
- После уточнения guard, что same-time reference валиден только при backend patch из активной брони, повторно пройдены `compileall app scripts`, `local_regression_suite.py --group post_booking`, `--group services --group handoff --group time` и `scripts/dialog_stress_suite.py` - 13/13 OK.
- Наблюдение: отдельной regression-группы `availability` нет; availability покрывается через `dates/gazebo/services/time/post_booking/waitlist`. В stress/regression все еще встречаются `dialog_timing_slow` на AI semantic ветках, функционально сценарии зеленые.

## 2026-05-28 - проведен edge-dialog прогон активных flow

- Добавлен `scripts/dialog_edge_suite.py`: 12 нестандартных сценариев с перебиванием активной анкеты, финального подтверждения, cancel-flow, reschedule-flow и post-booking состояния.
- Закрыты найденные нюансы: вопрос `что мы сейчас бронируем/подтверждаем` теперь deterministic показывает draft-summary и не меняет состояние; `отмени бронь, не будем` на `awaiting_confirmation` сбрасывает еще не созданную заявку, а не идет в reserved-hold glue; info-вопрос про аванс внутри cancel-flow отвечает по правилу возврата и оставляет подтверждение отмены активным; `нет, оставь` отменяет cancel-flow и позволяет затем начать перенос.
- Post-booking classifier уточнен: вопросы не по теме базы отдыха/брони отвечают коротко и не предлагают допы/следующий шаг. `_clean_reply` дополнительно чистит AI-опечатку `сразать -> сразу`.
- Edge-прогон подтвердил: info-вопросы во время подтверждения не мешают последующему `да`; info-вопросы внутри переноса не сбрасывают `reschedule_flow`; вопрос про варианты переноса с двумя бронями показывает варианты; посторонние вопросы в форме/cancel/post-booking не портят состояние.
- Проверки: `compileall app scripts`; `scripts/dialog_edge_suite.py` - 12/12 OK; `local_regression_suite.py --group payments --group post_booking --group cancel --group reschedule` - OK; `--group fresh --group gazebo --group services --group prices --group upsell --group time --group handoff` - OK; `--group dates --group media --group waitlist --group reminder` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; после prompt/text cleanup повторно `compileall`, `scripts/dialog_edge_suite.py` - 12/12 OK и `local_regression_suite.py --group post_booking` - OK.
- Перед live-проверкой `scripts/yclients_sync_status.py --strict` показал stale cache (`age_seconds=5944`), выполнен `scripts/sync_yclients_records.py --once`: `seen=121`, `upserted=121`; повторный strict status fresh (`age_seconds=90`, `last_error=None`).
- Наблюдение: отдельные off-topic вопросы внутри формы всё еще проходят через AI semantic и дают `dialog_timing_slow` около 7-8 секунд, но состояние сохраняется; это не блокер, а направление для будущих deterministic short-circuit.

## 2026-05-28 - разобран live-чат 6093 по беседке на 20 гостей

- По реальному чату `conversation_id=6093` найден новый набор live-регрессий перед продолжением рефакторинга: `20 чел` не был надежно сохранен как `guests_count`, ответ на 5 июня показал свободные беседки без фильтра вместимости и повторно спросил гостей.
- Причина по коду: если semantic-router трактует короткое `20 чел` как info-like, `_ai_first_patch` пропускает только `_capacity_guest_patch`, а этот guard не покрывает сокращение `чел`. Backend должен принимать expected-step answer независимо от AI-классификации.
- Неправильные даты 16-20 июня возникли из-за early route `_asks_for_free_slots` на `awaiting_new_date`: фраза `только эта свободна на 5 июня` не парсилась как уточнение 5 июня, а запускала `_next_free_dates_reply`, который пропускает уже показанные `last_suggested_free_dates`. Список 6-10, полученный без вместимости, загрязнил последующий поиск для 20 гостей.
- Текущая диагностика локальной availability-таблицы не подтверждает stale-cache как основную причину именно этого чата: 5 июня для 20 гостей подходящих слотов нет; 8 июня подходят `Беседка №1/№8/№3`; 4 июня подходят `Беседка №8/Крытая`. `yclients_sync_status.py --strict` на момент проверки свежий, но близко к порогу (`age_seconds=550`, `records_seen=121`, `last_error=None`).
- Вопросы по скидке обходят knowledge: deterministic price reply берет базовую цену `Беседка №1 = 10 500 ₽` из `services_map` до проверки фраз `скидка/со скидкой`. В базе знаний есть скидка 50% ПН-ЧТ и цена №1 5 250 ₽, поэтому нужен discount-aware ответ или явный routed knowledge reply.
- Финальное `form_data` разговора потеряло `time`, `duration`, `event_format`, хотя в transcript клиент дал `18,00`, `на 5`, `встреча однокласников`; при этом сохранился `upsell_items=["кальян"]`. Это объясняет повторный вопрос времени после допа/цены/кальяна и требует state-safe guard между AI-текстом, `last_assistant_asked_upsell` и фактическим `next_question(form_data)`.
- Production-код не менялся; выводы зафиксированы в `bugs/current-known-issues.md`. Следующий шаг перед refactor: точечно закрыть эти live-регрессии и добавить сценарии в regression/edge/stress.

## 2026-05-28 - закрыт live-баг `30 июня` -> `30 гостей`

- По последнему Telegram-чату найден конкретный poison-state: сообщение `на 30 июня` было ошибочно принято как `guests_count=30`, после чего backend авто-выбрал единственную подходящую для 30 гостей `Беседку №1`. Дальше бот отвечал уже из испорченного состояния: забывал дату в вопросе про выбор, говорил про 30 гостей и цену/скидку первой беседки, хотя количество гостей не спрашивал.
- Исправлено routing-правило: если AI ошибочно пометил ответ текущего шага как `answer_info`, но backend принял валидное изменение анкеты (`date`, `guests_count`, `time` и т.д.), сообщение больше не идет в info-ветку, а проходит через форму/availability.
- Добавлена защита от числа из даты: `guests_count` из AI-patch отклоняется, если в тексте есть date-сигнал (`30 июня`, относительная дата и т.п.) и нет явного маркера гостей (`чел`, `человек`, `гостей`, `нас будет`). При этом `на 30 июня нас будет 20` сохраняет и дату, и гостей.
- Для беседок `guests_count` теперь сам запускает availability-check при уже известной дате; после чистой даты без гостей бот не выбирает беседку, а спрашивает количество гостей перед подбором по вместимости.
- Вопрос `а какой у меня выбор есть?` при известной дате, но без гостей, больше не просит дату заново: бот напоминает дату и спрашивает гостей, чтобы показать подходящие варианты.
- Добавлен recovery guard для реплик вроде `ты же даже не спросил сколько человек`: backend очищает ошибочно выбранную беседку/гостей и возвращает шаг `guests_count`.
- `scripts/dialog_context_suite.py` расширен до 11 сценариев: добавлены чистая дата без гостей, вопрос про выбор после даты и восстановление после жалобы на неуточнённых гостей.
- Локальная DNS-проблема Windows временно обойдена для проверок через `DB_HOST=95.214.62.243` и `DB_SSLMODE=verify-ca`; `.env` не менялся. Перед regression был выполнен YCLIENTS sync: `records_seen=123`, strict-status fresh.
- Проверки: `compileall app scripts`; `scripts/dialog_context_suite.py` - 11/11 OK; `local_regression_suite.py --group gazebo --group dates --group prices --group upsell --group time --group fresh` - OK; `--group services --group post_booking --group payments --group cancel --group reschedule` - OK; `--group media --group waitlist --group handoff --group reminder` - OK; `scripts/dialog_edge_suite.py` - 13/13 OK; `scripts/dialog_stress_suite.py` - 13/13 OK.
- Операционно исправлен live-черновик `conversation_id=135`: очищены ошибочные `guests_count=30`, `service_variant=Беседка №1`, `last_available_gazebo_variants`; сохранены `service_type=gazebo` и `date=2026-06-30`, шаг возвращен на `guests_count`.
- Остаточное наблюдение: functional quality зелёная, но AI semantic на некоторых off-topic/сложных ветках всё ещё даёт `dialog_timing_slow` примерно 6-15 секунд. Это следующий UX-фокус, не текущая регрессия корректности.
