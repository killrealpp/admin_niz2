# Graph Report - best2graph  (2026-06-09)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 397 nodes · 1696 edges · 26 communities (9 shown, 17 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 25 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e6ed0e57`
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

## God Nodes (most connected - your core abstractions)
1. `Check` - 208 edges
2. `datetime` - 170 edges
3. `_send()` - 148 edges
4. `_base_form()` - 142 edges
5. `_latest_state()` - 119 edges
6. `_create_reserved_conversation()` - 111 edges
7. `_refresh_handler_globals()` - 73 edges
8. `str` - 71 edges
9. `date` - 60 edges
10. `Any` - 56 edges

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
- 1-file cycle: `scripts/local_regression_suite.py -> scripts/local_regression_suite.py`

## Communities (26 total, 17 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.09
Nodes (89): AIProviderUnavailable, Any, datetime, int, str, _AwaitingConfirmationCallbacks, bool, _CancelFlowCallbacks (+81 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (80): _base_form(), Check, Deterministic regression tests for the booking bot.  The suite stubs AI/paymen, _test_abort_current_draft_from_upsell_refusal(), _test_abort_current_draft_keeps_contact(), _test_addon_price_question_does_not_add_item(), _test_afternoon_time_words_parse_pm(), _test_ai_semantic_price_question_without_price_keywords() (+72 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (82): _create_reserved_conversation(), _latest_state(), _send(), _test_addon_price_during_upsell_does_not_repeat_event_format(), _test_addon_prices_plural_question_replies_immediately(), _test_ai_event_format_is_not_invented(), _test_bare_human_word_during_gazebo_choice_does_not_handoff(), _test_bare_ne_first_upsell_gets_soft_push() (+74 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (63): date, _add_paid_booking(), _add_paid_payment_for_latest_booking(), _create_active_hold(), _create_paid_booking_for_action(), _create_waitlist_request(), Any, datetime (+55 more)

### Community 4 - "Community 4"
Cohesion: 0.14
Nodes (18): Grill Sets, Hookah Service, Addons Pricing, Booking Logic, Bot Assistant Любовь, Gazebos Services, Guest House, Client Runtime Knowledge Base (+10 more)

### Community 5 - "Community 5"
Cohesion: 0.20
Nodes (14): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Bathhouse Object, Bathhouse Prices, Беседки (+6 more)

### Community 6 - "Community 6"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 7 - "Community 7"
Cohesion: 0.24
Nodes (9): _build_cases_by_name(), _cases_for_listing(), _cleanup(), _FakeWaitlistBot, install_regression_suite_lock(), main(), str, RegressionCase (+1 more)

### Community 8 - "Community 8"
Cohesion: 0.50
Nodes (5): Response Generator Prompt, Form Data Structure, JSON Response Schema, System Prompt, YCLIENTS Integration

## Knowledge Gaps
- **46 isolated node(s):** `_ReservedHoldCallbacks`, `_AwaitingConfirmationCallbacks`, `_NewBookingFlowCallbacks`, `_CancelFlowCallbacks`, `_RescheduleExecutionCallbacks` (+41 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_send()` connect `Community 2` to `Community 0`, `Community 1`, `Community 3`, `Community 7`?**
  _High betweenness centrality (0.298) - this node is a cross-community bridge._
- **Why does `IncomingMessage` connect `Community 0` to `Community 2`?**
  _High betweenness centrality (0.271) - this node is a cross-community bridge._
- **What connects `_ReservedHoldCallbacks`, `_AwaitingConfirmationCallbacks`, `_NewBookingFlowCallbacks` to the rest of the system?**
  _47 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.08739076154806492 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.06473953628425173 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.06504065040650407 - nodes in this community are weakly interconnected._
- **Should `Community 3` be split into smaller, more focused modules?**
  _Cohesion score 0.0931899641577061 - nodes in this community are weakly interconnected._