# 2026-06-08 - MAX webhook media task cancelled before photos send

## Status

Fixed locally; production deployment is still blocked by unstable SSH maintenance access.

## Symptoms

- In MAX, a user asked for gazebo photos.
- The bot answered that it would send gazebo photos, but no photos arrived.
- On a follow-up question, the bot mentioned Telegram in a MAX chat, which must not happen in a client-facing MAX channel.
- After the first local lifecycle fix, live MAX attempted media delivery but sent the fallback: "Фото сейчас не получилось отправить в MAX...".
- User asked "как тебя зовут"; the bot answered "Бест" even though project knowledge says the assistant is named "Любовь".

## Root Cause

`process_client_message()` sent related media through a background `asyncio.create_task()`.

That is fine in long-running polling loops, but production MAX webhook events are processed by a sync worker through `asyncio.run(process_max_update(...))`. When `asyncio.run()` returned after the text reply, it closed the event loop and cancelled the background media task before the MAX upload/send path could run.

Second root cause found from `system_logs.event_type='max_media_delivery_failed'`:

- live failure at `2026-06-08 10:39:59+03:00`;
- image `banya.jpg`;
- error `MAX upload did not return attachment token`.

The MAX upload endpoint returned a valid image payload with top-level `photos`, not a top-level `token`. The old parser accepted only simple token payloads and therefore treated a valid upload as failure.

The Telegram mention came from shared dialog/prompt text leaking a Telegram-specific platform word into a MAX response after the user asked where the photos were.

The "Бест" answer was an LLM drift on a simple identity question; it should be deterministic and should not depend on the model.

## Fix

- `process_client_message()` now supports `await_related_media`.
- `process_max_webhook_event()` enables `await_related_media=True`, so MAX webhook worker processing waits for related media before closing its temporary event loop. The HTTP webhook handler still returns `200` quickly because event processing happens in the existing worker queue after the request is accepted.
- `MaxChannelClient.send_text()` sanitizes accidental Telegram mentions before sending text to MAX.
- `app/knowledge/runtime.md` now says "client chat" instead of "Telegram" for generic response formatting guidance.
- `MaxApiClient.upload_file()` now accepts MAX image upload payloads containing `photos`, plus nested token payloads and upload URL token fallbacks.
- `app/services/dialog/info_flow.py` now answers bot-name questions deterministically as "Любовь" before calling the LLM.
- `app/prompts/system_prompt.md` and `app/prompts/response_generator.md` are channel-neutral for client-chat formatting.
- Regression coverage was added to `scripts/max_media_buttons_smoke.py` and `scripts/max_outbound_text_smoke.py`.
- `scripts/dialog_identity_smoke.py` covers the deterministic "как тебя зовут" answer.

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
- `scripts/dialog_identity_smoke.py`

Safe live MAX upload check without sending a message to any user:

- `MaxApiClient.upload_file(app/images/banya.jpg, upload_type='image')`
- result accepted with `payload_keys=photos`, `photos_count=1`, `has_token=False`

## Deployment Note

The live server still needs this patch deployed under `/opt/admin_niz2` and `best2.service` restarted.

Current SSH recheck from the workstation failed:

- port `2222`: intermittent banner timeout or `Permission denied (publickey,password)`;
- port `22`: banner timeout.

This is the known maintenance-access issue tracked in [[bugs/2026-06-08-server-ssh-https-blocker]].
