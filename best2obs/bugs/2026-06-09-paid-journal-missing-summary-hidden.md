# 2026-06-09 - Paid journal-missing booking hidden from client summary

## Status

Fixed locally and verified.

## Symptom

The DB-backed regression `available services uses active booking not stale form` failed:

- the user had a paid local booking;
- the conversation form had stale draft data for another service;
- asking `а у меня сейчас есть брони?` could answer `Пока не вижу активных броней`;
- the next `что еще можно забронировать?` still used the active booking correctly.

This is confusing because an already paid local booking must not disappear from the client-facing summary only because YCLIENTS journal cache is temporarily missing or stale.

## Cause

`active_user_bookings()` deliberately keeps paid local bookings visible as a fallback even when the journal cache is temporarily stale.

However `booking_texts.format_booking_summary()` filtered out all bookings with `status='journal_missing'`.
That meant the fallback booking was returned by the context layer, then hidden by the final summary formatter.

## Fix

`format_booking_summary()` now excludes cancelled bookings, but keeps `journal_missing` bookings when `payment_status='paid'`.

The existing `booking_status_text()` then gives the safer wording:

```text
оплата прошла, запись в журнале сейчас не найдена
```

instead of pretending there is no booking.

## Verification

Passed:

- `python -m compileall app scripts`
- `scripts/local_regression_suite.py --case "available services uses active booking not stale form"`
- `scripts/local_regression_suite.py --group post_booking`
- `scripts/local_regression_suite.py --group services --group time --group media`
- `scripts/local_regression_suite.py --group upsell --group prices --group gazebo --group dates`
- `scripts/local_regression_suite.py --group payments --group fresh`
- `scripts/local_regression_suite.py --group reschedule --group cancel`
- `scripts/local_regression_suite.py --group waitlist --group handoff --group reminder`

## Operational Note

This does not mark a missing YCLIENTS journal row as healthy. It only prevents the client summary from hiding a paid local booking while the operations layer continues to surface journal/cache issues separately through health reports.
