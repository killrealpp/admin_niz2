# best2 Project Memory

## 2026-05-28 best2info note

- `best2info/` теперь отдельная клиентская база знаний рядом с `best2obs/`: `best2obs` хранит память разработки, `best2info` хранит факты для ответов клиентам.
- `[[decisions/2026-05-28-best2info-client-knowledge]]`, `[[log]]`, `[[architecture/backend]]`, `[[bugs/current-known-issues]]`, `[[roadmap/pre-launch]]` обновлены после подключения retrieval и закрытия live-регрессий 6093.
- Ключевое правило закреплено в коде и тестах: AI определяет intent, backend валидирует состояние; `answer_info` идет в `best2info`, `check_availability` идет в локальную БД/YCLIENTS-cache, patch анкеты применяется только state-safe.

## Recent production-hardening notes

- [[log]] / [[architecture/backend]] / [[bugs/current-known-issues]] / [[roadmap/pre-launch]] - 2026-05-28 live payment/confirmation hardening: `ну давайте` after soft upsell accepts the offered mangal set, `а это хорошая беседка?` stays in confirmation instead of starting a second booking, Telegram messages are serialized per user, paid YCLIENTS creation retries faster and sends a journal-pending paid notice; live booking `213` repaired to YCLIENTS record `1741240914`.
- [[log]] / [[architecture/backend]] / [[bugs/current-known-issues]] / [[roadmap/pre-launch]] - 2026-05-28 structural AI field validation: `guests_count` больше не принимается/отклоняется по keyword-trigger `чел/гостей/нас будет`; AI может понять `на 30 июня двадцать` как 20 гостей, а backend структурно отклоняет только конфликты с числом даты или номером беседки.
- [[log]] / [[architecture/backend]] / [[bugs/current-known-issues]] / [[roadmap/pre-launch]] - 2026-05-28 date-only/guest-poison fix: `на 30 июня` больше не превращается в `30 гостей`, `answer_info` не перехватывает валидный ответ текущего шага, вопрос про выбор помнит дату, а complaint recovery очищает ошибочно выбранную беседку.
- [[log]] / [[architecture/backend]] / [[bugs/current-known-issues]] / [[roadmap/pre-launch]] - 2026-05-28 two-gazebo live-dialog fix: mixed info+booking for `2 беседки` теперь стартует последовательную очередь заявок, pending second date не затирает первую заявку, будние цены беседок показывают скидку 50%, а ночные интервалы пишутся как `до 08:00 следующего дня`.
- [[log]] / [[architecture/backend]] / [[bugs/current-known-issues]] - 2026-05-28 context availability fix: `на 30 июня нас будет 20` теперь идёт через локальную availability БД, вместимость фильтруется до предложения вариантов, а `scripts/dialog_context_suite.py` закрепляет память даты/гостей/выбранного объекта/confirmation-state.
- [[log]] / [[architecture/backend]] - 2026-05-28 edge-dialog suite: unusual interruptions inside form/confirmation/cancel/reschedule are covered; confirmation summary/cancel and cancel-flow info questions now stay deterministic and state-safe.
- [[log]] / [[bugs/current-known-issues]] - 2026-05-28 live-dialog fixes: unfinished booking summary uses draft, emotional language does not auto-handoff, vague time does not create AI-invented slot, same-time reference for second service is guarded by backend state.
- [[decisions/2026-05-27-production-hardening]] - atomic holds, payment intent flow, two-phase YCLIENTS sync, 48h retention and server run policy.
- [[architecture/api]] - updated with YooKassa webhook hardening: secret, body-size limit, smoke-test and remaining reverse-proxy/HTTPS requirement.
- [[architecture/backend]] - updated with first safe `post_booking_flow` refactor slice and regression guard list.

Это Obsidian-память проекта `best2`: Telegram-бота бронирования с AI, YCLIENTS, ЮKassa, PostgreSQL и фоновыми синками.

## Быстрые ссылки

- [[log]] - журнал важных изменений и анализов.
- [[architecture/overview]] - общий обзор системы и потоков.
- [[architecture/frontend]] - пользовательские интерфейсы и точки входа.
- [[architecture/backend]] - backend-модули, сервисы и фоновые процессы.
- [[architecture/database]] - таблицы PostgreSQL и назначение данных.
- [[architecture/auth]] - секреты, внешние токены и модель доступа.
- [[architecture/api]] - внешние API и интеграции.
- [[roadmap/pre-launch]] - проверки и задачи перед релизом.
- [[roadmap/dialog-regression-scenarios]] - живые и автоматические сценарии, которые защищают диалог от повторяющихся ошибок.
- [[testing/dialog-test-matrix]] - матрица успешно проверенных диалоговых сценариев: что покрыто, где покрыто и какой статус последнего прогона.
- [[bugs/current-known-issues]] - текущие риски, слабые места и наблюдаемые баги.
- [[prompts/codex-workflow]] - команды для дальнейшей работы с Codex и памятью.
- [[prompts/llm-wiki-method]] - правила LLM Wiki: ingest, query, lint, index/log.
- [[decisions/2026-05-26-use-llm-wiki]] - решение вести `best2obs` как LLM Wiki.
- [[decisions/2026-05-27-dialog-state-policy]] - правило: AI понимает смысл, backend валидирует состояние и переходы анкеты.
- [[daily/2026-05-26-scenario-check]] - отчет о самостоятельной проверке сценариев после последних правок.
- [[daily/2026-05-27-project-review]] - обзор проекта senior Python-разработчиком: логика, сильные стороны, риски, что исправлять и удалять.

## Рабочее правило

Перед изменениями читать этот файл и [[log]]. После значимых изменений обновлять память: log, architecture, decisions, roadmap или bugs по смыслу.
