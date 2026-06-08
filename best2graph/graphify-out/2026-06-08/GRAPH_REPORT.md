# Graph Report - best2graph  (2026-06-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 220 nodes · 526 edges · 39 communities (15 shown, 24 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 30 edges (avg confidence: 0.82)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8ea2eae3`
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
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]

## God Nodes (most connected - your core abstractions)
1. `_refresh_handler_globals()` - 72 edges
2. `str` - 69 edges
3. `Any` - 55 edges
4. `datetime` - 34 edges
5. `bool` - 19 edges
6. `str` - 11 edges
7. `InfoFlowCallbacks` - 10 edges
8. `Information Knowledge Base` - 10 edges
9. `deterministic_info_reply()` - 9 edges
10. `contextual_photo_reply()` - 9 edges

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
- 1-file cycle: `app/services/dialog/info_flow.py -> app/services/dialog/info_flow.py`
- 1-file cycle: `app/services/dialog/post_booking_flow.py -> app/services/dialog/post_booking_flow.py`

## Communities (39 total, 24 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.15
Nodes (45): Any, datetime, str, _impl_ai_first_patch(), _impl_ai_process_reply(), _impl_answer_info_during_form(), _impl_append_expected_question(), _impl_apply_contextual_day_number_patch() (+37 more)

### Community 1 - "Community 1"
Cohesion: 0.20
Nodes (26): Any, bool, datetime, str, active_booking_reference_info_reply(), ActiveBookingInfoCallbacks, answer_info_during_form(), append_current_service_question() (+18 more)

### Community 2 - "Community 2"
Cohesion: 0.18
Nodes (21): bool, _impl_ai_guest_count_conflicts_with_date_context(), _impl_ai_guest_count_conflicts_with_gazebo_variant(), _impl_ai_should_start_fresh_booking(), _impl_asks_available_services(), _impl_asks_booking_summary(), _impl_asks_specific_service_exists(), _impl_confirmation_yes() (+13 more)

### Community 3 - "Community 3"
Cohesion: 0.20
Nodes (14): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Bathhouse Object, Bathhouse Prices, Беседки (+6 more)

### Community 4 - "Community 4"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 5 - "Community 5"
Cohesion: 0.42
Nodes (10): Any, bool, datetime, str, classify_post_booking_safely(), continues_booking_summary_question(), is_waitlist_decline(), payment_status_reply() (+2 more)

### Community 6 - "Community 6"
Cohesion: 0.25
Nodes (9): Addons Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base, Prepayment System (+1 more)

### Community 7 - "Community 7"
Cohesion: 0.42
Nodes (8): main(), _parse_events(), _print_payload(), Any, str, Prepare or apply YooKassa webhook registration.  Default mode is dry-run and doe, _redact_url(), _validate_webhook_url()

### Community 8 - "Community 8"
Cohesion: 0.32
Nodes (8): Backend System, Bot Main Rules, Gazebos Service, Payment and Booking System, Photo Management System, Sauna + Gazebo Combo, Sauna with Pool Service, YClients Integration

### Community 9 - "Community 9"
Cohesion: 0.48
Nodes (6): main(), Any, str, Read-only YooKassa configuration and webhook status check., _redact_url(), _webhook_items()

### Community 10 - "Community 10"
Cohesion: 0.33
Nodes (6): _impl_free_dates_after_unavailable_route(), _impl_gazebo_capacity_change_request(), _impl_handle_incoming(), _impl_same_unavailable_date_route(), _impl_unavailable_alternatives_route(), IncomingMessage

### Community 11 - "Community 11"
Cohesion: 0.50
Nodes (5): AIProviderUnavailable, _impl_expected_guest_count_patch(), _impl_log_ai_provider_unavailable(), _impl_log_ai_semantic_degraded(), int

### Community 12 - "Community 12"
Cohesion: 0.40
Nodes (5): Base Knowledge File, Runtime Knowledge Base, Objects Knowledge File, Prices Knowledge File, YClients IDs Knowledge File

### Community 13 - "Community 13"
Cohesion: 0.50
Nodes (5): Response Generator Prompt, Form Data Structure, JSON Response Schema, System Prompt, YCLIENTS Integration

### Community 14 - "Community 14"
Cohesion: 0.33
Nodes (4): _impl_new_booking_flow_callbacks(), _impl_reserved_hold_callbacks(), _NewBookingFlowCallbacks, _ReservedHoldCallbacks

## Knowledge Gaps
- **58 isolated node(s):** `_ReservedHoldCallbacks`, `_AwaitingConfirmationCallbacks`, `_NewBookingFlowCallbacks`, `_CancelFlowCallbacks`, `_RescheduleExecutionCallbacks` (+53 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **24 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_explicit_photo_reply()` connect `Community 1` to `Community 0`, `Community 10`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `_refresh_handler_globals()` connect `Community 2` to `Community 0`, `Community 10`, `Community 11`, `Community 14`, `Community 16`, `Community 17`, `Community 19`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `str` connect `Community 0` to `Community 10`, `Community 2`, `Community 11`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **What connects `_ReservedHoldCallbacks`, `_AwaitingConfirmationCallbacks`, `_NewBookingFlowCallbacks` to the rest of the system?**
  _61 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.14589371980676327 - nodes in this community are weakly interconnected._