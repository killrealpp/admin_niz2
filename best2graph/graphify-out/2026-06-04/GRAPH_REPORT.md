# Graph Report - best2graph  (2026-06-04)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 73 nodes · 76 edges · 21 communities (5 shown, 16 thin omitted)
- Extraction: 66% EXTRACTED · 34% INFERRED · 0% AMBIGUOUS · INFERRED: 26 edges (avg confidence: 0.85)
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

## God Nodes (most connected - your core abstractions)
1. `Information Knowledge Base` - 10 edges
2. `_call_max_subscription_api()` - 8 edges
3. `Client Runtime Knowledge Base` - 8 edges
4. `Объекты и услуги базы отдыха` - 8 edges
5. `str` - 6 edges
6. `main()` - 6 edges
7. `Services Map Config` - 5 edges
8. `_json_response()` - 4 edges
9. `_safe_error_text()` - 4 edges
10. `_print_payload()` - 4 edges

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

## Communities (21 total, 16 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.28
Nodes (14): Any, bool, float, Response, _call_max_subscription_api(), _json_response(), main(), _parse_update_types() (+6 more)

### Community 1 - "Community 1"
Cohesion: 0.18
Nodes (12): Addons Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base, Prepayment System (+4 more)

### Community 2 - "Community 2"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 3 - "Community 3"
Cohesion: 0.27
Nodes (10): База знаний администратора, Единая база знаний компании, YCLIENTS ID услуг и ресурсов, Системный промпт, Bathhouse Object, Bathhouse Prices, Форма бронирования, Services Map Config (+2 more)

### Community 4 - "Community 4"
Cohesion: 0.43
Nodes (7): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), Объекты и услуги базы отдыха, Беседки, Гостевой дом, Теплая беседка

## Knowledge Gaps
- **39 isolated node(s):** `float`, `bool`, `Project Rules for best2`, `Graphify Workflow`, `LLM Wiki Workflow` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Объекты и услуги базы отдыха` connect `Community 4` to `Community 3`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `Services Map Config` connect `Community 3` to `Community 4`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `Information Knowledge Base` (e.g. with `Knowledge Base TODO` and `Banya Image`) actually correct?**
  _`Information Knowledge Base` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `Client Runtime Knowledge Base` (e.g. with `Addons Pricing` and `Pricing System`) actually correct?**
  _`Client Runtime Knowledge Base` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `Объекты и услуги базы отдыха` (e.g. with `Крытая беседка (фото)` and `Тёплая беседка (фото)`) actually correct?**
  _`Объекты и услуги базы отдыха` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `float`, `bool`, `Prepare or apply MAX webhook subscription changes.  Default mode is dry-run and` to the rest of the system?**
  _40 weakly-connected nodes found - possible documentation gaps or missing edges._