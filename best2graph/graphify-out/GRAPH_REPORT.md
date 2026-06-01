# Graph Report - best2graph  (2026-06-01)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1704 nodes · 6968 edges · 68 communities (62 shown, 6 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 346 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7ee0f3fc`
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
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]

## God Nodes (most connected - your core abstractions)
1. `Check` - 177 edges
2. `get_connection()` - 175 edges
3. `str` - 158 edges
4. `datetime` - 145 edges
5. `main()` - 135 edges
6. `Any` - 123 edges
7. `_send()` - 122 edges
8. `_base_form()` - 115 edges
9. `get_settings()` - 108 edges
10. `handle_incoming()` - 101 edges

## Surprising Connections (you probably didn't know these)
- `Information Knowledge Base` --conceptually_related_to--> `Banya Image`  [INFERRED]
  information.md → app/images/banya.jpg
- `Information Knowledge Base` --conceptually_related_to--> `Besedka 1 Image`  [INFERRED]
  information.md → app/images/besedka1.jpg
- `Information Knowledge Base` --conceptually_related_to--> `Besedka 2 Image`  [INFERRED]
  information.md → app/images/besedka2.jpg
- `Information Knowledge Base` --conceptually_related_to--> `Besedka 3 Image`  [INFERRED]
  information.md → app/images/besedka3.jpg
- `Information Knowledge Base` --conceptually_related_to--> `Besedka 4 Image`  [INFERRED]
  information.md → app/images/besedka4.jpg

## Import Cycles
- 1-file cycle: `app/ai/ai_orchestrator.py -> app/ai/ai_orchestrator.py`
- 1-file cycle: `app/ai/openai_client.py -> app/ai/openai_client.py`
- 1-file cycle: `app/bot/telegram_bot.py -> app/bot/telegram_bot.py`
- 1-file cycle: `app/db/repositories/bookings_repo.py -> app/db/repositories/bookings_repo.py`
- 1-file cycle: `app/db/repositories/conversation_summaries_repo.py -> app/db/repositories/conversation_summaries_repo.py`
- 1-file cycle: `app/db/repositories/conversations_repo.py -> app/db/repositories/conversations_repo.py`
- 1-file cycle: `app/db/repositories/payments_repo.py -> app/db/repositories/payments_repo.py`
- 1-file cycle: `app/db/repositories/slot_holds_repo.py -> app/db/repositories/slot_holds_repo.py`
- 1-file cycle: `app/db/repositories/users_repo.py -> app/db/repositories/users_repo.py`
- 1-file cycle: `app/db/repositories/waitlist_repo.py -> app/db/repositories/waitlist_repo.py`
- 1-file cycle: `app/db/repositories/yclients_records_repo.py -> app/db/repositories/yclients_records_repo.py`
- 1-file cycle: `app/integrations/yookassa_client.py -> app/integrations/yookassa_client.py`
- 1-file cycle: `app/services/availability_service.py -> app/services/availability_service.py`
- 1-file cycle: `app/services/conversation_service.py -> app/services/conversation_service.py`
- 1-file cycle: `app/services/dialog/availability_flow.py -> app/services/dialog/availability_flow.py`
- 1-file cycle: `app/services/dialog/booking_context.py -> app/services/dialog/booking_context.py`
- 1-file cycle: `app/services/dialog/cancel_flow.py -> app/services/dialog/cancel_flow.py`
- 1-file cycle: `app/services/dialog/confirmation_flow.py -> app/services/dialog/confirmation_flow.py`
- 1-file cycle: `app/services/dialog/date_parsing.py -> app/services/dialog/date_parsing.py`
- 1-file cycle: `app/services/dialog/handoff.py -> app/services/dialog/handoff.py`

## Communities (68 total, 6 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (203): AIResponse, PostBookingResponse, BaseModel, get_connection(), main(), main(), Clear all application data while keeping the database schema., main() (+195 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (117): Any, bool, datetime, int, str, bool, date, datetime (+109 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (92): Any, int, str, Any, bool, datetime, int, PgConnection (+84 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (86): build_user_prompt(), call_ai(), _chat_completion(), classify_post_booking_message(), _extract_json(), _format_history(), _format_summaries(), generate_final_reply() (+78 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (79): AiohttpSession, bool, datetime, Message, str, Any, str, Any (+71 more)

### Community 5 - "Community 5"
Cohesion: 0.11
Nodes (51): Any, bool, str, Any, bool, str, Any, bool (+43 more)

### Community 6 - "Community 6"
Cohesion: 0.10
Nodes (46): Any, date, int, PgConnection, str, time, bool, Bot (+38 more)

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (46): Any, trace_span(), new_booking_form_data(), _abort_current_draft(), _alternative_services_for_unavailable_date(), _awaiting_confirmation_side_reply(), _bathhouse_capacity_mismatch_reply(), call_ai() (+38 more)

### Community 8 - "Community 8"
Cohesion: 0.12
Nodes (41): str, next_question(), _ai_process_reply(), _answer_info_during_form(), _append_current_service_question(), _append_expected_question(), _asks_available_services(), _asks_booking_summary() (+33 more)

### Community 9 - "Community 9"
Cohesion: 0.25
Nodes (38): AIResponse, context_ai_understands_guest_without_keyword(), context_bathhouse_large_group_blocks_before_format(), context_confirmation_no_means_not_confirmed(), context_confirmation_summary_then_abort(), context_confirmation_time_change_and_typo_summary(), context_date_and_guests_uses_availability(), context_date_only_does_not_become_guests() (+30 more)

### Community 10 - "Community 10"
Cohesion: 0.18
Nodes (38): AIProviderUnavailable, date, datetime, int, ZoneInfo, _AvailabilityExecutionCallbacks, _AwaitingConfirmationCallbacks, _CancelFlowCallbacks (+30 more)

### Community 11 - "Community 11"
Cohesion: 0.13
Nodes (34): bool, _ai_first_patch(), _ai_guest_count_conflicts_with_gazebo_variant(), _bathhouse_guest_limit_exceeded(), _changes_booking_core_fields(), _complains_guest_count_not_asked(), _confirmation_no(), _confirmation_yes() (+26 more)

### Community 12 - "Community 12"
Cohesion: 0.27
Nodes (32): _confirmation_conversation(), _draft_conversation(), edge_cancel_info_question(), edge_cancel_no_then_reschedule(), edge_cancel_unrelated_question(), edge_confirmation_cancel_immediately(), edge_confirmation_info_then_yes(), edge_confirmation_summary_question() (+24 more)

### Community 13 - "Community 13"
Cohesion: 0.17
Nodes (30): Any, bool, str, Any, bool, float, int, str (+22 more)

### Community 14 - "Community 14"
Cohesion: 0.06
Nodes (31): audio-recorder, backlink, bases, bookmarks, canvas, command-palette, daily-notes, editor-status (+23 more)

### Community 15 - "Community 15"
Cohesion: 0.25
Nodes (31): Any, date, datetime, int, PgConnection, str, time, cancel_by_hold() (+23 more)

### Community 16 - "Community 16"
Cohesion: 0.17
Nodes (29): Any, Message, str, normalize_incoming(), normalize_telegram_message(), normalize_telegram_voice_message(), Unified entry for future MAX / VK adapters., IncomingMessage (+21 more)

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (30): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), База знаний администратора, Клиентская база знаний, Единая база знаний компании, Объекты и услуги базы отдыха, Цены и предоплата (+22 more)

### Community 18 - "Community 18"
Cohesion: 0.26
Nodes (29): Any, bool, date, datetime, int, str, CancelFlowResult, advance_refund_allowed() (+21 more)

### Community 19 - "Community 19"
Cohesion: 0.07
Nodes (29): active, bases:Создать новую базу, canvas:Создать новый холст, command-palette:Открыть палитру команд, daily-notes:Сегодняшняя заметка, graph:Граф, switcher:Меню быстрого перехода, templates:Вставить шаблон (+21 more)

### Community 20 - "Community 20"
Cohesion: 0.28
Nodes (27): Any, bool, datetime, Decimal, int, PgConnection, str, YooKassaError (+19 more)

### Community 21 - "Community 21"
Cohesion: 0.15
Nodes (23): Any, float, str, Any, int, str, current_trace(), PerformanceTrace (+15 more)

### Community 22 - "Community 22"
Cohesion: 0.26
Nodes (24): Any, bool, date, datetime, int, PgConnection, str, time (+16 more)

### Community 23 - "Community 23"
Cohesion: 0.30
Nodes (24): _contains_all(), main(), _now(), _print_result(), bool, datetime, str, Stress scenarios with unusual client phrasing.  This suite is intentionally clos (+16 more)

### Community 24 - "Community 24"
Cohesion: 0.17
Nodes (18): bool, PgConnection, run_bot(), get_settings(), setup_logging(), _checkout_connection(), connect(), _connect_kwargs() (+10 more)

### Community 25 - "Community 25"
Cohesion: 0.22
Nodes (21): Any, bool, str, wants_cancel_booking(), service_type_patch(), ai_should_start_fresh_booking(), should_start_fresh_booking(), wants_multi_booking_reschedule() (+13 more)

### Community 26 - "Community 26"
Cohesion: 0.20
Nodes (21): int, event_format_patch(), guests_count_patch(), phone_patch(), service_variant_patch(), duration_from_text(), time_period_patch(), _asks_specific_service_exists() (+13 more)

### Community 27 - "Community 27"
Cohesion: 0.10
Nodes (20): centerStrength, close, collapse-color-groups, collapse-display, collapse-filter, collapse-forces, colorGroups, hideUnresolved (+12 more)

### Community 28 - "Community 28"
Cohesion: 0.32
Nodes (19): Any, bool, datetime, int, PgConnection, str, delete_busy_interval(), delete_record_by_id() (+11 more)

### Community 29 - "Community 29"
Cohesion: 0.37
Nodes (18): Any, datetime, Decimal, int, PgConnection, str, attach_provider_response(), create_pending() (+10 more)

### Community 30 - "Community 30"
Cohesion: 0.15
Nodes (14): AbstractEventLoop, Any, bool, Bot, str, BaseHTTPRequestHandler, Future, HTTPStatus (+6 more)

### Community 31 - "Community 31"
Cohesion: 0.13
Nodes (16): Any, bool, datetime, int, PgConnection, str, Any, bool (+8 more)

### Community 32 - "Community 32"
Cohesion: 0.14
Nodes (18): AI Booking Administrator, Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image (+10 more)

### Community 33 - "Community 33"
Cohesion: 0.20
Nodes (17): bool, asks_reschedule_options(), initial_reschedule_flow_patch(), means_change_object(), means_same_date(), means_same_object(), means_same_time(), referenced_service_type_for_same_time() (+9 more)

### Community 34 - "Community 34"
Cohesion: 0.25
Nodes (7): Any, Decimal, str, YooKassaClient, main(), Register YooKassa webhooks from YOOKASSA_WEBHOOK_URL.  Usage:     python scripts, main()

### Community 35 - "Community 35"
Cohesion: 0.36
Nodes (15): Any, bool, Bot, datetime, int, str, _date_ru(), _duration_minutes() (+7 more)

### Community 36 - "Community 36"
Cohesion: 0.33
Nodes (15): _check_fixed_service_prices(), _check_gazebo_prices(), _check_single_price(), _load_services_map(), main(), _markdown_files(), _money(), Any (+7 more)

### Community 37 - "Community 37"
Cohesion: 0.45
Nodes (14): Any, int, PgConnection, str, _client_name_for_hold(), _conversation_form_data(), _existing_booking_ids(), _field_from_conversation() (+6 more)

### Community 38 - "Community 38"
Cohesion: 0.40
Nodes (14): Any, datetime, int, PgConnection, str, clear_handoff(), create(), find_by_external_id() (+6 more)

### Community 39 - "Community 39"
Cohesion: 0.34
Nodes (14): Any, date, datetime, int, PgConnection, str, time, close_for_user() (+6 more)

### Community 40 - "Community 40"
Cohesion: 0.49
Nodes (10): Any, datetime, int, PgConnection, str, create(), expire_stale(), find_active_for_user() (+2 more)

### Community 41 - "Community 41"
Cohesion: 0.25
Nodes (8): DummyConnection, FakeSettings, main(), int, object, str, Smoke-test YooKassa webhook request hardening without external side effects., request_json()

### Community 42 - "Community 42"
Cohesion: 0.51
Nodes (9): Any, int, PgConnection, str, create(), delete_ids(), list_old_conversation_batches(), list_recent() (+1 more)

### Community 43 - "Community 43"
Cohesion: 0.49
Nodes (9): Any, bool, str, deterministic_process_reply(), fallback_process_reply(), _looks_like_internal_instruction(), looks_like_internal_instruction_text(), _looks_like_json_or_schema() (+1 more)

### Community 44 - "Community 44"
Cohesion: 0.40
Nodes (9): Any, bool, datetime, int, str, handoff_active(), is_location_question(), looks_like_handoff_needed() (+1 more)

### Community 45 - "Community 45"
Cohesion: 0.43
Nodes (7): datetime, int, PgConnection, str, create(), list_for_conversation(), list_for_user()

### Community 46 - "Community 46"
Cohesion: 0.46
Nodes (7): Any, int, PgConnection, str, create(), list_admin_unnotified(), mark_admin_notified()

### Community 47 - "Community 47"
Cohesion: 0.29
Nodes (7): Any, bool, int, PgConnection, str, create_if_new(), mark_processed()

### Community 48 - "Community 48"
Cohesion: 0.32
Nodes (7): Namespace, _digits(), _load_candidates(), main(), object, str, Dry-run first cleanup for bot-created test records in YCLIENTS.  The script is i

### Community 49 - "Community 49"
Cohesion: 0.60
Nodes (5): bool, str, asks_for_free_slots(), asks_nearest_free_dates(), _fresh_start_immediate_reply()

### Community 50 - "Community 50"
Cohesion: 0.33
Nodes (3): str, BaseSettings, Settings

### Community 51 - "Community 51"
Cohesion: 0.40
Nodes (5): _iso(), main(), object, str, Print YCLIENTS local sync freshness diagnostics.

### Community 52 - "Community 52"
Cohesion: 0.67
Nodes (3): compact_item(), main(), Print YCLIENTS service and staff ids without exposing tokens.

## Knowledge Gaps
- **163 isolated node(s):** `str`, `int`, `Any`, `Exception`, `bool` (+158 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_connection()` connect `Community 0` to `Community 2`, `Community 3`, `Community 4`, `Community 35`, `Community 6`, `Community 7`, `Community 9`, `Community 11`, `Community 12`, `Community 48`, `Community 16`, `Community 51`, `Community 20`, `Community 23`, `Community 24`, `Community 30`, `Community 31`?**
  _High betweenness centrality (0.146) - this node is a cross-community bridge._
- **Why does `get_settings()` connect `Community 24` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 9`, `Community 10`, `Community 11`, `Community 12`, `Community 16`, `Community 20`, `Community 23`, `Community 26`, `Community 30`, `Community 34`, `Community 35`, `Community 44`, `Community 48`, `Community 50`, `Community 51`?**
  _High betweenness centrality (0.146) - this node is a cross-community bridge._
- **Why does `AIProviderUnavailable` connect `Community 3` to `Community 0`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 16`, `Community 22`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `Check` (e.g. with `AIProviderUnavailable` and `AIResponse`) actually correct?**
  _`Check` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `str` (e.g. with `AIProviderUnavailable` and `AvailabilityExecutionCallbacks`) actually correct?**
  _`str` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `datetime` (e.g. with `AIProviderUnavailable` and `AIResponse`) actually correct?**
  _`datetime` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `AI booking bot application package.`, `str`, `int` to the rest of the system?**
  _193 weakly-connected nodes found - possible documentation gaps or missing edges._