# Graph Report - best2graph  (2026-06-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 234 nodes · 508 edges · 32 communities (11 shown, 21 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 53 edges (avg confidence: 0.68)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `29b93acd`
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

## God Nodes (most connected - your core abstractions)
1. `MaxChannelClient` - 47 edges
2. `run_client_channels()` - 17 edges
3. `process_max_update()` - 16 edges
4. `str` - 15 edges
5. `Any` - 14 edges
6. `process_client_message()` - 13 edges
7. `str` - 13 edges
8. `_process_non_text_update()` - 10 edges
9. `_find_audio_attachment()` - 10 edges
10. `RecordingMaxApiClient` - 10 edges

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
- 1-file cycle: `app/bot/client_message_processor.py -> app/bot/client_message_processor.py`

## Communities (32 total, 21 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.16
Nodes (24): MaxChannelClient, MaxApiError, assert_api_upload_file(), assert_channel_media_upload_and_retry(), assert_max_processor_auto_media(), assert_max_webhook_processor_sends_related_media_before_return(), assert_media_failure_fallback_and_log(), assert_payment_link_button() (+16 more)

### Community 1 - "Community 1"
Cohesion: 0.14
Nodes (20): assert_api_guards_and_redaction(), assert_api_send_message_payload(), assert_bot_started_direct_welcome(), assert_channel_client_target_and_split(), assert_inbound_to_shared_processor(), assert_max_text_sanitizes_telegram_mentions(), _assert_safe_auth(), _client() (+12 more)

### Community 2 - "Community 2"
Cohesion: 0.16
Nodes (25): Any, bool, str, Bot, _ensure_max_runtime_allowed(), _max_runner(), _needs_runtime_telegram_bot(), parse_client_channels() (+17 more)

### Community 3 - "Community 3"
Cohesion: 0.20
Nodes (18): Any, bool, DeliveryTarget, Exception, int, Path, str, _attachments_from_options() (+10 more)

### Community 4 - "Community 4"
Cohesion: 0.29
Nodes (20): Any, bool, ChannelClient, int, MaxApiClient, str, _attachment_filename(), _AudioAttachment (+12 more)

### Community 5 - "Community 5"
Cohesion: 0.32
Nodes (18): Any, bool, ChannelClient, DeliveryTarget, str, _log_related_media_result(), _media_resend_due(), process_client_message() (+10 more)

### Community 6 - "Community 6"
Cohesion: 0.17
Nodes (17): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), База знаний администратора, Единая база знаний компании, Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Системный промпт (+9 more)

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
Cohesion: 0.40
Nodes (5): Base Knowledge File, Runtime Knowledge Base, Objects Knowledge File, Prices Knowledge File, YClients IDs Knowledge File

## Knowledge Gaps
- **48 isolated node(s):** `MaxApiClient`, `float`, `int`, `Exception`, `Project Rules for best2` (+43 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MaxChannelClient` connect `Community 0` to `Community 11`, `Community 1`, `Community 3`, `Community 4`?**
  _High betweenness centrality (0.309) - this node is a cross-community bridge._
- **Why does `make_max_webhook_event_processor()` connect `Community 4` to `Community 2`?**
  _High betweenness centrality (0.142) - this node is a cross-community bridge._
- **Why does `process_client_message()` connect `Community 5` to `Community 4`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Are the 26 inferred relationships involving `MaxChannelClient` (e.g. with `Any` and `bool`) actually correct?**
  _`MaxChannelClient` has 26 INFERRED edges - model-reasoned connections that need verification._
- **What connects `MaxApiClient`, `float`, `int` to the rest of the system?**
  _51 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.14482758620689656 - nodes in this community are weakly interconnected._