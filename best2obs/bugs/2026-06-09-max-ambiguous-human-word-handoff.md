# 2026-06-09 - MAX ambiguous "human/person" word caused handoff

Status: fixed locally, pending deploy.

## Symptom

In the latest MAX dialog (`conversations.id=816`, user `Евгений Ермантович`), the client was choosing between available gazebo variants for 20 guests. After the bot asked which gazebo to choose, the client sent the short ambiguous word `человек`.

The AI classified that as `handoff_to_human=True`, so the runtime set the conversation to `handoff` and blocked further normal dialog until the user was manually unblocked.

## Root Cause

The main dialog path trusted AI handoff flags too broadly during an active booking form. A bare people/count word such as `человек`, `людей`, `гостей` can be a fragment of guest-count context, not a request for a live operator.

This is especially risky in MAX because the user may send short fragmented messages while correcting date, guest count or object choice.

## Fix

`app/services/dialog/message_handler_flow_glue.py` now suppresses AI handoff only for short ambiguous people words during active booking-form steps.

Explicit human requests are still allowed to become handoff, for example phrases with `оператор`, `администратор`, `менеджер`, `живой`, `позовите`, `соедините`, `к человеку`, `с человеком`.

## Verification

- `python -m compileall app scripts`
- `scripts/lint_best2info.py`
- `scripts/local_regression_suite.py --case "bare human word during gazebo choice does not handoff" --case "coal price is known"`
- `scripts/local_regression_suite.py --group handoff`

The handoff group also verifies the opposite boundary: `нужен человек` still becomes handoff and stores `current_step/next_step='handoff'`.

The latest MAX user was rechecked after the previous unblock: `handoff_active=false`, active conversation `816` is `reserved`, not `handoff`.

## Follow-Up

Deploy the local fix to the server and restart `best2.service`.
