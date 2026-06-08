# Graph Report - best2graph  (2026-06-07)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 102 nodes · 139 edges · 22 communities (6 shown, 16 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 26 edges (avg confidence: 0.85)
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

## God Nodes (most connected - your core abstractions)
1. `run_client_channels()` - 17 edges
2. `Information Knowledge Base` - 10 edges
3. `Client Runtime Knowledge Base` - 8 edges
4. `Объекты и услуги базы отдыха` - 8 edges
5. `_telegram_target()` - 6 edges
6. `run_polling()` - 6 edges
7. `run_bot()` - 6 edges
8. `parse_client_channels()` - 5 edges
9. `_telegram_runner()` - 5 edges
10. `Message` - 5 edges

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
- None detected.

## Communities (22 total, 16 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.17
Nodes (17): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), База знаний администратора, Единая база знаний компании, Объекты и услуги базы отдыха, YCLIENTS ID услуг и ресурсов, Системный промпт (+9 more)

### Community 1 - "Community 1"
Cohesion: 0.23
Nodes (15): bool, Bot, str, create_bot(), create_dispatcher(), on_start(), on_status(), on_text() (+7 more)

### Community 2 - "Community 2"
Cohesion: 0.18
Nodes (13): Any, bool, Bot, str, _ensure_max_runtime_allowed(), _max_runner(), _needs_runtime_telegram_bot(), _run_channel_runners() (+5 more)

### Community 3 - "Community 3"
Cohesion: 0.39
Nodes (10): parse_client_channels(), run_client_channels(), assert_dual_channel_runners_start(), assert_unsafe_max_runtime_blocks(), assert_webhook_max_runtime_can_start(), main(), str, Smoke-check local client runtime channel selection without live bot calls. (+2 more)

### Community 4 - "Community 4"
Cohesion: 0.18
Nodes (12): Addons Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base, Prepayment System (+4 more)

### Community 5 - "Community 5"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

## Knowledge Gaps
- **40 isolated node(s):** `str`, `DeliveryTarget`, `Dispatcher`, `Project Rules for best2`, `Graphify Workflow` (+35 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `run_client_channels()` connect `Community 3` to `Community 1`, `Community 2`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Why does `create_bot()` connect `Community 1` to `Community 2`, `Community 3`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `run_bot()` connect `Community 1` to `Community 2`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `Information Knowledge Base` (e.g. with `Knowledge Base TODO` and `Banya Image`) actually correct?**
  _`Information Knowledge Base` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `Client Runtime Knowledge Base` (e.g. with `Addons Pricing` and `Pricing System`) actually correct?**
  _`Client Runtime Knowledge Base` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `Объекты и услуги базы отдыха` (e.g. with `Крытая беседка (фото)` and `Тёплая беседка (фото)`) actually correct?**
  _`Объекты и услуги базы отдыха` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `str`, `DeliveryTarget`, `Dispatcher` to the rest of the system?**
  _41 weakly-connected nodes found - possible documentation gaps or missing edges._