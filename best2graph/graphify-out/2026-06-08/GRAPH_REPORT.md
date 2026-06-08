# Graph Report - best2graph  (2026-06-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 311 nodes · 773 edges · 41 communities (16 shown, 25 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 70 edges (avg confidence: 0.63)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8bfceccc`
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
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]

## God Nodes (most connected - your core abstractions)
1. `Any` - 148 edges
2. `str` - 107 edges
3. `bool` - 46 edges
4. `datetime` - 28 edges
5. `InfoFlowCallbacks` - 26 edges
6. `InfoQuestionCallbacks` - 18 edges
7. `ActiveBookingInfoCallbacks` - 18 edges
8. `str` - 11 edges
9. `deterministic_info_reply()` - 11 edges
10. `contextual_photo_reply()` - 11 edges

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
- 1-file cycle: `app/services/message_handler.py -> app/services/message_handler.py`

## Communities (41 total, 25 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (55): bool, str, _asks_booking_summary(), _asks_gazebo_options(), _asks_how_to_book_last_discussed_service(), _bathhouse_guest_limit_exceeded(), _booking_ready(), _changes_booking_core_fields() (+47 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (42): Any, _ai_guest_count_conflicts_with_date_context(), _ai_guest_count_conflicts_with_gazebo_variant(), _ai_should_start_fresh_booking(), _answer_info_during_form(), _append_expected_question(), _asks_available_services(), _awaiting_confirmation_callbacks() (+34 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (41): _abort_current_draft(), _ai_first_patch(), _ai_process_reply(), _apply_contextual_day_number_patch(), _asks_specific_service_exists(), check_availability(), classify_post_booking_message(), _commit_assistant_response() (+33 more)

### Community 3 - "Community 3"
Cohesion: 0.18
Nodes (29): Any, bool, datetime, str, _InfoFlowCallbacks, active_booking_reference_info_reply(), answer_info_during_form(), append_current_service_question() (+21 more)

### Community 4 - "Community 4"
Cohesion: 0.13
Nodes (19): datetime, _alternative_services_for_unavailable_date(), _cancel_flow_callbacks(), _classify_post_booking(), _create_hold(), _deterministic_patch(), _fresh_booking_patch_from_ai(), _fresh_start_immediate_reply() (+11 more)

### Community 5 - "Community 5"
Cohesion: 0.16
Nodes (19): _ActiveBookingInfoCallbacks, _AvailabilityExecutionCallbacks, date, ActiveBookingInfoCallbacks, InfoQuestionCallbacks, _InfoQuestionCallbacks, _active_booking_info_callbacks(), _active_booking_reference_info_reply() (+11 more)

### Community 6 - "Community 6"
Cohesion: 0.20
Nodes (14): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Bathhouse Object, Bathhouse Prices, Беседки (+6 more)

### Community 7 - "Community 7"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 8 - "Community 8"
Cohesion: 0.25
Nodes (9): Addons Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base, Prepayment System (+1 more)

### Community 9 - "Community 9"
Cohesion: 0.32
Nodes (8): Backend System, Bot Main Rules, Gazebos Service, Payment and Booking System, Photo Management System, Sauna + Gazebo Combo, Sauna with Pool Service, YClients Integration

### Community 10 - "Community 10"
Cohesion: 0.29
Nodes (8): int, _bathhouse_large_group_followup_reply(), _capacity_guest_patch(), _contextual_day_number(), _large_group_manual_reply(), _last_rejected_guest_count(), _next_free_dates_reply(), _persist_user_profile()

### Community 11 - "Community 11"
Cohesion: 0.50
Nodes (5): Response Generator Prompt, Form Data Structure, JSON Response Schema, System Prompt, YCLIENTS Integration

### Community 12 - "Community 12"
Cohesion: 0.40
Nodes (5): Base Knowledge File, Runtime Knowledge Base, Objects Knowledge File, Prices Knowledge File, YClients IDs Knowledge File

### Community 13 - "Community 13"
Cohesion: 0.50
Nodes (4): _execute_reschedule(), _execute_swap_reschedule(), _reschedule_execution_callbacks(), _restore_booking_after_failed_reschedule()

### Community 14 - "Community 14"
Cohesion: 0.67
Nodes (3): _available_services_reply(), _available_services_reply_for_active_bookings(), _primary_service_type_from_bookings()

### Community 15 - "Community 15"
Cohesion: 0.67
Nodes (3): _bathhouse_capacity_mismatch_reply(), _capacity_mismatch_reply(), _gazebo_capacity_mismatch_reply()

## Knowledge Gaps
- **50 isolated node(s):** `Project Rules for best2`, `Graphify Workflow`, `LLM Wiki Workflow`, `PLAN.md - Development Plan`, `База знаний администратора` (+45 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Any` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 10`, `Community 13`, `Community 14`, `Community 15`, `Community 17`, `Community 18`, `Community 19`, `Community 20`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Why does `str` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 10`, `Community 13`, `Community 14`, `Community 15`, `Community 17`, `Community 18`, `Community 19`, `Community 20`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `InfoFlowCallbacks` connect `Community 3` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 5`, `Community 10`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `Any` (e.g. with `ActiveBookingInfoCallbacks` and `InfoFlowCallbacks`) actually correct?**
  _`Any` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `str` (e.g. with `ActiveBookingInfoCallbacks` and `InfoFlowCallbacks`) actually correct?**
  _`str` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `bool` (e.g. with `ActiveBookingInfoCallbacks` and `InfoFlowCallbacks`) actually correct?**
  _`bool` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `datetime` (e.g. with `ActiveBookingInfoCallbacks` and `InfoFlowCallbacks`) actually correct?**
  _`datetime` has 3 INFERRED edges - model-reasoned connections that need verification._