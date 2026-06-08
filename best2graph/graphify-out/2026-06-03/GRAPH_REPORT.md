# Graph Report - best2graph  (2026-06-03)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 398 nodes · 1517 edges · 35 communities (19 shown, 16 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 260 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9452bcab`
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

## God Nodes (most connected - your core abstractions)
1. `Any` - 146 edges
2. `str` - 105 edges
3. `_impl_handle_incoming()` - 96 edges
4. `_refresh_handler_globals()` - 68 edges
5. `str` - 65 edges
6. `Any` - 51 edges
7. `bool` - 44 edges
8. `_impl_handle_post_booking_message()` - 34 edges
9. `datetime` - 31 edges
10. `datetime` - 26 edges

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
- 1-file cycle: `app/services/dialog/date_parsing.py -> app/services/dialog/date_parsing.py`
- 1-file cycle: `app/services/dialog/new_booking_flow.py -> app/services/dialog/new_booking_flow.py`
- 1-file cycle: `app/services/message_handler.py -> app/services/message_handler.py`

## Communities (35 total, 16 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.10
Nodes (79): AIProviderUnavailable, Any, bool, datetime, int, str, _impl_ai_first_patch(), _impl_ai_guest_count_conflicts_with_date_context() (+71 more)

### Community 1 - "Community 1"
Cohesion: 0.08
Nodes (46): _AwaitingConfirmationCallbacks, _impl_awaiting_confirmation_callbacks(), _impl_handle_incoming(), IncomingMessage, _abort_current_draft(), _active_booking_info_callbacks(), _active_booking_reference_info_reply(), _ai_first_patch() (+38 more)

### Community 2 - "Community 2"
Cohesion: 0.09
Nodes (44): bool, int, str, _awaiting_confirmation_side_reply(), _bathhouse_guest_limit_exceeded(), _bathhouse_large_group_followup_reply(), _booking_ready(), _capacity_guest_patch() (+36 more)

### Community 3 - "Community 3"
Cohesion: 0.18
Nodes (32): _ActiveBookingInfoCallbacks, Any, bool, datetime, str, date, _AvailabilityExecutionCallbacks, context_service_for_generic_new_booking() (+24 more)

### Community 4 - "Community 4"
Cohesion: 0.09
Nodes (29): Any, _ai_should_start_fresh_booking(), _append_expected_question(), _available_services_reply(), _available_services_reply_for_active_bookings(), _bathhouse_capacity_mismatch_reply(), call_ai(), _capacity_info_reply() (+21 more)

### Community 5 - "Community 5"
Cohesion: 0.13
Nodes (22): datetime, _impl_start_reschedule_flow(), _create_hold(), _deterministic_patch(), _effective_message_time(), _fresh_booking_patch_from_ai(), _fresh_start_immediate_reply(), _handle_reschedule_flow() (+14 more)

### Community 6 - "Community 6"
Cohesion: 0.32
Nodes (20): bool, date, datetime, int, str, bare_day_patch(), bare_weekday_candidate(), bare_weekday_confirmation() (+12 more)

### Community 7 - "Community 7"
Cohesion: 0.12
Nodes (19): _impl_handle_post_booking_message(), _asks_available_services(), _asks_how_to_book_last_discussed_service(), _asks_specific_service_exists(), _cancel_flow_callbacks(), _classify_post_booking(), create_missing_yclients_records(), _current_request_summary() (+11 more)

### Community 8 - "Community 8"
Cohesion: 0.17
Nodes (17): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), База знаний администратора, Единая база знаний компании, Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Системный промпт (+9 more)

### Community 9 - "Community 9"
Cohesion: 0.18
Nodes (12): Addons Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base, Prepayment System (+4 more)

### Community 10 - "Community 10"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 11 - "Community 11"
Cohesion: 0.53
Nodes (8): _checkout_connection(), connect(), _connect_kwargs(), get_connection(), _get_pool(), _release_connection(), PgConnection, ThreadedConnectionPool

### Community 12 - "Community 12"
Cohesion: 0.25
Nodes (9): _impl_answer_info_during_form(), _answer_info_during_form(), _append_current_service_question(), _deterministic_info_reply(), _explicit_photo_reply(), _info_flow_callbacks(), _price_reply_if_known(), _reply_already_asks() (+1 more)

### Community 13 - "Community 13"
Cohesion: 0.29
Nodes (7): _CancelFlowCallbacks, _impl_cancel_flow_callbacks(), _impl_reschedule_execution_callbacks(), _RescheduleExecutionCallbacks, create_yclients_record_for_booking(), delete_yclients_record_for_booking(), upsert_local_busy_interval_for_booking()

### Community 14 - "Community 14"
Cohesion: 0.40
Nodes (5): _impl_build_reply(), _build_reply(), _clean_reply(), _fallback_reply(), _has_too_many_questions()

### Community 15 - "Community 15"
Cohesion: 0.50
Nodes (4): _impl_pending_additional_booking_reply(), _explicit_numeric_dates(), _pending_additional_booking_reply(), _question_text_for_key()

### Community 16 - "Community 16"
Cohesion: 0.50
Nodes (4): _impl_reserved_hold_callbacks(), _ReservedHoldCallbacks, _handle_reserved_hold_command(), _reserved_hold_callbacks()

### Community 17 - "Community 17"
Cohesion: 0.50
Nodes (4): _asks_booking_summary(), _asks_gazebo_options(), _should_route_existing_booking_command(), _starts_gazebo_browsing_after_booking()

### Community 18 - "Community 18"
Cohesion: 0.67
Nodes (3): _impl_new_booking_flow_callbacks(), _NewBookingFlowCallbacks, _new_booking_flow_callbacks()

## Knowledge Gaps
- **44 isolated node(s):** `int`, `_ReservedHoldCallbacks`, `_AwaitingConfirmationCallbacks`, `_NewBookingFlowCallbacks`, `_CancelFlowCallbacks` (+39 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Any` connect `Community 4` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 5`, `Community 7`, `Community 12`, `Community 13`, `Community 14`, `Community 15`, `Community 16`, `Community 17`, `Community 18`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `get_connection()` connect `Community 11` to `Community 1`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `_impl_handle_incoming()` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 11`, `Community 12`, `Community 14`, `Community 15`, `Community 16`, `Community 17`, `Community 18`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 90 inferred relationships involving `_impl_handle_incoming()` (e.g. with `get_connection()` and `_abort_current_draft()`) actually correct?**
  _`_impl_handle_incoming()` has 90 INFERRED edges - model-reasoned connections that need verification._
- **What connects `int`, `_ReservedHoldCallbacks`, `_AwaitingConfirmationCallbacks` to the rest of the system?**
  _44 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.09968354430379747 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.08233117483811286 - nodes in this community are weakly interconnected._