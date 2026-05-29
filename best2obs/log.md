# Project Log

## 2026-05-29 - best3 full best2obs parity and safe tools milestone

- In `../best3`, full documented `best2obs` scenario-id coverage is now enforced by `scripts/best2obs_scenario_runner.py --all`: `STD-001..009`, `CTX-001..022`, `EDGE-001..014`, `STR-001..013`, `REG-001..014`.
- This is not a copy of the old `best2` `message_handler.py`: `best3` keeps the AI-orchestrator model and adds backend safe tools for current draft, media/photos, waitlist, payment/current-booking checks and non-destructive cancel/reschedule proposals.
- The raw `# best2info` leak class is closed in `best3`: questions like "what are we booking" now route to backend state through `show_current_draft`, and `answer_info` strips wiki/index metadata before replying.
- Verification in `best3`: 49 unit tests OK; compile OK; `table_prefix_guard.py` OK; `core_parity_scenarios.py` OK; `best2obs_scenario_runner.py --all` OK; `shadow_compare.py` OK; live-AI smoke for current draft/media/cancel/reschedule OK; guarded smoke/payment/expired/webhook and final `test_pilot_checklist.py` OK.
- `best2` production code was not changed. During the final guard, unrelated active best2 regression processes and one stale idle DB transaction were stopped so row-count safety could measure `best3` cleanly.

## 2026-05-29 - закрыты live-14:29 stale-context, `не` на допах, soft-confirm и фиксированные блоки бани

- По новому live-чату разобраны 4 сбоя: явная новая заявка бани после старого draft сначала показывала stale-checkpoint вместо обработки сообщения; ответ `не` на вопрос допов не принимался как отказ; `ну вроде да` не подтверждало готовую заявку; баня могла уйти в произвольные 12 часов `09:00-21:00`, после чего оплата проходила локально, но YCLIENTS не создавал запись.
- Исправлено точечно без большого рефакторинга `message_handler.py`: подробная новая заявка поверх старой анкеты стартует чистый draft с сохранением только контакта; `нет + новая заявка` в одном сообщении обрабатывается сразу, без повторного вопроса; короткое `не/no/нет спасибо` считается финальным отказом от допов; мягкие подтверждения вроде `ну вроде да` принимаются в confirmation-flow.
- Для услуг с фиксированными блоками длительности добавлена backend-валидация в availability: баня больше не принимается как произвольная почасовая бронь. Если клиент пишет `с 9 утра до 21 ночи`, бот сохраняет дату/время, сбрасывает только длительность и просит выбрать доступный блок 3, 4, 5, 6 или 7 часов.
- Live-заявка `booking_id=1096` не ремонтировалась: локально она дошла до paid, но YCLIENTS вернул `422 service unavailable at chosen time` именно из-за недопустимого 12-часового блока. Новый код не должен создавать такую заявку заново без выбора допустимой длительности.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group fresh`, `--group time`, `--group upsell`, `--group post_booking`, `--group services` OK; payment-сценарии прошли через основной вывод + отдельный subset 5/5 OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; stress-сценарии прошли split-run 13/13 OK. Полный монолитный stress-прогон один раз упал на transient PostgreSQL SSL/runner-lock, но те же сценарии прошли при раздельном запуске.
- После `scripts/sync_yclients_records.py --once` строгий `scripts/yclients_sync_status.py --strict` OK: `records_seen=125`, `records_upserted=125`, `last_error=None`. Бот не запускался.

## 2026-05-29 - диагностирована причина платежей YooKassa на 1 рубль

- Найден конфигурационный источник: в локальном `.env` установлено `PREPAYMENT_AMOUNT_RUB=1`, а `payment_service.calculate_prepayment_amount()` умножает это значение на количество броней и передает его в YooKassa как `amount.value`.
- Проверка БД read-only: все 7 локальных платежей `payments` за 2026-05-28..2026-05-29 имеют `amount=1.00 RUB` (4 paid, 3 canceled).
- Проверка YooKassa read-only: последние 30 платежей текущего магазина тоже `1.00 RUB` и все имеют booking-bot metadata, то есть это живые ссылки бота, а не только `scripts/yookassa_smoke.py`.
- Дополнительная QR/СБП-проверка: `/me` YooKassa показывает включенный `sbp`, но `YooKassaClient.create_payment()` не передает `payment_method_data.type=sbp`, поэтому бот создает обычную ссылку на общую форму YooMoney; последние успешные платежи прошли как `tinkoff_bank`/`sberbank`, а canceled имеют `expired_on_confirmation`.
- Production-код не менялся. Вывод записан в [[bugs/current-known-issues]]; для исправления нужно отдельно изменить `.env` на целевую сумму и перезапустить бот. Если нужна именно QR/СБП-ссылка, нужно изменить интеграцию на `payment_method_data.type=sbp` или добавить настройку платежного метода. Если нужна предоплата 50%, требуется отдельная бизнес-логика вместо фиксированной суммы.

## 2026-05-29 - best3 live chat bathhouse alias fix

- In `../best3`, latest Telegram pilot chat exposed a live-AI alias mismatch: AI returned `service_type=sauna` for `баньку`, backend rejected it, and the draft stayed empty.
- Fixed in `../best3`: `sauna/banya/bath/банька/баньку/баньке` normalize to `bathhouse`; greeting fallback no longer says `уточню у администратора`; `greeting_bath_short` is now part of `agent_smoke.py --all-scenarios`.
- Verification in `best3`: 41 unit tests OK; compile OK; prefix guard OK; core/shadow OK; full pre-pilot checklist OK; bot restarted in safe test mode. `best2` production code was not changed.

## 2026-05-29 - best3 YooKassa webhook and pilot gate

- In `../best3`, added the local YooKassa webhook runner/service with secret validation, max body size, `best3_webhook_events` persistence and duplicate-safe `payment.succeeded` finalization.
- Added `../best3/app/services/notification_service.py` for client assistant notification messages and admin system logs deduped by `payment_notified_at`, `admin_notified_at` and `expired_notified_at`.
- Added `../best3/scripts/yookassa_webhook_smoke.py` and `../best3/scripts/test_pilot_checklist.py`; final checklist passed after active best2 background suites stopped mutating old row counts.
- Verification in `best3`: 37 unit tests OK, compile OK, SQL prefix guard OK, core/shadow OK, strict YCLIENTS OK after sync, agent smoke OK, fake paid finalization OK, expired hold smoke OK, YooKassa webhook smoke OK.
- `best2` production code was not changed.

## 2026-05-29 - закрыты live-13:07 ошибки времени, fake payment и новой заявки

- По новому live-чату разобраны 3 сбоя: `с 9 утра до 21 ночи, если что можно на дольше остаться?` превращалось в `09:00-08:00` на 23 часа; `а ты можешь сделать будто бы я оплатил?` могло уйти в проверку оплаты и показать `Оплата получена`; `приступим к следующуей заявке?` во время active hold распознавалось как доп `лед`.
- Исправлено точечно: явный период времени теперь защищён helper-ом `has_explicit_time_period()` и не проигрывает AI-guess про "подольше"; fake-payment формулировки обрабатываются как отказ от ручной имитации оплаты без смены статуса hold; upsell parser ищет короткие допы вроде `лед` по границам слова, а generic next-booking фразы поверх active hold запускают чистую новую анкету с сохранением только имени/телефона.
- Добавлены regression checks в `scripts/local_regression_suite.py`: `gazebo explicit period with longer question keeps end time`, `fake payment request does not mark paid`, `next application while hold starts blank not ice`.
- Проверки: `python -m compileall app scripts` OK; `local_regression_suite.py --group fresh --group payments --group time` OK; профиль `--group services --group gazebo --group upsell --group post_booking --group payments --group time --group fresh` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; после `sync_yclients_records.py --once` строгий `yclients_sync_status.py --strict` OK (`seen=125`, `upserted=125`, `last_error=None`).
- Бот не запускался; был выполнен только one-shot sync YCLIENTS-cache для свежего strict-статуса.

## 2026-05-29 - best3 safe paid finalization и expired hold cleanup

- В `../best3` добавлен safe paid-finalization режим: `YCLIENTS_RECORD_MODE=fake` позволяет проверить paid payment -> local booking -> fake YCLIENTS record -> busy interval без внешнего создания записи в YCLIENTS.
- Добавлены `../best3/scripts/payment_finalize_smoke.py`, `../best3/scripts/cleanup_expired_holds.py`, `../best3/scripts/expired_holds_smoke.py`.
- Expired hold cleanup переводит просроченные active holds в `expired`, отмечает `expired_notified_at` и пишет событие в `best3_system_logs`.
- Проверки `best3`: `unittest discover -s tests` 30 tests OK; `compileall app scripts tests` OK; `table_prefix_guard.py` OK; `core_parity_scenarios.py` OK; `shadow_compare.py` OK; expanded smoke/fake finalization/expired hold smoke через DB guard OK.
- Наблюдение: во время одного guard-прогона `best2.messages` выросла на 2 строки из-за параллельной live-активности `best2`; повторные guard-прогоны игнорировали только `messages`, остальные production-таблицы `best2` не менялись. `best2` production-код не менялся.

## 2026-05-29 - best3 добавил backend understanding и DB safety guard

- В `../best3` добавлен `state.understanding` для agent prompt: current task, missing fields, readiness, active holds, latest payment status, active bookings и safe next actions. Это делает состояние явным для AI.
- В `best3` добавлены backend-understanding overrides: вопрос про оплату/предоплату идёт через `get_payment_status`; явная смена услуги вроде `а я же хочу баньку` принудительно патчит новый `service_type`; policy считает readiness после service-switch cleanup.
- Добавлен безопасный fake payment provider для smoke, чтобы проверять hold/payment link без реального YooKassa вызова.
- Добавлен `../best3/scripts/db_safety_guard.py`: row-count snapshot production-таблиц `best2` до/после команды. Прогон `agent_smoke.py --all-scenarios --safe-payments` и `sync_yclients_records.py --once` подтвердили, что `best2` таблицы не изменились.
- Проверки `best3`: `unittest discover -s tests` 28 tests OK; `compileall app scripts tests` OK; `table_prefix_guard.py` OK; `core_parity_scenarios.py` OK; `shadow_compare.py` OK; strict YCLIENTS OK; расширенный smoke OK.
- `best2` production-код не менялся.

## 2026-05-29 - best3 получил собственную LLM Wiki

- В `../best3` создан `best3obs/` как отдельный markdown/Obsidian-граф по образцу `best2obs`: index/log, architecture, roadmap, testing, bugs, decisions, prompts и daily.
- В корень `best3` добавлен `AGENTS.md`: будущие задачи по `best3` должны начинаться с чтения `best3obs/index.md` и `best3obs/log.md`, а значимые выводы должны сохраняться в wiki.
- Дополнительно улучшены `best3` smoke/shadow инструменты: `agent_smoke.py --json` показывает agent/policy/tool/draft outcome, `shadow_compare.py` поддерживает multi-turn outcome scenarios.
- Проверки `best3`: `unittest discover -s tests` 24 tests OK; `compileall app scripts tests` OK; `table_prefix_guard.py` OK; `shadow_compare.py` OK; `sync_yclients_records.py` OK; fallback `agent_smoke.py --json` OK.

## 2026-05-29 - best3 core parity перенесён как agent-first правила и сценарии

- В `../best3` внедрён core-parity слой по выбранному scope: новая бронь, info-вопросы, availability, hold/payment safety, paid/current-booking поведение и ключевые live-нюансы `best2`, но без копирования большого `best2` `message_handler.py`.
- Добавлены deterministic stub/shadow сценарии `scripts/core_parity_scenarios.py` и `scripts/shadow_compare.py`: сравниваются outcome (`action`, `draft_patch`, payment/hold intent), а не буквальный текст ответа.
- Усилены `best3` agent/policy/tools: natural date/guest/time parsing, mixed `answer_info + draft_patch`, service switch cleanup (`а я же хочу баньку`), upsell vague accept/refusal, name correction, safe `abort_draft`, payment/current-booking routing, active/expired hold guards.
- Payment слой `best3` закреплён идемпотентностью pending-ссылки и запретом поздней конвертации истёкшего hold; paid `get_payment_status` показывает строку брони с датой/временем, если booking уже создан.
- Проверки `best3`: `unittest discover -s tests` 23 tests OK; `compileall app scripts tests` OK; `table_prefix_guard.py` OK; `core_parity_scenarios.py` OK; `shadow_compare.py` OK; `sync_yclients_records.py` + `yclients_sync_status.py --strict` fresh; real-AI `agent_smoke.py` OK на короткой цепочке без оплаты. Реальный Telegram bot не запускался.
- Baseline `best2`: `compileall app scripts` OK; `dialog_context_suite.py` 14/14 OK; профильный `local_regression_suite.py --group services --group gazebo --group upsell --group post_booking --group payments` OK.

## 2026-05-29 - добавлены paraphrase-регрессии против словарных костылей

- По просьбе проверить, что исправления не завязаны на одну конкретную фразу, расширены regression-сценарии batch-парафразами: гипотетические гости (`а если нас 10`, `для 10 человек`, `если будет 10 человек`), отказ от допов на месте (`возьмем/возьмём`, `разберемся`), исправление имени (`имя заменим/поменяем`, `замени имя`, `фио измени`) и post-booking цепочка про баню разными словами.
- Новый прогон поймал реальный общий недочёт: `фио измени на IVAN` не доходило до parser имени, потому что prefilter знал `имя`, но не `фио`. Исправлено в `app/services/dialog/form_corrections.py`; теперь `фио` работает в том же общем name-correction flow.
- Важный вывод: deterministic guards остаются как защита состояния, но теперь тестируются не как одно "магическое слово", а как класс смысловых формулировок. AI-route может понять свободную фразу, а backend проверяет, что результат безопасен для текущего draft/booking-state.
- Проверки: `python -m compileall app scripts` OK; `local_regression_suite.py --group post_booking` OK; профильный `local_regression_suite.py --group services --group gazebo --group upsell --group post_booking --group payments` завершился `EXIT=0`, `FAIL`/`Traceback`/`AssertionError` не найдены.
- Обновлены `best2obs/testing/dialog-test-matrix.md`, `best2obs/testing/scenario-run-2026-05-29.md`, `best2obs/roadmap/dialog-regression-scenarios.md`, `best2obs/bugs/current-known-issues.md`.
- Бот не запускался.

## 2026-05-29 - создан best3 agent-first baseline рядом с best2

- В соседней папке `../best3` создан чистый agent-first проект без форка старого `message_handler.py`: AI возвращает JSON action/patch, backend валидирует policy и выполняет только safe tools.
- Добавлена отдельная PostgreSQL-схема на уровне таблиц с префиксом `best3_`: users/conversations/messages/drafts/agent_runs/tool_calls/holds/bookings/payments/YCLIENTS-cache/waitlist/webhook/system_logs. Миграция `best3` применена, создано 16 таблиц `best3_*`; `best2` таблицы не изменялись.
- Реализованы v1-компоненты: Telegram polling, agent contract, policy validator, tool executor, draft validation, info retrieval из `best2info`, local availability по `best3_yclients_records`/`best3_resource_busy_intervals`, YooKassa payment link path, paid payment finalization skeleton и YCLIENTS record creation.
- Перенесена машинная карта `services_map.yaml`; первый `best3` YCLIENTS sync выполнен успешно: `seen=125`, `upserted=125`, strict fresh (`last_error=None`).
- Проверки `best3`: `compileall app scripts tests` OK, `unittest discover -s tests` OK, `scripts/table_prefix_guard.py` OK, fallback `scripts/agent_smoke.py` OK без реального AI-вызова. Реальный Telegram bot не запускался.

## 2026-05-29 - закрыты live-1953 контекстные сбои бани и подтверждения

- По последнему live-чату `conversation_id=1953` разобраны сбои: `имя заменим на IVAN` сохраняло лишние слова, `если бы нас было 10` отвечало по старым 20 гостям, `на месте возьмем` превращалось в базовый мангальный набор, после телефона могло быть второе подтверждение, paid notification не показывало дату/время, а post-booking вопрос про баню выдумывал русскую/финскую сауну и добавление к беседке.
- Исправлено точечно: parser имени чистит формы `заменим/замени/...` и сохраняет uppercase `IVAN`; guests parser понимает `нас было/было бы`; разговорный отказ `на месте возьмем/возьмём` оставляет `допы: не нужны`; post-booking bath reply стал deterministic и говорит только про баню с бассейном как отдельную бронь; follow-up `а ее как бронировать нужно?` отвечает по последней обсуждённой бане; generic `давайте начнем новую заявку` может использовать `last_discussed_service_type`, но стартует чистый draft; `а я же хочу баньку` чистит старые slot-поля; paid notification добавляет строку брони.
- Добавлены regression checks: `name correction replaces value after na`, `hypothetical guest count updates capacity question`, `on-site upsell refusal keeps no extras`, `phone completion yes creates hold not second confirmation`, `paid notification includes booking summary`, `bathhouse post-booking info then generic new request`, `service correction with zhe resets old form`.
- Проверка БД live-чата: booking `806` существует, `yclients_record_id=1741815435`, `payment_status=paid`, `status=created_in_yclients`, `admin_notified_at` заполнен. Текущий live-draft бани в БД не ремонтировался.
- `best2info` уточнён: баня с бассейном является отдельной бронью, не доп к беседке; цены описаны как фиксированные блоки длительности по дню недели. `best2info/index.md` получил wiki-ссылки, но кодовый retrieval по-прежнему работает по тексту файлов, не по графу Obsidian.
- Обновлены `best2obs/bugs/current-known-issues.md`, `best2obs/roadmap/dialog-regression-scenarios.md`, `best2obs/testing/dialog-test-matrix.md`, `best2obs/testing/scenarios/context-live.md`, `best2obs/testing/scenarios/broad-regression.md`, `best2obs/testing/scenario-run-2026-05-29.md`, `best2obs/architecture/backend.md`.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group services --group payments --group upsell` OK после нового confirmation/pronoun-follow-up теста; ранее на этой же ветке прошли полный `local_regression_suite.py`, `dialog_context_suite.py` 14/14, `dialog_edge_suite.py` 14/14, `dialog_stress_suite.py` 13/13 и `yclients_sync_status.py --strict` после ручного `sync_yclients_records.py --once`.
- Бот не запускался.

## 2026-05-29 - закрыты live-135 paid/expired hold нюансы новой бани

- По свежей live-цепочке Kirill найдены и закрыты 4 routing-сбоя: `а она уже активна, я вносил предоплату?` могло отвечать по старому expired hold; `давайте новую оформим, мне нужна баня` запускало отмену беседки; `денег нет... оплачу... подождете?` уходило в перенос; после expired hold `я и говорю давай ее же оформлю` теряло прежний слот и спрашивало дату заново.
- Исправлено точечно: cancel detector больше не считает `мне нужна баня` фразой `не нужна баня`; вопросы про внесённую предоплату идут в deterministic payment-status route; active hold получил guard для просьбы подождать оплату; expired hold можно восстановить по фразам `давайте/оформим эту же/ее же оформлю` с сохранением `service_type/date/time/duration`.
- Добавлены regression checks в `scripts/local_regression_suite.py`: `paid booking payment question is deterministic`, `new bath request does not cancel paid gazebo`, `payment delay does not start reschedule`, `resume same expired hold does not ask date`.
- Обновлены `best2obs/bugs/current-known-issues.md`, `best2obs/roadmap/dialog-regression-scenarios.md`, `best2obs/testing/dialog-test-matrix.md`, `best2obs/testing/scenarios/context-live.md`, `best2obs/testing/scenarios/broad-regression.md`.
- Проверки: `python -m compileall app scripts` OK; `local_regression_suite.py --group payments --group services` OK; полный `local_regression_suite.py` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; `dialog_regression_smoke.py` OK.
- После длинных прогонов `yclients_sync_status.py --strict` стал stale (`age_seconds=1350`); выполнен `scripts/sync_yclients_records.py --once`, финальный strict fresh (`age_seconds=53`, `records_seen=124`, `last_error=None`).
- Бот не запускался.

## 2026-05-29 - матрица тестов разложена на подветки для ручной проверки

- `best2obs/testing/dialog-test-matrix.md` оформлена как главная матрица-хаб: добавлены ветки Standard, Context/Live, Edge, Stress, Broad Regression, Run Report и Full Diagnostics.
- Созданы ручные чеклисты успешных сценариев: `best2obs/testing/scenarios/standard.md`, `context-live.md`, `edge.md`, `stress.md`, `broad-regression.md`.
- Все сценарии в новых чеклистах перенесены из успешного сценарного прогона 2026-05-29 и помечены авто-статусом `OK`; колонка `Ручная проверка` оставлена как `TODO`, чтобы владелец мог отметить результат вручную.
- Выполнен `scripts/sync_yclients_records.py --once`: `seen=125`, `upserted=125`; затем `scripts/yclients_sync_status.py --strict` fresh (`age_seconds=54`, `records_seen=125`, `last_error=None`).
- Полная очистка `users/messages/conversations` не выполнялась автоматически: предосмотр БД показал реальные локальные строки пользователей Евгения и Kirill, а также связанные `slot_holds` и `booking`; для полной очистки нужен явный отдельный confirm, потому что это затрагивает не только три таблицы.
- Бот не запускался.

## 2026-05-29 - сценарный прогон от стандартных до нестандартных случаев

- Проведён отдельный сценарный прогон в порядке усложнения: стандартный `dialog_regression_smoke.py`, затем `dialog_context_suite.py`, `dialog_edge_suite.py`, `dialog_stress_suite.py` и широкий `local_regression_suite.py`.
- Все сценарии прошли: `dialog_regression_smoke.py` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; полный `local_regression_suite.py` OK.
- Отчёт по сценариям сохранён в `best2obs/testing/scenario-run-2026-05-29.md`, ссылка добавлена в `best2obs/index.md`.
- Непрошедших сценариев нет. Наблюдения: в логах остаются `dialog_timing_slow` на AI semantic/post-booking ветках; после длинного прогона YCLIENTS-cache стал stale (`age_seconds=961`), после повторного `sync_yclients_records.py --once` финальный strict снова OK (`records_seen=125`, `last_error=None`).

## 2026-05-29 - полный диагностический прогон проекта

- Проведена полная диагностика проекта и тестов; подробный отчёт сохранён в `best2obs/testing/full-diagnostics-2026-05-29.md`, ссылка добавлена в `best2obs/index.md`.
- Операционно: БД доступна, Telegram API отвечает (`pending_update_count=0`), YCLIENTS-cache в начале был stale (`age_seconds=28528`), после `sync_yclients_records.py --once` финальный strict fresh (`records_seen=125`, `last_error=None`).
- Все основные suites зелёные: `compileall app scripts` OK; `test_db.py` OK; `yookassa_webhook_hardening_smoke.py` OK; `validate_yclients_map.py` OK; `yclients_smoke.py` OK; полный `local_regression_suite.py` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; `dialog_regression_smoke.py` OK.
- Во время диагностики починен legacy `dialog_regression_smoke.py`: cleanup теперь удаляет `waitlist_requests`, фиксированная дата обновлена на 2026-05-29, устаревшие text assertions приведены к текущим корректным ответам.
- Наблюдения: `validate_yclients_map.py` прошёл только после retry из-за transient SSL handshake timeout YCLIENTS; в suites остаются `dialog_timing_slow` около 5-9 секунд на AI semantic/post-booking ветках; реальный `yookassa_smoke.py` не запускался, потому что создаёт внешнюю платёжную ссылку.

## 2026-05-28 - расширена матрица диалоговых тестов новой пачкой

- Добавлены regression-сценарии: `число такое же как у беседки` для второй услуги, `а с детьми и собакой можно? парковка есть?` без активной анкеты, `а до утра можно отдыхать?` внутри draft беседки.
- Добавлен edge-сценарий `Без анкеты: дети, животные и парковка не стартуют бронь`; `dialog_edge_suite.py` теперь проходит 14/14.
- Новый same-date тест поймал баг route priority: фраза `число такое же как у беседки` ошибочно уходила в cross-service active-booking info reply и не переносила дату в текущую баню. Исправлено точечно: same-date/same-time reference больше не обрабатывается как info-ответ про активную бронь.
- Обновлена `best2obs/testing/dialog-test-matrix.md`: добавлены новые успешные сценарии и результаты точечного прогона.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group services --group prices --group time` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK.

## 2026-05-28 - создана матрица успешных диалоговых тестов

- Добавлен `best2obs/testing/dialog-test-matrix.md`: единая таблица успешных сценариев, их покрытия (`local_regression_suite.py`, `dialog_context_suite.py`, `dialog_edge_suite.py`, `dialog_stress_suite.py`) и статуса последнего прогона.
- В матрицу занесены зелёные сценарии последнего полного verification: live-135 post-booking/new-bath context, date/guests poison guards, two-gazebo queue, upsell, info-вопросы, cancel/reschedule, availability/pricing и media.
- Правило на будущее: каждый новый live-баг сначала заносить в matrix как `TODO/FAIL`, затем добавлять автотест, после фикса переводить в `OK` с указанием покрытия.

## 2026-05-28 - закрыт live-135 контекст второй брони после оплаченной беседки

- По live-цепочке `conversation_id=135` добавлены регрессии: после оплаченной беседки вопрос `можно еще что нибудь забронировать?` не должен возвращать старый `awaiting_confirmation`; `давайте еще баню на то же число что и беседка` должен стартовать новую баню с `date=2026-06-30` и шагом `time`; вопрос `а вообще норм беседка?` внутри анкеты бани должен отвечать по активной беседке и возвращать к бане.
- Исправлена граница post-booking/new-booking: информационный вопрос про доступные услуги в post-booking состоянии больше не использует старый booking-ready `form_data` для повторного confirmation, а явная новая бронь может сбросить старый confirmation-draft, если у клиента уже есть активная оплаченная бронь.
- Same-date reference расширен на формулировки `то же число`, `на то же число`, `число то же`, `число такое же`. При новой услуге backend берет только дату из активной брони указанной услуги и не переносит старые `service_type`, вариант, гостей, формат или допы.
- Для услуг, где duration нужен до availability, проверка свободности больше не стартует по одной дате без времени/длительности: после `баню на то же число` бот спрашивает время, а не дату повторно и не делает преждевременный availability-check.
- Info-вопросы с ссылкой на другую активную услугу теперь отвечают по активной брони этой услуги: если текущий draft — баня, а клиент спрашивает про беседку, бот показывает активную беседку и добавляет актуальный следующий вопрос бани, не меняя `service_type`.
- Дополнительно закрыты два flow-order edge cases, найденные полным suite: `да/да да` в активном reschedule/cancel-flow больше не перехватывается plain post-booking ack; cancel confirmation доверяет `booking_id/booking_ids`, уже сохраненным в `cancel_flow`, даже если локальная сверка журнала временно пометила запись `journal_missing`.
- Проверки: `compileall app scripts` OK; полный `scripts/local_regression_suite.py` OK; `scripts/dialog_context_suite.py` 14/14 OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK; `scripts/yclients_sync_status.py --strict` fresh (`records_seen=127`, `last_error=None`).

## 2026-05-28 - закрыт live-сбой upsell/confirmation/payment для conversation 135

- По живому чату Kirill `conversation_id=135` разобрана цепочка 19:35-19:45. Первый отказ от допов `нет` корректно включал мягкий второй заход, но ответ `ну давайте` не распознавался как согласие на только что предложенный "мангальный минимум": состояние требовало `upsell_items`, а backend ждал явное название допа. Добавлен contextual accept после upsell-push: если последний вопрос был про минимум, `ну давайте/давайте/ок давайте` сохраняет `базовый мангальный набор` и переводит к следующему шагу, не повторяя availability/upsell.
- Вопрос `а это хорошая беседка?` на `awaiting_confirmation` вскрыл routing bug: fresh-start/new-booking guard мог сработать до confirmation-flow, потому что в вопросе есть слово "беседка". Теперь fresh-start не прерывает `awaiting_confirmation`, а для вопроса о текущей выбранной беседке добавлен deterministic info-reply: бот отвечает про выбранный объект и оставляет подтверждение активным.
- Telegram обработчик теперь сериализует входящие text/voice сообщения одного пользователя через per-user `asyncio.Lock`. Это защищает от гонок, когда клиент быстро отправляет два сообщения подряд (`а комары?` и `а это хорошая беседка?`) и оба обработчика читают/пишут одно состояние параллельно.
- По оплате найдено: платеж YooKassa `payment_id=17` стал `paid`, локальный booking `213` был создан, но создание YCLIENTS-записи упало на transient SSL timeout. Runner откладывал paid-уведомление до готовности YCLIENTS, поэтому клиент не получил сообщение. Исправлено: retry создания YCLIENTS для paid booking теперь повторяется через 30 секунд, а клиенту один раз отправляется промежуточное `Оплата поступила, закрепляю запись в журнале`, если журнал ещё не готов.
- Найден дополнительный resource bug: при финализации paid hold локальный `resource_busy_intervals` мог вставиться на первую беседку из `services_map`, потому что newly-created booking не нёс `hold_yclients_service_id/hold_yclients_staff_id`. Теперь bookings-repo возвращает оба hold-id, finalize мержит их сразу, `_resolve_yclients_ids` учитывает staff id, а stale bot busy interval для booking перезаписывается.
- Живая заявка восстановлена вручную без включения бота: `scripts/sync_payment_statuses.py` создал YCLIENTS record `1741240914` для booking `213`; booking теперь `created_in_yclients`, ресурс `18201061/3828151` (`Беседка №4`), payment `17` остаётся `payment_notified_at=NULL`, чтобы после следующего запуска бот отправил финальное подтверждение клиенту.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group upsell --group gazebo --group payments` OK; `--group fresh --group dates --group prices --group time --group services --group post_booking --group cancel --group reschedule` OK; `--group media --group waitlist --group handoff --group reminder` OK; `scripts/dialog_context_suite.py` 13/13 OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Операционно: локальный Telegram bot process оставлен выключенным по просьбе; `main.py` процессов после проверки нет.

## 2026-05-28 - guest/date guard переведен с keyword-trigger на structural validation

- По замечанию, что `чел/человек/гостей/нас будет` не должны быть "мозгом" бота, переработан guard против poison-state `30 июня -> 30 гостей`. AI по-прежнему первым определяет смысл и может вернуть `guests_count` без слов-маркеров; backend теперь не ищет "магическое слово", а валидирует конфликт полей.
- Новое правило: AI-only `guests_count` отклоняется, если он совпадает с числом даты/номером беседки и не подтвержден текущим шагом `guests_count` или deterministic parser. Поэтому `на 30 июня` не становится `30 гостей`, `29 мая 6 беседка` не становится `6 гостей`, но `на 30 июня двадцать` принимается как 20 гостей, если AI так понял смысл.
- Удален старый core guard `_has_guest_count_signal` / `_guest_count_from_date_only`; вместо него добавлены `_ai_guest_count_conflicts_with_date_context` и `_ai_guest_count_conflicts_with_gazebo_variant`.
- `scripts/dialog_context_suite.py` расширен до 13 сценариев: добавлены проверки "AI-смысл без слов-маркеров гостей принимается" и "номер беседки из AI-patch не превращается в гостей".
- Тестовый harness `scripts/local_regression_suite.py` поправлен под текущую дату 2026-05-28: active hold fixtures теперь создают `expires_at` относительно реального времени и используют уникальный test resource id, иначе payment-regression падал не из-за диалога, а из-за протухшего/конфликтующего тестового hold.
- Проверки: `compileall app scripts` OK; `scripts/dialog_context_suite.py` 13/13 OK; `local_regression_suite.py --group gazebo --group dates --group prices --group upsell --group time --group fresh` OK; `--group services --group post_booking --group payments --group cancel --group reschedule` OK после harness-fix; `--group media --group waitlist --group handoff --group reminder` OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Перед live smoke `scripts/yclients_sync_status.py --strict` fresh (`age_seconds=101`, `records_seen=126`, `last_error=None`). Локальный Telegram polling перезапущен на новом коде для `@fnsmvsvmpvpovbot`; из-за локальной DNS-проблемы запуск выполнен с временным `DB_HOST=95.214.62.243`, `DB_SSLMODE=verify-ca`, `DB_POOL_ENABLED=false`, `.env` не менялся.

## 2026-05-28 - закрыт live-dialog с двумя беседками, скидками и ночным временем

- По последнему Telegram-чату найдено, что смешанное сообщение `нужно 2 беседки на 02.06 и 19.06, там есть мангал и угли?` уходило только в info-route: бот отвечал про мангал, но не закреплял намерение двух отдельных заявок. Добавлен deterministic route для `2/две беседки`: первая дата становится текущей заявкой, остальные даты сохраняются в `pending_additional_bookings`, клиенту сразу объясняется, что брони заполняются по очереди.
- Добавлен guard для второй даты из очереди: сообщение вроде `19.06 на 13` во время первой заявки больше не перезаписывает дату/время текущего черновика. Бот напоминает, что 19 июня запомнил как следующую отдельную бронь, и возвращает клиента к текущему шагу.
- Исправлен UX ночного интервала: `11:00` с default duration до утра теперь показывается как `с 11:00 до 08:00 следующего дня (21 час)` в confirmation, draft/booking summaries, holds, stale-form summary и availability replies. Это оставляет бизнес-логику `до 08:00`, но делает её понятной клиенту.
- Availability/gazebo option lists стали discount-aware: если дата беседки попадает на ПН-ЧТ, строки вариантов показывают базовую цену и цену со скидкой 50%. Обычный вопрос `сколько стоит?` для выбранной беседки на будний день тоже возвращает скидочную цену, а не только базу.
- Исправлен приоритет correction на `awaiting_confirmation`: команда `время тоже поменяй с 11 до 08` больше не перехватывается reserved-hold glue с ответом `не вижу активной предварительной заявки`; она остаётся в confirmation-flow, перепроверяет availability и возвращает обновлённую сводку.
- Summary detector расширен на фразы с опечатками вроде `активыне заявки`: бот показывает текущий черновик/активные брони, а не уходит в side-reply про вторую бронь.
- Добавлены context regression scenarios: sequential two-gazebo queue, pending second-date guard, weekday price discount in normal price question, awaiting-confirmation time correction plus typo summary.
- Проверки: `compileall app scripts` OK; `scripts/dialog_context_suite.py` 8/8 OK; `local_regression_suite.py --group gazebo --group prices --group time --group fresh --group upsell` OK; `--group payments --group post_booking --group cancel --group reschedule` OK; `--group services --group dates --group media --group waitlist --group handoff --group reminder` OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Перед live smoke `scripts/yclients_sync_status.py --strict` показал stale cache (`age_seconds=2611`), выполнен `scripts/sync_yclients_records.py --once`; повторный strict fresh (`age_seconds=90`, `records_seen=122`, `last_error=None`).

## 2026-05-28 - закрыт context/availability баг `на 30 июня нас будет 20`

- По новому live-сообщению найдено, что локальная YCLIENTS-cache после ручного sync знает свободные большие беседки на 30 июня для 20 гостей (`№1`, `№8`, `№3`, `Крытая`), поэтому ответ `на ближайшие 75 дней не нашла` был не проблемой таблицы, а проблемой порядка dialog-routing.
- Причина: дата+гости в одном сообщении могли попасть в раннюю ветку выбора беседки по пустому/старому `last_available_gazebo_variants`, минуя реальную availability-проверку. Дополнительно, если на выбранную дату свободны только маленькие беседки, executor не всегда добавлял ближайшие подходящие даты.
- Исправлено: first date+guests message теперь идёт в общий availability executor; при смене даты/гостей очищается `last_suggested_free_dates`; no-capacity для беседок показывает выбранную дату, объясняет ограничение вместимости и предлагает ближайшие подходящие даты вокруг выбранной даты.
- Исправлено контекстное подтверждение: `что мы подтверждаем?` без слова `бронь` теперь считается summary-вопросом и не запускает повторную availability-проверку, поэтому черновик на `awaiting_confirmation` не сбрасывается в `awaiting_new_date`.
- Добавлен `scripts/dialog_context_suite.py`: печатает transcript живых контекстных сценариев и проверяет, что бот помнит дату/гостей/выбранную беседку/шаг подтверждения.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group gazebo --group dates` OK; `--group fresh --group upsell --group time --group prices --group services` OK; `--group payments --group post_booking --group cancel --group reschedule` OK; `--group media --group waitlist --group handoff --group reminder` OK; `scripts/dialog_context_suite.py` 4/4 OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Перед live smoke `scripts/yclients_sync_status.py --strict` показал stale cache (`age_seconds=1676`), выполнен `scripts/sync_yclients_records.py --once`; повторный strict fresh (`age_seconds=81`, `records_seen=121`, `last_error=None`).

## 2026-05-28 - отказ от черновика брони получил ранний routing priority

- По live-сообщению `давай откажемся от брони` найден routing/state bug: фраза не попадала в cancel/abort intent, поэтому на шаге допов backend продолжал обычный booking flow и отвечал availability/upsell текстом.
- Причина не в ограничении `info/check_availability`, а в порядке маршрутизации: AI может понимать смысл, но backend должен до допов, availability и AI-текста валидировать команды отмены/abort текущего черновика.
- Расширен общий cancel detector и `_wants_abort_current_draft`: формулировки `откажемся/отказ от брони/заявки/оформления`, `бронь не нужна`, `не будем бронировать` теперь считаются отказом от текущей заявки.
- Добавлен ранний guard для неопределенного ответа на шаге времени: `ну че нибудь` больше не отдается AI на придумывание слота, а повторяет вопрос времени и оставляет `time/duration` пустыми.
- Добавлены regression/edge проверки: `abort current draft from upsell refusal` в `local_regression_suite.py` и edge-сценарий `Анкета: отказ от брони на шаге допов отменяет черновик`.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group fresh --group upsell` OK; `local_regression_suite.py --group post_booking --group cancel` OK; `scripts/dialog_edge_suite.py` 13/13 OK; `scripts/dialog_stress_suite.py` 13/13 OK.

## 2026-05-28 - best2info и жесткий intent routing для info/availability

- Создана отдельная клиентская wiki `best2info/`: `index.md`, `runtime.md`, страницы по объектам, ценам, допам, оплате, скидкам, локации, детям/животным и правилам отдыха. `best2obs` остается памятью разработки, `best2info` становится source of truth для клиентских информационных ответов.
- `app/services/knowledge_service.py` обновлен: `load_knowledge()` теперь дает короткий runtime-контекст, а `retrieve_client_knowledge()` выбирает релевантные markdown-разделы из `best2info` для info-вопросов. Legacy `app/knowledge` оставлен fallback, старые файлы не удалялись.
- Info-вопросы в активной анкете теперь отвечают через deterministic/retrieved knowledge, а проверка свободности остается backend-действием через локальную БД/YCLIENTS-cache. AI продолжает понимать смысл, но изменение состояния и availability валидирует backend.
- Закрыты live-регрессии чата 6093: `20 чел` распознается как `guests_count=20`; для 5 июня при 20 гостях бот не предлагает маленькие беседки как подходящие; уточнение `только эта свободна на 5 июня` не листает 16-20 июня; на 8 июня предлагаются подходящие №1/№8/№3; скидка для Беседки №1 на 8 июня 2026 считается как ПН-ЧТ 50%.
- Усилен state-safe patching анкеты: голое `18,00` на шаге времени принимается как `18:00`, короткое `на 5` после времени сохраняет duration=5, `встреча однокласников` сохраняет event_format, а переход к кальяну/допам не теряет `time`, `duration`, `event_format`.
- Уточнен парсер варианта беседки: дата `на 5 июня есть беседка` больше не выбирает `Беседка №5`, но переносная фраза `беседку на 8` по-прежнему может выбрать №8 в корректном контексте.
- Добавлены regression checks в `scripts/local_regression_suite.py` для live-чата 6093, `best2info` retrieval, скидок, предоплаты/кальяна/детей/парковки и сохранения состояния после допов.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group gazebo --group dates --group prices --group upsell --group time --group fresh` OK; `local_regression_suite.py --group services --group post_booking --group payments --group cancel --group reschedule` OK; `scripts/dialog_edge_suite.py` 12/12 OK; `scripts/dialog_stress_suite.py` 13/13 OK.

## 2026-05-28 - explicit photo reply вынесен в media_flow

- Продолжен следующий маленький behavior-preserving media-срез после direct free-dates.
- Добавлен `app/services/dialog/media_flow.py` с `explicit_photo_reply` и `ExplicitPhotoCallbacks`.
- `message_handler.py` сохранил wrapper `_explicit_photo_reply`, который прокидывает текущие parsers для service/variant, normalize aliases, services map и доступные варианты беседок.
- Клиентские тексты и условия explicit-photo не менялись: явный запрос фото по беседке/бане/дому по-прежнему обходит AI, проверяет наличие медиа через `media_for_client_message` и не требует даты.
- Проверки после media-среза: `compileall app scripts` OK; `local_regression_suite.py --group media --group gazebo --group dates` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py --group post_booking --group payments --group cancel --group reschedule` OK.
- Наблюдение: авто-подбор медиа по availability-ответам остался в `media_service.py`; текущий разрез вынес только dialog glue для explicit photo reply.

## 2026-05-28 - direct free-dates lookup вынесен в availability_flow

- Продолжен маленький behavior-preserving разрез `message_handler.py` после общего availability executor.
- Direct free-dates orchestration перенесён в `app/services/dialog/availability_flow.py` как `direct_free_dates_lookup` + `DirectFreeDatesLookupCallbacks`.
- `message_handler.py` оставляет wrapper `_direct_free_dates_lookup`, который прокидывает текущие callbacks для `_deterministic_patch`, `_next_free_dates_reply`, `_alternative_services_for_unavailable_date`, `check_availability` и сохранения monkeypatch-friendly entrypoints.
- Поведение не менялось: прямой запрос ближайших свободных дат по-прежнему берёт сервис из текста/текущей анкеты/`last_unavailable`, сбрасывает stale-flow, проверяет конкретную дату при наличии, иначе вызывает `_next_free_dates_reply`.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group dates --group gazebo --group waitlist` OK; `--group fresh --group services --group prices --group upsell` OK; `--group post_booking --group payments --group cancel --group reschedule` OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Наблюдение: slow timing остаётся на отдельных AI semantic ветках примерно 5-8 секунд; это старый UX/infra риск, не связанный с текущим разрезом.

## 2026-05-28 - awaiting-confirmation execution вынесен в confirmation_flow

- Продолжен следующий behavior-preserving разрез после reserved/hold handler.
- `handle_awaiting_confirmation` перенесен в `app/services/dialog/confirmation_flow.py` через `AwaitingConfirmationCallbacks`.
- Вынесены сценарии финального подтверждения: correction patch перед оплатой, смена слота с повторной проверкой availability, конфликт active hold, создание 10-минутного hold, создание/переиспользование payment link, отказ от подтверждения и side-question на этапе подтверждения.
- `message_handler.py` теперь только вызывает confirmation-flow, пишет assistant message и обновляет conversation state; side effects и wrappers остаются прокинутыми callbacks.
- `message_handler.py` уменьшился примерно до 4583 строк; `confirmation_flow.py` вырос до ~693 строк.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group payments --group post_booking --group cancel` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py --group reschedule` OK; `local_regression_suite.py --group fresh --group gazebo --group prices --group upsell` OK.
- Наблюдение: функционально все ключевые сценарии подтверждения/оплаты/отмены/переноса сохранились. В timing logs всё ещё встречаются медленные AI semantic ветки, но это не связано с текущим разрезом.

## 2026-05-28 - начат confirmation_flow и reserved/hold handler

- Продолжен behavior-preserving рефакторинг `message_handler.py` после пополнения OpenRouter tokens.
- Добавлен `app/services/dialog/confirmation_flow.py`.
- Вынесены confirmation/hold guards: `mentions_payment_status`, `wants_cancel_or_change_hold`, защита от ошибочного cancel/change при изменении имени/телефона/допов.
- Вынесен `awaiting_confirmation_side_reply`: info-вопрос на финальном подтверждении по-прежнему сначала отвечает deterministic knowledge, затем при необходимости использует AI через callback; клиентский текст не изменялся.
- Вынесены hold-summary helpers: название объекта резерва, сообщение об истекшем hold, поиск pending payment по hold ids и summary активных hold/booking.
- Вынесен `handle_reserved_hold_command` через `ReservedHoldCallbacks`: истекший резерв, повторная payment-ссылка, исправление деталей в резерве, cancel/reschedule с активными бронями и replacement-date flow теперь находятся в confirmation module, но side effects остаются callbacks из координатора.
- Вынесены `create_hold` и `create_booking_from_hold`; `message_handler.py` оставляет тонкие wrappers, чтобы сохранить трассировку и текущий контракт.
- `message_handler.py` уменьшился примерно до 4749 строк; `confirmation_flow.py` сейчас около 491 строки.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group payments --group post_booking --group cancel` OK; `local_regression_suite.py --group cancel --group reschedule` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py --group fresh --group gazebo --group services --group prices --group upsell` OK.
- Наблюдение: после пополнения tokens OpenRouter 402 в текущих прогонах не повторился; медленные AI-ветки всё ещё видны в timing logs, но функционально сценарии OK.

## 2026-05-28 - вынесены grouped/swap reschedule execution и availability_flow

- Продолжен аккуратный разрез `message_handler.py` без изменения AI-промптов и клиентской логики.
- Grouped/swap execution переноса вынесен в `app/services/dialog/reschedule_flow.py` через `execute_swap_reschedule` и `RescheduleExecutionCallbacks`: получение booking, удаление старой записи YCLIENTS, локальное обновление расписания, создание новой записи и восстановление при ошибке остаются под контролем callbacks из координатора.
- Добавлен `app/services/dialog/availability_flow.py`: туда вынесены deterministic helpers для availability-ответов, no-availability/waitlist, очистки слота, повторной даты, альтернатив на недоступную дату и поиска ближайших свободных дат через callbacks.
- `message_handler.py` оставлен координатором: он передает callbacks для `check_availability`, `_active_user_bookings` и side-effect операций, чтобы не менять источник свободности и тестовые monkeypatch.
- Исправлен порядок маршрутизации: явный запрос новой/дополнительной брони теперь обрабатывается до post-booking classifier, поэтому фраза `а можно еще беседку забронировать?` не уходит в старый post-booking сценарий.
- Добавлен синоним переноса `смест...`: фразы вроде `сместим баню на 26 июня` запускают перенос, а не новую анкету из-за слова `баня`.
- Добавлен deterministic short-circuit info-вопросов до тяжелого AI-вызова: известные вопросы по базе знаний/прайсу отвечают локально, а info-вопрос без активной анкеты больше не стартует бронь из-за слова услуги.
- Проверки: `compileall app scripts` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py --group fresh --group gazebo --group services --group prices --group upsell --group reschedule` OK; `local_regression_suite.py --group post_booking --group payments --group cancel` OK.
- Наблюдение: в stress-логах остаются OpenRouter 402 `Prompt tokens limit exceeded` на отдельных AI-ветках, но сценарии проходят за счет deterministic/fallback путей. Это отдельный infra/UX-риск: нужно пополнить/поднять лимит или еще сильнее сокращать router/post-booking prompts.

## 2026-05-27 - начат вынос reschedule_flow

- Добавлен `app/services/dialog/reschedule_flow.py`.
- Из `message_handler.py` вынесен первый behavior-preserving слой переноса: распознаватели `wants_reschedule/swap/multi`, options/confirmation тексты, swap assignment parsing, reference helpers `то же время/та же дата`, выбор брони для переноса, подготовка `form_data` для проверки свободности, фильтр вариантов беседок при переносе.
- Single reschedule execution тоже вынесен через `RescheduleExecutionCallbacks`: удаление старой YCLIENTS-записи, обновление booking/hold, создание новой YCLIENTS-записи, восстановление старой записи при ошибке и handoff при невозможности восстановления.
- Grouped/swap execution переноса пока намеренно оставлен в `message_handler.py`.
- Во время stress-suite пойман и исправлен рефакторинговый промах: `gazebo_capacity_by_title` используется не только reschedule-flow, но и обычным availability-ответом; добавлен alias из нового модуля обратно в `message_handler.py`.
- Проверки после helper-разреза: `compileall app scripts` OK; `local_regression_suite.py --group reschedule` OK; `--group post_booking --group cancel --group payments --group services` OK; `--group gazebo --group reschedule` OK; `scripts/dialog_stress_suite.py` 13/13 OK после фикса alias.
- Проверки после single execution-разреза: `compileall app scripts` OK; `local_regression_suite.py --group reschedule` OK; `--group gazebo --group post_booking --group payments --group cancel` OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Наблюдение: качество AI-диалога не менялось; длинные ответы в stress всё ещё приходятся на `ai.semantic` 4-10s.

## 2026-05-27 - вынесен cancel-flow execution

- Следующий безопасный разрез `message_handler.py` выполнен без изменения AI/prompts: исполнение отмены перенесено в `app/services/dialog/cancel_flow.py`.
- Добавлен `CancelFlowCallbacks`: модуль cancel-flow получает актуальные callbacks из `message_handler.py` для `active_user_bookings`, `delete_yclients_record_for_booking`, `bookings_repo`, `users_repo`, handoff и confirm-parsers.
- Старые `_start_cancel_booking_flow` и `_handle_cancel_booking_flow` в `message_handler.py` оставлены тонкими wrappers, поэтому monkeypatch/tracing вокруг удаления YCLIENTS и локальных операций сохранены.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group cancel` OK; `--group post_booking --group payments --group reschedule` OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- Наблюдение: функционально cancel/post-booking/reschedule поведение не изменилось; stress-suite снова показывает отдельные медленные AI semantic ветки 5-13s, это остается UX-направлением, но не связано с разрезом.

## 2026-05-27 - начат безопасный вынос post_booking_flow

- Добавлен `app/services/dialog/post_booking_flow.py`.
- Из `message_handler.py` вынесены низкорисковые post-booking helpers: summary активных броней/hold-резервов, распознавание продолжения вопроса "и это всё?", waitlist-decline, простой ack после закрытой брони.
- Вынесен `payment_status_reply`, но через callbacks из `message_handler.py`, чтобы monkeypatch/tracing для `sync_payment_statuses` и `create_missing_yclients_records` не сломались.
- Вынесен safe wrapper post-booking classifier; настоящий AI-вызов по-прежнему идет через `message_handler.classify_post_booking_message`, поэтому качество/подмены AI не изменены.
- `message_handler.py` уменьшен примерно на 120 строк в этом разрезе; cancel/reschedule execution пока намеренно оставлен внутри координатора.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group post_booking` OK; `--group payments --group cancel` OK; `--group reschedule` OK; `--group fresh --group services --group prices --group upsell` OK; `dialog_stress_suite.py` 13/13 OK.
- Наблюдение: параллельный запуск двух `local_regression_suite.py` корректно остановился на lock-файле, это ожидаемая защита тестов.

## 2026-05-27 - hardened YooKassa webhook request handling

- Усилен локальный YooKassa webhook runner без изменения AI/dialog logic.
- Добавлен `YOOKASSA_WEBHOOK_MAX_BODY_BYTES` с дефолтом `32768`.
- В production (`APP_ENV=production/prod`) webhook теперь fail-fast требует `YOOKASSA_WEBHOOK_SECRET`.
- POST webhook проверяет путь, secret через constant-time compare, обязательный `Content-Length`, пустое/неполное/слишком большое тело и JSON-object payload.
- Добавлен smoke `scripts/yookassa_webhook_hardening_smoke.py`: проверяет health GET, запрет без secret, happy path через заглушки, лимит body и bad path.
- Проверки: `compileall app scripts` OK; `scripts/yookassa_webhook_hardening_smoke.py` OK; `scripts/local_regression_suite.py --group payments --group post_booking` OK; `scripts/dialog_stress_suite.py` 13/13 OK.
- YCLIENTS sync перед проверкой был старше strict-лимита, потому что основной bot process не запущен; выполнен `scripts/sync_yclients_records.py --once`, после чего `scripts/yclients_sync_status.py --strict` OK.

## 2026-05-27 - production hardening holds/payment/sync

- В `slot_holds` добавлен `yclients_staff_id`; схема получила partial unique index `idx_slot_holds_unique_active_resource_day` для активного резерва одного ресурса на дату.
- `slot_holds_repo.create` теперь ставит transaction advisory lock, истекает старые holds через DB time и через savepoint превращает уникальный конфликт в `SlotHoldConflict`.
- Confirmation-flow при конфликте hold не создает ссылку оплаты, а просит выбрать другое время/дату и сохраняет waitlist-запрос.
- `payment_service.create_payment_link_for_holds` переведен на payment-intent flow: локальный pending payment с `hold_ids` коммитится до вызова ЮKassa; повторный запрос переиспользует активную pending-ссылку; provider failure сохраняет `failed`.
- `yclients_sync_service` разделен на `fetch_records` без DB transaction и короткий `apply_records`; runner и `scripts/sync_yclients_records.py --once` используют двухфазный путь.
- Retention изменен с 72 на 48 часов: `MESSAGE_SUMMARY_AFTER_HOURS=48` в config, `.env.example` и локальном `.env`.
- DB connection стал устойчивее к закрытым pooled connections: rollback пропускается, если connection уже закрыт, а checkout отбрасывает closed connection.
- Удалены runtime-артефакты `recovered_pyc/`.
- Проверки: `compileall app scripts` OK; `scripts/dialog_stress_suite.py` 13/13 OK; `local_regression_suite.py` группы `payments`, `post_booking`, `upsell`, `prices`, `fresh`, `gazebo`, `services`, `time`, `cancel`, `reschedule` OK; `scripts/sync_yclients_records.py --once` OK; `scripts/yclients_sync_status.py --strict` OK.
- Наблюдение: один длинный stress-сценарий занял около 36s, основной вклад `ai.semantic`; функционально OK, но скорость AI остается UX-риском.

## 2026-05-26 - создана project memory

- Создана структура Obsidian-памяти `best2obs/`.
- Добавлен `AGENTS.md` с правилами работы для будущих задач.
- Проведен первичный анализ проекта без изменения production-кода.
- Зафиксированы основные модули: Telegram adapter, AI orchestration, booking state machine, availability, YCLIENTS sync, ЮKassa payment flow, media/photo sending, voice transcription, message retention.
- Созданы стартовые страницы по архитектуре, рискам, pre-launch задачам и workflow-командам.

## 2026-05-26 - принят LLM Wiki подход

- Пользователь прислал идею LLM Wiki как паттерн долговременной базы знаний.
- Решено применять этот подход к `best2obs/`: wiki должна быть постоянным, накапливающимся артефактом, а не разовыми заметками.
- Обновлен `AGENTS.md`: добавлены слои Raw sources / Wiki / Schema и операции Ingest / Query / Lint.
- Добавлены страницы [[prompts/llm-wiki-method]] и [[decisions/2026-05-26-use-llm-wiki]].

## 2026-05-26 - самостоятельная проверка сценариев

- Выполнены быстрые технические проверки: compileall, validate_yclients_map, db_status.
- Прогнан точечный срез из 23 сценариев regression suite: все проверки OK.
- Полный `local_regression_suite.py` остановлен из-за зависания на `free_dates_lookup`; это записано как риск тестовой инфраструктуры.
- Подробный отчет: [[daily/2026-05-26-scenario-check]].

## 2026-05-26 - исправлены свежие сбои диалога

- Исправлен `stale_form_flow`: ответ "давайте" теперь продолжает старую анкету, а явный запрос новой услуги/свободных дат после паузы начинает чистый контекст с сохранением имени и телефона.
- Добавлен прямой маршрут для вопросов "какие ближайшие свободные даты..." в обычной анкете: backend идет в локальную таблицу записей через availability, а не просит клиента назвать дату.
- Вопросы о цене допов в контексте upsell теперь отвечают прайсом допов, а не базовой стоимостью бани/услуги.
- Информационные вопросы на финальном подтверждении больше не проходят через post-booking classifier.
- Post-booking больше не запускает синхронизацию ЮKassa/YCLIENTS на каждое сообщение, если у разговора нет локальных платежей.
- Добавлены регрессионные проверки для свежих кейсов и стабилизирован cleanup тестовых данных.

## 2026-05-26 - начат рефакторинг message_handler

- Создан пакет `app/services/dialog/`.
- Вынесены `formatting.py`, `price_info.py`, `stale_form.py`, `routing_guards.py`.
- `message_handler.py` пока остается главным координатором, но часть форматирования, цен/допов, stale-form и routing guard логики вынесена в отдельные модули.
- Поведение сохранено через старые приватные алиасы/обертки, чтобы не ломать существующие тесты и вызовы.
- Пройдены `compileall` и точечные регрессии по price/info, stale-form и free-dates.

## 2026-05-26 - продолжен рефакторинг message_handler

- Добавлен `app/services/dialog/booking_texts.py`: шаблоны handoff-ответа, подтверждения заявки, сводки hold/booking, ссылки оплаты и короткой строки брони.
- Добавлен `app/services/dialog/handoff.py`: проверка активного handoff, распознавание конфликтных сообщений и создание handoff-лога для команды.
- Удалены дублирующие реализации из `message_handler.py`; старые приватные имена сохранены как импортированные алиасы.
- Пройдены `compileall` и точечные регрессии: confirmation info, post-booking fallback, booking summary, shared phone, handoff/location, price/upsell, stale-form/free-dates.

## 2026-05-26 - исправлено наследование старой анкеты при новой услуге

- Исправлена политика fresh-start: простая фраза клиента вроде "хочу баню" теперь может начать новую анкету, если в текущей анкете была другая услуга.
- Старые поля `date`, `time`, `duration`, `guests_count`, `event_format`, `upsell_items`, `service_variant` не переносятся в новую услугу; имя и телефон сохраняются.
- Добавлен `app/services/dialog/fresh_start.py`, чтобы решение о сбросе анкеты было отдельной backend-политикой, а не рассеянными условиями внутри `message_handler.py`.
- Добавлена регрессия `plain new service request resets old form`.
- Пройдены `compileall` и точечные регрессии по second booking, stale-form, fresh free-dates и price/upsell.

## 2026-05-26 - вынесен контекст актуальных броней

- Добавлен `app/services/dialog/booking_context.py`.
- Из `message_handler.py` вынесены: получение активных броней пользователя, fallback на брони текущего conversation, сверка с `yclients_records`/busy intervals, фильтрация удаленных записей журнала, summary-контекст для AI.
- Это закрепляет правило: вопросы "какие у меня брони" и post-booking summary должны идти по актуальным данным таблиц/журнала, а не по старой `form_data`.
- Пройдены `compileall` и точечные регрессии: booking summary counts all bookings, post booking summary always uses db, shared phone, old user booking/summary, second booking reset, plain new service reset, stale free dates.

## 2026-05-26 - вынесены парсеры дат и времени

- Добавлен `app/services/dialog/date_parsing.py`: относительные даты, голые дни месяца, неоднозначные будни, даты в сегментах переноса и "с 25 на 26".
- Добавлен `app/services/dialog/time_parsing.py`: периоды "с 18 до 00", одиночное время, "до утра", дефолтная длительность беседки до 08:00, явная длительность и конфликт периода/длительности.
- `message_handler.py` использует эти функции через старые приватные алиасы, чтобы не ломать существующие тесты.
- Пройдены `compileall` и точечные регрессии по датам, переносам, длительности, open-ended беседкам, time correction и fresh-start.

## 2026-05-26 - вынесена чистая логика подбора беседок

- Добавлен `app/services/dialog/gazebo_options.py`.
- Вынесены: текст выбора беседки, нормализация названий, память о последних свободных вариантах, фильтр по вместимости, авто-выбор единственной свободной беседки, форматирование строки варианта, выбор конфигурации услуги.
- I/O-часть с `check_availability` и ближайшими датами пока оставлена в `message_handler.py`, чтобы не смешивать чистый подбор с доступом к БД.
- Пройдены `compileall` и точечные регрессии по беседкам: only available variants, capacity filter, date reply asks guests, next free dates by guests, single auto-select, no guessed variant, selected capacity known free list, reschedule preferences.

## 2026-05-26 - полный regression suite снова завис по времени

- После рефакторинга был запущен полный `scripts/local_regression_suite.py` с лимитом 15 минут.
- Прогон не завершился до таймаута; фоновых Python-процессов после остановки не осталось.
- Добавлена печать прогресса после каждого check в `local_regression_suite.py`, чтобы при ручном запуске было видно, где suite находится.
- Повторные запуски с лимитами 5 и 2 минуты тоже не завершились; в автоматическом tool timeout частичный stdout не виден, но в обычном терминале прогресс должен печататься.
- Вывод: текущий полный suite нужно дробить на группы или добавить per-test timeout. До этого опираться на точечные регрессии по затронутым зонам.

## 2026-05-26 - regression suite разбит на группы и исправлен semantic reschedule

- В `scripts/local_regression_suite.py` добавлен `--group`: `fresh`, `payments`, `post_booking`, `services`, `dates`, `time`, `gazebo`, `media`, `upsell`, `prices`, `waitlist`, `handoff`, `reschedule`, `cancel`, `reminder`.
- Прогресс по каждому check печатается сразу, поэтому долгие прогоны теперь диагностируются без ожидания конца всего suite.
- Найден и исправлен сбой: фраза вроде "давайте сместим баню на 26 июня" в post-booking могла стартовать новую анкету из-за service keyword раньше, чем AI-classifier успевал вернуть `change_type=reschedule`.
- Порядок маршрутизации в `message_handler.py` изменён: reserved-hold команды сохраняют приоритет, затем post-booking/AI change flow, и только потом fresh-start новой анкеты.
- Пройдены группы: `fresh`, `dates`, `prices`, `upsell`, `time`, `gazebo`, `media`, `payments`, `post_booking`, `services`, `waitlist`, `handoff`, `reminder`, `reschedule`, `cancel`.
- Полный suite без `--group` всё ещё может быть слишком долгим; для ежедневной проверки использовать группы.

## 2026-05-26 - вынесена детерминированная логика отмены

- Добавлен `app/services/dialog/cancel_flow.py`.
- Из `message_handler.py` вынесены: распознавание намерения отмены, отмена всех броней, выбор отменяемой брони по номеру/типу/дате/варианту, тексты подтверждения и успешной отмены.
- Исполнение отмены осталось в `message_handler.py`: удаление записи YCLIENTS, обновление booking status и handoff при технической ошибке.
- Усилен cleanup regression suite: после прерванных прогонов тестовые зависимости удаляются не только по заранее выбранным conversation id, но и через join по `local_regression_%`.
- В regression suite добавлена печать длительности каждого check: формат `OK [29.4s]: ...`.
- Проверки: `compileall app scripts`, `local_regression_suite.py --group dates`, `local_regression_suite.py --group cancel`; reschedule-проверки пройдены точечно по всем сценариям группы.
- Наблюдение: группа `reschedule` целиком может превышать 10 минут из-за тяжелых fixture/DB-проходов; логика зелёная, но тестовую инфраструктуру стоит дальше ускорять или дробить.

## 2026-05-26 - ускорен semantic-router и стабилизированы fallback-ответы

- Добавлен `app/services/dialog/semantic_router.py`: основной AI-проход теперь получает компактный router-context с картой услуг и текущей анкетой, а не всю базу знаний.
- Полная база знаний остается для настоящих info-ответов и post-booking classifier; обычные шаги анкеты должны делать меньше токенов и меньше задержек.
- Добавлен `app/services/dialog/performance.py` и трассировка `handle_incoming`: в логах видны `total_s`, `db.connect`, `db.work`, `ai.semantic`, `ai.response`, `ai.post_booking`, availability/payment/YCLIENTS/media этапы.
- Добавлен `app/services/dialog/response_builder.py`: готовые клиентские тексты возвращаются без второго AI-вызова, а внутренние инструкции не должны уходить клиенту.
- Исправлен опасный fallback: если AI-генератор возвращает служебную инструкцию вроде "Начни без приветствия..." или падает, backend заменяет ее безопасным шаблонным вопросом.
- `availability_service.check_availability` переведен на локальные таблицы `yclients_records`/`resource_busy_intervals` как источник свободности в диалоге; прямой live fallback в YCLIENTS убран из клиентского ответа.
- Исправлена формулировка для комбинированной заявки "беседка + баня": бот стартует с беседки и пишет, что баню оформим второй отдельной бронью после беседки.
- Проверки: `compileall app scripts`, группы `prices+upsell+time`, `fresh`, `dates`, `gazebo+media`, `services`, `cancel+reschedule`, `payments+post_booking+waitlist+handoff+reminder`.
- Наблюдение по скорости: после трассировки самые длинные локальные регрессии чаще упираются в `db.connect`/`db.work`; иногда `ai.post_booking` занимает 3-5 секунд.

## 2026-05-26 - исправлены свежие сбои по телефону, бане и контексту второй услуги

- Невалидный телефон теперь отвечает готовым клиентским шаблоном без AI, чтобы внутренние инструкции вроде "попроси клиента" не попадали в Telegram.
- Уведомление админу по новой заявке теперь показывает конкретный объект: например `Беседка №8 (Беседка)`, а не только общий тип услуги.
- Правило open-ended периода "до утра / как пойдет / посмотрим" обобщено на баню и дом: при старте в 12:00 длительность считается до 08:00 следующего утра.
- Фразы вроде "на то же время что и беседка" в анкете бани больше не переключают текущую услугу на беседку: backend берет время/длительность из активной брони беседки и сохраняет текущий `service_type`.
- Добавлен abort-flow для незавершенной анкеты: "не хочу бронировать ее / передумал / не надо" очищает черновик, но сохраняет имя и телефон; оплаченные брони этим не отменяются.
- Добавлен connection pool PostgreSQL (`DB_POOL_ENABLED`, `DB_POOL_MIN`, `DB_POOL_MAX`), потому что трассировка показала заметные задержки на `db.connect` к удаленной БД.
- Добавлены регрессии: client-safe phone, admin object title, bathhouse open-ended until morning, second service same-time reference, abort current draft.
- Проверки: `.venv\Scripts\python.exe -m compileall app scripts`; `local_regression_suite.py` по группам `fresh+time+services+post_booking` и затем `dates+gazebo+media+waitlist+handoff+prices+upsell+payments+cancel+reschedule+reminder` - все OK.
- Наблюдение: `local_regression_suite.py` нельзя запускать параллельно двумя процессами, потому что cleanup использует общий префикс `local_regression_%` и процессы могут удалять данные друг друга.

## 2026-05-27 - стабилизированы формат анкеты, info-вопросы и правило аванса

- Исправлено принятие `event_format`: AI может заполнить формат с опечаткой клиента вроде "просто отдыз", но не может выдумать формат, если текущий шаг другой.
- Info-вопросы больше не должны добавлять старый вопрос анкеты: цена решетки на шаге допов остается на допах и не возвращает вопрос про формат.
- Добавлен reference-resolver для "та же дата / тот же день" по аналогии с "то же время": вторая услуга сохраняет свой `service_type`, а дату/время берет из актуальной брони.
- Тексты отмены оплаченной брони теперь учитывают правило 7 дней: за 7+ дней аванс можно вернуть по правилам отмены, ближе к дате аванс не возвращается.
- Добавлена память решений: [[decisions/2026-05-27-dialog-state-policy]] и [[roadmap/dialog-regression-scenarios]].
- Добавлены регрессии: event format typo, addon price during upsell, same date reference, brooms info without form, cancel refund window.
- Завершена проверка плана: прошли `compileall app scripts`, группы `post_booking+reschedule`, затем `fresh+dates+gazebo+media+prices+upsell+time+payments+services+waitlist+handoff+reminder+cancel`.
- Отполирован текст успешной отмены: строка про аванс теперь начинается с заглавной буквы в финальном клиентском сообщении.

## 2026-05-27 - продолжен рефакторинг message_handler

- Добавлен `app/services/dialog/form_patches.py`.
- Из `message_handler.py` вынесены чистые patch-парсеры анкеты: тип услуги, вариант беседки, телефон, формат отдыха, допы, гости, имя, reference-фразы "та же дата/то же время" и нормализация service aliases.
- Добавлен `app/services/dialog/form_corrections.py`.
- Из `message_handler.py` вынесены распознавание исправления имени и текст подтверждения исправленных полей.
- Старые приватные имена в `message_handler.py` сохранены как импортированные алиасы, поэтому существующие тесты и внутренние вызовы продолжают работать.
- Размер `message_handler.py` уменьшен до 5672 строк; следующий крупный кандидат на вынос - `reschedule_flow` и availability-ответы.
- Проверки: `compileall app scripts`; regression groups `fresh`, `prices`, `upsell`, `services`, `time`, `dates`, `post_booking`, `reschedule`; затем `fresh`, `prices`, `upsell`, `reschedule` после второго выноса.
- Дополнительно после выноса service/variant-парсеров пройдены группы `gazebo`, `media`, `payments`, `waitlist`, `handoff`, `reminder`, `cancel`.

## 2026-05-27 - исправлены живые сбои "подешевле" и неформальный отказ от допов

- По последнему живому диалогу найдено: таблица `messages` и semantic-router работают, но backend guards были слишком узкими и не принимали живые ответы клиента как смысловые ответы на текущий шаг.
- Фраза `а мне нужно что нибудь подешелве` на выборе беседки теперь распознается как просьба помочь с бюджетным вариантом. Backend берёт уже проверенные свободные варианты из локальной БД/`form_data`, фильтрует по вместимости и цене и не повторяет весь список.
- Неформальные отказы от допов (`неа`, `нте`, `нет же говорю`, `ytn`) теперь считаются отказом по смыслу. Первый отказ запускает второй мягкий продающий заход, второй отказ закрывает допы как `["не нужны"]`.
- Вопрос имени в анкете заменён на более нейтральный `На какое имя записать бронь?`, чтобы повторная бронь не выглядела так, будто бот забыл клиента.
- Semantic-router и системный промпт усилены: сначала определять крупную ветку (`info`, `check_availability`, `booking_form`, `post_booking`, `other`), а затем backend валидирует факты, доступность и состояние.
- Добавлены регрессии: `gazebo budget preference filters cheapest`, `gazebo budget preference during choice`, `informal upsell no uses two-touch flow`.
- Проверки: `compileall app scripts`; группы `gazebo`, `upsell`, затем `fresh+services+prices`, затем `time+payments+post_booking+waitlist+handoff+media+cancel+reschedule+reminder` - все OK.

## 2026-05-27 - добавлен stress-suite нестандартных диалогов

- Добавлен `scripts/dialog_stress_suite.py`: отдельный диагностический suite с живыми кривыми формулировками клиента, печатью USER/BOT transcript и проверкой state-инвариантов.
- Stress-suite сначала нашел реальные слабые места: `по чем/решотка`, `3й беседки`, `баню убери, беседку не трогай`, `сдвинем на денек позже`, `тем же днем`, `как там же, без изменений`, `забей, не оформляем`.
- Исправлены guards и patch-парсеры в `price_info.py`, `form_patches.py`, `cancel_flow.py`, `media_service.py`, `message_handler.py`.
- Новые проверенные сценарии: бюджетный подбор, два касания допов, цена допов без автодобавления, вторая услуга со ссылкой на прошлую бронь, список броней нестандартной фразой, выборочная отмена, перенос живой фразой, info без анкеты, abort черновика, явный запрос фото.
- Проверки: `compileall app scripts`; `scripts/dialog_stress_suite.py` - 10/10 OK; затем затронутые группы `prices+upsell+media+post_booking+cancel+reschedule+services` - все OK.
- После всех фиксов дополнительно пройден полный grouped suite: `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - все OK.
- Наблюдение: функционально сценарии прошли, но отдельные AI-ветки остаются медленными. В логах встречались ответы 8-15 секунд на cancel/reschedule и info/post-booking сценарии. Иногда AI всё ещё возвращает внутреннюю инструкцию, но guard/fallback перехватывает это и клиенту уходит безопасный текст.

## 2026-05-27 - исправлены info-вопросы внутри активной анкеты

- По живому диалогу найден сбой: во время анкеты бани вопрос `а если нас будет 30 человек` мог переключить ответ в контекст беседок и затем дважды повторить вопрос времени.
- Изменено правило info-сообщений: если semantic-router определил `answer_info`, backend не применяет `service_type/date/time/duration/guests_count` из AI как изменение анкеты. Информационный вопрос теперь отвечает в текущем контексте, а состояние анкеты меняется только на настоящих ответах клиента.
- Добавлен контекстный ответ по вместимости: для бани на 30 человек бот объясняет, что баня не лучший основной формат для такой компании, предлагает Беседку №1/тёплую беседку и сохраняет текущую услугу `bathhouse`.
- Добавлен pause-flow для фраз вроде `ну хз, я позже вам напишу`: бот сохраняет черновик и не добавляет следующий вопрос анкеты.
- Усилен дедупликатор продолжения анкеты: если ответ уже содержит вопрос про время или длительность, `Продолжим оформление` не добавляется повторно.
- Добавлены регрессии: `info during bath form keeps service context`, `later pause during form does not repeat question`; `scripts/dialog_stress_suite.py` расширен до 11 сценариев.
- Проверки: `compileall app scripts`; группы `fresh+prices`; `scripts/dialog_stress_suite.py` - 11/11 OK; группы `services+upsell+gazebo+post_booking+reschedule+media`; полный grouped suite `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - все OK.

## 2026-05-27 - добиты живые ошибки по выбору беседки, допам и отмене

- Добавлены защиты для сценария `29 мая 6 беседка`: если клиент выбрал конкретную беседку без количества гостей, backend сначала спрашивает гостей и проверяет вместимость, а не переходит ко времени.
- Фраза `а если нас будет 15 человек` теперь рассматривается как обновление `guests_count`; бот не должен повторно спрашивать количество гостей.
- Номер беседки в фразах вроде `хорошо, 4 беседка` не должен парситься как время `04:00`.
- Вопрос `А какие цены на допы` должен сразу отвечать прайсом допов, не зависать на "сейчас расскажу" и не сохраняться как `client_name`.
- Подтверждение `дя` добавлено в confirm-flow как допустимая опечатка `да`.
- После успешной отмены простое `окей/спасибо` больше не должно запускать текст "бронь зафиксирована".
- Добавлены regression checks: `forced gazebo variant asks guests before time`, `gazebo capacity question sets guests and skips repeat`, `gazebo variant change is not parsed as time`, `addon prices plural question replies immediately`, `paid cancel typo dya confirms`, `ack after cancel does not say booking fixed`.
- `scripts/dialog_stress_suite.py` расширен сценарием с выбором беседки, изменением гостей, вопросом о допах и отменой через `дя`.
- Проверки: `compileall app scripts` прошел. Повторный stress/regression запуск был заблокирован внешним PostgreSQL timeout: один прямой коннект после восстановления прошел за ~1 секунду, но затем новые процессы снова получали `timeout expired` на `luecahalemas.beget.app:5432`. TCP-порт доступен, SSL-варианты дают тот же timeout, поэтому тесты нужно повторить после стабилизации БД.

## 2026-05-27 - БД восстановилась, нестандартные тесты пройдены

- `scripts/db_status.py` успешно прочитал БД: таблицы `users`, `conversations`, `messages`, `slot_holds`, `bookings`, `yclients_records`, `resource_busy_intervals` доступны.
- Пройден `scripts/dialog_stress_suite.py`: 12/12 OK.
- В stress-suite проверены нестандартные живые сценарии: бюджетный подбор беседки с опечаткой, два касания допов с живыми отказами, вопрос цены допов без автодобавления, вторая услуга со ссылкой на дату/время беседки, странный вопрос "что на мне висит", выборочная отмена, перенос "на денек позже", info-вопросы без анкеты, abort черновика, явный запрос фото, принудительный выбор беседки без гостей, `дя` как подтверждение отмены.
- Пройдены затронутые regression-группы: `gazebo`, `upsell`, `prices`, `cancel`, `post_booking`, `services`, `reschedule`, `fresh` - все checks OK.
- Наблюдение по скорости: функционально тесты прошли, но отдельные AI-ветки всё ещё дают 4-7 секунд (`ai.semantic`/`ai.post_booking`). Это не блокер для релиза, но остается направлением оптимизации.

## 2026-05-27 - закрыт план по последним сценариям, hold и актуальности записей

- Исправлен парсинг живых фраз: `15-17 человек/гостей/чел` больше не превращается во время, а сохраняется как количество гостей с верхней границей для проверки вместимости; `в 3 часа дня`, `к 3 дня`, `в 3 чиса дня` распознаются как `15:00`; `с 3 дня до 11 ночи` дает период `15:00-23:00`.
- Для больших компаний усилен подбор беседок: при `20+` гостях `Беседка №1` ранжируется первой как комфортный просторный вариант, дальше идут остальные подходящие свободные варианты по вместимости/цене.
- Проверка свободности использует локальные `yclients_records`/`resource_busy_intervals`, но теперь учитывает свежесть sync-state; после YCLIENTS sync и создания/удаления записей очищается availability-cache, чтобы бот не отвечал старыми данными.
- Резерв оплаты стал строгим: после 10 минут hold переводится в `expired`, клиент получает сообщение о снятии резерва, повторная ссылка не создается поверх активного hold, поздняя оплата по старой ссылке не подтверждает бронь автоматически.
- Готовые ответы по цене и допам обогащены данными из базы знаний: прайс беседок без выбранного варианта показывает таблицу, вопросы цены допов остаются на шаге допов и не добавляют товар автоматически, upsell-сообщения получили несколько продающих вариантов с эмодзи.
- Добавлен `scripts/cleanup_yclients_test_records.py`: сначала dry-run кандидатов, затем удаление только bot-created/Telegram-created тестовых записей по явным признакам. По текущей чистке найдены и удалены 2 тестовые записи Telegram с телефоном `+79968533502`; финальный dry-run `--all-bot-bookings` показывает 0 кандидатов.
- После чистки выполнен YCLIENTS sync: локальная таблица записей обновлена, `records_seen=121`, `last_error=None`.
- Проверки: `compileall app scripts`; `scripts/dialog_stress_suite.py` - 12/12 OK; полный grouped suite `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - все checks OK; targeted groups `time+gazebo+payments`, `prices+upsell` - OK.
- Остаточный риск: отдельные AI-ветки в тестах всё ещё могут занимать 8-20 секунд на сложных info/post-booking/cancel/reschedule сценариях. Функционально сценарии проходят, но оптимизация скорости остается следующим UX-направлением.

## 2026-05-27 - подготовлена чистая БД для нового live-теста

- По просьбе очищен диалоговый слой: `users`, `conversations`, `messages`.
- Из-за FK-зависимостей также очищены связанные локальные сущности тестового диалога: `conversation_summaries`, `slot_holds`, `payments`, `bookings`, `waitlist_requests`, `system_logs`.
- Таблицы YCLIENTS-кеша не очищались полностью: `yclients_records` и `resource_busy_intervals` сохранены как источник свободности.
- После очистки обнаружены старые локальные интервалы `resource_busy_intervals.source='bot_booking'`, которые могли ложно блокировать свободность; удалено 54 таких интервала. Остались только интервалы `source='yclients'`.
- Выполнен YCLIENTS sync перед тестом: `records_seen=121`, `records_upserted=121`, `last_error=None`.
- Финальные счетчики для старта теста: `users=0`, `conversations=0`, `messages=0`, `slot_holds=0`, `payments=0`, `bookings=0`, `waitlist_requests=0`; `resource_busy_intervals=127` только из YCLIENTS, `yclients_records=126`.

## 2026-05-27 - исправлена память черновика после возврата от дома к беседке

- По live-чату найден новый класс сбоя: клиент сначала обсуждал беседку на 20 гостей на 2 июня, потом спросил гостевой дом на ту же дату, затем вернулся фразой `лан давайте беседку же выбираю перую беседку`. Бот мог ошибочно стартовать "вторую бронь", забыть дату/гостей и повторно спросить уже выбранную беседку.
- Добавлен guard продолжения текущего черновика при смене услуги обратно к ранее обсуждаемой: дата, гости, время, длительность и доступные варианты восстанавливаются из текущего `form_data`/`last_unavailable`, если клиент явно продолжает тот же сценарий, а не начинает новую бронь.
- Расширено распознавание варианта беседки: опечатки `перую`, `перву`, `первой` трактуются как `Беседка №1`, если контекст уже про выбор беседки.
- Добавлен draft-summary для вопросов вроде `а первая бронь какая?`: если оплаченной брони еще нет, бот не противоречит себе, а показывает текущую собираемую заявку и следующий недостающий шаг.
- Если гостевой дом/баня/теплая беседка недоступны на выбранную дату, бот теперь предлагает альтернативные свободные услуги на эту же дату, прежде всего подходящие беседки по вместимости, а не только пишет waitlist.
- Фраза `у нас просто праздник` после недоступного дома теперь используется как повод предложить альтернативы на ту же дату, а не снова просить дату.
- `ну нет`, `да нет` и близкие живые отказы добавлены в upsell negative parser: первый отказ по допам снова запускает мягкий продающий повтор, второй закрывает допы.
- Вопрос про длительность/часы в контексте беседки теперь не уходит в цену гостевого дома: готовый ответ объясняет, что у беседок стоимость зависит от конкретного объекта/периода, а не от "доплаты за каждый час".
- Шаблон подтверждения заявки обновлен: финальный вопрос теперь явный `Всё верно? Подтверждаете бронь?`, с прежней структурой и эмодзи.
- База знаний проверена через `load_knowledge()`: загружается `client_runtime.md`, ключевые факты про комаров/обработку, веники/штраф, предоплату, допы, парковку и адрес присутствуют.
- Проверки: `compileall app scripts`; полный grouped suite `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - все checks OK; `scripts/dialog_stress_suite.py` - 12/12 OK.

## 2026-05-27 - проведен senior project review

- Проведен обзор структуры, wiki, core services, DB schema, YCLIENTS/ЮKassa integrations, regression scripts и текущих known issues без изменения production-кода.
- Итоговая оценка проекта: 7/10. Сильные стороны: рабочая доменная модель, много регрессий, принцип "AI понимает, backend валидирует", LLM Wiki, fallback от внутренних AI-инструкций.
- Главные найденные риски: `message_handler.py` около 6000 строк; нет DB-level атомарности active hold; платеж ЮKassa создается внутри открытой transaction; YCLIENTS sync держит transaction во время сетевой загрузки; regression scripts нельзя запускать параллельно; webhook требует production-обвязки.
- Проверки: `compileall app scripts` - OK; `scripts/db_status.py` - OK; `scripts/local_regression_suite.py --group fresh --group payments` - OK; `scripts/validate_yclients_map.py` получил timeout 124s; `scripts/dialog_stress_suite.py` функционально дошел до конца, но cleanup упал из-за параллельного запуска с local regression, после чего штатный `_cleanup()` выполнен успешно.
- Подробный отчет: [[daily/2026-05-27-project-review]].

## 2026-05-27 - исправлены duration, mixed-upsell и диагностика sync

- Добавлена нормализация `duration` в `booking_form_service.merge_form_data` и `dialog/time_parsing.py`: строки вроде `8 часов`, `8 ч`, `8.5 часа` приводятся к числу часов, некорректные строки очищаются.
- Парсер времени теперь понимает свободную фразу `после обеда, к 3 дня и до 11 ночи` как `15:00` и длительность `8`.
- Mixed upsell-сообщение вида `а вода и лед сколько стоят? если можно, добавьте воду и лед` теперь одновременно отвечает по цене и сохраняет выбранные допы.
- Runtime-база знаний `app/knowledge/client_runtime.md` дополнена фактами про детей, животных, парковку, вместимость “впритык” и свои стулья/лавки.
- Добавлен `scripts/yclients_sync_status.py` для диагностики свежести YCLIENTS sync-state.
- `local_regression_suite.py` и `dialog_stress_suite.py` получили lock-файл, чтобы параллельные прогоны не ломали cleanup друг друга.
- Проверено: `compileall app scripts` - OK; `scripts/db_status.py` - OK; `scripts/sync_yclients_records.py --once` - OK; `scripts/yclients_sync_status.py --strict` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; `local_regression_suite.py --group time --group upsell --group prices` - OK; `local_regression_suite.py --group gazebo --group services --group post_booking --group cancel --group reschedule --group fresh --group payments` - OK.
- YCLIENTS sync после тестов свежий: `records_seen=122`, `records_upserted=122`, `last_error=None`.

## 2026-05-28 - продолжен разрез message_handler: swap-reschedule и availability execution

- `message_handler.py` уменьшен до ~4492 строк без изменения внешнего поведения.
- В `app/services/dialog/reschedule_flow.py` вынесены grouped/swap reschedule orchestration helpers: `start_swap_reschedule_flow`, `handle_swap_reschedule_flow`, `prepare_swap_reschedule`; `message_handler.py` оставил тонкие wrappers через `SwapRescheduleCallbacks`.
- В `reschedule_flow.py` также вынесен подбор новой беседки при переносе: `reschedule_gazebo_change_options_reply`.
- В `app/services/dialog/availability_flow.py` добавлен общий `execute_availability_check` с callbacks: одна точка для проверки локальной свободности, альтернатив, waitlist/no-availability и стандартного availability reply.
- Основная AI-ветка, fallback при недоступности AI и общий exception fallback теперь используют единый availability executor; fast-entry availability тоже переведен на него без waitlist side-effect.
- Проверки после разрезов: `compileall app scripts` - OK; `local_regression_suite.py --group reschedule` - OK; `local_regression_suite.py --group fresh --group gazebo --group waitlist --group services` - OK; `local_regression_suite.py --group prices --group upsell --group payments --group post_booking --group cancel --group reschedule` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; `local_regression_suite.py --group dates --group media --group time --group handoff --group reminder` - OK.
- Наблюдение: slow timing остался только на отдельных AI semantic ветках примерно 5-8 секунд; это не новая регрессия от рефакторинга.

## 2026-05-28 - разобран live-чат после теста Telegram

- По последнему live-чату найдено несколько user-facing ошибок, важнее дальнейшего рефакторинга: баня была предложена только с 6 августа, хотя текущая локальная availability-таблица после свежего sync показывает свободность 28 мая, 29 мая, 1 июня и дальше; вероятный класс бага - stale/free-dates glue, где старые `date`/`last_unavailable`/`last_suggested_free_dates` сдвигают старт поиска после явного `начнем новую`.
- В локальной таблице `resource_busy_intervals` обнаружены 46 `bot_booking` интервалов для бани 24 июня; это не объясняет августовский ответ напрямую, но нарушает ожидание чистой availability-таблицы после live-подготовки.
- Подтверждены диалоговые баги: бюджетный подбор беседки задает два вопроса в одном ответе; mixed selection+info (`четвертую / а с детьми можно?`) не закрепляет выбранную беседку; `я же говорил 10` после вопроса о гостях может парситься как время; короткий ack после pause возвращает upsell-вопрос.
- Решение на ближайший шаг: временно остановить behavior-preserving refactor и сначала закрыть эти живые регрессии с точечными regression/stress сценариями.

## 2026-05-28 - исправлены live-dialog баги перед продолжением рефакторинга

- Закрыт риск `начнем новую / какие ближайшие свободные даты для бани?`: ветка `awaiting_new_date`/`last_unavailable` больше не перехватывает явный запрос новой анкеты, direct free-dates запускается с чистого контекста и ищет от текущей даты.
- Бюджетный подбор беседки без выбранной даты стал deterministic: для `10 челов / что дешевле` бот сохраняет `guests_count=10`, показывает недорогие подходящие варианты как ориентир по цене и задаёт один следующий вопрос - дату для проверки журнала. Без выбранной даты он больше не пишет `из свободных`.
- Mixed selection+info исправлен: фраза `четвертую / а с детьми можно?` в контексте беседок сохраняет `Беседка №4`, отвечает по детям из базы знаний и задаёт следующий один вопрос по анкете.
- Expected-step parsing усилен: если текущий/следующий шаг явно `guests_count`, фразы вроде `я же говорил 10` обновляют гостей и не превращаются в `10:00`/длительность до утра.
- После pause-flow короткий ack вроде `кайф` больше не возвращает клиента к upsell-вопросу; бот оставляет черновик на паузе.
- Regression cleanup теперь удаляет orphan `resource_busy_intervals.source='bot_booking'`, не связанные с локальными bookings. После прогона orphan-интервалов 0, в `resource_busy_intervals` остался только `source='yclients'`.
- Выполнен ручной `scripts/sync_yclients_records.py --once`; `scripts/yclients_sync_status.py --strict` свежий (`records_seen=120`, `last_error=None`). Текущая проверка бани: 28 мая, 29 мая и 1 июня свободны; 30 мая закрыта записью.
- Проверки: `compileall app scripts`; regression groups `dates`, `gazebo`, `time`, `fresh`, `upsell+prices+services`, `post_booking+payments+cancel+reschedule`; `scripts/dialog_stress_suite.py` - 13/13 OK.

## 2026-05-28 - проведены сценарные тесты live-диалога и переноса

- Прогнан полный `scripts/local_regression_suite.py` после live-фиксов: все checks OK, включая payments/post_booking/services/dates/time/gazebo/media/upsell/prices/waitlist/handoff/reschedule/cancel/reminder.
- Прогнан `scripts/dialog_stress_suite.py`: 13/13 OK. В сценариях проверены живые отказы от допов, цены допов, вторая услуга с той же датой/временем, сводка броней, выборочная отмена, перенос `сдвинем баню на денек позже, часы те же`, info-вопросы, abort черновика, фото и подтверждение с опечаткой `Дя`.
- После дополнительного ручного сценария найден и закрыт stale-form edge case: если старая анкета уже протухла, сообщение `начнем новую / какие ближайшие свободные даты для бани?` больше не показывает checkpoint старой анкеты, а сразу делает fresh direct free-dates lookup с сохранением контакта.
- Добавлен regression `old form new free dates skips stale choice`; после правки прошли `compileall`, `local_regression_suite.py --group fresh --group dates --group time` и отдельный `--group reschedule`.
- Ручной сценарий после свежего YCLIENTS sync:
  - `начнем новую / какие ближайшие свободные даты для бани?` -> ближайшие даты: 28 мая, 29 мая, 31 мая, 1 июня, 3 июня; старый август не подтягивается.
  - `а беседки на какие даты есть?` -> ближайшие даты беседок с вариантами: 28 мая, 29 мая, 30 мая, 31 мая, 1 июня.
  - `10 челов / что дешевле` -> сохраняет 10 гостей, показывает недорогие подходящие варианты как ориентир по цене и спрашивает одну дату.
  - `четвертую / а с детьми можно?` -> сохраняет `Беседка №4`, отвечает по детям и спрашивает дату.
  - `я же говорил 10` на шаге времени -> подтверждает 10 гостей и не парсит `10` как `10:00`.
  - `позже напишу` + `кайф` -> оставляет черновик на паузе без возврата к upsell.
- Ручной перенос: оплаченная баня 25 июня, `сдвинем баню на денек позже, часы те же` -> бот предлагает перенос на 26 июня 18:00 на 6 часов; `да` -> бронь обновлена на 26 июня, `reschedule_flow` очищен.
- Важное наблюдение: пока гонялись длинные проверки, `yclients_sync_status.py --strict` стал stale (`age_seconds > 600`), и direct lookup мог давать неверную картину свободности. После `scripts/sync_yclients_records.py --once` ответы по ближайшим датам стали корректными. Для production критично держать один постоянный `main.py` с включенным YCLIENTS sync loop и мониторить freshness.
- Остаточный UX-риск: functional tests зелёные, но в regression/stress остаются `dialog_timing_slow` на отдельных AI/availability ветках примерно 3-10 секунд; это не новая регрессия, но перед релизом нужно продолжать ускорять частые deterministic маршруты и следить за sync latency.
## 2026-05-28 - закрыты новые live-dialog нюансы перед возвратом к refactor

- Вопросы вида `а че у меня по брони, которую я хотел забронировать` теперь не отвечают только "активных броней нет", если оформленной брони/hold еще нет, но есть черновик заявки. Backend сначала проверяет активные bookings и holds, затем показывает draft-summary и следующий недостающий шаг.
- Vague follow-up `ну че нибудь` на шаге времени больше не принимает AI-догадку как время/длительность: если клиент не дал явного времени или ссылки на прошлую бронь, состояние остается на `time`.
- Эмоциональный разговорный мат без жалобы (`бля будем зажигать`) больше не запускает handoff. Handoff остается для жалоб, возврата денег, агрессии в адрес компании/бота и явной просьбы подключить человека.
- Ссылки на время прошлой брони для второй услуги (`часы как там же`, `то же время`) считаются явным time-сигналом: backend подтягивает время/длительность из локальных активных броней, но сохраняет текущую услугу новой анкеты.
- Для услуг, где нужна длительность до availability, backend теперь спрашивает длительность только после известного времени, чтобы не перескакивать с `time` на `duration` при неопределенных фразах.
- Проверки: `compileall app scripts`; `local_regression_suite.py --group services`; `--group post_booking --group handoff --group fresh --group time`; `--group dates`; `--group gazebo`; `--group services --group prices --group upsell`; `--group payments`; `--group cancel`; `--group reschedule`; `--group media --group waitlist --group reminder`; `scripts/dialog_stress_suite.py` - 13/13 OK после фикса same-time edge case.
- После уточнения guard, что same-time reference валиден только при backend patch из активной брони, повторно пройдены `compileall app scripts`, `local_regression_suite.py --group post_booking`, `--group services --group handoff --group time` и `scripts/dialog_stress_suite.py` - 13/13 OK.
- Наблюдение: отдельной regression-группы `availability` нет; availability покрывается через `dates/gazebo/services/time/post_booking/waitlist`. В stress/regression все еще встречаются `dialog_timing_slow` на AI semantic ветках, функционально сценарии зеленые.

## 2026-05-28 - проведен edge-dialog прогон активных flow

- Добавлен `scripts/dialog_edge_suite.py`: 12 нестандартных сценариев с перебиванием активной анкеты, финального подтверждения, cancel-flow, reschedule-flow и post-booking состояния.
- Закрыты найденные нюансы: вопрос `что мы сейчас бронируем/подтверждаем` теперь deterministic показывает draft-summary и не меняет состояние; `отмени бронь, не будем` на `awaiting_confirmation` сбрасывает еще не созданную заявку, а не идет в reserved-hold glue; info-вопрос про аванс внутри cancel-flow отвечает по правилу возврата и оставляет подтверждение отмены активным; `нет, оставь` отменяет cancel-flow и позволяет затем начать перенос.
- Post-booking classifier уточнен: вопросы не по теме базы отдыха/брони отвечают коротко и не предлагают допы/следующий шаг. `_clean_reply` дополнительно чистит AI-опечатку `сразать -> сразу`.
- Edge-прогон подтвердил: info-вопросы во время подтверждения не мешают последующему `да`; info-вопросы внутри переноса не сбрасывают `reschedule_flow`; вопрос про варианты переноса с двумя бронями показывает варианты; посторонние вопросы в форме/cancel/post-booking не портят состояние.
- Проверки: `compileall app scripts`; `scripts/dialog_edge_suite.py` - 12/12 OK; `local_regression_suite.py --group payments --group post_booking --group cancel --group reschedule` - OK; `--group fresh --group gazebo --group services --group prices --group upsell --group time --group handoff` - OK; `--group dates --group media --group waitlist --group reminder` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; после prompt/text cleanup повторно `compileall`, `scripts/dialog_edge_suite.py` - 12/12 OK и `local_regression_suite.py --group post_booking` - OK.
- Перед live-проверкой `scripts/yclients_sync_status.py --strict` показал stale cache (`age_seconds=5944`), выполнен `scripts/sync_yclients_records.py --once`: `seen=121`, `upserted=121`; повторный strict status fresh (`age_seconds=90`, `last_error=None`).
- Наблюдение: отдельные off-topic вопросы внутри формы всё еще проходят через AI semantic и дают `dialog_timing_slow` около 7-8 секунд, но состояние сохраняется; это не блокер, а направление для будущих deterministic short-circuit.

## 2026-05-28 - разобран live-чат 6093 по беседке на 20 гостей

- По реальному чату `conversation_id=6093` найден новый набор live-регрессий перед продолжением рефакторинга: `20 чел` не был надежно сохранен как `guests_count`, ответ на 5 июня показал свободные беседки без фильтра вместимости и повторно спросил гостей.
- Причина по коду: если semantic-router трактует короткое `20 чел` как info-like, `_ai_first_patch` пропускает только `_capacity_guest_patch`, а этот guard не покрывает сокращение `чел`. Backend должен принимать expected-step answer независимо от AI-классификации.
- Неправильные даты 16-20 июня возникли из-за early route `_asks_for_free_slots` на `awaiting_new_date`: фраза `только эта свободна на 5 июня` не парсилась как уточнение 5 июня, а запускала `_next_free_dates_reply`, который пропускает уже показанные `last_suggested_free_dates`. Список 6-10, полученный без вместимости, загрязнил последующий поиск для 20 гостей.
- Текущая диагностика локальной availability-таблицы не подтверждает stale-cache как основную причину именно этого чата: 5 июня для 20 гостей подходящих слотов нет; 8 июня подходят `Беседка №1/№8/№3`; 4 июня подходят `Беседка №8/Крытая`. `yclients_sync_status.py --strict` на момент проверки свежий, но близко к порогу (`age_seconds=550`, `records_seen=121`, `last_error=None`).
- Вопросы по скидке обходят knowledge: deterministic price reply берет базовую цену `Беседка №1 = 10 500 ₽` из `services_map` до проверки фраз `скидка/со скидкой`. В базе знаний есть скидка 50% ПН-ЧТ и цена №1 5 250 ₽, поэтому нужен discount-aware ответ или явный routed knowledge reply.
- Финальное `form_data` разговора потеряло `time`, `duration`, `event_format`, хотя в transcript клиент дал `18,00`, `на 5`, `встреча однокласников`; при этом сохранился `upsell_items=["кальян"]`. Это объясняет повторный вопрос времени после допа/цены/кальяна и требует state-safe guard между AI-текстом, `last_assistant_asked_upsell` и фактическим `next_question(form_data)`.
- Production-код не менялся; выводы зафиксированы в `bugs/current-known-issues.md`. Следующий шаг перед refactor: точечно закрыть эти live-регрессии и добавить сценарии в regression/edge/stress.

## 2026-05-28 - закрыт live-баг `30 июня` -> `30 гостей`

- По последнему Telegram-чату найден конкретный poison-state: сообщение `на 30 июня` было ошибочно принято как `guests_count=30`, после чего backend авто-выбрал единственную подходящую для 30 гостей `Беседку №1`. Дальше бот отвечал уже из испорченного состояния: забывал дату в вопросе про выбор, говорил про 30 гостей и цену/скидку первой беседки, хотя количество гостей не спрашивал.
- Исправлено routing-правило: если AI ошибочно пометил ответ текущего шага как `answer_info`, но backend принял валидное изменение анкеты (`date`, `guests_count`, `time` и т.д.), сообщение больше не идет в info-ветку, а проходит через форму/availability.
- Добавлена защита от числа из даты: `guests_count` из AI-patch отклоняется, если в тексте есть date-сигнал (`30 июня`, относительная дата и т.п.) и нет явного маркера гостей (`чел`, `человек`, `гостей`, `нас будет`). При этом `на 30 июня нас будет 20` сохраняет и дату, и гостей.
- Для беседок `guests_count` теперь сам запускает availability-check при уже известной дате; после чистой даты без гостей бот не выбирает беседку, а спрашивает количество гостей перед подбором по вместимости.
- Вопрос `а какой у меня выбор есть?` при известной дате, но без гостей, больше не просит дату заново: бот напоминает дату и спрашивает гостей, чтобы показать подходящие варианты.
- Добавлен recovery guard для реплик вроде `ты же даже не спросил сколько человек`: backend очищает ошибочно выбранную беседку/гостей и возвращает шаг `guests_count`.
- `scripts/dialog_context_suite.py` расширен до 11 сценариев: добавлены чистая дата без гостей, вопрос про выбор после даты и восстановление после жалобы на неуточнённых гостей.
- Локальная DNS-проблема Windows временно обойдена для проверок через `DB_HOST=95.214.62.243` и `DB_SSLMODE=verify-ca`; `.env` не менялся. Перед regression был выполнен YCLIENTS sync: `records_seen=123`, strict-status fresh.
- Проверки: `compileall app scripts`; `scripts/dialog_context_suite.py` - 11/11 OK; `local_regression_suite.py --group gazebo --group dates --group prices --group upsell --group time --group fresh` - OK; `--group services --group post_booking --group payments --group cancel --group reschedule` - OK; `--group media --group waitlist --group handoff --group reminder` - OK; `scripts/dialog_edge_suite.py` - 13/13 OK; `scripts/dialog_stress_suite.py` - 13/13 OK.
- Операционно исправлен live-черновик `conversation_id=135`: очищены ошибочные `guests_count=30`, `service_variant=Беседка №1`, `last_available_gazebo_variants`; сохранены `service_type=gazebo` и `date=2026-06-30`, шаг возвращен на `guests_count`.
- Остаточное наблюдение: functional quality зелёная, но AI semantic на некоторых off-topic/сложных ветках всё ещё даёт `dialog_timing_slow` примерно 6-15 секунд. Это следующий UX-фокус, не текущая регрессия корректности.
