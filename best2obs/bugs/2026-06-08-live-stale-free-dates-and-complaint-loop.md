# 2026-06-08 live stale free-dates and complaint loop

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
