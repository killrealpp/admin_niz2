# Graph Report - best2graph  (2026-06-02)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 450 nodes · 2201 edges · 19 communities (13 shown, 6 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 44 edges (avg confidence: 0.77)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `fe31fd7d`
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

## God Nodes (most connected - your core abstractions)
1. `Check` - 182 edges
2. `str` - 159 edges
3. `datetime` - 149 edges
4. `main()` - 143 edges
5. `_send()` - 129 edges
6. `Any` - 122 edges
7. `_base_form()` - 119 edges
8. `_latest_state()` - 99 edges
9. `handle_incoming()` - 95 edges
10. `_create_reserved_conversation()` - 92 edges

## Surprising Connections (you probably didn't know these)
- `Баня` --semantically_similar_to--> `Объекты и услуги базы отдыха`  [INFERRED] [semantically similar]
  best2info/objects/bathhouse.md → app/knowledge/objects.md
- `Допы` --semantically_similar_to--> `Цены и предоплата`  [INFERRED] [semantically similar]
  best2info/prices/addons.md → app/knowledge/prices.md
- `Цены на баню` --semantically_similar_to--> `Цены и предоплата`  [INFERRED] [semantically similar]
  best2info/prices/bathhouse.md → app/knowledge/prices.md
- `Цены на беседки` --semantically_similar_to--> `Цены и предоплата`  [INFERRED] [semantically similar]
  best2info/prices/gazebos.md → app/knowledge/prices.md
- `Цены на гостевой дом` --semantically_similar_to--> `Цены и предоплата`  [INFERRED] [semantically similar]
  best2info/prices/house.md → app/knowledge/prices.md

## Import Cycles
- 1-file cycle: `app/services/message_handler.py -> app/services/message_handler.py`
- 1-file cycle: `scripts/local_regression_suite.py -> scripts/local_regression_suite.py`

## Communities (19 total, 6 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (70): _base_form(), Check, _cleanup(), Deterministic regression tests for the booking bot.  The suite stubs AI/payment/, _test_addon_price_question_does_not_add_item(), _test_addon_prices_plural_question_replies_immediately(), _test_afternoon_time_words_parse_pm(), _test_ai_semantic_price_question_without_price_keywords() (+62 more)

### Community 1 - "Community 1"
Cohesion: 0.08
Nodes (64): _create_reserved_conversation(), _latest_state(), _send(), _test_abort_current_draft_from_upsell_refusal(), _test_abort_current_draft_keeps_contact(), _test_addon_price_during_upsell_does_not_repeat_event_format(), _test_ai_event_format_is_not_invented(), _test_bathhouse_blocks_large_group() (+56 more)

### Community 2 - "Community 2"
Cohesion: 0.10
Nodes (58): str, bool, _abort_current_draft(), _ai_guest_count_conflicts_with_gazebo_variant(), _ai_should_start_fresh_booking(), _asks_available_services(), _asks_booking_summary(), _asks_specific_service_exists() (+50 more)

### Community 3 - "Community 3"
Cohesion: 0.13
Nodes (53): _create_paid_booking_for_action(), main(), date, datetime, _test_ack_after_cancel_does_not_say_booking_fixed(), _test_admin_notification_includes_booking_object(), _test_ai_change_type_cancel_starts_flow(), _test_ai_change_type_reschedule_starts_flow() (+45 more)

### Community 4 - "Community 4"
Cohesion: 0.10
Nodes (35): _AwaitingConfirmationCallbacks, _CancelFlowCallbacks, _RescheduleExecutionCallbacks, _ReservedHoldCallbacks, _asks_how_to_book_last_discussed_service(), _awaiting_confirmation_callbacks(), _cancel_flow_callbacks(), _classify_post_booking() (+27 more)

### Community 5 - "Community 5"
Cohesion: 0.10
Nodes (31): Any, _alternative_services_for_unavailable_date(), _append_expected_question(), _available_services_reply(), _available_services_reply_for_active_bookings(), _awaiting_confirmation_side_reply(), _bathhouse_capacity_mismatch_reply(), _booking_ready() (+23 more)

### Community 6 - "Community 6"
Cohesion: 0.11
Nodes (30): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), База знаний администратора, Клиентская база знаний, Единая база знаний компании, Объекты и услуги базы отдыха, Цены и предоплата (+22 more)

### Community 7 - "Community 7"
Cohesion: 0.13
Nodes (30): datetime, _active_booking_reference_info_reply(), _ai_first_patch(), _confirmation_no(), _confirmation_yes(), _create_hold(), _current_step_patch(), _deterministic_patch() (+22 more)

### Community 8 - "Community 8"
Cohesion: 0.19
Nodes (18): _add_paid_booking(), _add_paid_payment_for_latest_booking(), _create_active_hold(), _create_waitlist_request(), _FakeWaitlistBot, install_regression_suite_lock(), Any, int (+10 more)

### Community 9 - "Community 9"
Cohesion: 0.15
Nodes (19): _ai_process_reply(), _answer_info_during_form(), _append_current_service_question(), _asks_gazebo_options(), _build_reply(), _capacity_guest_patch(), _capacity_info_reply(), _clean_reply() (+11 more)

### Community 10 - "Community 10"
Cohesion: 0.18
Nodes (13): AIProviderUnavailable, date, int, _ai_guest_count_conflicts_with_date_context(), _apply_contextual_day_number_patch(), _context_date_for_day_number(), _contextual_day_number(), _date_numbers_from_context() (+5 more)

### Community 11 - "Community 11"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 12 - "Community 12"
Cohesion: 0.40
Nodes (5): _AvailabilityExecutionCallbacks, _availability_execution_callbacks(), _execute_availability_check(), _fast_entry_reply(), _is_plain_greeting()

## Knowledge Gaps
- **31 isolated node(s):** `_ReservedHoldCallbacks`, `_AwaitingConfirmationCallbacks`, `_CancelFlowCallbacks`, `_SwapRescheduleCallbacks`, `_RescheduleExecutionCallbacks` (+26 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `handle_incoming()` connect `Community 2` to `Community 0`, `Community 1`, `Community 4`, `Community 5`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 12`?**
  _High betweenness centrality (0.283) - this node is a cross-community bridge._
- **Why does `_send()` connect `Community 1` to `Community 0`, `Community 8`, `Community 2`, `Community 3`?**
  _High betweenness centrality (0.108) - this node is a cross-community bridge._
- **Why does `IncomingMessage` connect `Community 8` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **What connects `_ReservedHoldCallbacks`, `_AwaitingConfirmationCallbacks`, `_CancelFlowCallbacks` to the rest of the system?**
  _33 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.07237871674491393 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.0818452380952381 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.10405323653962492 - nodes in this community are weakly interconnected._