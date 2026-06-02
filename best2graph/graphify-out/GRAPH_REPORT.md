# Graph Report - best2graph  (2026-06-02)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 671 nodes · 3119 edges · 30 communities (21 shown, 9 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 149 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8e77c57a`
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

## God Nodes (most connected - your core abstractions)
1. `Check` - 192 edges
2. `str` - 168 edges
3. `datetime` - 154 edges
4. `main()` - 149 edges
5. `_send()` - 134 edges
6. `Any` - 130 edges
7. `_base_form()` - 126 edges
8. `_latest_state()` - 104 edges
9. `_create_reserved_conversation()` - 96 edges
10. `handle_incoming()` - 93 edges

## Surprising Connections (you probably didn't know these)
- `Баня` --semantically_similar_to--> `Объекты и услуги базы отдыха`  [INFERRED] [semantically similar]
  best2info/objects/bathhouse.md → app/knowledge/objects.md
- `Information Knowledge Base` --conceptually_related_to--> `Banya Image`  [INFERRED]
  information.md → app/images/banya.jpg
- `Information Knowledge Base` --conceptually_related_to--> `Besedka 1 Image`  [INFERRED]
  information.md → app/images/besedka1.jpg
- `Information Knowledge Base` --conceptually_related_to--> `Besedka 2 Image`  [INFERRED]
  information.md → app/images/besedka2.jpg
- `Information Knowledge Base` --conceptually_related_to--> `Besedka 3 Image`  [INFERRED]
  information.md → app/images/besedka3.jpg

## Import Cycles
- 1-file cycle: `app/db/repositories/payments_repo.py -> app/db/repositories/payments_repo.py`
- 1-file cycle: `app/services/dialog/confirmation_flow.py -> app/services/dialog/confirmation_flow.py`
- 1-file cycle: `app/services/dialog/info_flow.py -> app/services/dialog/info_flow.py`
- 1-file cycle: `app/services/message_handler.py -> app/services/message_handler.py`
- 1-file cycle: `scripts/local_regression_suite.py -> scripts/local_regression_suite.py`
- 1-file cycle: `app/services/payment_service.py -> app/services/payment_service.py`
- 1-file cycle: `app/services/payment_status_runner.py -> app/services/payment_status_runner.py`

## Communities (30 total, 9 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (71): _base_form(), Check, Deterministic regression tests for the booking bot.  The suite stubs AI/payment/, _test_abort_current_draft_keeps_contact(), _test_addon_price_question_does_not_add_item(), _test_afternoon_time_words_parse_pm(), _test_bare_duration_answer(), _test_bathhouse_gazebo_order_starts_with_bathhouse() (+63 more)

### Community 1 - "Community 1"
Cohesion: 0.10
Nodes (71): _cleanup(), _create_reserved_conversation(), _latest_state(), main(), _send(), _test_abort_current_draft_from_upsell_refusal(), _test_addon_price_during_upsell_does_not_repeat_event_format(), _test_addon_prices_plural_question_replies_immediately() (+63 more)

### Community 2 - "Community 2"
Cohesion: 0.10
Nodes (63): str, Any, bool, datetime, Decimal, int, PgConnection, str (+55 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (47): Any, datetime, _active_booking_reference_info_reply(), _ai_guest_count_conflicts_with_date_context(), _alternative_services_for_unavailable_date(), _append_expected_question(), _availability_execution_callbacks(), _awaiting_confirmation_side_reply() (+39 more)

### Community 4 - "Community 4"
Cohesion: 0.15
Nodes (43): _add_paid_booking(), _create_paid_booking_for_action(), date, datetime, _test_ack_after_cancel_does_not_say_booking_fixed(), _test_admin_notification_includes_booking_object(), _test_ai_change_type_cancel_starts_flow(), _test_ai_change_type_reschedule_starts_flow() (+35 more)

### Community 5 - "Community 5"
Cohesion: 0.17
Nodes (38): Any, int, str, Any, bool, datetime, int, str (+30 more)

### Community 6 - "Community 6"
Cohesion: 0.10
Nodes (38): _asks_how_to_book_last_discussed_service(), _available_services_reply(), _available_services_reply_for_active_bookings(), _cancel_flow_callbacks(), _classify_post_booking(), _contextual_upsell_accept_patch(), create_missing_yclients_records(), create_yclients_record_for_booking() (+30 more)

### Community 7 - "Community 7"
Cohesion: 0.10
Nodes (39): bool, _abort_current_draft(), _ai_guest_count_conflicts_with_gazebo_variant(), _asks_available_services(), _asks_booking_summary(), _asks_specific_service_exists(), _bathhouse_guest_limit_exceeded(), _changes_booking_core_fields() (+31 more)

### Community 8 - "Community 8"
Cohesion: 0.21
Nodes (31): _ActiveBookingInfoCallbacks, AIProviderUnavailable, Any, bool, datetime, str, _AvailabilityExecutionCallbacks, _AwaitingConfirmationCallbacks (+23 more)

### Community 9 - "Community 9"
Cohesion: 0.24
Nodes (26): Any, bool, int, str, apply_gazebo_default_duration(), apply_open_ended_default_duration(), bare_duration_from_text(), default_duration_until_morning_from_time() (+18 more)

### Community 10 - "Community 10"
Cohesion: 0.16
Nodes (26): int, str, _ai_process_reply(), _answer_info_during_form(), _append_current_service_question(), _asks_gazebo_options(), _booking_ready(), _build_reply() (+18 more)

### Community 11 - "Community 11"
Cohesion: 0.12
Nodes (23): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), База знаний администратора, Единая база знаний компании, Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Системный промпт (+15 more)

### Community 12 - "Community 12"
Cohesion: 0.12
Nodes (21): _add_paid_payment_for_latest_booking(), _create_waitlist_request(), _FakeWaitlistBot, install_regression_suite_lock(), Any, int, str, _test_basic_upsell_is_saved_to_yclients_comment() (+13 more)

### Community 13 - "Community 13"
Cohesion: 0.36
Nodes (19): Any, datetime, Decimal, int, PgConnection, str, attach_provider_response(), create_pending() (+11 more)

### Community 14 - "Community 14"
Cohesion: 0.33
Nodes (19): Any, bool, str, addon_price_followup(), addon_price_reply(), bathhouse_extended_price_reply(), discount_reply_if_known(), duration_price_rule_reply() (+11 more)

### Community 15 - "Community 15"
Cohesion: 0.16
Nodes (18): _ai_first_patch(), _confirmation_no(), _confirmation_yes(), _current_step_patch(), _effective_message_time(), _expected_guest_count_patch(), _expected_step_detected_patch(), _guest_count_answer_without_time() (+10 more)

### Community 16 - "Community 16"
Cohesion: 0.18
Nodes (13): Addons Pricing, Bathhouse Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base (+5 more)

### Community 17 - "Community 17"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 18 - "Community 18"
Cohesion: 0.22
Nodes (10): date, _apply_contextual_day_number_patch(), _context_date_for_day_number(), _contextual_day_number(), _explicit_numeric_dates(), _has_explicit_month_name(), _multi_gazebo_booking_patch(), _parallel_booking_question_reply() (+2 more)

### Community 19 - "Community 19"
Cohesion: 0.36
Nodes (9): _ai_should_start_fresh_booking(), _context_service_for_generic_new_booking(), _continues_current_draft_service_switch(), _fresh_booking_form_data_for_text(), _generic_new_booking_request(), _restore_draft_context_after_service_switch(), _should_start_fresh_booking(), _starts_new_booking_request() (+1 more)

### Community 20 - "Community 20"
Cohesion: 0.25
Nodes (8): _create_active_hold(), _test_fake_payment_request_does_not_mark_paid(), _test_generic_second_booking_keeps_only_contact(), _test_next_application_while_hold_starts_blank_not_ice(), _test_paid_status_refreshes_on_any_message(), _test_payment_intent_retry_no_duplicate_link(), _test_reserved_yes_retries_payment_link(), _test_reserved_yes_reuses_existing_payment_link()

## Knowledge Gaps
- **38 isolated node(s):** `str`, `int`, `Project Rules for best2`, `Graphify Workflow`, `LLM Wiki Workflow` (+33 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `Community 2` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 12`, `Community 14`, `Community 15`, `Community 20`?**
  _High betweenness centrality (0.149) - this node is a cross-community bridge._
- **Why does `handle_incoming()` connect `Community 7` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 6`, `Community 8`, `Community 10`, `Community 12`, `Community 15`, `Community 18`, `Community 19`?**
  _High betweenness centrality (0.141) - this node is a cross-community bridge._
- **Why does `ZoneInfo` connect `Community 2` to `Community 0`, `Community 1`, `Community 4`, `Community 6`, `Community 7`, `Community 8`, `Community 12`, `Community 15`, `Community 20`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `str` (e.g. with `AwaitingConfirmationCallbacks` and `ReservedHoldCallbacks`) actually correct?**
  _`str` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `str`, `int`, `Normalize duration to hours for form_data and availability checks.` to the rest of the system?**
  _41 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.07191780821917808 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.09738430583501007 - nodes in this community are weakly interconnected._