# 2026-06-08 - MAX webhook media task cancelled before photos send

## Status

Fixed locally; production deployment is still blocked by unstable SSH maintenance access.

## Symptoms

- In MAX, a user asked for gazebo photos.
- The bot answered that it would send gazebo photos, but no photos arrived.
- On a follow-up question, the bot mentioned Telegram in a MAX chat, which must not happen in a client-facing MAX channel.

## Root Cause

`process_client_message()` sent related media through a background `asyncio.create_task()`.

That is fine in long-running polling loops, but production MAX webhook events are processed by a sync worker through `asyncio.run(process_max_update(...))`. When `asyncio.run()` returned after the text reply, it closed the event loop and cancelled the background media task before the MAX upload/send path could run.

The Telegram mention came from shared dialog/prompt text leaking a Telegram-specific platform word into a MAX response after the user asked where the photos were.

## Fix

- `process_client_message()` now supports `await_related_media`.
- `process_max_webhook_event()` enables `await_related_media=True`, so MAX webhook worker processing waits for related media before closing its temporary event loop. The HTTP webhook handler still returns `200` quickly because event processing happens in the existing worker queue after the request is accepted.
- `MaxChannelClient.send_text()` sanitizes accidental Telegram mentions before sending text to MAX.
- `app/knowledge/runtime.md` now says "client chat" instead of "Telegram" for generic response formatting guidance.
- Regression coverage was added to `scripts/max_media_buttons_smoke.py` and `scripts/max_outbound_text_smoke.py`.

## Verification

Local checks passed:

- `python -m compileall app scripts`
- `scripts/max_media_buttons_smoke.py`
- `scripts/max_outbound_text_smoke.py`
- `scripts/max_inbound_normalization_smoke.py`
- `scripts/max_webhook_runner_smoke.py`
- `scripts/channel_contract_smoke.py`
- `scripts/local_regression_suite.py --group media`
- `scripts/max_status.py`

## Deployment Note

The live server still needs this patch deployed under `/opt/admin_niz2` and `best2.service` restarted.

Current SSH recheck from the workstation failed:

- port `2222`: intermittent banner timeout or `Permission denied (publickey,password)`;
- port `22`: banner timeout.

This is the known maintenance-access issue tracked in [[bugs/2026-06-08-server-ssh-https-blocker]].
