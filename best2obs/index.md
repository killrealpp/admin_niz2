# best2 Project Memory

## 2026-06-02 large-file decomposition Phase 2

- Реализован второй срез [[roadmap/large-file-decomposition-plan]]: fresh/stale/new-booking routing вынесен в `app/services/dialog/new_booking_flow.py`, а `message_handler.py` оставлен владельцем side effects и persistence. `NewBookingFlowResult` возвращает `reply/status/intent/current_step/next_step/form_data`; context-only stale reset продолжает routing без ответа.
- DB-dependent baseline на этот раз зеленый: `test_db.py`, context 19/19, edge 15/15, stress 13/13, grouped `local_regression_suite.py --group fresh --group services --group post_booking --group payments` OK. Graphify обновлен полным ресканом (`1759 nodes`, `7271 edges`, query находит `new_booking_flow.py`). Детали: [[log]], [[architecture/backend]], [[bugs/current-known-issues]].

## 2026-06-02 large-file decomposition Phase 1

- Реализован первый срез [[roadmap/large-file-decomposition-plan]]: `message_handler.py` получил единый helper `_commit_assistant_response()`/`commit_reply()` для записи assistant message и `conversations_repo.update_after_message`, без изменения порядка routing.
- Проверки: `compileall app scripts`, `lint_best2info.py`, `validate_yclients_map.py` OK; Graphify обновлен полным пересканом (`1745 nodes`, `7207 edges`, query находит `message_handler.py`). Полный DB-зависимый Phase 1 regression заблокирован PostgreSQL timeout к `95.214.62.243:5432`; см. [[bugs/current-known-issues]] и [[log]].

## 2026-06-02 live services/upsell/late hookah price fixes

- Закрыт пакет live-сбоев: стартовое `че можно?` перечисляет все основные варианты и остается на `service_type`; parking/info-вопросы на `upsell_items` отвечают и возвращают к допам без прыжка к телефону; late `добавить калик в допы, цена изменится?` сохраняет `кальян`, отвечает ценой 1 500 ₽ и показывает confirmation с `Допы: кальян`.
- Дополнительно post-booking weather question теперь deterministic и не пишет про предоплату при `payment_paid`; voice transcription проверена реальным OpenRouter smoke на WAV и fake Telegram voice path. Детали: [[log]], [[bugs/current-known-issues]].

## 2026-06-01 live 19:09 post-booking/photo/confirmation fixes

- Закрыт пакет live-сбоев 19:09-19:16: post-booking `что еще можно забронить?` после оплаченной беседки теперь смотрит активные брони из БД, общий запрос `а беседки покажете?` реально приводит к отправке фото беседок, а `я перехотел, давай нет` на финальном подтверждении закрывает черновик без создания брони.
- При продолжении найден и закрыт дополнительный риск: `current_booking_question` больше не использует AI `reply_to_user`, если нужен список текущих броней; canonical summary берётся из БД/holds. Это защищает фразу `а у меня сейчас есть брони?` от ложного `Пока не вижу активных броней`.
- Проверки: `compileall app scripts`, `dialog_context_suite.py` 19/19, `dialog_edge_suite.py` 15/15, `local_regression_suite.py --group post_booking --group media --group fresh`, `dialog_stress_suite.py` 13/13; Graphify обновлён. Детали: [[log]], [[bugs/current-known-issues]], [[architecture/backend]], [[testing/dialog-test-matrix]].

## 2026-06-01 post-booking startup/regression fix

- После жалобы на запуск проверено: `main.py` компилируется и не падает за 20 секунд, уходит в polling; БД доступна через `scripts/test_db.py`.
- Реальный сбой был в post-booking regression: paid booking текущего разговора мог исчезнуть из current-booking summary/cancel/reschedule, если YCLIENTS-cache временно не подтверждал одну из локальных paid записей. `active_user_bookings()` теперь досоединяет paid локальные брони текущего разговора в статусах `created_in_yclients`/`journal_missing`; `ок`/`окей` после отмены deterministic отвечает про новую бронь, а не через AI fallback.
- Проверки: `compileall app scripts main.py`, `dialog_stress_suite.py` 13/13, `dialog_edge_suite.py` 14/14, `dialog_context_suite.py` 17/17, `local_regression_suite.py --group post_booking --group cancel --group payments`, `test_db.py`, `live_db_hygiene_audit.py --limit 20`, `lint_best2info.py`; Graphify обновлен. Детали: [[log]], [[bugs/current-known-issues]], [[architecture/backend]].

## 2026-06-01 state/text consistency hardening implemented

- Рабочий пакет [[roadmap/state-text-consistency-hardening-plan]] реализован без большого разбора `message_handler.py`: активные входящие клиентские сообщения получают semantic preflight через `AIResponse`, degraded AI path пишет `system_logs.event_type='ai_semantic_degraded'`, а основной AI-branch переиспользует preflight result.
- Добавлен state/text guard для важных ответов по допам: если текст говорит, что кальян добавлен, но `form_data.upsell_items` не содержит `кальян`, или summary говорит `Допы: не нужны` при другом state, backend пересобирает ответ из canonical state и логирует `state_text_consistency_rebuilt`.
- Допы расширены на живые фразы `кальянчик`, `калик один`, `ничего кроме кальяна`, `уберите все, кальян оставьте`; positive addon не перезаписывается последующим `нет`, mixed price+selection сохраняет выбранные items. Cancel/refund закреплен на границе 6/7/8 дней, multi-cancel создает refund events только для paid+refundable броней, admin runner drains все pending `refund_required`.
- Добавлен read-only `scripts/live_db_hygiene_audit.py`; текущий audit чистый. Проверки: `compileall app scripts`, `local_regression_suite.py --group upsell`, `--group cancel`, `--group post_booking --group payments`, `dialog_context_suite.py` 17/17, `dialog_edge_suite.py` 14/14, `dialog_stress_suite.py` 13/13, Graphify обновлен (`547 nodes`, `3466 edges` до recluster). Наблюдение: active semantic preflight ожидаемо увеличил `dialog_timing_slow` в context/edge/stress.

## 2026-06-01 state/text consistency hardening plan

- Новый рабочий пакет зафиксирован в [[roadmap/state-text-consistency-hardening-plan]]: закрыть риски 1-6 вокруг AI-first semantic pass, state/text consistency guard, допов, отмены/возвратов, admin refund notifications и live DB hygiene.
- Пункт 7 с большим разбором `message_handler.py` явно отложен: сейчас только точечные guard-ы, сценарии и проверки вокруг текущей архитектуры. Production-код не менялся.

## 2026-06-01 live kalik addon/refundable cancel notice

- Последний live-чат 16:48-16:57 разобран: `Калик` теперь deterministic сохраняется как `кальян`, поэтому подтверждение не может уйти в `Допы: не нужны` после уже выбранного кальяна; paid-cancel в refundable window теперь создает `system_logs.event_type='refund_required'`, а `payment_status_runner` уведомляет админа, что клиенту требуется вернуть предоплату.
- Проверки: `compileall app scripts`, `local_regression_suite.py --group upsell`, `local_regression_suite.py --group cancel`, `dialog_edge_suite.py` 14/14; Graphify-карта обновлена. Детали: [[log]], [[bugs/current-known-issues]], [[architecture/backend]].

## 2026-06-01 stable test-run package

- Live Telegram 11:45 fixes are guarded: `нас будет 30 человек, какая беседка подойдет` now saves guests and does not ask them again; `давайте первый набор` selects mangal set №1; after a gazebo booking, `что еще можно забронировать?` answers `Кроме вашей беседки...` instead of `Помимо бани...`.
- `best2info/` is now a client-facing markdown graph for runtime answers: retrieval scores pages by text/tokens/headings, always includes `runtime.md`, and expands relevant pages through one-hop `[[wikilinks]]`. `scripts/lint_best2info.py` checks links, orphans and prices against `config/services_map.yaml`.
- Local config is intentionally in test mode: `PREPAYMENT_MODE=fixed`, `PREPAYMENT_AMOUNT_RUB=1`, `PREPAYMENT_PERCENT=50`. Production target is `PREPAYMENT_MODE=percent` with `PREPAYMENT_PERCENT=50`, calculated from the main service/package price and gazebo weekday discount; addons are not included in the advance payment yet.
- Bathhouse test artifact is cleaned up: `bookings.id=1` is `cancelled`, the `bot_booking` busy interval for `2026-06-30 12:00-16:00` is removed, `payments.id=2` remains `paid` with `payment_notified_at`, and `system_logs` has `manual_cleanup_test_bathhouse_2026_06_30`.
- Regression side effect was repaired and guarded: live `waitlist_requests.id=35` is active again without `notified_at`; the waitlist regression now filters to its own test rows instead of touching unrelated live waitlist requests.
- Verification: `compileall`, `lint_best2info.py`, `validate_yclients_map.py`, webhook hardening smoke, all grouped `local_regression_suite.py` blocks, latest `dialog_context_suite.py` 17/17, `dialog_edge_suite.py` 14/14, `dialog_stress_suite.py` 13/13 and `dialog_regression_smoke.py` passed after fresh YCLIENTS sync. Details: [[log]], [[bugs/current-known-issues]], [[architecture/backend]], [[roadmap/pre-launch]], [[decisions/2026-06-01-best2info-graph-and-prepayment]].

## 2026-05-31 best2 pre-live fallback/proxy fixes

- Закрыт regression `bathhouse blocks large group`: общий capacity guard теперь работает в normal/fallback/AI-unavailable paths; баня на `40` гостей очищает `guests_count` и не переходит к `event_format`. По пути smoke поймал и закрыл баг `давай беседку номер 2` -> `guests_count=2`.
- Добавлен безопасный HTTP default `HTTP_TRUST_ENV=false` для OpenAI/OpenRouter, YCLIENTS, YooKassa и voice transcription, чтобы системный Windows `socks4://127.0.0.1:10808` не ломал `httpx`. Локальный `.env` теперь держит `PREPAYMENT_AMOUNT_RUB=2000`.
- Проверки: compileall OK; все listed chunks `local_regression_suite.py` OK; `dialog_context_suite.py` 16/16, `dialog_edge_suite.py` 14/14, `dialog_stress_suite.py` 13/13; YCLIENTS strict fresh (`records_seen=129`, `last_error=None`); `dialog_regression_smoke.py` OK. Детали: [[log]], [[bugs/current-known-issues]], [[roadmap/pre-launch]], [[testing/dialog-test-matrix]].

## 2026-05-30 best2 live waitlist/context hardening

- `best2` production-код обновлён для live-нюансов 17:48: safe waitlist gate, лимит бани 15 гостей, контекстное `на 30 число`, отказ `нет` на confirmation и нейтральный `ну окей` на upsell-info.
- Проверки: compileall OK; targeted `local_regression_suite.py` groups dates/gazebo/services/upsell/waitlist/payments/post_booking OK; `dialog_context_suite.py` 16/16, `dialog_edge_suite.py` 14/14, `dialog_stress_suite.py` 13/13, `yclients_sync_status.py --strict` OK после one-shot sync.
- Детали: [[log]], [[bugs/current-known-issues]], [[testing/dialog-test-matrix]], [[roadmap/dialog-regression-scenarios]], [[architecture/backend]].

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
- [[roadmap/message-handler-refactor]] - план безопасного уменьшения `message_handler.py` без потери контекстной логики.
- [[roadmap/large-file-decomposition-plan]] - будущий план разгрузки `message_handler.py`, `local_regression_suite.py` и соседних крупных сервисов.
- [[roadmap/state-text-consistency-hardening-plan]] - ближайший точечный пакет guard-ов против рассинхрона AI-текста, `form_data` и БД; большой разбор `message_handler.py` отложен.
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
- [[decisions/2026-06-01-best2info-graph-and-prepayment]] - graph-aware retrieval для `best2info` и явные режимы предоплаты.
- [[daily/2026-05-26-scenario-check]] - отчет о самостоятельной проверке сценариев после последних правок.
- [[daily/2026-05-27-project-review]] - обзор проекта senior Python-разработчиком: логика, сильные стороны, риски, что исправлять и удалять.

## Рабочее правило

Перед изменениями читать этот файл и [[log]]. После значимых изменений обновлять память: log, architecture, decisions, roadmap или bugs по смыслу.
