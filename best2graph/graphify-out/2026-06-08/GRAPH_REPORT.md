# Graph Report - best2graph  (2026-06-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 169 nodes · 337 edges · 31 communities (9 shown, 22 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 48 edges (avg confidence: 0.69)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `75548284`
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

## God Nodes (most connected - your core abstractions)
1. `MaxApiClient` - 28 edges
2. `MaxApiError` - 27 edges
3. `str` - 23 edges
4. `Any` - 17 edges
5. `deterministic_info_reply()` - 11 edges
6. `RecordingMaxApiClient` - 11 edges
7. `Any` - 10 edges
8. `Information Knowledge Base` - 10 edges
9. `InfoFlowCallbacks` - 9 edges
10. `FakeResponse` - 9 edges

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

## Communities (31 total, 22 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.17
Nodes (22): Any, bool, int, Path, str, bytes, float, _attachment_payload_from_response() (+14 more)

### Community 1 - "Community 1"
Cohesion: 0.19
Nodes (20): object, assert_api_upload_file(), assert_api_upload_file_accepts_photos_payload(), assert_channel_media_upload_and_retry(), assert_max_processor_auto_media(), assert_max_webhook_processor_sends_related_media_before_return(), assert_media_failure_fallback_and_log(), assert_payment_link_button() (+12 more)

### Community 2 - "Community 2"
Cohesion: 0.21
Nodes (22): Any, bool, str, datetime, active_booking_reference_info_reply(), ActiveBookingInfoCallbacks, answer_info_during_form(), append_current_service_question() (+14 more)

### Community 3 - "Community 3"
Cohesion: 0.20
Nodes (14): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Bathhouse Object, Bathhouse Prices, Беседки (+6 more)

### Community 4 - "Community 4"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 5 - "Community 5"
Cohesion: 0.25
Nodes (9): Addons Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base, Prepayment System (+1 more)

### Community 6 - "Community 6"
Cohesion: 0.32
Nodes (8): Backend System, Bot Main Rules, Gazebos Service, Payment and Booking System, Photo Management System, Sauna + Gazebo Combo, Sauna with Pool Service, YClients Integration

### Community 7 - "Community 7"
Cohesion: 0.40
Nodes (5): Base Knowledge File, Runtime Knowledge Base, Objects Knowledge File, Prices Knowledge File, YClients IDs Knowledge File

### Community 8 - "Community 8"
Cohesion: 0.50
Nodes (5): Response Generator Prompt, Form Data Structure, JSON Response Schema, System Prompt, YCLIENTS Integration

## Knowledge Gaps
- **52 isolated node(s):** `bytes`, `Response`, `Project Rules for best2`, `Graphify Workflow`, `LLM Wiki Workflow` (+47 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `datetime` connect `Community 2` to `Community 0`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Why does `MaxApiClient` connect `Community 0` to `Community 1`, `Community 11`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Why does `MaxApiError` connect `Community 0` to `Community 1`, `Community 11`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `MaxApiClient` (e.g. with `Exception` and `object`) actually correct?**
  _`MaxApiClient` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `MaxApiError` (e.g. with `Exception` and `object`) actually correct?**
  _`MaxApiError` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `bytes`, `Response`, `Smoke-check deterministic bot identity answers.` to the rest of the system?**
  _54 weakly-connected nodes found - possible documentation gaps or missing edges._