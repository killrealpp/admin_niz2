# 2026-06-10 - YooKassa link failed on non-Russian phone shape

## Symptom

In the latest Telegram dialog (`conversation_id=1006`), the bot accepted `96865785568` as `+96865785568`, reserved the slot, then failed to create a YooKassa payment link.

The payment row showed:

- `status=failed`
- `amount=1.00`
- `raw_payload.error=Invalid customer phone for YooKassa receipt`

## Cause

`phone_patch()` and `valid_phone()` allowed 11-15 digit international-looking numbers. YooKassa receipt creation in this project requires a Russian phone shape (`7XXXXXXXXXX`) and rejects `+968...`.

## Fix

- `phone_patch()` now normalizes only supported Russian formats:
  - `9XXXXXXXXX` -> `+79XXXXXXXXX`
  - `8XXXXXXXXXX` -> `+7XXXXXXXXXX`
  - `7XXXXXXXXXX` -> `+7XXXXXXXXXX`
- `valid_phone()` now accepts only those supported Russian shapes.
- Added regression `non russian phone does not reach yookassa`.

## Verification

- `python -m compileall app scripts`
- `scripts/local_regression_suite.py --case "non russian phone does not reach yookassa"`
- `scripts/local_regression_suite.py --case "invalid phone reply is client safe"`

Expected client-facing behavior now: if a user sends `96865785568`, the bot asks for a full phone number in `+7XXXXXXXXXX` format instead of reaching payment-link creation and failing late.
