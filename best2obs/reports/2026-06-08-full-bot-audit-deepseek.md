# 2026-06-08 - Full bot audit and DeepSeek smoke

## Summary

The main live bug class found in this audit was payment/hold state drift: an unpaid preliminary hold could be treated as a finalized booking cancel request. This is fixed locally in `confirmation_flow` with a deterministic unpaid-hold decline flow.

Production model switch to DeepSeek is not recommended yet. `deepseek/deepseek-chat` works through OpenRouter and returned parseable JSON, but it classified `Я не хочу оплачивать` the same broad way as Sonnet. The problem was routing/state ownership, not model choice.

## Knowledge Sources

- `best2info/` is the client-facing knowledge base. It stores facts the bot may say to clients: objects, prices, rules, payment, discounts, location, children/pets and rest rules.
- `best2info/runtime.md` is always loaded into runtime knowledge through `knowledge_service.load_knowledge()`.
- Other `best2info/**/*.md` pages are selected by `knowledge_service.retrieve_client_knowledge()` using keyword/token/headings scoring and one-hop `[[wikilinks]]`.
- `config/services_map.yaml` is the code source for prices, YCLIENTS service IDs/staff IDs, package durations and capacity-like structured data.
- Availability is never a knowledge-file fact. It comes from local DB/YCLIENTS cache and runtime tables: `yclients_records`, `resource_busy_intervals`, `slot_holds`, `bookings`, `payments`.
- `app/knowledge/` and `information.md` are legacy/fallback knowledge sources only when `best2info` runtime files are missing.
- `best2graph/` is a developer/AI code map. It helps find code, but it is not used for client answers.
- `best2obs/` is project memory: architecture, bugs, decisions, reports, runbooks and roadmap. It is not a client-answer source.

## Runtime And Background Processes

- Telegram entry/exit: Telegram polling channel in the common runtime.
- MAX entry/exit: MAX webhook runner in production, MAX polling only for local/dev.
- Dialog core: shared `message_handler` / dialog flow modules. Telegram and MAX should not fork business logic.
- YCLIENTS sync: background runner refreshes local records from YCLIENTS into DB/cache.
- Payment status sync: background runner checks pending YooKassa payments and finalizes paid bookings.
- YooKassa webhook runner: receives payment notifications if nginx proxies `/webhooks/yookassa` to the local runner.
- Message retention/summary: background process summarizes old raw messages and keeps context manageable.
- Admin notifications: currently Telegram.

## Scenario Audit

| Scenario | Expected | Result | Status | Where to fix |
| --- | --- | --- | --- | --- |
| `Я не хочу оплачивать` during active unpaid hold | Ask whether to remove preliminary request; after yes cancel hold and pending payment only | Fixed locally | Needs server DB regression | `app/services/dialog/confirmation_flow.py` |
| `да` after unpaid-hold decline prompt | Cancel active `slot_holds`, mark pending payment `superseded`, reset to new request | Fixed locally | Needs server DB regression | `confirmation_flow.py`, `payments_repo`, `slot_holds_repo` |
| `а когда свободно?` after stale gazebo context | Should not reuse old concrete gazebo unless user names it | Already fixed in previous slice | Server regression still recommended | `message_handler_flow_glue.py` |
| Complaint like `ты в своем уме?` | Handoff/complaint handling, not repeat form question | Already fixed in previous slice | Server regression still recommended | `message_handler_flow_glue.py` |
| `покажи баню`, `покажите беседки`, `а их фото?` | Deterministic media route, no Telegram wording in MAX | Fake smokes green | Needs manual live paired smoke | `info_flow.py`, MAX adapter |
| `как тебя зовут?` | Любовь | Smoke green | OK | identity guard |
| Payment status `оплата прошла?` | Check local paid state / pending payment status, no fake marking paid | Existing guards | Server/live payment gate still separate | payment flow |
| MAX vs Telegram parity | Same dialog meaning, channel-neutral wording | Static/fake smokes green | Manual paired smoke remains | shared dialog core + adapters |

## DeepSeek Smoke

Source checked: OpenRouter page for DeepSeek V3 lists model `deepseek/deepseek-chat`, OpenAI-compatible `POST /chat/completions`, and context/pricing metadata: <https://openrouter.ai/deepseek/deepseek-chat/api>.

Temporary local env override used:

```powershell
$env:AI_PROVIDER='openrouter'
$env:OPENAI_MODEL='deepseek/deepseek-chat'
$env:OPENAI_TEMPERATURE='0.2'
$env:OPENAI_MAX_TOKENS='700'
```

Results:

| Model | `какие беседки есть?` | `Я не хочу оплачивать` post-booking classifier |
| --- | --- | --- |
| `deepseek/deepseek-chat` | `object_selection_help`, `answer_info`, parse OK | `change_existing_booking`, `cancel`, confidence `1.0` |
| `anthropic/claude-sonnet-4` | `object_selection_help`, `answer_info`, parse OK | `change_existing_booking`, `cancel`, confidence `0.9` |

Conclusion: DeepSeek is available and parses JSON on this small smoke, but it does not solve the payment/hold misroute. Keep Sonnet in production until broader real-dialog comparison proves DeepSeek is equal or better.

## Verification Run

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
- DeepSeek and Sonnet two-case model smoke

Blocked locally:

- `scripts/db_status.py` and DB-mutating `local_regression_suite` cases: Beget PostgreSQL connection from the Windows workstation timed out on `kifloquomirab.beget.app:5432`.
- Live Telegram test: no separate test Telegram bot token was provided, and production token must not be run locally while server polling/webhook is active.
- Live YooKassa payment: intentionally not performed.

## Server Commands To Finish This Audit

```bash
cd /opt/admin_niz2
git pull
.venv/bin/python -m compileall app scripts
.venv/bin/python scripts/local_regression_suite.py --case "decline unpaid hold prompts and cancels pending payment"
.venv/bin/python scripts/local_regression_suite.py --case "stale continued free dates clears old gazebo variant"
.venv/bin/python scripts/local_regression_suite.py --case "stale complaint bypasses stale choice"
.venv/bin/python scripts/dialog_contextual_photo_smoke.py
.venv/bin/python scripts/dialog_identity_smoke.py
.venv/bin/python scripts/max_media_buttons_smoke.py
.venv/bin/python scripts/max_outbound_text_smoke.py
.venv/bin/python scripts/yookassa_webhook_hardening_smoke.py
systemctl restart best2.service
systemctl status best2.service --no-pager
```

Manual paired smoke after deploy:

- Telegram and MAX: `/start`.
- Telegram and MAX: `какие беседки есть?`, then `а покажете их?`.
- Telegram and MAX: `покажи баню`.
- Active unpaid hold: `Я не хочу оплачивать`, then `да`.
- Payment status: `оплата прошла?`.
- Complaint: `ты в своем уме?`.
- Voice/audio in both channels if test user can send voice.

## Recommendation

Do not switch production to DeepSeek yet. Use DeepSeek only as an experiment profile until a broader paired regression/manual smoke shows stable JSON, good intent choice and no worse Russian dialog behavior.
