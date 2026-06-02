# Current Known Issues

## 2026-06-02 live knowledge/time/reserve/payment package

- Status: closed by the 2026-06-02 completion pass.
- Symptoms: price/knowledge answers did not consistently state bathhouse pricing after 7 hours or the exact coal price; `4 или 5 вечера` could be read as `04:00-05:00`; `до 12 ночи` during correction could overwrite the start time instead of changing duration; unpaid reserved date/time edits could leave the old hold/payment link active; reserve/payment copy still mentioned 10 minutes while the desired policy was 30 minutes with link refreshes at 10/20 minutes.
- Fix: bathhouse extra-hour pricing and coal price were updated in deterministic price helper and knowledge files; time parsers gained PM-choice and until-midnight guards; unpaid hold correction now cancels the old hold, supersedes old pending payments, creates a fresh hold/payment; TTL text is settings-driven at 30 minutes; payment runner can resend fresh links and superseded late payments no longer auto-finalize old bookings.
- Covered by: `payment reply uses 30 minute ttl and refund note`, `unpaid reserved date correction recreates hold and link`, `bathhouse ten hour price formula`, `coal price is known`, `people range is not parsed as time`, `evening time choice uses early option`, `until midnight uses existing start`, plus context/edge/stress suites.

## 2026-06-02 Phase 2 stale reset lost current-message service (fixed)

- Status: closed by Phase 2 refactor follow-up.
- Symptom: during the new `new_booking_flow.py` extraction, the scenario `нет` + new bathhouse request in one stale-choice message could clear the old draft but lose the service from the current message, then answer with the generic services list instead of continuing the bathhouse form.
- Cause: the context-only stale reset path used `new_booking_form_data(previous)` and persisted/continued with an empty service. In the monolithic handler, later routing could still recover from the raw message; after extraction, the deterministic services-list branch intercepted first.
- Fix: context-only stale reset now uses the existing fresh form builder for the current text, preserving service/contact while still clearing stale slot fields. Covered by `local_regression_suite.py --group fresh`, especially `stale no plus new bath request processes same message`.

## 2026-06-02 PostgreSQL timeout verification blocker status

- Status: not reproduced during Phase 2 verification. `scripts/test_db.py`, context/edge/stress suites and grouped `fresh/services/post_booking/payments` regression were green on 2026-06-02 after the Phase 2 slice.
- Keep the previous timeout note below for history: if PostgreSQL timeouts return, treat them as an external verification blocker and do not start the next refactor phase until a DB-dependent regression baseline is green again.

## 2026-06-02 PostgreSQL timeout blocks Phase 1 regression verification

- Статус: открыто как verification blocker, production-код не менялся для этого пункта.
- Симптом: после Phase 1 refactor `scripts/dialog_context_suite.py` и `scripts/test_db.py` не доходят до сценариев/DB smoke. Pool init делает 3 попытки, затем direct connections делают 3 попытки и завершаются `psycopg2.OperationalError: connection to server at "luecahalemas.beget.app" (95.214.62.243), port 5432 failed: timeout expired`.
- Диагностика: `Test-NetConnection -ComputerName 95.214.62.243 -Port 5432` показывает `TcpTestSucceeded=True` через интерфейс `happ-tun`, но PostgreSQL handshake из приложения не завершается до timeout.
- Влияние: `.venv\Scripts\python.exe -m compileall app scripts`, `scripts/lint_best2info.py` и `scripts/validate_yclients_map.py` проходят; полный regression/context/edge/stress и `local_regression_suite.py --group payments --group post_booking --group fresh` нужно повторить после восстановления DB-соединения.

## 2026-06-02 live services/upsell/late hookah price and post-booking weather

- Статус: закрыто кодом и regression/context/edge проверками.
- Симптомы: стартовый вопрос `че можно?` после начала бронирования мог не перечислять все основные варианты; info-вопрос на `upsell_items` вроде `а че с парковкой` мог перескочить к телефону; `хочу добавить калик в допы, цена изменится?` на позднем шаге мог дать цену/текст без canonical `upsell_items=["кальян"]`; post-booking вопрос про погоду иногда получал AI-текст про предоплату при `payment_paid`.
- Причины: общий services-list detector был заточен под `что еще`, info-на-допах использовал `next_question(info_form_data)` вместо активного `current_step/next_step`, late addon+price не имел общего deterministic обработчика вне шага допов, а weather post-booking отдавался AI-классификатору.
- Исправлено: расширен `_asks_available_services()` и общий `_available_services_reply()`; добавлены `_upsell_info_followup_reply()` и `_late_addon_price_update()`; `addon_price_reply()` понимает разговорные алиасы кальяна; weather post-booking получает короткий deterministic ответ без изменения брони.
- Защищено: `start available services lists all primary options`, `upsell parking info returns to empty addons`, `upsell parking info keeps selected addon`, `late kalik price adds addon to confirmation`, edge `телефон + инфо-вопрос`, edge `Post-booking: вопрос на другую тему не меняет бронь`.
- Проверки: `compileall app scripts`, `local_regression_suite.py --group services`, `--group upsell`, `--group upsell --group prices --group post_booking`, `dialog_context_suite.py` 19/19, `dialog_edge_suite.py` 15/15. Голосовой smoke через OpenRouter также успешен.

## 2026-06-01 live Telegram 19:09 post-booking/photo/confirmation regressions

- Статус: закрыто кодом и regression/context/edge/stress проверками.
- Симптомы: после оплаченной беседки `а что еще можно забронить?` мог отвечать от старого `form_data` и писать `Помимо бани...`; общий запрос `а беседки покажете?` мог не приводить к реальной отправке фото; на финальном подтверждении `я перехотел, давай нет` оставлял черновик в состоянии `ожидает подтверждения`.
- Дополнительно при продолжении найден риск: AI `current_booking_question` мог вернуть текст `Пока не вижу активных броней`, даже когда paid booking есть в БД, если deterministic summary marker не сработал.
- Причины: service-list reply смотрел на `form_data.service_type` вместо активных броней; explicit-photo reply не называл конкретные gazebo variants; confirmation abort phrases не были в раннем abort guard; current-booking intent всё ещё мог использовать AI `reply_to_user`.
- Исправлено: service context берётся из `active_user_bookings()`; current-booking intent всегда отвечает `_post_booking_summary()` из БД/holds; general gazebo photo reply перечисляет беседки; `_wants_abort_confirmation_draft()` закрывает живые отказные фразы на `awaiting_confirmation`.
- Защищено: context live 19:09 `а у меня сейчас есть брони?` -> `а что еще можно забронить?`, edge `перехотел`, local regression `available services uses active booking not stale form`, `general gazebo photo request sends gazebo media`.
- Проверки: `compileall app scripts` OK; `dialog_context_suite.py` 19/19 OK; `dialog_edge_suite.py` 15/15 OK; `local_regression_suite.py --group post_booking --group media --group fresh` OK; `dialog_stress_suite.py` 13/13 OK; Graphify обновлён.

## 2026-06-01 post-booking current-booking visibility regression

- Статус: закрыто кодом и regression-проверками `post_booking`/`cancel`/`payments` плюс context/edge/stress.
- Симптом: после последних изменений stress мог показать только часть текущих paid броней или уйти в неудачный cancel/ack path; особенно рискованно для фраз вроде `чо там на мне висит по записям`, `баню убери, а беседку не трогай`, `Окей` после успешной отмены.
- Причина: `active_user_bookings()` полностью доверял `filter_actual_journal_bookings()`. Если локальная paid booking текущего разговора временно теряла подтверждение из YCLIENTS-cache, она могла исчезнуть из summary/cancel/reschedule, хотя в локальной БД оставалась оплаченная created booking.
- Исправлено: `active_user_bookings()` досоединяет paid локальные брони текущего разговора в статусах `created_in_yclients`/`journal_missing`, даже если journal-cache временно stale; `plain_ack_after_closed_booking()` deterministic принимает `ок`/`окей` после закрытой брони.
- Защищено: `dialog_stress_suite.py` сценарии `Постбронь: странный вопрос про текущие брони`, `Отмена одной услуги, вторую оставить`, `Принудительный выбор беседки... «Дя» при отмене`; `local_regression_suite.py --group post_booking --group cancel --group payments` включает `post booking summary always uses db`, `ack after cancel does not say booking fixed`, paid cancel/refund checks.

## 2026-06-01 state/text consistency hardening package

- Статус: закрыто кодом и regression-проверками `upsell`/`cancel`/`post_booking`/`payments` плюс context/edge/stress.
- Симптом риска: бот мог написать клиенту state-changing текст (`кальян добавлен`, `Допы: не нужны`, `аванс можно вернуть`) без гарантии, что canonical `form_data`/БД уже содержит соответствующее состояние или backoffice event.
- Исправлено: active-dialog semantic preflight, degraded AI log, state/text consistency rebuild guard, расширенные hookah/keep/remove upsell-фразы, refund boundary 6/7/8 дней, partial multi-booking refund events only for paid+refundable bookings, full pending refund admin drain.
- Защищено: `AI semantic preflight for active routes`, `AI said added with empty state is rebuilt`, `positive addon survives later negative`, `live hookah upsell phrases`, `cancel refund boundary 6 7 8 days`, `multi booking cancel refund only paid refundable`, `refund required notifies admin`.
- Проверки: `compileall`, `local_regression_suite.py --group upsell`, `--group cancel`, `--group post_booking --group payments`, `dialog_context_suite.py`, `dialog_edge_suite.py`, `dialog_stress_suite.py`, read-only `live_db_hygiene_audit.py --limit 20` clean. Остаточное наблюдение: больше `dialog_timing_slow` в активных deterministic ветках из-за обязательного semantic pass.

## 2026-06-01 live Telegram 16:48 kalik addon and refundable cancel notice

- Статус: закрыто кодом и regression-проверками `upsell`/`cancel`.
- Симптомы: в live-чате `Калик` получил ответ `Кальян добавлен`, но в следующем цикле бот снова спросил допы; после `Ничего`/`Нет` сводка показала `Допы: не нужны`, хотя клиент уже просил кальян. Для отмен оплаченных броней за 7+ дней клиенту писалось, что аванс можно вернуть, но админу не создавалось отдельное уведомление на ручной возврат.
- Причины: `калик` не был deterministic marker-ом для `кальян`, поэтому первый ответ мог зависеть от AI-текста без надежного состояния `upsell_items=["кальян"]`. Cancel-flow знал правило 7 дней для клиентского текста, но не создавал отдельное событие для backoffice-возврата.
- Исправлено: `upsell_items_patch()` распознает `калик/калян/калиан` как `кальян`; cancel-flow создает `system_logs.event_type='refund_required'` для paid-cancel в refundable window, а `payment_status_runner` отправляет админу текст `Требуется вернуть предоплату клиенту...`.
- Защищено: `kalik addon survives to confirmation`, `paid cancel refund window text and admin refund log`, `refund required notifies admin`.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group upsell` OK; `local_regression_suite.py --group cancel` OK; `dialog_edge_suite.py` 14/14 OK; Graphify-карта обновлена.

## 2026-06-01 live Telegram 11:45 guest/options, upsell and post-booking context

- Статус: закрыто кодом и regression/context/edge/stress проверками.
- Симптомы: `нас будет 30 человек, какая беседка подойдет` могло завершиться повторным вопросом `Сколько примерно гостей?`, хотя число уже было в сообщении; после прайса допов `давайте первый набор` не сохраняло мангальный набор №1 и возвращало старый вопрос `Что подготовить для вас?`; после брони беседки вопрос `что еще можно забронировать?` отвечал `Помимо бани...`, будто текущей услугой была баня.
- Причины: вопрос о подборе беседки с числом гостей попадал в object-selection/info route без фиксации `guests_count` как ответа на текущий шаг; upsell parser знал общие маркеры допов, но не ordinal-choice из только что показанного прайса; post-booking services reply был шаблонным и не учитывал `form_data.service_type`.
- Исправлено: `_gazebo_guest_options_shortcut()` сохраняет гостей из вопроса о подходящей беседке и переводит на `service_variant`; `upsell_items_patch()` распознаёт `первый/второй/малый набор`, `№1/№2`, 500/1000 как выбор конкретного мангального набора; `_available_services_reply()` теперь пишет `Кроме вашей беседки...` для активной беседки, `Помимо бани...` только для активной бани.
- Защищено: `Гости внутри вопроса про беседку сохраняются и не спрашиваются повторно`, `first mangal set selection from price list`, live-135 context `можно еще что нибудь забронировать?`.
- Проверки: `compileall app scripts` OK; `dialog_context_suite.py` 17/17 OK; `local_regression_suite.py --group upsell` OK; `local_regression_suite.py --group post_booking` OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; `lint_best2info.py` OK.

## 2026-06-01 local failed bathhouse booking blocked availability

- Статус: закрыто ручным cleanup 2026-06-01 в тестовом режиме.
- Симптом: по YCLIENTS-журналу баня на 30 июня могла выглядеть свободной, но бот считал слот занятым.
- Причина: локальная paid-заявка `bookings.id=1` на `2026-06-30 12:00`, 4 часа, имела `yclients_record_id=NULL` и `yclients_create_error` с HTTP 422 `Услуга недоступна в выбранное время. Выберите другое время.` При этом в `resource_busy_intervals` оставался active interval `source=bot_booking`, `source_record_id=1`, `2026-06-30 12:00-16:00`.
- Исправлено: `bookings.id=1` переведен в `cancelled` с архивной пометкой, busy interval `id=1251` удален, `payments.id=2` оставлен `paid` как история тестовой оплаты и помечен `payment_notified_at`, чтобы runner не отправил старое уведомление. В `system_logs` записано `manual_cleanup_test_bathhouse_2026_06_30`.
- Проверено по БД: для `source='bot_booking'` и `source_record_id='1'` больше нет active busy intervals; payment history сохранена. После cleanup обязательная привычка перед живым smoke остается прежней: свежий `sync_yclients_records.py --once` и `yclients_sync_status.py --strict`.

## 2026-06-01 waitlist regression touched a live row

- Статус: закрыто в test isolation.
- Симптом: grouped regression `media/waitlist/handoff/reminder` после cleanup увидел свободный слот и waitlist runner обработал существующую live-строку `waitlist_requests.id=35`, хотя тест должен был проверять только свои fixtures.
- Причина: тест вызывал общий `waitlist_service.notify_waitlist_matches()` без ограничения списка active waitlist rows.
- Исправлено: `waitlist_requests.id=35` восстановлен в `active` без `notified_at`; regression-тест теперь подменяет `waitlist_repo.list_active_due` и пропускает только waitlist ids, созданные внутри конкретного теста.
- Проверено: повторный grouped regression прошел; текущая проверка БД показывает `waitlist_requests.id=35` в статусе `active`, `notified_at=NULL`.

## 2026-05-31 pre-live fallback/proxy/smoke package

- Статус: закрыто кодом и полным listed test plan 2026-05-31.
- Симптом: regression `bathhouse blocks large group` снова красный в fallback/AI-unavailable path. Ответ на `40` гостей в активной анкете бани мог перейти к `event_format` и сохранить `guests_count=40`, вместо блокировки бани больше 15 гостей.
- Причина: normal path уже имел bathhouse capacity guard, но fallback/exception paths в `message_handler.py` проверяли только `_gazebo_capacity_mismatch_reply()`. Системный Windows proxy `socks4://127.0.0.1:10808` дополнительно переводил OpenAI/OpenRouter и YCLIENTS вызовы в ошибки `httpx`, поэтому fallback path стал реально частым.
- Исправлено: добавлен общий `_capacity_mismatch_reply()` для всех трёх мест обработки patch/fallback; он вызывает сначала gazebo guard, затем bathhouse guard. Для бани `guests_count > 15` очищается, а клиент получает явный ответ, что баню без ручного уточнения больше чем на 15 человек не оформляем.
- Исправлено операционно: добавлен `HTTP_TRUST_ENV=false` в settings, `.env.example` и локальный `.env`; OpenAI/OpenRouter, YCLIENTS, YooKassa и voice transcription создают HTTP-клиенты с `trust_env=settings.http_trust_env`. One-shot sync YCLIENTS прошёл штатно без `NO_PROXY`, strict-status fresh, `last_error=None`.
- Исправлено live-env: локальный `.env` теперь `PREPAYMENT_AMOUNT_RUB=2000`; smoke fake-payment проверяет `2000.00 ₽`.
- Дополнительный найденный баг: на шаге `guests_count` фраза `давай беседку номер 2` могла записать `guests_count=2`. Добавлен guard явной ссылки на номер беседки и smoke-check `gazebo number selection does not become guest count`.
- Защищено: `bathhouse blocks large group`, `Баня на 40 гостей блокируется до шага формата`, `friends hangout event format not birthday`, `gazebo number selection does not become guest count`, strict YCLIENTS и `dialog_regression_smoke.py`.

## 2026-05-30 live-dialog 17:48: waitlist relevance, bath capacity and confirmation "no"

- Статус: закрыто кодом и regression/context/edge/stress проверками 2026-05-30.
- Симптомы: баня принимала `40` гостей как нормальную анкету; `на 30 число` после июньского контекста могло прыгнуть на 30 мая; голое `нет` на финальном подтверждении трактовалось как правка допов; `ну окей` после info-вопроса на шаге допов мог принять допы без явного выбора; waitlist мог уведомить клиента даже если запрос уже не актуален.
- Причины: capacity guard для бани не был отдельной backend-валидацией; day-only parser не использовал свежий месяц из текущего draft/last_unavailable; confirmation-flow сначала запускал correction patch, а уже потом отрицание подтверждения; upsell-state не различал нейтральный ack после info-вопроса и явный выбор допов; waitlist notification не имел relevance gate перед отправкой.
- Исправлено: баня больше 15 гостей блокируется без ручного уточнения и предлагает просторную беседку; `30 число/на 30/на 30-е` берёт месяц из свежего контекста; `нет` на `awaiting_confirmation` переводит в change-flow и спрашивает, что изменить; `ну окей` после info-вопроса на допах оставляет шаг допов без автодобавления; waitlist перед уведомлением проверяет статус, дату, активные bookings/holds, отказ в последних сообщениях и свежую доступность.
- Защищено: `bathhouse blocks large group`, `contextual day number keeps discussed month`, `confirmation no is not upsell correction`, `generic ok after upsell info does not accept items`, `waitlist notifies only relevant requests`, context-сценарии `Баня на 40 гостей блокируется до шага формата` и `Подтверждение: «нет» не меняет допы`.
- Проверки: `compileall app scripts` OK; `local_regression_suite.py --group dates/gazebo/services/upsell/waitlist/payments/post_booking` OK по группам; `dialog_context_suite.py` 16/16 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; после one-shot sync `yclients_sync_status.py --strict` OK (`records_seen=127`, `last_error=None`).

## 2026-05-30 live-dialog 16:38: price/common-info, upsell, YCLIENTS book_times, media

- Статус: закрыто кодом и regression/context/edge/stress проверками 2026-05-30.
- Симптомы: `сколько будет стоить?` попало в ответ про детей из-за подстроки `дет` внутри `будет`; первый `не` на допах закрывал допы без второго мягкого захода; баня `30 июня 12:00-16:00` получила локальный hold/payment, но YCLIENTS после оплаты вернул `422 Услуга недоступна в выбранное время`; `нас если что 30 челове` не сразу фильтровало маленькие беседки; в сводке двух броней отправилась только баня, без фото Беседки №1; `просто посидеть с друзьями` могло стать `день рождения`.
- Причины: common-info про детей использовал слишком широкий substring `дет`; upsell final-negative считал короткое `не` финальным на первом касании; локальная availability для фиксированных услуг не сверяла выбранный старт с live `book_times`; guests parser не принимал обрезанную словоформу `челове`; media selection для booking summary не всегда восстанавливал беседку по `service_variant/yclients_service_id` или тексту сводки.
- Исправлено: children-info перешёл на словоформенный helper без подстрочного `дет`; добавлен `classify_upsell_reply()` и двухкасательный negative-flow; `bathhouse/house` с фиксированными пакетами проверяют YCLIENTS `book_times` до hold/payment и не говорят “свободно”, если API недоступен; guests parser принимает `челов*`; media берет беседку по `service_variant`, `hold_yclients_service_id`, `yclients_service_id` и текущей booking-summary строке; формат `с друзьями` сохраняется как `компания друзей`.
- Важно по архитектуре: это не зашивка одной фразы. Для цены добавлен semantic route: если AI вернул `intent=price_question`, backend считает цену по `services_map` даже без слов `цена/стоить/сколько`; deterministic слой только защищает от ложного children-info.
- Защищено: `price question with budet is not children info`, `AI semantic price question without price keywords`, `bare ne first upsell gets soft push`, `fixed service rejects missing yclients book time`, `fixed service yclients unavailable does not claim free`, `truncated people word extracts guests`, `gazebo media selection`, `friends hangout event format not birthday`.
- Проверки: `.venv\Scripts\python.exe -m compileall app scripts` OK; `local_regression_suite.py --group prices --group upsell --group services --group gazebo --group media --group payments` OK; `dialog_context_suite.py` 14/14 OK; `dialog_edge_suite.py` 14/14 OK; `dialog_stress_suite.py` 13/13 OK; после one-shot `sync_yclients_records.py` строгий `yclients_sync_status.py --strict` OK (`records_seen=126`, `last_error=None`).
- Не ремонтировалось: live paid-but-journal-pending запись бани с 422 остаётся историческим артефактом без отдельной команды на ручной ремонт.

## 2026-05-29 live-dialog 19:02: subsequent gazebo booking fell back to old bath draft

- Статус: закрыто кодом и regression/context/edge/stress проверками 2026-05-29.
- Симптом: после старого draft бани клиент спросил `а какие беседки есть`, получил общий ответ про беседку, затем написал `хочу добвить отдельной бронью`, а бот ответил ошибкой про 12 часов бани. То есть новая отдельная беседка не стартовала, а старый draft бани снова попал в availability validation.
- Причины: `отдельной бронью` и опечатка `добвить` не считались generic new-booking request; `last_discussed_service_type=gazebo` не использовался для такой фразы; service-exists route был слишком широким и мог перехватывать booking-сообщения со словом `можно`.
- Исправлено: detector новой отдельной брони расширен на `отдельной/отдельную бронью`, `добавить/добвить отдельной`; вопрос о наличии/вариантах услуги теперь исключает сообщения с датой/периодом/same-reference и дополнительные booking requests; `а какие беседки есть` отвечает списком беседок и сохраняет обсуждаемую услугу без смены текущего draft.
- Дополнительно: post-booking вопрос про комаров отвечает deterministic текстом до AI; текст по бане теперь говорит о фиксированных пакетах, а не о произвольной почасовой аренде.
- Защищено: `gazebo info then separate booking ignores old bath draft`, `mosquito question after booking bypasses AI`; пройдены `services/prices`, `fresh/post_booking/payments/time`, context 14/14, edge 14/14, stress 13/13.

## 2026-05-29 unavailable same-reference branch can look like context loss

- Статус: под наблюдением после сценарной диагностики; production-код не менялся.
- Наблюдение: первый `dialog_stress_suite.py` прогон упал на live-like цепочке `баньку тем же днем что и беседка хочу` -> `и часы как там же, без изменений`, когда скопированный слот бани оказался недоступен. Ответ был корректно про недоступность, но backend очистил основные `date/time/duration` в `form_data` и перенёс их в `last_unavailable`; для клиента это может выглядеть как потеря контекста.
- Повторный stress после cleanup fixtures прошёл 13/13, потому что тот же слот стал свободным и контекст сохранился. Значит same-reference parser работает, но unavailable-slot branch требует отдельного regression-сценария: при недоступности скопированной даты/времени бот должен явно помнить исходные `date/time/duration`, объяснять, что не свободно именно это окно, и предлагать новую длительность/время без ощущения сброса заявки.
- Следующий шаг: добавить red-first тест на unavailable same-date/same-time second service и решить, хранить ли поля в active draft вместе с `last_unavailable` или улучшить reply/current_step так, чтобы следующий ответ клиента продолжал ту же баню без повторного старта.

## 2026-05-29 YooKassa 1-ruble live payment configuration

- Статус: найдено диагностикой, production-код не менялся.
- Симптомы: реальные ссылки YooKassa из `best2` создавались на `1.00 RUB`; в локальной таблице `payments` все 7 платежей за 2026-05-28..2026-05-29 имеют `amount=1.00`, включая paid/canceled.
- Причина: в локальном `.env` задано `PREPAYMENT_AMOUNT_RUB=1`. `app/services/payment_service.py` считает сумму как `prepayment_amount_rub * bookings_count`, а `app/integrations/yookassa_client.py` отправляет это значение в `amount.value` и чек. В `.env.example` дефолт остается `PREPAYMENT_AMOUNT_RUB=2000`.
- Дополнительная проверка: read-only запрос к YooKassa по текущему магазину показал последние 30 платежей на `1.00 RUB`; все они имеют metadata booking bot (`conversation_id/user_id/payment_id/hold_ids/booking_ids`), то есть это не отдельный `scripts/yookassa_smoke.py` и не внешний источник без metadata.
- QR/СБП-диагностика: `/me` YooKassa показывает, что у магазина включен `sbp`, но текущий `YooKassaClient.create_payment()` не передает `payment_method_data={"type":"sbp"}`. Он создает обычную redirect-ссылку на общую форму `yoomoney.ru/checkout/payments/v2/contract`, где способ выбирается на стороне YooMoney; последние успешные платежи прошли как `tinkoff_bank`/`sberbank`, а не `sbp`. Отмененные платежи имеют `cancellation_details.reason=expired_on_confirmation`, то есть не завершены на странице оплаты вовремя.
- Смежный риск: `scripts/yookassa_smoke.py` тоже создает реальную внешнюю ссылку на `1.00 RUB`, но с metadata `source=booking_bot_smoke`; запускать его только как осознанный live-smoke.
- Следующий шаг: перед live-работой поставить в `.env` целевую сумму предоплаты и перезапустить бот. Если нужна именно QR/СБП-ссылка, нужно отдельное изменение интеграции: передавать `payment_method_data.type=sbp` или добавить настройку выбора платежного метода. Если нужна предоплата 50%, это отдельная логика: текущий код умеет только фиксированную сумму за бронь.

## 2026-05-29 live-dialog 14:29: stale draft, upsell refusal, soft yes and bath fixed duration

- Статус: закрыто кодом и regression/context/edge/stress split-проверками 2026-05-29.
- Симптомы: старая анкета бани на 29 мая мешала новой явной заявке `я бы хотел баню на 30 июня...`; ответ `не` на допы не принимался как отказ и бот снова продавал допы; `ну вроде да` не считалось подтверждением; баня принимала произвольный интервал `09:00-21:00` на 12 часов, хотя в YCLIENTS она продаётся фиксированными блоками.
- Причины: stale-form guard требовал отдельного ответа "новая/старая", даже когда в этом же сообщении уже были новая услуга/дата/время; upsell negative parser не считал короткое `не` финальным отказом; confirmation yes parser был слишком строгим; availability не валидировала `duration` против фиксированных `duration_minutes` вариантов до создания hold/payment.
- Исправлено: явная подробная новая заявка поверх старой анкеты стартует чистый draft с сохранением только имени/телефона; `нет/не + новая заявка` в stale-choice обрабатывается тем же сообщением; `не/no/нет спасибо` закрывает допы как `не нужны`; `ну вроде да/вроде да` подтверждает заявку; услуги с фиксированными duration-variant блоками отклоняют неподдерживаемую длительность и возвращают клиента на шаг `duration`.
- Защищено на тот момент: `stale explicit new bath request skips choice`, `stale no plus new bath request processes same message`, `bare ne upsell refusal goes to name`, `soft yes confirms awaiting confirmation`, `bathhouse rejects non-fixed duration` в `scripts/local_regression_suite.py`; дополнительно пройдены context 14/14, edge 14/14 и stress 13/13 через split-run. Политика `bare ne` 2026-05-30 изменена на двухкасательную и теперь покрыта `bare ne first upsell gets soft push`.
- Не ремонтировалось: live `booking_id=1096` остался историческим артефактом paid-local без `yclients_record_id`; причина зафиксирована как недопустимый 12-часовой блок, который новый код больше не должен пропускать.

## 2026-05-29 live-dialog 13:07: explicit period, fake payment and next-request typo

- Статус: закрыто кодом и regression/context/edge/stress проверками 2026-05-29.
- Симптомы: фраза `с 9 утра до 21 ночи, если что можно на дольше остаться?` дала беседку `с 09:00 до 08:00 следующего дня (23 часа)` вместо явного `09:00-21:00`; фраза `а ты можешь сделать будто бы я оплатил?` могла получить ответ `Оплата получена`, хотя реальной оплаты не было; фраза `приступим к следующуей заявке?` во время active hold распозналась как обновление допов `лед`.
- Причины: duration из AI-patch мог перетереть явный период, если сообщение одновременно выглядело как info-вопрос; payment-status route не отличал вопрос про имитацию оплаты от реальной проверки оплаты; короткий marker допа `лед` искался как substring и находился внутри слова `следующуей/следующей`; generic-фраза про следующую заявку поверх hold не стартовала чистую анкету без указанной услуги.
- Исправлено: `time_parsing.has_explicit_time_period()` защищает явный период `с ... до ...`; fake-payment формулировки обрабатываются отдельным guard в `confirmation_flow` и `message_handler` без смены статуса оплаты; `form_patches` проверяет короткие upsell markers по границам слова; generic next-booking request поверх active hold запускает чистую анкету с сохранением только имени/телефона.
- Защищено: `gazebo explicit period with longer question keeps end time`, `fake payment request does not mark paid`, `next application while hold starts blank not ice` в `scripts/local_regression_suite.py`; пройдены `compileall`, профиль `fresh/payments/time`, расширенный профиль `services/gazebo/upsell/post_booking/payments/time/fresh`, `dialog_context_suite.py` 14/14, `dialog_edge_suite.py` 14/14, `dialog_stress_suite.py` 13/13 и `yclients_sync_status.py --strict` после one-shot sync.

## 2026-05-29 live-dialog 1953: bath boundary, inherited gazebo draft and confirmation glitches

- Статус: закрыто кодом и профильными regression-проверками 2026-05-29.
- Симптомы: `имя заменим на IVAN` сохранялось как `Заменим На Ivan`; вопрос `а если бы нас было 10` отвечал по старым 20 гостям; после `не нужны` + `если что там на месте возьмем` в подтверждение попадал `базовый мангальный набор`; после ввода телефона клиент видел вторую confirmation-сводку; paid notification не показывало дату/время брони; post-booking вопрос про баню выдумывал русскую/финскую сауну и возможность добавить баню к беседке; generic `давайте начнем новую заявку` и `а я же хочу баньку` наследовали поля старой беседки.
- Причины: name-correction regex не покрывал форму `заменим`; hypothetical guest parser не понимал `нас было/было бы`; разговорное `на месте возьмем` не считалось отказом от допов; после info-вопроса про баню не сохранялся безопасный контекст последней обсуждаемой услуги для generic new booking; service-correction фраза `я же хочу` могла продолжать старый draft вместо чистой новой услуги; paid text не включал краткую строку брони.
- Исправлено: расширен parser исправления имени и сохранение uppercase Latin; добавлен parser `нас было/было бы`; `на месте возьмем/возьмём` считается отказом от допов; post-booking bath info стал deterministic: только баня с бассейном, отдельная бронь, не доп к беседке; follow-up `а ее как бронировать нужно?` отвечает по последней обсуждённой бане через `last_discussed_service_type`; generic new booking использует этот контекст, но создаёт чистый draft с сохранением только контакта; `а я же хочу баньку` сбрасывает старые slot-поля; paid notification добавляет строку `Бронь в журнале`; добавлен regression на `телефон -> да`, чтобы не возвращалась вторая confirmation-сводка.
- Проверка БД по live-чату: booking `806` в локальной БД есть, `yclients_record_id=1741815435`, `payment_status=paid`, `status=created_in_yclients`, `admin_notified_at` заполнен. Значит backend создал запись и отметил admin notification; отдельная проблема могла быть в видимости/доставке, но не в отсутствии записи в БД.
- Защищено: `name correction replaces value after na`, `hypothetical guest count updates capacity question`, `on-site upsell refusal keeps no extras`, `phone completion yes creates hold not second confirmation`, `paid notification includes booking summary`, `bathhouse post-booking info then generic new request`, `service correction with zhe resets old form` в `scripts/local_regression_suite.py`; профильный прогон `local_regression_suite.py --group services --group payments --group upsell` OK, ранее полный набор suites на 2026-05-29 зелёный.
- Дополнительно защищено paraphrase-пакетом 2026-05-29: разные формулировки `имя/фио ... на IVAN`, `если нас 10/для 10 человек`, `на месте возьмем/возьмём/разберемся`, а также post-booking цепочки про баню. Этот пакет поймал и закрыл общий prefilter-баг `фио измени на IVAN`; профиль `local_regression_suite.py --group services --group gazebo --group upsell --group post_booking --group payments` завершился `EXIT=0`.

## 2026-05-29 live-dialog 135: paid/expired hold context around new bath request

- Статус: закрыто кодом и regression/context/edge/stress/smoke проверками 2026-05-29.
- Симптомы: на вопрос `а она уже активна, я вносил предоплату?` бот мог ответить, что предоплата не поступила, хотя по локальной БД была оплаченная беседка; фраза `давайте новую оформим, мне нужна баня` запускала отмену оплаченной беседки; фраза про ожидание оплаты `денег нет... подождете?` уходила в перенос; после истечения резерва `давайте` / `я и говорю давай ее же оформлю` теряли старый слот и снова спрашивали дату.
- Причины: `мне нужна баня` матчилась как `не нужна баня` из-за substring-поиска в cancel detector; вопросы про внесённую предоплату не попадали в deterministic payment-status route и могли уйти в AI/post-booking текст; фразы про задержку оплаты не имели reserved-hold guard и могли быть классифицированы как reschedule; после expired hold не было восстановления контекста "этот же слот".
- Исправлено: cancel detector теперь использует word-boundary для `не нужна/не нужен/не нужно`; payment-status detector расширен на вопросы `вносил предоплату/бронь активна`; для active hold добавлен ответ про 10-минутный резерв и повторную проверку после истечения; для expired hold добавлено восстановление `service_type/date/time/duration` из последнего истёкшего hold по фразам `давайте`, `оформим эту же`, `ее же оформлю`.
- Защищено: `paid booking payment question is deterministic`, `new bath request does not cancel paid gazebo`, `payment delay does not start reschedule`, `resume same expired hold does not ask date` в `scripts/local_regression_suite.py`; пройдены `compileall app scripts`, полный `local_regression_suite.py`, `dialog_context_suite.py` 14/14, `dialog_edge_suite.py` 14/14, `dialog_stress_suite.py` 13/13, `dialog_regression_smoke.py`, `yclients_sync_status.py --strict`.

## 2026-05-28 same-date wording: `число такое же как у беседки`

- Статус: закрыто кодом и regression/context/edge/stress проверками 2026-05-28.
- Симптом: в новой регрессии для второй услуги фраза `число такое же как у беседки` внутри draft бани не переносила дату активной беседки. Бот отвечал справкой `По активной брони у вас...` и затем снова спрашивал дату по бане.
- Причина: cross-service active-booking info route был слишком широким и принимал same-date/same-time reference как информационный вопрос про активную беседку.
- Исправлено: `_active_booking_reference_info_reply` теперь не обрабатывает сообщения, которые являются same-date/same-time reference; такие фразы уходят в `_same_booking_reference_patch` и обновляют текущий draft.
- Защищено: `second service same number wording keeps current service` в `scripts/local_regression_suite.py`; дополнительно пройдены `dialog_context_suite.py` 14/14, `dialog_edge_suite.py` 14/14 и `dialog_stress_suite.py` 13/13.

## 2026-05-28 live-dialog 135: second booking after paid gazebo lost context

- Статус: закрыто кодом и regression/context/edge/stress проверками 2026-05-28.
- Симптомы: после оплаченной беседки вопрос `можно еще что нибудь забронировать?` мог вернуть старое `Заявка пока ожидает подтверждения`; фраза `давайте еще баню на то же число что и беседка` брала 30 июня, но следующим ответом снова спрашивала дату; вопрос `а вообще норм беседка?` внутри draft бани отвечал общим рекламным текстом про беседки и путал текущую услугу.
- Причины: post-booking/info route мог использовать старый booking-ready `form_data`; fresh-start не всегда пробивал `awaiting_confirmation`, если у клиента уже есть оплаченная активная бронь; same-date filter новой заявки вычищал date-patch от reference-фразы; `на то же число` частично матчился как same-time; info-вопрос про другую услугу не искал активную бронь этой услуги.
- Исправлено: post-booking `что еще можно забронировать` отвечает списком услуг без запуска confirmation; явная новая бронь после оплаченной активной брони чистит slot-поля через new-booking policy; `то же число` сохраняет date-patch для новой услуги; баня с известной датой спрашивает время; cross-service info reply отвечает по активной беседке и возвращает к текущему draft бани.
- Дополнительно усилены flow guards: plain ack после закрытой брони не перехватывает активные `cancel_flow/reschedule_flow/swap_reschedule_flow`; cancel-flow на подтверждении использует сохраненный `booking_id/booking_ids`, если активная сверка журнала временно не вернула запись.
- Защищено: `live 135 paid gazebo then bathhouse keeps context` в `scripts/local_regression_suite.py`; live-chain в `scripts/dialog_context_suite.py`; полный `local_regression_suite.py`, context/edge/stress suites и `yclients_sync_status.py --strict`.

## 2026-05-28 live-dialog: upsell accept, confirmation info and paid journal record

- Статус: закрыто кодом, regression/context/edge/stress проверками и ручным repair live booking `213`.
- Симптомы: после soft upsell клиент написал `ну давайте`, но бот повторил вопрос допов; на `а это хорошая беседка?` бот ответил `Оформляем вторую бронь`; после оплаты не пришло paid-сообщение, а запись в YCLIENTS не появилась сразу.
- Причины: vague accept после upsell-push не мапился на только что предложенный набор; fresh-start guard мог сработать до confirmation-flow на вопросе со словом `беседка`; Telegram updates одного пользователя обрабатывались параллельными `to_thread`; YCLIENTS create упал на transient SSL timeout, а paid notification ждал journal-ready; локальный busy interval paid booking создавался без hold staff id и мог выбрать первую беседку из config.
- Исправлено: contextual accept для soft upsell; deterministic answer про текущую выбранную беседку; fresh-start не прерывает `awaiting_confirmation`; per-user Telegram lock; retry YCLIENTS create через 30 секунд; one-time промежуточное paid уведомление при journal-pending; bookings repo возвращает hold service/staff, busy interval перезаписывается на правильный ресурс.
- Live repair: `scripts/sync_payment_statuses.py` создал YCLIENTS record `1741240914` для booking `213`, ресурс `18201061/3828151` (`Беседка №4`), `yclients_create_error=NULL`.
- Защищено: новые checks `soft upsell accept after push adds basic set`, `gazebo quality question during confirmation stays in confirmation`, `paid finalize busy interval uses hold variant`, плюс полный набор `compileall`, grouped regression, `dialog_context_suite.py`, `dialog_edge_suite.py`, `dialog_stress_suite.py`.

## 2026-05-28 keyword-trigger concern for guest parsing

- Статус: закрыто 2026-05-28.
- Нюанс: после фикса `30 июня -> 30 гостей` backend всё ещё выглядел так, будто ищет слова `чел/человек/гостей/нас будет` и на них строит понимание. Это противоречило архитектурному принципу: AI понимает смысл, backend валидирует состояние.
- Исправлено: core guard больше не использует guest-keywords как условие принятия/отклонения. AI-only `guests_count` проверяется структурно: не является ли оно числом даты или номером беседки, не является ли текущий шаг `guests_count`, не подтвердил ли это deterministic parser.
- Защищено: `на 30 июня двадцать` принимается как 20 гостей через AI-смысл; `на 30 июня` не становится 30 гостями; `29 мая 6 беседка` не становится 6 гостями.
- Проверено: `dialog_context_suite.py` 13/13, профильные regression-группы, `dialog_edge_suite.py` 13/13, `dialog_stress_suite.py` 13/13.

## 2026-05-28 live-dialog: `на 30 июня` became `30 guests`

- Статус: закрыто кодом и regression/context/edge/stress проверками 2026-05-28.
- Симптом: после `нужна беседка` клиент написал `на 30 июня`, а бот ответил `беседка свободна` и спросил, какую беседку выбрать. Затем на `а какой у меня выбор есть?` попросил дату заново, а на `я же писал 30 июня` уже отвечал, что `Беседка №1` подходит для `30 гостей`. В финальном состоянии диалога лежали `date=2026-06-30`, `guests_count=30`, `service_variant=Беседка №1`, хотя гостей клиент не называл.
- Причина: AI мог классифицировать ответ текущего шага как `answer_info` и вернуть patch с датой/гостями; backend раньше мог выкинуть валидную дату из info-like сообщения или принять `guests_count=30` из AI-patch. После этого availability для 30 гостей оставляла одну беседку №1, и состояние становилось отравленным.
- Исправлено: ответ текущего шага не считается info, если backend принял state-changing fields; число из date-only текста не принимается как `guests_count` по структурному конфликту с датой; AI может принимать semantic guest без слов-маркеров, если число не конфликтует с датой/вариантом; после даты без гостей бот спрашивает количество гостей перед подбором вариантов; вопрос про выбор при известной дате больше не теряет дату.
- Добавлен recovery: если клиент пишет, что бот не спросил количество гостей, backend очищает ошибочный `guests_count/service_variant/last_available_gazebo_variants` и возвращает шаг `guests_count`.
- Защищено: `scripts/dialog_context_suite.py` 13/13, включая `Чистая дата не превращается в 30 гостей`, `AI-смысл без слов-маркеров гостей принимается`, `Номер беседки из AI-patch не превращается в гостей`, `Вопрос про выбор помнит дату и просит гостей`, `Жалоба на неуточненных гостей чинит испорченное состояние`; профильные regression-группы, `dialog_edge_suite.py` 13/13, `dialog_stress_suite.py` 13/13.
- Остаточный риск: скорость отдельных AI semantic веток (`dialog_timing_slow` до ~15 секунд на off-topic внутри формы). Состояние не портится, но нужен будущий deterministic short-circuit для частых посторонних вопросов.

## 2026-05-28 live-dialog: two-gazebo request loses multi-booking context

- Статус: закрыто кодом и regression/context/edge/stress проверками 2026-05-28.
- Исправлено: mixed info+booking для `2 беседки` теперь не теряет booking intent; текущая заявка и следующая дата ведутся последовательно через `pending_additional_bookings`; вторая дата не перезаписывает первую заявку; будние цены беседок показывают скидку 50%; confirmation correction имеет приоритет над reserved-hold glue; `активыне заявки` распознаётся как summary-вопрос; ночной интервал показывается как `до 08:00 следующего дня`.
- Защищено тестами: `scripts/dialog_context_suite.py` содержит сценарии sequential two-gazebo queue, pending second-date guard, weekday price discount and awaiting-confirmation typo summary. Дополнительно пройдены профильные regression-группы, `dialog_edge_suite.py` и `dialog_stress_suite.py`.
- Клиент сразу написал смешанный запрос: `нужно 2 беседки на 02.06 и 19.06. там есть мангал и угли?`. Бот ответил только на info-часть про мангал и не закрепил intent `две отдельные беседки`.
- Дальше бот вел один текущий draft вместо двух последовательных броней: `02.06 на 11` было воспринято как 11 гостей, `19.06 на 13` вмешалось в тот же draft и не стало второй заявкой на 19 июня.
- Availability/price list для 2 июня показал базовые цены беседок без будней скидки 50%, хотя 2 июня 2026 — вторник. Discount-aware path сейчас срабатывает на явный вопрос про скидку, но не применяется к списку свободных вариантов с ценами.
- На подтверждении `время тоже поменяй с 11 до 08` было перехвачено reserved-hold command guard до `awaiting_confirmation` correction-flow и получило неверный ответ `не вижу активной предварительной заявки`, хотя draft был на подтверждении.
- Summary-вопрос с опечаткой `активыне заявки` не распознался как вопрос о текущей заявке и ушел в side-reply, который ответил `Оформляем вторую бронь`, хотя нужно было показать текущий черновик или сказать, что оформленных активных заявок пока нет.
- UX-решение: одиночное `на 11.00` для беседки по текущим правилам может стать интервалом до 08:00, но клиенту обязательно нужно показывать это явно как `до 08:00 следующего дня`, чтобы не выглядело как ошибка времени.
- Требуется fix-step: multi-booking intent memory (`pending_second_booking`/queue), mixed booking+info должен применять booking intent до info-ответа, discount-aware formatting для gazebo availability list, correction priority на `awaiting_confirmation`, fuzzy summary detector для `активные заявки` с опечатками.

## 2026-05-28 live-dialog: date+guests context routed past availability

- Статус: закрыто кодом и regression/context/edge/stress проверками.
- Симптом: после `Понял, беседку` клиент написал `на 30 июня нас будет 20`, а бот ответил, что на 30 июня нет подходящих беседок и на ближайшие 75 дней свободных дат не нашёл. Это выглядело как неактуальная таблица и потеря контекста.
- Диагностика: после свежего `scripts/sync_yclients_records.py --once` локальная БД показывает на 30 июня для 20 гостей свободные `Беседка №1`, `Беседка №8`, `Беседка №3`, `Крытая беседка`. Значит основная причина была в routing, не в данных.
- Причина: date+guests в одном сообщении могло попасть в selection/no-capacity glue до реальной availability-проверки или использовать старые `last_suggested_free_dates`. Для маленьких свободных беседок no-capacity ответ не всегда добавлял ближайшие подходящие даты.
- Исправлено: date+guests first message идёт в availability executor; stale suggestions очищаются при смене даты/гостей; маленькие свободные беседки объясняются как неподходящие по вместимости; ближайшие подходящие даты ищутся вокруг выбранной даты.
- Дополнительно закрыт context-bug: `что мы подтверждаем?` на `awaiting_confirmation` без слова `бронь` теперь показывает черновик, а не запускает повторную availability-проверку.
- Защищено: `gazebo date+guests first message checks availability`, `gazebo small slots on date offers nearest suitable`, `scripts/dialog_context_suite.py` 4/4, `dialog_edge_suite.py` 13/13, `dialog_stress_suite.py` 13/13.

## 2026-05-28 live-dialog: refusal during upsell continued booking flow

- Статус: закрыто кодом и regression/stress проверками.
- Симптом: после info-ответа про правила/корпоратив клиент написал `давай откажемся от брони`, а бот ответил `Беседка: 18:00-00:00 свободно` и снова предложил допы. Это выглядело как отсутствие понимания у AI.
- Причина: формулировка `откажемся от брони` не попадала в cancel/abort detector; в активной анкете на шаге допов сообщение проваливалось ниже, где booking flow продолжал availability/upsell. Это routing priority bug: cancel/abort должен обрабатываться раньше допов, availability и AI-generated ответа.
- Исправлено: detector отмены/abort покрывает `откажемся/отказ от брони/заявки/оформления`, `бронь не нужна`, `не будем бронировать`. Для незавершенной заявки backend очищает slot-поля, сохраняет контакт и возвращает шаг `service_type`.
- Дополнительно закрыт соседний guard: неопределенное `ну че нибудь` на шаге времени больше не запускает AI-инвенцию популярных слотов, а повторяет вопрос времени.
- Защищено тестами: `fresh+upsell`, `post_booking+cancel`, `dialog_edge_suite.py` 13/13 и `dialog_stress_suite.py` 13/13.

## 2026-05-28 live-dialog 6093: status fixed

- Статус: закрыто кодом и regression/stress проверками. Старый диагностический блок ниже оставлен как история причины.
- Исправлено: `20 чел` надежно принимается как `guests_count=20`; 5 июня для 20 гостей не предлагает маленькие беседки как подходящие; уточнение `только эта свободна на 5 июня` не листает stale `last_suggested_free_dates`; 8 июня показывает подходящие №1/№8/№3.
- Исправлено: вопросы `скидка/со скидкой` идут через discount-aware path и `best2info/rules/discounts.md`; для 8 июня 2026 и Беседки №1 применяется ПН-ЧТ скидка 50%.
- Исправлено: после `18,00` -> `на 5` -> `встреча однокласников` -> `кальян давайте` сохраняются `time=18:00`, `duration=5`, `event_format`, а upsell не возвращает форму к шагу времени.
- Защищено тестами: live-сценарий 6093, `best2info` retrieval, скидки/предоплата/кальян/дети/парковка, state regression после перехода к допам.
- Остаточный риск не функциональный: в regression/stress все еще встречается `dialog_timing_slow` на отдельных AI semantic ветках; это наблюдение по скорости, а не открытый баг корректности.

## 2026-05-28 live-dialog 6093: capacity, nearest dates, discounts, form state

- Статус: найдено по последнему реальному Telegram-чату `conversation_id=6093`; production-код пока не менялся, нужен отдельный fix-step с regression.
- `20 чел` после вопроса о гостях не был надежно принят как `guests_count`: если AI/semantic помечает сообщение как info-like, `_ai_first_patch` оставляет только `_capacity_guest_patch`, а тот сейчас не покрывает сокращение `чел`. Поэтому бот ответил списком свободных беседок на 5 июня без фильтра по 20 гостям и снова спросил количество.
- После этого `last_suggested_free_dates` запомнил нерелевантные для 20 гостей даты. Сообщение `только эта свободна на 5 июня` попало в early route `_asks_for_free_slots` на `awaiting_new_date`, который сразу вызывает `_next_free_dates_reply` и не парсит явную дату/уточнение. В итоге бот показал 16-20 июня как следующую страницу, хотя ближайшая подходящая дата была 8 июня.
- По текущей локальной availability-таблице ошибка не похожа на stale YCLIENTS-cache: 5 июня для 20 гостей нет подходящих слотов, 8 июня подходят `Беседка №1/№8/№3`, 4 июня подходят `Беседка №8/Крытая`. Но freshness на момент live-чата из текущего `yclients_sync_state` задним числом не восстановить.
- Вопросы про скидку перехватываются deterministic price path: `_deterministic_info_reply -> _price_reply_if_known` возвращает базовую цену из `services_map` до обращения к базе знаний. В knowledge есть 50% скидка ПН-ЧТ и таблица цен, но backend не применяет discount-aware ответ для фраз `скидка`, `со скидкой`; поэтому 8 июня, понедельник, бот написал 10 500 ₽ вместо объяснения скидки/условий.
- После ответов `18,00`, `на 5`, `встреча однокласников` бот затем снова спросил время после `кальян давайте`. Финальное состояние разговора подтверждает потерю `time`, `duration`, `event_format` при сохранённом `upsell_items=["кальян"]`. Вероятный класс бага: AI-текст/last-assistant-asked-upsell может перескочить к допам, пока backend фактически не закрепил все поля; затем upsell branch мержит допы поверх form snapshot, где время/длительность/формат отсутствуют. Нужен state-safe guard: ответ клиенту должен соответствовать `next_question(form_data)`, а form patch на ожидаемом шаге должен иметь приоритет над AI-текстом.
- Дополнительный UX-нюанс: `а скидка есть` получил пустой ответ-заготовку `Сейчас расскажу про скидки и акции` без фактов. Такие ответы надо считать невалидными для info-вопросов: если deterministic/knowledge не дал содержательного факта, лучше честно сказать, что условия уточним, и не создавать ощущение, что бот "не думает".

## 2026-05-28 edge-dialog interruptions

- Статус: найдено самостоятельным `scripts/dialog_edge_suite.py` и закрыто кодом/промптом. Summary-вопросы внутри анкеты/подтверждения теперь показывают черновик; отмена на `awaiting_confirmation` сбрасывает еще не созданную заявку; info-вопросы внутри cancel-flow не подтверждают отмену и отвечают по авансу/возврату; `нет, оставь` закрывает cancel-flow без удаления брони; off-topic post-booking больше не предлагает допы.
- Добавлен защитный сценарный набор `scripts/dialog_edge_suite.py` - 12/12 OK после правок.
- Остаточный риск: совсем посторонние вопросы внутри активной формы могут идти через AI semantic и давать `dialog_timing_slow`; состояние при этом не портится. Следующий UX-фокус - больше быстрых deterministic short-circuit для частых off-topic/info-вопросов.

## 2026-05-28 current-request and soft-handoff follow-up

- Статус: закрыто кодом и regression/stress проверками. Вопросы о "броне, которую хотел забронировать" теперь показывают черновик, если активной брони/hold нет; `ну че нибудь` не создает выдуманное время; `бля будем зажигать` не запускает handoff без жалобы; same-time reference для второй услуги подтягивает время из активной брони.
- Добавлены regression checks: `booking summary uses draft when no active booking`, `emotional event format does not handoff`, `second service same time reference on time step`.
- Остаточный риск: live Telegram smoke перед следующим релизным прогоном все равно должен начинаться с проверки fresh YCLIENTS sync, потому что direct free-dates зависит от локальных `yclients_records` / `resource_busy_intervals`.
- Остаточный UX-риск: отдельные AI semantic ветки все еще дают `dialog_timing_slow` примерно 3-10 секунд в regression/stress. Функционально тесты зеленые, но скорость остается под наблюдением.

## 2026-05-28 live-dialog: free dates, mixed info, and state glue

- Статус 2026-05-28: основные live-баги закрыты кодом, regression-сценариями и ручным live-like прогоном. Перед реальным Telegram smoke обязательно проверить, что YCLIENTS sync fresh.
- В live-чате 09:05 бот на запрос `начнем новую / какие ближайшие свободные даты для бани?` ответил, что ближайшая баня только с 6 августа. Текущая диагностика после sync показывает, что локальная availability-таблица считает баню свободной 28 мая, 29 мая, 1 июня и дальше; значит ошибка не подтверждается текущими данными и вероятнее связана со stale form/free-dates glue: старые `date`/`last_unavailable`/`last_suggested_free_dates` могли сдвинуть старт поиска ближайших дат, даже когда клиент явно начал новую анкету.
- В `resource_busy_intervals` снова обнаружены локальные интервалы `source='bot_booking'` для бани 24 июня, хотя после подготовки live-теста ожидались только `yclients` intervals. Они не объясняют августовский ответ напрямую, но это отдельный риск чистоты локальной таблицы свободности.
- Ответ на `а че нас типо 10 челов / какую нам выбрать, что дешевле` задал два вопроса в одном сообщении: сначала `Какую выбираете?`, затем `Продолжим оформление: На какую дату планируете отдых?`. Источник: info/budget reply уже содержит выбор, а `_answer_info_during_form` добавляет следующий вопрос анкеты, если `_reply_already_asks` не распознал общий вопрос выбора как уже заданный.
- Сообщение `ну окей давайте четвертую / а с детьми можно?` ответило только про детей и не закрепило `Беседка №4`. Нужна обработка mixed selection + info: backend должен сначала применить валидный выбор варианта, затем ответить на info-вопрос и задать ровно один следующий вопрос.
- Сообщение `я же говорил 10` после вопроса о количестве гостей было принято как время `10:00`, что привело к слоту `10:00-08:00`. Нужен expected-step-aware guard: если текущий/следующий шаг `guests_count`, голое число и фразы `я же говорил 10` должны обновлять гостей, а не время.
- После pause-фразы `окей, лан я позже напишу` короткое `кайф` снова вернуло к upsell-вопросу. Нужен post-pause ack guard, чтобы клиентское подтверждение/эмоциональная реакция не перезапускали текущий вопрос.
- Что изменено: direct free-dates с явным `новую` обходит старый `last_unavailable`; бюджетный подбор без даты не заявляет свободность и спрашивает дату; `челов` распознаётся как гости; mixed selection+info сохраняет вариант беседки; `guests_count` как активный шаг имеет приоритет над YAML-порядком полей; post-pause ack отвечает без повторного upsell.
- Дополнительно найден и закрыт edge case: протухшая анкета без активного `stale_form_flow` больше не показывает checkpoint, если клиент явно пишет `начнем новую` вместе с запросом ближайших свободных дат; добавлен regression `old form new free dates skips stale choice`.
- Проверено: `compileall`; полный `local_regression_suite.py`; `dialog_stress_suite.py` 13/13; после последней stale-form правки - groups `fresh/dates/time` и `reschedule`; ручной live-like сценарий с ближайшими датами, бюджетным подбором, mixed selection+info, `я же говорил 10`, pause ack и переносом.
- Наблюдение: если `yclients_sync_status.py --strict` stale, direct lookup может давать неверную картину свободности. После ручного `sync_yclients_records.py --once` ближайшие даты снова корректны. Это production-риск настройки фонового sync, а не user-facing dialog bug.

## 2026-05-27 reschedule-flow refactor status

- Снижено: первый слой reschedule helpers и single reschedule execution вынесены из `message_handler.py` в `app/services/dialog/reschedule_flow.py`.
- Проверено: `compileall`, `reschedule`, `gazebo+reschedule`, `post_booking+cancel+payments+services`, `gazebo+post_booking+payments+cancel`, `dialog_stress_suite.py` 13/13.
- Найдено и закрыто в ходе проверки: `gazebo_capacity_by_title` оказался shared helper для обычного availability-flow; после добавления alias regression/stress снова зелёные.
- Остаточный риск: grouped/swap execution переноса всё ещё в `message_handler.py`; следующий шаг должен быть callback-based, как cancel-flow, потому что там есть удаление нескольких YCLIENTS-записей, rollback старых записей и busy intervals.

## 2026-05-27 cancel-flow refactor status

- Снижено: execution отмены вынесен из `message_handler.py` в `app/services/dialog/cancel_flow.py` через `CancelFlowCallbacks`.
- Проверено: `compileall`, `local_regression_suite.py --group cancel`, `--group post_booking --group payments --group reschedule`, `dialog_stress_suite.py` 13/13.
- Остаточный риск: reschedule execution, `availability_flow` и часть confirmation-flow всё ещё в `message_handler.py`; следующий разрез должен быть таким же маленьким и callback-based.

## 2026-05-27 post_booking_flow refactor status

- Снижено: часть post-booking логики вынесена из `message_handler.py` в `app/services/dialog/post_booking_flow.py`, без изменения AI/prompts.
- Проверено: `dialog_stress_suite.py` 13/13 и связанные regression-группы прошли.
- Остаточный риск: основной `_handle_post_booking_message`, reschedule-flow и availability-flow всё ещё в `message_handler.py`; следующий вынос должен быть ещё более осторожным, маленькими кусками и с теми же группами тестов.

## 2026-05-27 webhook hardening update

- Закрыто частично: YooKassa webhook теперь имеет application-level secret check, production fail-fast без secret, body-size limit и smoke-тест.
- Остаточный production-риск: публичный webhook всё равно нужно открывать только через reverse proxy/HTTPS и серверные лимиты; сам встроенный `ThreadingHTTPServer` не должен напрямую смотреть в интернет без обвязки.
- Диалоговая логика этим изменением не тронута; `dialog_stress_suite.py` после правки прошёл 13/13.

## Под наблюдением

- `message_handler.py` очень большой и содержит много пересекающихся сценариев. Риск регрессий высокий при точечных правках.
- Рефакторинг `message_handler.py` начат, но не завершен: вынесены formatting/price-info/stale-form/routing guards/semantic-router/response-builder/performance/post-booking/cancel/reschedule/availability helpers, confirmation-flow, direct free-dates lookup и explicit photo reply; дальше нужны оставшийся media scheduling и glue-код fresh-start/stale-form.
- AI может ошибаться в неоднозначных сообщениях, поэтому backend должен продолжать валидировать state и доступность.
- Проверка свободности зависит от свежести `yclients_records` и `resource_busy_intervals`.
- 2026-05-29 full diagnostics: если основной bot/sync runner выключен больше 10 минут, `yclients_sync_status.py --strict` и availability freshness снова падают; перед live smoke обязательно запускать/проверять `sync_yclients_records.py --once`.
- 2026-05-29 full diagnostics: `validate_yclients_map.py` прошёл, но YCLIENTS несколько раз дал transient SSL handshake timeout на `book_staff`; retry спасает, внешний API остаётся infra-ризком.
- ЮKassa webhook пока зависит от серверной настройки; без него подтверждение оплаты идет через polling или следующее сообщение.
- Голосовые сообщения зависят от provider/model и формата Telegram audio.
- Media flow зависит от имен файлов в `app/images/`; после замены фото нужно проверять реальные отправки.
- Полный `scripts/local_regression_suite.py` всё ещё слишком долгий для обычного прогона: ежедневную проверку лучше запускать по группам через `--group`. Печать длительности check уже добавлена, per-test timeout пока не добавлен.
- Трассировка показала, что долгие ответы часто связаны с `db.connect`/`db.work`; connection pooling добавлен, дальше нужно наблюдать за стабильностью удаленного PostgreSQL и битых pooled-соединений после сетевых сбоев.
- 2026-05-27: после пополнения/восстановления хостинга PostgreSQL некоторое время давал `timeout expired` при подключении к `luecahalemas.beget.app:5432`, хотя TCP-порт был доступен. Позже `scripts/db_status.py` прошел, stress-suite и затронутые regression-группы прошли OK. Риск остается под наблюдением: если снова появятся задержки 30+ секунд на первом сообщении, сначала проверять БД/хостинг.
- Параллельный запуск `local_regression_suite.py`/`dialog_stress_suite.py` теперь защищён lock-файлом. Если прогон будет аварийно убит timeout-ом, может потребоваться проверить stale lock в `%TEMP%\best2_regression_suite.lock`.
- Даже после оптимизации dialog routing отдельные AI-ветки остаются медленными: в regression/stress логах встречаются 8-15 секунд на cancel/reschedule и до 20+ секунд на сложные info/post-booking ответы. Следующий UX-фокус - ограничить тяжелые AI-вызовы, добавить более быстрые deterministic replies для частых info-вопросов и/или вынести semantic-router на более быструю модель после замеров.
- AI всё ещё иногда возвращает текст, похожий на внутреннюю инструкцию. Сейчас guard/fallback перехватывает это и клиенту уходит безопасный ответ, но сам факт нужно держать под наблюдением при смене модели/промпта.
- 2026-05-28: до пополнения tokens в stress/regression логах повторялся OpenRouter 402 `Prompt tokens limit exceeded` на отдельных AI-ветках. После пополнения в текущем confirmation-flow прогоне 402 не повторился, но live-качество сложных info/post-booking ответов всё равно зависит от доступного лимита/кредитов и дальнейшего сокращения prompt.
- 2026-05-27: strict hold-flow функционально исправлен и покрыт тестами, но в live нужно дополнительно проверить связку Telegram + payment polling: сообщение о снятии резерва через 10 минут, отсутствие автоподтверждения поздней оплаты, отсутствие повторной ссылки на тот же hold.
- 2026-05-27 project review: critical hold/payment/sync риски закрыты production-hardening разрезом; теперь следить за live-сценариями Telegram + payment polling и свежестью sync-state.
- 2026-05-27 project review: `scripts/validate_yclients_map.py` не завершился за 124 секунды на ручном прогоне; нужна диагностика timeout и повтор в стабильном окне.

## Уже закрытые классы проблем

- Старые поля анкеты после паузы 2+ часа не должны применяться молча.
- Ответ "давайте" на checkpoint старой анкеты не должен приводить к уточняющему циклу.
- Запрос "какие ближайшие свободные даты..." должен идти в availability/локальную таблицу записей, а не в вопрос "на какую дату".
- Вопрос "сколько это всё стоит?" в момент допов должен отвечать по допам, а не по базовой цене услуги.
- Финальное подтверждение не должно маршрутизировать информационные вопросы в post-booking classifier.
- Post-booking не должен дергать ЮKassa/YCLIENTS на каждое сообщение, если у разговора нет локального платежа.
- Формат отдыха не должен выдумываться AI без явного сообщения клиента.
- Допы должны попадать в booking/YCLIENTS comment.
- Подтверждения `да`, `да да`, `+`, `хорошо` должны закрывать confirm-flow.
- Перенос должен очищать `reschedule_flow` после успеха.
- Внутренние инструкции AI вроде "Начни без приветствия..." не должны уходить клиенту: добавлен guard/fallback в `response_builder.py`.
- Обычная проверка свободности не должна делать live fallback в YCLIENTS; клиентский диалог использует локальные `yclients_records`/`resource_busy_intervals`.
- Комбинированный запрос "беседка + баня" должен стартовать с первой услуги и объяснять, что вторую оформим отдельной бронью после первой.
- Невалидный телефон больше не должен уходить через AI и возвращать внутреннюю фразу "попроси клиента".
- Вторая услуга "баня на то же время что и беседка" должна сохранять текущую услугу и брать только время/длительность из активной брони беседки.
- "До утра / как пойдет" теперь работает не только для беседок, но и для бани/дома.
- `event_format` с опечаткой клиента сохраняется только на шаге формата; AI больше не должен выдумывать формат на других шагах.
- Info-вопрос по цене допов на шаге допов не должен повторять вопрос про формат отдыха.
- "Та же дата/то же время что и беседка" для второй услуги не должно переключать текущую услугу обратно на беседку.
- Текст отмены теперь зависит от правила 7 дней, а не всегда пишет "аванс не возвращается".
- Запрос "подешевле/дешевле/недорого" на выборе беседки не должен повторять весь список: нужно фильтровать уже проверенные свободные варианты по вместимости и цене.
- Живые отказы от допов (`неа`, `нте`, `нет же говорю`, `ytn`) не должны ломать двухкасательную upsell-логику и не должны приводить к повторному вопросу про допы после телефона.
- Вопросы по ценам с разговорным `по чем` и опечаткой `решотка` должны отвечать ценой допов и не добавлять доп автоматически.
- Явный запрос фото с формой `3й/3-й/третьей беседки` должен отправлять фото конкретной беседки.
- Выборочная отмена вроде `баню убери, а беседку не трогай` должна исключать защищенную услугу из отмены.
- Живая фраза переноса `сдвинем баню на денек позже, часы те же` должна переносить выбранную бронь на следующий день и сохранять время.
- Abort-фразы `забей`, `не оформляем`, `отбой` должны закрывать только текущий черновик анкеты, не трогая оплаченные брони.
- Info-вопросы внутри активной анкеты не должны менять основное состояние анкеты через AI patch: вопрос `а если нас будет 30 человек` в анкете бани остается в контексте бани, а не переключается на беседки.
- Пауза клиента `позже напишу/подумаю/пока хз` должна сохранять черновик и не добавлять следующий вопрос анкеты.
- Конкретный выбор беседки без гостей теперь должен сначала спрашивать гостей; номер беседки не должен ошибочно становиться временем.
- Вопросы о ценах допов во множественном виде должны отвечать прайсом сразу и не должны попадать в `client_name`.
- Подтверждение с опечаткой `дя` должно закрывать confirm-flow.
- Сообщение после отмены/закрытия брони не должно писать "бронь зафиксирована".
- Диапазон гостей `15-17 человек/гостей/чел` не должен парситься как время `15:00-17:00`; для вместимости используется верхняя граница.
- Фразы `в 3 часа дня`, `к 3 дня`, `в 3 чиса дня` должны распознаваться как `15:00`, а `до 11 ночи` в дневном контексте - как `23:00`.
- Для компаний `20+` гостей в списке подходящих свободных беседок первой должна идти `Беседка №1`, если она свободна.
- Availability-cache должен очищаться после YCLIENTS sync, создания и удаления записей, чтобы бот не предлагал устаревшие свободные места.
- Просроченный hold после 10 минут должен освобождать слот и уведомлять клиента; поздняя оплата по старой ссылке не должна автоматически создавать бронь.
- Повторное подтверждение активного резерва должно переиспользовать существующую платежную ссылку, а не создавать новую.
- YCLIENTS cleanup должен начинаться с dry-run и удалять только bot-created/Telegram-created тестовые записи по явным признакам.
- Возврат к беседке после недоступного дома не должен стартовать новую/вторую бронь, если клиент явно продолжает текущий черновик; дата, гости и выбранный вариант должны сохраняться.
- Разговорные опечатки выбора первой беседки (`перую`, `перву`, `первой`) должны распознаваться в контексте выбора беседки.
- Вопрос о текущей "первой брони" до оплаты должен показывать черновик заявки, а не выдумывать оформленную бронь.
- Недоступность гостевого дома на дату должна предлагать подходящие свободные альтернативы на эту же дату, а не только ставить waitlist.
- Живой первый отказ от допов `ну нет/да нет` должен запускать второй upsell-заход, а не сразу закрывать допы.
- Вопрос о стоимости дополнительных часов в контексте беседки должен отвечать по правилам беседок, а не подставлять цену гостевого дома.
- Шаблон подтверждения заявки должен оставаться читаемым и явно спрашивать `Подтверждаете бронь?`.
- `duration` из AI/анкеты больше не должен сохраняться строкой вроде `8 часов`: нормализация приводит значение к числу часов перед сохранением и форматированием.
- Фраза `после обеда, к 3 дня и до 11 ночи` должна распознаваться как `15:00` и длительность `8`.
- Mixed upsell-сообщение `а вода и лед сколько стоят? если можно, добавьте воду и лед` должно отвечать по цене, сохранять `вода`/`лёд` в допы и переходить к следующему шагу.
- Info-вопросы про детей/парковку/животных должны отвечать из `client_runtime.md`; если точного правила по животным нет, бот не должен обещать.
- Добавлен `scripts/yclients_sync_status.py`: диагностика показывает `last_success_at`, возраст sync, `records_seen`, `records_upserted`, `last_error`.
- Cancel-flow execution вынесен из `message_handler.py` через callbacks; отмена одной/нескольких броней, правило аванса, `дя`, handoff на ошибке удаления YCLIENTS и post-cancel ack покрыты regression/stress.
- Grouped/swap reschedule execution вынесен из `message_handler.py` через callbacks; перенос нескольких броней и swap-flow покрыты `reschedule` regression.
- Availability reply layer вынесен в `availability_flow.py`; ответы по свободности, no-availability, waitlist, альтернативам на недоступную дату и ближайшим свободным датам покрыты `gazebo/services/fresh` и stress-suite.
- Confirmation-flow вынесен в `confirmation_flow.py`: reserved hold commands, expired hold reply, pending payment reuse, hold summary, awaiting-confirmation execution, confirmation side reply и create-hold wrappers покрыты `payments/post_booking/cancel/reschedule`, `fresh/gazebo/prices/upsell` и stress-suite.
- Post-booking classifier больше не должен перехватывать явную новую бронь: `а можно еще беседку забронировать?` стартует новую анкету до post-booking AI.
- Фразы переноса с `смест...` больше не должны стартовать новую бронь из-за названия услуги.
- Info-вопрос без активной анкеты с названием услуги (`веник в баню`, `комары`, `адрес/парковка`) не должен стартовать бронирование; deterministic info short-circuit отвечает без вопроса анкеты.

## Проверено 2026-05-27 после восстановления БД

- `scripts/dialog_stress_suite.py` - 12/12 OK.
- `scripts/local_regression_suite.py --group gazebo --group upsell --group prices --group cancel --group post_booking --group services --group reschedule --group fresh` - все checks OK.
- `python -m compileall app scripts` - OK.
- Полный grouped suite `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - все checks OK после фиксов парсинга, availability-cache и hold-flow.
- 2026-05-27 поздний прогон после фиксов памяти черновика: `compileall app scripts` - OK; полный grouped suite `fresh+dates+gazebo+media+prices+upsell+time+payments+post_booking+services+waitlist+handoff+reminder+cancel+reschedule` - OK; `scripts/dialog_stress_suite.py` - 12/12 OK.
- 2026-05-27 вечерний прогон после фиксов duration/mixed-upsell/sync-status: `compileall app scripts` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; `local_regression_suite.py --group time --group upsell --group prices` - OK; `local_regression_suite.py --group gazebo --group services --group post_booking --group cancel --group reschedule --group fresh --group payments` - OK; `scripts/yclients_sync_status.py --strict` - OK после ручного `sync_yclients_records.py --once`.
- 2026-05-28 после выноса grouped/swap reschedule execution и availability-flow: `compileall app scripts` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; `local_regression_suite.py --group fresh --group gazebo --group services --group prices --group upsell --group reschedule` - OK; `local_regression_suite.py --group post_booking --group payments --group cancel` - OK.
- 2026-05-28 после выноса confirmation/hold layer: `compileall app scripts` - OK; `local_regression_suite.py --group payments --group post_booking --group cancel` - OK; `local_regression_suite.py --group cancel --group reschedule` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; `local_regression_suite.py --group fresh --group gazebo --group services --group prices --group upsell` - OK.
- 2026-05-28 после выноса awaiting-confirmation execution: `compileall app scripts` - OK; `local_regression_suite.py --group payments --group post_booking --group cancel` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; `local_regression_suite.py --group reschedule` - OK; `local_regression_suite.py --group fresh --group gazebo --group prices --group upsell` - OK.
- 2026-05-28 после дополнительного разреза swap-reschedule orchestration, reschedule gazebo-change options и общего availability executor: `compileall app scripts` - OK; `local_regression_suite.py --group reschedule` - OK; `local_regression_suite.py --group fresh --group gazebo --group waitlist --group services` - OK; `local_regression_suite.py --group prices --group upsell --group payments --group post_booking --group cancel --group reschedule` - OK; `scripts/dialog_stress_suite.py` - 13/13 OK; `local_regression_suite.py --group dates --group media --group time --group handoff --group reminder` - OK.
- `load_knowledge()` доступен: загружает `client_runtime.md`, в базе найдены ключевые факты про комаров/обработку, веники/штраф, предоплату, допы, парковку и адрес.
- YCLIENTS cleanup dry-run после удаления тестовых Telegram-записей показывает 0 bot-created кандидатов; локальный sync после чистки: `records_seen=121`, `last_error=None`.
- В логах тестов остались наблюдения по скорости: отдельные AI-ветки занимают 4-7 секунд, но функционально сценарии прошли.

## Что проверять при каждом большом изменении

- Нет ли циклов в cancel/reschedule.
- Не предлагает ли бот занятые или неподходящие по вместимости беседки.
- Не отправляет ли фото слишком часто.
- Не теряются ли `upsell_items`.
- Не появляются ли слова про администратора в клиентских шаблонах без необходимости.

## Обновление 2026-05-26

- Риск `message_handler.py` снижен частично: вынесены `formatting`, `price_info`, `stale_form`, `routing_guards`, `booking_texts`, `handoff`.
- Закрыт свежий риск наследования старых полей при простой новой заявке: фраза вроде "хочу баню" поверх старой анкеты с беседкой теперь сбрасывает дату, время, гостей, формат и допы, сохраняя имя и телефон.
- Сводка активных броней теперь выделена в `booking_context.py`; при изменениях в YCLIENTS-синке нужно отдельно проверять, что `journal_missing`/удаленные записи не попадают клиенту.
- Основной оставшийся риск: сами сценарии `post_booking`, `cancel`, `reschedule`, `availability` еще находятся внутри `message_handler.py`; при следующем разрезе нужны точечные регрессии по переносам и отменам.
- `local_regression_suite.py` теперь поддерживает групповой запуск и печатает прогресс после каждого check. Следующее улучшение тестовой инфраструктуры: per-test timeout и, возможно, профилирование самых долгих групп.
- Закрыт риск semantic reschedule: post-booking AI `change_type=reschedule` больше не проигрывает fresh-start логике, когда в тексте есть название услуги.
- Cancel-flow частично вынесен из `message_handler.py`; следующий риск рядом - переносы всё ещё находятся в большом координаторе и требуют аккуратного выноса отдельным модулем.
- Группа `reschedule` может быть слишком долгой для автоматического tool timeout; все сценарии прошли точечно, но suite нужно оптимизировать по fixture/cleanup.
- Semantic-router ускорен компактным context, но качество нужно проверять на живых свободных формулировках: модель должна понимать смысл, а backend валидировать состояние и БД.
# 2026-05-27 production-hardening status

- Закрыто: риск двойного active hold закрыт DB-индексом, advisory lock и regression `concurrent active hold conflict`.
- Закрыто частично: риск рассинхронизации ЮKassa снижен payment-intent flow; локальный pending коммитится до provider-call.
- Закрыто: YCLIENTS fetch больше не держит DB transaction вокруг сетевого запроса.
- Закрыто: raw messages сжимаются после 48 часов; regression проверяет summary и удаление старых raw messages.
- Остаточный риск: AI semantic в отдельных stress-сценариях может занимать 30+ секунд; нужна дальнейшая оптимизация router prompt/модели и deterministic маршрутов.
- Остаточный риск: YooKassa webhook для production все еще требует reverse proxy/HTTPS и серверные лимиты; application-level secret и body-size limit уже добавлены.
- Остаточный риск: `message_handler.py` остается крупным координатором; следующий разрез - `post_booking_flow`, затем `reschedule_flow`/`availability_flow`.
