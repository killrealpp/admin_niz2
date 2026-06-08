# Graph Report - best2graph  (2026-06-05)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 333 nodes · 935 edges · 28 communities (12 shown, 16 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 148 edges (avg confidence: 0.57)
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

## God Nodes (most connected - your core abstractions)
1. `MaxApiError` - 66 edges
2. `MaxApiClient` - 66 edges
3. `MaxChannelClient` - 32 edges
4. `get_settings()` - 23 edges
5. `str` - 22 edges
6. `Any` - 21 edges
7. `str` - 21 edges
8. `process_max_update()` - 20 edges
9. `VoiceTranscriptionError` - 19 edges
10. `str` - 18 edges

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
- 1-file cycle: `app/bot/max_router.py -> app/bot/max_router.py`

## Communities (28 total, 16 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (48): Any, str, DeliveryTarget, Message, str, str, bool, bytes (+40 more)

### Community 1 - "Community 1"
Cohesion: 0.10
Nodes (34): float, int, MaxApiClient, bool, Any, bool, bytes, float (+26 more)

### Community 2 - "Community 2"
Cohesion: 0.17
Nodes (20): MaxChannelClient, assert_api_guards_and_redaction(), assert_api_send_message_payload(), assert_bot_started_direct_welcome(), assert_channel_client_target_and_split(), assert_inbound_to_shared_processor(), _assert_safe_auth(), _client() (+12 more)

### Community 3 - "Community 3"
Cohesion: 0.16
Nodes (24): Any, int, str, _emit(), ensure_max_live_polling_allowed(), extract_updates(), MaxLivePollingBlocked, MaxLivePollingOptions (+16 more)

### Community 4 - "Community 4"
Cohesion: 0.15
Nodes (19): datetime, assert_bot_started(), assert_ignored_shapes(), assert_message_created(), assert_nested_message_created(), assert_non_text_fallback_and_audio_path(), assert_polling_wrapper_still_text_only(), audio_payload() (+11 more)

### Community 5 - "Community 5"
Cohesion: 0.36
Nodes (25): Any, str, _chat_id(), _event_payload(), _external_user_id(), max_delivery_target_from_update(), max_message_id_from_update(), max_message_payload() (+17 more)

### Community 6 - "Community 6"
Cohesion: 0.26
Nodes (23): Any, bool, int, MaxApiClient, str, DeliveryTarget, _attachment_filename(), _AudioAttachment (+15 more)

### Community 7 - "Community 7"
Cohesion: 0.24
Nodes (15): Any, bool, DeliveryTarget, Path, str, _attachments_from_options(), _ensure_max_target(), _existing_attachments() (+7 more)

### Community 8 - "Community 8"
Cohesion: 0.17
Nodes (17): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), База знаний администратора, Единая база знаний компании, Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Системный промпт (+9 more)

### Community 9 - "Community 9"
Cohesion: 0.18
Nodes (12): Addons Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base, Prepayment System (+4 more)

### Community 10 - "Community 10"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

## Knowledge Gaps
- **48 isolated node(s):** `ChannelRunner`, `str`, `Any`, `str`, `bytes` (+43 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MaxApiClient` connect `Community 1` to `Community 2`, `Community 3`, `Community 6`, `Community 7`?**
  _High betweenness centrality (0.175) - this node is a cross-community bridge._
- **Why does `MaxApiError` connect `Community 1` to `Community 2`, `Community 3`, `Community 6`, `Community 7`?**
  _High betweenness centrality (0.171) - this node is a cross-community bridge._
- **Why does `get_settings()` connect `Community 0` to `Community 1`, `Community 3`, `Community 6`?**
  _High betweenness centrality (0.150) - this node is a cross-community bridge._
- **Are the 46 inferred relationships involving `MaxApiError` (e.g. with `Any` and `bool`) actually correct?**
  _`MaxApiError` has 46 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `MaxApiClient` (e.g. with `Any` and `bool`) actually correct?**
  _`MaxApiClient` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `MaxChannelClient` (e.g. with `Any` and `bool`) actually correct?**
  _`MaxChannelClient` has 18 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ChannelRunner`, `str`, `Any` to the rest of the system?**
  _53 weakly-connected nodes found - possible documentation gaps or missing edges._