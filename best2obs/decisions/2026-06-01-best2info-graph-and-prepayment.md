# 2026-06-01 - best2info graph retrieval and prepayment modes

## Decision

`best2info/` remains a small markdown wiki for client-facing facts, but runtime retrieval is now graph-aware: relevant pages are selected by keyword/token scoring and expanded through one-hop `[[wikilinks]]`. `runtime.md` is always included.

Prepayment is split into two explicit modes:

- Local test mode: `PREPAYMENT_MODE=fixed`, `PREPAYMENT_AMOUNT_RUB=1`.
- Production target: `PREPAYMENT_MODE=percent`, `PREPAYMENT_PERCENT=50`.

Percent prepayment is calculated from the main service or package price in `config/services_map.yaml`. Gazebo weekday discounts are included. Addons are not included in the advance payment yet.

## Rationale

The bot needs concise, reliable client facts without reading one oversized knowledge file. Small linked pages are easier to maintain, and one-hop retrieval lets an answer pull the object, price and rule pages that belong together.

The 1-ruble local mode is useful for safe YooKassa smoke tests, but it must not be confused with production. Making the mode explicit prevents hidden config drift and gives production a clear 50% rule based on the real service price.

## Consequences

- Prices for code stay in `config/services_map.yaml`; `best2info` must mirror them and is checked by `scripts/lint_best2info.py`.
- Availability stays a backend/local-DB concern, not a `best2info` fact.
- If `best2info` has no exact fact or exact price, the bot must say that the team will clarify instead of inventing.
- Before production launch, fixed 1-ruble mode must be disabled and percent mode enabled.
