# 2026-06-09 - OpenRouter context limit live errors

## Status

Open.

## Symptom

`scripts/live_health_report.py` reports `recent_system_errors_present`.
Recent live errors include `ai_provider_unavailable` / `ai_semantic_degraded` for user messages like `ты в своем уме?` and `ау`.

The provider payload says prompt tokens exceeded the current OpenRouter limit, for example approximately `11660 > 10506`.

## Impact

- The bot can fall back to deterministic/default form prompts instead of answering the actual complaint or short follow-up.
- This matches the live UX issue where the bot repeated `На какую дату планируете отдых?` after irritation messages.

## Likely Cause

The semantic prompt/history context can grow past the current provider token budget in active conversations.
This is not a MAX-specific transport bug; it affects the common dialog core when AI routing is needed.

## Next Steps

- Reduce semantic-router/post-booking prompt context and history size.
- Add a regression or smoke that simulates long history plus a complaint/short follow-up and expects deterministic handoff/fallback before AI if the text is obviously a complaint.
- Consider a larger-context model only after the deterministic guard is improved.
- Keep monitoring `live_health_report.py` until recent `ai_provider_unavailable` errors disappear.
