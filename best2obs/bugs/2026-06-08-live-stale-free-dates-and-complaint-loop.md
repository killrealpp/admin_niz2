# 2026-06-08 live stale free-dates and complaint loop

## Status

Fixed locally and verified on 2026-06-09.

## Symptoms

- In MAX, after a stale-form choice the user continued the old draft with `да`, then asked `а когда будет свободан`.
- The bot answered: `На ближайшие 75 дней свободных дат для «Беседка» не нашла`, even though the user asked a generic free-date question.
- When the user wrote `ты в своем уме?` and then `ау`, the bot repeated the current form question instead of apologizing/escalating.

## Cause

- `direct_free_dates_lookup()` reused stale `service_variant` for gazebo nearest-free-date lookup. The user-facing title still said generic `Беседка`, so a search narrowed to one old gazebo looked like all gazebos were unavailable.
- Handoff/complaint detection ran after stale-form routing. While `stale_form_flow` was active, the stale-choice branch could return `Уточните...` before complaint handling.
- The deterministic complaint markers did not include `ты что` / `в своем уме`.

## Fix

- Generic nearest-free-date questions for gazebo now clear stale `service_variant`, `single_available_gazebo_variant_auto`, and old available-variant context unless the text explicitly mentions a concrete gazebo number/name.
- If a specific gazebo is still requested, `next_free_dates_reply()` uses that concrete gazebo title in the response instead of the generic service title.
- Handoff/complaint handling now runs before stale-form routing in `handle_incoming()`.
- Complaint markers now include `ты что`, `в своем уме`, and `в своём уме`.

## Coverage

- Added regression cases:
  - `stale continued free dates clears old gazebo variant`
  - `stale complaint bypasses stale choice`
- Local compile passed: `python -m compileall app scripts`.
- Pure no-DB smoke passed for `looks_like_handoff_needed()` and `direct_free_dates_lookup()` behavior.
- Full DB regression could not run from the Windows workstation because Beget PostgreSQL timed out locally; run the new named cases on the server.

## 2026-06-09 Verification Update

- `scripts/local_regression_suite.py --case "stale complaint bypasses stale choice"` passed.
- `scripts/local_regression_suite.py --case "stale free dates request starts fresh lookup" --case "old form new free dates skips stale choice"` passed.
- `scripts/local_regression_suite.py --case "stale continued free dates clears old gazebo variant"` failed.
- Current failure shape:
  - after stale continuation (`yes`), the conversation keeps the old gazebo variant;
  - a generic free-date question still checks that stale `service_variant`;
  - user-facing reply can again say no dates were found for the old gazebo instead of doing a broad gazebo lookup.
- Required next step: clear stale gazebo variant when continuing an old stale form and then asking a generic nearest/free-date question, unless the new text explicitly names a concrete gazebo.

## 2026-06-09 Fix Verification

- `direct_free_dates_lookup()` now treats generic gazebo free-date questions as broad lookup even when `callbacks.asks_nearest_free_dates()` does not classify the text strongly enough.
- The broad lookup guard only triggers when:
  - current service is `gazebo`;
  - the text does not mention a concrete gazebo variant;
  - the new patch has no date/time/duration;
  - current form has no fresh date.
- Verified green:
  - `scripts/local_regression_suite.py --case "stale continued free dates clears old gazebo variant"`
  - `scripts/local_regression_suite.py --case "stale free dates request starts fresh lookup" --case "old form new free dates skips stale choice" --case "stale complaint bypasses stale choice"`
  - `scripts/local_regression_suite.py --group payments --group fresh --group dates --group gazebo`
  - `python -m compileall app scripts`
