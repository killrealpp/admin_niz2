# Graph Report - best2graph  (2026-06-09)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 90 nodes · 89 edges · 29 communities (8 shown, 21 thin omitted)
- Extraction: 72% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 25 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1a3c0b9a`
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

## God Nodes (most connected - your core abstractions)
1. `Information Knowledge Base` - 10 edges
2. `str` - 9 edges
3. `Any` - 7 edges
4. `Client Runtime Knowledge Base` - 7 edges
5. `Объекты и услуги базы отдыха` - 7 edges
6. `format_booking_summary()` - 6 edges
7. `booking_object_title()` - 5 edges
8. `Services Map Config` - 5 edges
9. `booking_status_text()` - 4 edges
10. `booking_word()` - 4 edges

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

## Communities (29 total, 21 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.38
Nodes (12): Any, booking_line_short(), booking_object_title(), booking_status_text(), booking_word(), confirmation_reply_text(), format_booking_summary(), format_hold_summary() (+4 more)

### Community 1 - "Community 1"
Cohesion: 0.17
Nodes (12): Banya Image, Besedka 1 Image, Besedka 2 Image, Besedka 3 Image, Besedka 4 Image, Besedka 5 Image, Besedka 6 Image, Besedka 8 Image (+4 more)

### Community 2 - "Community 2"
Cohesion: 0.25
Nodes (9): Addons Pricing, Bathhouse with Pool Service, Booking System Logic, Bot Assistant Lyubov, Gazebos Service, Guest House Service, Client Runtime Knowledge Base, Prepayment System (+1 more)

### Community 3 - "Community 3"
Cohesion: 0.32
Nodes (8): Backend System, Bot Main Rules, Gazebos Service, Payment and Booking System, Photo Management System, Sauna + Gazebo Combo, Sauna with Pool Service, YClients Integration

### Community 4 - "Community 4"
Cohesion: 0.43
Nodes (7): Крытая беседка (фото), Тёплая беседка (фото), Гостевой дом (фото), Объекты и услуги базы отдыха, Беседки, Гостевой дом, Теплая беседка

### Community 5 - "Community 5"
Cohesion: 0.38
Nodes (7): YCLIENTS ID услуг и ресурсов, Bathhouse Object, Bathhouse Prices, Форма бронирования, Services Map Config, Best2info Knowledge Base, Runtime Rules

### Community 6 - "Community 6"
Cohesion: 0.50
Nodes (5): Response Generator Prompt, Form Data Structure, JSON Response Schema, System Prompt, YCLIENTS Integration

### Community 7 - "Community 7"
Cohesion: 0.40
Nodes (5): Base Knowledge File, Runtime Knowledge Base, Objects Knowledge File, Prices Knowledge File, YClients IDs Knowledge File

## Knowledge Gaps
- **51 isolated node(s):** `int`, `Project Rules for best2`, `Graphify Workflow`, `LLM Wiki Workflow`, `PLAN.md - Development Plan` (+46 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Объекты и услуги базы отдыха` connect `Community 4` to `Community 5`?**
  _High betweenness centrality (0.014) - this node is a cross-community bridge._
- **Why does `Services Map Config` connect `Community 5` to `Community 4`?**
  _High betweenness centrality (0.013) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `Information Knowledge Base` (e.g. with `Knowledge Base TODO` and `Banya Image`) actually correct?**
  _`Information Knowledge Base` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `Client Runtime Knowledge Base` (e.g. with `Addons Pricing` and `Pricing System`) actually correct?**
  _`Client Runtime Knowledge Base` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `Объекты и услуги базы отдыха` (e.g. with `Крытая беседка (фото)` and `Тёплая беседка (фото)`) actually correct?**
  _`Объекты и услуги базы отдыха` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `int`, `Project Rules for best2`, `Graphify Workflow` to the rest of the system?**
  _51 weakly-connected nodes found - possible documentation gaps or missing edges._