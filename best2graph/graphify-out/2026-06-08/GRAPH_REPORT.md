# Graph Report - best2graph  (2026-06-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 501 nodes · 1960 edges · 37 communities (16 shown, 21 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 39 edges (avg confidence: 0.82)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1a3c0b9a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]

## God Nodes (most connected - your core abstractions)
1. `Check` - 206 edges
2. `datetime` - 168 edges
3. `_send()` - 146 edges
4. `_base_form()` - 140 edges
5. `_latest_state()` - 117 edges
6. `_create_reserved_conversation()` - 109 edges
7. `_refresh_handler_globals()` - 72 edges
8. `str` - 69 edges
9. `date` - 60 edges
10. `Any` - 55 edges

## Surprising Connections (you probably didn't know these)
- `Беседки` --semantically_similar_to--> `Объекты и услуги базы отдыха`  [INFERRED] [semantically similar]
  best2info/objects/gazebos.md → app/knowledge/objects.md
- `Гостевой дом` --semantically_similar_to--> `Объекты и услуги базы отдыха`  [INFERRED] [semantically similar]
  best2info/objects/house.md → app/knowledge/objects.md
- `Теплая беседка` --semantically_similar_to--> `Объекты и услуги базы отдыха`  [INFERRED] [semantically similar]
  best2info/objects/warm_gazebo.md → app/knowledge/objects.md
- `Information Knowledge Base` --conceptually_related_to--> `Banya Image`  [INFERRED]
  information.md → app/images/banya.jpg
- `Information Knowledge Base` --conceptually_related_to--> `Besedka 1 Image`  [INFERRED]
  information.md → app/images/besedka1.jpg

## Import Cycles
- 1-file cycle: `app/integrations/yookassa_client.py -> app/integrations/yookassa_client.py`
- 1-file cycle: `scripts/local_regression_suite.py -> scripts/local_regression_suite.py`
- 1-file cycle: `app/services/dialog/availability_flow.py -> app/services/dialog/availability_flow.py`
- 1-file cycle: `app/services/dialog/confirmation_flow.py -> app/services/dialog/confirmation_flow.py`
- 1-file cycle: `app/services/dialog/handoff.py -> app/services/dialog/handoff.py`

## Communities (37 total, 21 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (93): _create_reserved_conversation(), _latest_state(), datetime, _send(), _test_addon_price_during_upsell_does_not_repeat_event_format(), _test_addon_prices_plural_question_replies_immediately(), _test_ai_event_format_is_not_invented(), _test_ai_semantic_preflight_for_active_routes() (+85 more)

### Community 1 - "Community 1"
Cohesion: 0.09
Nodes (87): AIProviderUnavailable, Any, bool, datetime, int, _ReservedHoldCallbacks, str, _AwaitingConfirmationCallbacks (+79 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (75): _base_form(), Check, Deterministic regression tests for the booking bot.  The suite stubs AI/paymen, _test_abort_current_draft_from_upsell_refusal(), _test_abort_current_draft_keeps_contact(), _test_addon_price_question_does_not_add_item(), _test_afternoon_time_words_parse_pm(), _test_bare_duration_answer() (+67 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (50): date, Decimal, _add_paid_booking(), _add_paid_payment_for_latest_booking(), _create_paid_booking_for_action(), _create_waitlist_request(), _FakeWaitlistBot, Any (+42 more)

### Community 4 - "Community 4"
Cohesion: 0.20
Nodes (34): Any, bool, datetime, int, ReservedHoldCallbacks, str, awaiting_confirmation_side_reply(), AwaitingConfirmationCallbacks (+26 more)

### Community 5 - "Community 5"
Cohesion: 0.15
Nodes (17): Any, int, str, YooKassaClient, YooKassaError, RuntimeError, _build_cases_by_name(), _cases_for_listing() (+9 more)

### Community 6 - "Community 6"
Cohesion: 0.26
Nodes (24): Any, bool, datetime, int, str, alternative_services_for_unavailable_date(), append_waitlist_offer(), apply_previous_period_for_new_date() (+16 more)

### Community 7 - "Community 7"
Cohesion: 0.20
Nodes (14): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Bathhouse Object, Bathhouse Prices, Беседки (+6 more)

### Community 8 - "Community 8"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 9 - "Community 9"
Cohesion: 0.40
Nodes (9): Any, bool, datetime, int, str, handoff_active(), is_location_question(), looks_like_handoff_needed() (+1 more)

### Community 10 - "Community 10"
Cohesion: 0.25
Nodes (9): Addons Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base, Prepayment System (+1 more)

### Community 11 - "Community 11"
Cohesion: 0.42
Nodes (8): main(), _parse_events(), _print_payload(), Any, str, Prepare YooKassa HTTP-notification webhook setup.  For the shopId/secret-key HTT, _redact_url(), _validate_webhook_url()

### Community 12 - "Community 12"
Cohesion: 0.32
Nodes (8): Backend System, Bot Main Rules, Gazebos Service, Payment and Booking System, Photo Management System, Sauna + Gazebo Combo, Sauna with Pool Service, YClients Integration

### Community 13 - "Community 13"
Cohesion: 0.25
Nodes (8): _create_active_hold(), _test_fake_payment_request_does_not_mark_paid(), _test_generic_second_booking_keeps_only_contact(), _test_next_application_while_hold_starts_blank_not_ice(), _test_paid_status_refreshes_on_any_message(), _test_payment_intent_retry_no_duplicate_link(), _test_reserved_yes_retries_payment_link(), _test_reserved_yes_reuses_existing_payment_link()

### Community 14 - "Community 14"
Cohesion: 0.40
Nodes (5): Base Knowledge File, Runtime Knowledge Base, Objects Knowledge File, Prices Knowledge File, YClients IDs Knowledge File

### Community 15 - "Community 15"
Cohesion: 0.50
Nodes (5): Response Generator Prompt, Form Data Structure, JSON Response Schema, System Prompt, YCLIENTS Integration

## Knowledge Gaps
- **60 isolated node(s):** `int`, `int`, `ReservedHoldCallbacks`, `int`, `_ReservedHoldCallbacks` (+55 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_impl_handle_incoming()` connect `Community 1` to `Community 4`?**
  _High betweenness centrality (0.274) - this node is a cross-community bridge._
- **Why does `_send()` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 13`?**
  _High betweenness centrality (0.268) - this node is a cross-community bridge._
- **Why does `IncomingMessage` connect `Community 1` to `Community 0`?**
  _High betweenness centrality (0.251) - this node is a cross-community bridge._
- **What connects `int`, `int`, `ReservedHoldCallbacks` to the rest of the system?**
  _63 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.07433380084151472 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.08881922675026123 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.0673274094326726 - nodes in this community are weakly interconnected._