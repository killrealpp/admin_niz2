# Graph Report - best2graph  (2026-06-02)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1759 nodes · 7271 edges · 72 communities (63 shown, 9 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 368 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a87e248c`
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
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]

## God Nodes (most connected - your core abstractions)
1. `get_connection()` - 190 edges
2. `Check` - 190 edges
3. `str` - 173 edges
4. `datetime` - 157 edges
5. `main()` - 148 edges
6. `Any` - 135 edges
7. `_send()` - 133 edges
8. `_base_form()` - 122 edges
9. `get_settings()` - 109 edges
10. `handle_incoming()` - 104 edges

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

## Communities (72 total, 9 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (216): AIResponse, PostBookingResponse, BaseModel, get_connection(), main(), main(), Clear all application data while keeping the database schema., main() (+208 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (138): AIProviderUnavailable, AIProviderUnavailable, Any, int, str, Any, int, str (+130 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (94): Any, int, str, Any, bool, datetime, int, PgConnection (+86 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (79): AiohttpSession, bool, datetime, Message, str, Any, str, Any (+71 more)

### Community 4 - "Community 4"
Cohesion: 0.09
Nodes (76): Any, bool, datetime, int, str, Any, bool, int (+68 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (74): Any, str, next_question(), _abort_current_draft(), _ai_first_patch(), _ai_process_reply(), _alternative_services_for_unavailable_date(), _answer_info_during_form() (+66 more)

### Community 6 - "Community 6"
Cohesion: 0.09
Nodes (52): datetime, trace_span(), new_booking_form_data(), _ai_guest_count_conflicts_with_date_context(), _asks_how_to_book_last_discussed_service(), call_ai(), _cancel_flow_callbacks(), check_availability() (+44 more)

### Community 7 - "Community 7"
Cohesion: 0.15
Nodes (44): Any, bool, int, str, classify_upsell_reply(), client_name_patch(), _contains_upsell_marker(), event_format_patch() (+36 more)

### Community 8 - "Community 8"
Cohesion: 0.13
Nodes (39): Any, bool, str, Any, bool, datetime, str, Any (+31 more)

### Community 9 - "Community 9"
Cohesion: 0.25
Nodes (40): AIResponse, context_ai_understands_guest_without_keyword(), context_bathhouse_large_group_blocks_before_format(), context_confirmation_no_means_not_confirmed(), context_confirmation_perexotel_aborts_draft(), context_confirmation_summary_then_abort(), context_confirmation_time_change_and_typo_summary(), context_date_and_guests_uses_availability() (+32 more)

### Community 10 - "Community 10"
Cohesion: 0.12
Nodes (39): bool, wants_cancel_booking(), wants_multi_booking_reschedule(), wants_reschedule(), wants_swap_bookings(), _ai_should_start_fresh_booking(), _asks_available_services(), _asks_booking_summary() (+31 more)

### Community 11 - "Community 11"
Cohesion: 0.15
Nodes (34): bool, Bot, int, str, bool, Bot, int, str (+26 more)

### Community 12 - "Community 12"
Cohesion: 0.26
Nodes (33): _confirmation_conversation(), _draft_conversation(), edge_cancel_info_question(), edge_cancel_no_then_reschedule(), edge_cancel_unrelated_question(), edge_confirmation_cancel_immediately(), edge_confirmation_info_then_yes(), edge_confirmation_perexotel_aborts() (+25 more)

### Community 13 - "Community 13"
Cohesion: 0.06
Nodes (31): audio-recorder, backlink, bases, bookmarks, canvas, command-palette, daily-notes, editor-status (+23 more)

### Community 14 - "Community 14"
Cohesion: 0.25
Nodes (31): Any, date, datetime, int, PgConnection, str, time, cancel_by_hold() (+23 more)

### Community 15 - "Community 15"
Cohesion: 0.17
Nodes (29): Any, Message, str, normalize_incoming(), normalize_telegram_message(), normalize_telegram_voice_message(), Unified entry for future MAX / VK adapters., IncomingMessage (+21 more)

### Community 16 - "Community 16"
Cohesion: 0.26
Nodes (30): Any, bool, date, datetime, int, str, CancelFlowResult, advance_refund_allowed() (+22 more)

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (30): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), База знаний администратора, Клиентская база знаний, Единая база знаний компании, Объекты и услуги базы отдыха, Цены и предоплата (+22 more)

### Community 18 - "Community 18"
Cohesion: 0.07
Nodes (29): active, bases:Создать новую базу, canvas:Создать новый холст, command-palette:Открыть палитру команд, daily-notes:Сегодняшняя заметка, graph:Граф, switcher:Меню быстрого перехода, templates:Вставить шаблон (+21 more)

### Community 19 - "Community 19"
Cohesion: 0.19
Nodes (25): build_user_prompt(), call_ai(), _chat_completion(), classify_post_booking_message(), _extract_json(), _format_history(), _format_summaries(), generate_final_reply() (+17 more)

### Community 20 - "Community 20"
Cohesion: 0.28
Nodes (27): Any, bool, datetime, Decimal, int, PgConnection, str, YooKassaError (+19 more)

### Community 21 - "Community 21"
Cohesion: 0.15
Nodes (23): Any, float, str, Any, int, str, current_trace(), PerformanceTrace (+15 more)

### Community 22 - "Community 22"
Cohesion: 0.13
Nodes (16): str, BaseSettings, run_bot(), get_settings(), Settings, setup_logging(), main(), main() (+8 more)

### Community 23 - "Community 23"
Cohesion: 0.26
Nodes (24): Any, bool, date, datetime, int, PgConnection, str, time (+16 more)

### Community 24 - "Community 24"
Cohesion: 0.30
Nodes (24): _contains_all(), main(), _now(), _print_result(), bool, datetime, str, Stress scenarios with unusual client phrasing.  This suite is intentionally clos (+16 more)

### Community 25 - "Community 25"
Cohesion: 0.14
Nodes (22): bool, asks_reschedule_options(), initial_reschedule_flow_patch(), means_change_object(), means_same_date(), means_same_object(), means_same_time(), referenced_service_type_for_same_time() (+14 more)

### Community 26 - "Community 26"
Cohesion: 0.10
Nodes (20): centerStrength, close, collapse-color-groups, collapse-display, collapse-filter, collapse-forces, colorGroups, hideUnresolved (+12 more)

### Community 27 - "Community 27"
Cohesion: 0.32
Nodes (19): Any, bool, datetime, int, PgConnection, str, delete_busy_interval(), delete_record_by_id() (+11 more)

### Community 28 - "Community 28"
Cohesion: 0.13
Nodes (16): Any, bool, datetime, int, PgConnection, str, Any, bool (+8 more)

### Community 29 - "Community 29"
Cohesion: 0.15
Nodes (14): AbstractEventLoop, Any, bool, Bot, str, BaseHTTPRequestHandler, Future, HTTPStatus (+6 more)

### Community 30 - "Community 30"
Cohesion: 0.37
Nodes (18): Any, datetime, Decimal, int, PgConnection, str, attach_provider_response(), create_pending() (+10 more)

### Community 31 - "Community 31"
Cohesion: 0.28
Nodes (7): Any, Decimal, str, YooKassaClient, main(), Register YooKassa webhooks from YOOKASSA_WEBHOOK_URL.  Usage:     python scripts, main()

### Community 32 - "Community 32"
Cohesion: 0.33
Nodes (15): _check_fixed_service_prices(), _check_gazebo_prices(), _check_single_price(), _load_services_map(), main(), _markdown_files(), _money(), Any (+7 more)

### Community 33 - "Community 33"
Cohesion: 0.36
Nodes (15): Any, bool, Bot, datetime, int, str, _date_ru(), _duration_minutes() (+7 more)

### Community 34 - "Community 34"
Cohesion: 0.45
Nodes (14): Any, int, PgConnection, str, _client_name_for_hold(), _conversation_form_data(), _existing_booking_ids(), _field_from_conversation() (+6 more)

### Community 35 - "Community 35"
Cohesion: 0.40
Nodes (14): Any, datetime, int, PgConnection, str, clear_handoff(), create(), find_by_external_id() (+6 more)

### Community 36 - "Community 36"
Cohesion: 0.34
Nodes (14): Any, date, datetime, int, PgConnection, str, time, close_for_user() (+6 more)

### Community 37 - "Community 37"
Cohesion: 0.27
Nodes (13): Any, date, int, PgConnection, str, time, main(), _admin_booking_title() (+5 more)

### Community 38 - "Community 38"
Cohesion: 0.42
Nodes (13): Any, bool, datetime, str, active_user_bookings(), as_post_booking_conversation(), booking_sync_grace_active(), context_summaries() (+5 more)

### Community 39 - "Community 39"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 40 - "Community 40"
Cohesion: 0.58
Nodes (10): Any, bool, datetime, str, _fresh_start_result(), handle_ai_fresh_start(), handle_fresh_start_after_confirmation(), handle_fresh_start_before_post_booking() (+2 more)

### Community 41 - "Community 41"
Cohesion: 0.49
Nodes (10): Any, datetime, int, PgConnection, str, create(), expire_stale(), find_active_for_user() (+2 more)

### Community 42 - "Community 42"
Cohesion: 0.25
Nodes (8): DummyConnection, FakeSettings, main(), int, object, str, Smoke-test YooKassa webhook request hardening without external side effects., request_json()

### Community 43 - "Community 43"
Cohesion: 0.40
Nodes (9): Any, bool, datetime, int, str, handoff_active(), is_location_question(), looks_like_handoff_needed() (+1 more)

### Community 44 - "Community 44"
Cohesion: 0.49
Nodes (9): Any, bool, str, deterministic_process_reply(), fallback_process_reply(), _looks_like_internal_instruction(), looks_like_internal_instruction_text(), _looks_like_json_or_schema() (+1 more)

### Community 45 - "Community 45"
Cohesion: 0.51
Nodes (9): Any, int, PgConnection, str, create(), delete_ids(), list_old_conversation_batches(), list_recent() (+1 more)

### Community 46 - "Community 46"
Cohesion: 0.44
Nodes (8): bool, PgConnection, _checkout_connection(), connect(), _connect_kwargs(), _get_pool(), _release_connection(), ThreadedConnectionPool

### Community 47 - "Community 47"
Cohesion: 0.39
Nodes (8): _fetch(), _json_default(), main(), Any, int, str, Read-only audit for live DB artifacts after regression runs., run_audit()

### Community 48 - "Community 48"
Cohesion: 0.43
Nodes (7): datetime, int, PgConnection, str, create(), list_for_conversation(), list_for_user()

### Community 49 - "Community 49"
Cohesion: 0.46
Nodes (7): Any, int, PgConnection, str, create(), list_admin_unnotified(), mark_admin_notified()

### Community 50 - "Community 50"
Cohesion: 0.29
Nodes (7): Any, bool, int, PgConnection, str, create_if_new(), mark_processed()

### Community 51 - "Community 51"
Cohesion: 0.53
Nodes (5): Any, bool, str, ai_should_start_fresh_booking(), should_start_fresh_booking()

### Community 52 - "Community 52"
Cohesion: 0.60
Nodes (5): bool, str, asks_for_free_slots(), asks_nearest_free_dates(), _fresh_start_immediate_reply()

### Community 53 - "Community 53"
Cohesion: 0.40
Nodes (5): _iso(), main(), object, str, Print YCLIENTS local sync freshness diagnostics.

## Knowledge Gaps
- **168 isolated node(s):** `str`, `int`, `Any`, `Exception`, `bool` (+163 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_connection()` connect `Community 0` to `Community 2`, `Community 3`, `Community 5`, `Community 6`, `Community 9`, `Community 11`, `Community 12`, `Community 15`, `Community 19`, `Community 20`, `Community 22`, `Community 24`, `Community 28`, `Community 29`, `Community 33`, `Community 37`, `Community 46`, `Community 47`, `Community 53`?**
  _High betweenness centrality (0.160) - this node is a cross-community bridge._
- **Why does `get_settings()` connect `Community 22` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 9`, `Community 11`, `Community 12`, `Community 15`, `Community 19`, `Community 20`, `Community 24`, `Community 25`, `Community 29`, `Community 31`, `Community 33`, `Community 43`, `Community 46`, `Community 53`?**
  _High betweenness centrality (0.142) - this node is a cross-community bridge._
- **Why does `AIProviderUnavailable` connect `Community 1` to `Community 0`, `Community 5`, `Community 6`, `Community 9`, `Community 10`, `Community 15`, `Community 19`, `Community 23`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `Check` (e.g. with `AIProviderUnavailable` and `AIResponse`) actually correct?**
  _`Check` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `str` (e.g. with `AIProviderUnavailable` and `AvailabilityExecutionCallbacks`) actually correct?**
  _`str` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `datetime` (e.g. with `AIProviderUnavailable` and `AIResponse`) actually correct?**
  _`datetime` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `AI booking bot application package.`, `str`, `int` to the rest of the system?**
  _200 weakly-connected nodes found - possible documentation gaps or missing edges._