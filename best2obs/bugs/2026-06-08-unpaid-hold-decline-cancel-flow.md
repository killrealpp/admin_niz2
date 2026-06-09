# 2026-06-08 - Unpaid hold decline routed to booking cancel flow

## Status

Fixed locally and verified against the DB-backed regression on 2026-06-09.

Deploy to the server is still a separate operational step.

## Symptom

Live client text after a payment-link/prepayment step:

```text
Я не хочу оплачивать
```

could be answered as:

```text
Активной брони для отмены не нашла...
```

This is wrong because at that moment the client may have an active unpaid `slot_holds` reservation and pending payment row, not a finalized paid booking.

## Root Cause

- `confirmation_flow.wants_cancel_or_change_hold()` only matched explicit hold changes like `отменить`, `убрать`, `поменять`, `перенести`.
- `Я не хочу оплачивать` did not enter the reserved-hold path.
- Later post-booking routing treated the phrase as a generic booking cancel and called `start_cancel_booking_flow()`.
- `start_cancel_booking_flow()` searches active finalized bookings, so for an unpaid hold it correctly found no booking, but produced the wrong user-facing answer.
- DeepSeek and Sonnet both classify the same phrase as a generic cancel intent in post-booking classifier, so this needs a deterministic backend guard before AI/post-booking routing.

## Fix

- Added `wants_decline_unpaid_hold()` in `app/services/dialog/confirmation_flow.py`.
- Added `unpaid_hold_cancel_flow` for active unpaid holds:
  - first message asks confirmation and keeps the hold active;
  - `нет` keeps the preliminary request unchanged;
  - `да` cancels active hold IDs and marks matching pending/waiting payment rows as `superseded`;
  - paid bookings are not touched.
- Extended `ReservedHoldCallbacks` with `confirmation_no`.
- Added regression case:
  - `decline unpaid hold prompts and cancels pending payment`.

## Verification

Passed locally:

- `python -m compileall app scripts`
- `scripts/lint_best2info.py`
- `scripts/validate_yclients_map.py`
- `scripts/dialog_identity_smoke.py`
- `scripts/dialog_contextual_photo_smoke.py`
- `scripts/max_media_buttons_smoke.py`
- `scripts/max_outbound_text_smoke.py`
- `scripts/channel_contract_smoke.py`
- `scripts/channel_notifications_smoke.py`
- `scripts/max_webhook_runner_smoke.py`
- in-memory unpaid-hold decline smoke

Blocked locally:

- `scripts/local_regression_suite.py --case "decline unpaid hold prompts and cancels pending payment"` because local Windows workstation currently times out connecting to Beget PostgreSQL.
- `scripts/db_status.py` for the same Beget PostgreSQL timeout.

Server verification needed:

```bash
cd /opt/admin_niz2
.venv/bin/python scripts/local_regression_suite.py --case "decline unpaid hold prompts and cancels pending payment"
```

## 2026-06-09 Verification Update

- Local DB-backed regression was run from the workstation and failed.
- First message is now routed correctly to the unpaid-hold decline prompt.
- Confirmation with `yes` does not complete the expected cleanup in the current regression run:
  - the test hold becomes `expired`, not cleanly cancelled;
  - the matching pending payment remains `pending`, not `superseded`.
- Likely fixture/code interaction: the regression creates `expires_at` from its fixed test `now`, while `slot_holds_repo.create()` also expires old rows using database `NOW()`. With a live DB this can create a hold that is already stale relative to real time.
- Required next step: fix the regression fixture and/or flow so the test creates a genuinely active hold relative to DB time, then confirm that `yes` cancels the hold and supersedes the pending payment.

## 2026-06-09 Fix Verification

- The regression fixture now creates a unique active test hold with `expires_at` based on the actual current app timezone time, so the DB `NOW()` cleanup no longer turns the test hold stale before confirmation.
- `handle_reserved_hold_command()` now also handles the edge case where the unpaid-hold cancel flow exists but the hold has already expired: it closes/supersedes the matching pending payment and resets the form instead of falling back to finalized-booking cancellation.
- Verified green:
  - `scripts/local_regression_suite.py --case "decline unpaid hold prompts and cancels pending payment"`
  - `scripts/local_regression_suite.py --group payments --group fresh --group dates --group gazebo`
  - `python -m compileall app scripts`
- Expected behavior is now under local control: first decline asks for confirmation, `да` cancels the active hold and marks the pending payment `superseded`, while paid bookings are not touched.

## Expected Live Behavior

First message:

```text
Поняла, без предоплаты бронь не закрепляется.

Снять предварительную заявку и освободить слот? Если хотите подобрать другой вариант, напишите «да» — после этого начнём новую заявку.
```

After `да`:

```text
Сняла предварительную заявку ✅

Без предоплаты бронь не закрепляется. Если хотите подобрать другой вариант, напишите услугу и дату.
```
