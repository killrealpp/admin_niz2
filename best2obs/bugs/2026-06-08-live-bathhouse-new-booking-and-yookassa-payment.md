# 2026-06-08 - Live MAX new bathhouse booking routed through old gazebo state

## Status

Open; diagnostics only.

## User Symptom

In MAX after confirming a gazebo hold, the user wrote:

- `давай еще баню забронируем на 14 июня`
- bot replied as if checking the current gazebo: `На эту дату для «Беседка» уже есть предварительная заявка...`
- follow-up `а когда свободно?` also answered for `Беседка`, not `Баня`.

The user also reported that the payment link was not sent.

## Findings

- `live_health_report.py` is `status=ok`; YCLIENTS sync is fresh and local DB hygiene is clean apart from one active hold.
- Runtime DB has active `slot_holds.id=150` for `conversation_id=1`, `service_type='gazebo'`, `slot_date=2026-06-14`, `slot_time=12:00`, `duration_minutes=240`.
- The current conversation state is `status='waiting_user'`, `current_step='awaiting_new_date'`, and `form_data.service_type='gazebo'` with `service_variant='Беседка №4'` and `last_unavailable` also pointing to gazebo.
- A read-only local availability check for `service_type='bathhouse'`, `date=2026-06-14` reports the date is available by local calendar. With explicit `time=12:00`, bathhouse start 12:00 is not available, but alternative starts are offered. So the local availability tables are not the root cause of this specific wrong-service answer.
- A payment row was created for the gazebo hold and failed: `payments.status='failed'`, `provider='yookassa'`, `payment_url` missing, provider error `YooKassa error 401 invalid_credentials`. This explains why the bot did not send a payment URL.
- Local `scripts/register_yookassa_webhook.py --dry-run` passes after fixing local `.env`, but read-only `scripts/yookassa_status.py` from the workstation still hit an SSL handshake timeout. Server-side YooKassa status must be checked from `/opt/admin_niz2`.

## Likely Causes

1. Payment link:
   - Server `.env` has wrong YooKassa `PAYMENT_SHOP_ID` or `PAYMENT_SECRET_KEY`, or the key was copied incorrectly. YooKassa returned `401 invalid_credentials` during live payment creation.

2. Wrong service routing:
   - The dialog was in a stale/failed-payment state for a gazebo hold. The phrase explicitly requested a second/new bathhouse booking, but the runtime reused the old gazebo state when answering availability.
   - The fresh-start helpers can detect the phrase as `service_type='bathhouse'`, `date=2026-06-14`, `starts_new_booking_request=True`, `wants_additional_booking=True` in isolation, so the missed behavior is likely in the surrounding live route order/state transition after failed payment/active hold, not in the base service keyword parser.

## Needed Fix

- Add a regression case for: active gazebo hold + failed/no payment + `current_step='awaiting_new_date'` + user says `давай еще баню забронируем на 14 июня`.
- Expected behavior: start a fresh bathhouse form, preserve contact/name only, clear gazebo `service_variant` and `last_unavailable`, check bathhouse availability for 2026-06-14, and ask for a bathhouse time if needed.
- Do not change Telegram/MAX adapters for this bug; fix should be inside shared dialog routing/fresh-start logic.
- Fix YooKassa separately by correcting server credentials and running read-only `scripts/yookassa_status.py` before any live payment smoke.

## Safety

- No production code change was made during this diagnostic.
- No YooKassa webhook registration `--apply` was run.
- No real payment was created by Codex during this diagnostic.
