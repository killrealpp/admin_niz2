# best2 Project Memory

## 2026-05-29 best3 full parity milestone

- `../best3` now has a full `best2obs` outcome-parity gate for all documented scenario ids (`STD-001..009`, `CTX-001..022`, `EDGE-001..014`, `STR-001..013`, `REG-001..014`).
- The milestone is agent-first: AI remains the dialog orchestrator, while backend safe tools own draft state, media, waitlist, payment/current booking checks and non-destructive cancel/reschedule proposals.
- Verification in `best3`: 49 unit tests OK, compile OK, table-prefix guard OK, full best2obs scenario runner OK, shadow OK, safe smoke/payment/expired/webhook/checklist OK. `best2` production code was not changed.

## 2026-05-29 YooKassa 1-ruble payment config incident

- Диагностика показала, что live-ссылки YooKassa создавались на `1.00 RUB`, потому что в локальном `.env` стоит `PREPAYMENT_AMOUNT_RUB=1`; код берет это значение как фиксированную предоплату за бронь.
- БД `payments` и read-only проверка YooKassa подтвердили: последние платежи текущего магазина имеют booking-bot metadata и сумму `1.00 RUB`. QR/СБП в магазине включен, но бот не форсирует `payment_method_data.type=sbp`, а создает общую форму YooMoney. Production-код не менялся; детали в [[log]] и [[bugs/current-known-issues]].

## 2026-05-29 best3 webhook/pilot milestone

- `../best3` now has local YooKassa webhook processing, event persistence, duplicate-safe paid finalization, notification markers and `scripts/test_pilot_checklist.py`.
- This is a best3 migration milestone only; `best2` production code was not changed. Details live in `../best3/best3obs/` and the bridge entry in [[log]].

## 2026-05-29 best3 backend-understanding milestone

- `best3` получил слой `state.understanding`: AI видит current task, missing fields, safe next actions, holds/payments/bookings, а backend страхует критичные live-AI промахи.
- Добавлены `../best3/scripts/db_safety_guard.py` и расширенный `agent_smoke.py --all-scenarios --safe-payments`; проверки подтвердили, что `best3` smoke и YCLIENTS sync не меняют row counts таблиц `best2`.
- `best3` теперь лучше объясняет агенту, что происходит, но production parity по paid finalization/webhook/cancel/reschedule ещё ведётся в `../best3/best3obs/`.

## 2026-05-29 best3 safe paid/cleanup milestone

- `best3` получил safe paid-finalization smoke: fake payment переводится в paid, создаёт local booking, fake YCLIENTS record id и busy interval без внешнего POST в YCLIENTS.
- Добавлен expired hold cleanup runner/smoke: overdue holds переходят в `expired`, `expired_notified_at` отмечается, событие пишется в `best3_system_logs`.
- Проверки `best3` дошли до 30 unit tests; `best2` production-код не менялся.

## 2026-05-29 best3obs note

- `best3` теперь имеет собственную LLM Wiki `../best3/best3obs/` и корневой `AGENTS.md`.
- Дальнейшие задачи по `best3` должны опираться на `best3obs`, а `best2obs` остаётся памятью `best2` и мостом истории миграции.

## 2026-05-29 best3 core parity

- `best3` поднят с baseline до core-parity слоя относительно `best2` в выбранном scope: новая бронь, info, availability, hold/payment, paid/current-booking.
- Перенос сделан agent-first способом: live-фиксы `best2` стали policy/tool/prompt правилами и deterministic/shadow сценариями `best3`, а не копией старого монолитного `message_handler.py`.
- Новые проверки `best3`: 23 unit tests, `core_parity_scenarios.py`, `shadow_compare.py`, `table_prefix_guard.py`, strict YCLIENTS и короткий real-AI smoke прошли. См. [[decisions/2026-05-29-best3-core-parity]] и [[log]].

## 2026-05-29 best3 agent-first baseline

- Рядом с `best2` создан `best3`: чистый agent-first baseline для той же доменной задачи, но с отдельными таблицами `best3_*` в общей PostgreSQL-БД.
- `best3` не форкает большой `best2` `message_handler.py`; AI выбирает JSON action/patch, backend выполняет safe tools: draft, info, availability, hold, payment, booking/YCLIENTS.
- Первый scope `best3`: новая бронь + info + локальная availability + hold + YooKassa payment + paid finalization skeleton. Cancel/reschedule/voice/reminders/multi-booking оставлены на следующие этапы.
- См. [[log]] за 2026-05-29: миграция применена, YCLIENTS sync `seen=125/upserted=125`, проверки `compileall`, `unittest`, `table_prefix_guard`, fallback `agent_smoke` прошли.

## 2026-05-28 best2info note

- `best2info/` теперь отдельная клиентская база знаний рядом с `best2obs/`: `best2obs` хранит память разработки, `best2info` хранит факты для ответов клиентам.
- `[[decisions/2026-05-28-best2info-client-knowledge]]`, `[[log]]`, `[[architecture/backend]]`, `[[bugs/current-known-issues]]`, `[[roadmap/pre-launch]]` обновлены после подключения retrieval и закрытия live-регрессий 6093.
- Ключевое правило закреплено в коде и тестах: AI определяет intent, backend валидирует состояние; `answer_info` идет в `best2info`, `check_availability` идет в локальную БД/YCLIENTS-cache, patch анкеты применяется только state-safe.

## Recent production-hardening notes

- [[log]] / [[architecture/backend]] / [[bugs/current-known-issues]] / [[testing/dialog-test-matrix]] - 2026-05-29 live-14:29 hardening: подробная новая баня поверх старого draft больше не застревает в stale-checkpoint, `не` на допах закрывает допы, `ну вроде да` подтверждает заявку, а баня валидируется только по фиксированным блокам 3-7 часов.
- [[log]] / [[architecture/backend]] / [[bugs/current-known-issues]] / [[testing/dialog-test-matrix]] - 2026-05-29 live-13:07 hardening: явный период `09:00-21:00` больше не превращается в 23 часа, fake-payment просьба не засчитывает оплату, `следующая заявка` не распознаётся как доп `лед`.
- [[log]] / [[architecture/backend]] / [[bugs/current-known-issues]] / [[testing/dialog-test-matrix]] - 2026-05-29 live-1953 hardening: bathhouse info is deterministic and separate from gazebo addons, generic new booking after bath info starts a clean bath draft, `а я же хочу баньку` clears inherited gazebo fields, `имя заменим на IVAN`, `если бы нас было 10`, `на месте возьмем`, phone-confirmation and paid notification date are regression-covered.
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
- [[testing/scenarios/standard]] - ручной чеклист стандартного happy-path.
- [[testing/scenarios/context-live]] - ручной чеклист context/live-like сценариев.
- [[testing/scenarios/edge]] - ручной чеклист edge-сценариев.
- [[testing/scenarios/stress]] - ручной чеклист stress-сценариев.
- [[testing/scenarios/broad-regression]] - ручной чеклист широких regression-зон.
- [[testing/full-diagnostics-2026-05-29]] - полный диагностический прогон 2026-05-29: операционка, suites, smoke-проверки, legacy-smoke fix и остаточные риски.
- [[testing/scenario-run-2026-05-29]] - сценарный прогон от стандартных happy-path до нестандартных stress cases; все сценарии прошли.
- [[bugs/current-known-issues]] - текущие риски, слабые места и наблюдаемые баги.
- [[prompts/codex-workflow]] - команды для дальнейшей работы с Codex и памятью.
- [[prompts/llm-wiki-method]] - правила LLM Wiki: ingest, query, lint, index/log.
- [[decisions/2026-05-26-use-llm-wiki]] - решение вести `best2obs` как LLM Wiki.
- [[decisions/2026-05-27-dialog-state-policy]] - правило: AI понимает смысл, backend валидирует состояние и переходы анкеты.
- [[daily/2026-05-26-scenario-check]] - отчет о самостоятельной проверке сценариев после последних правок.
- [[daily/2026-05-27-project-review]] - обзор проекта senior Python-разработчиком: логика, сильные стороны, риски, что исправлять и удалять.

## Рабочее правило

Перед изменениями читать этот файл и [[log]]. После значимых изменений обновлять память: log, architecture, decisions, roadmap или bugs по смыслу.
