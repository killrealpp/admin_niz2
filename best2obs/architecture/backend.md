# Backend

## 2026-06-02 info-flow, payment TTL and unpaid-hold correction

- `app/services/dialog/info_flow.py` is the Phase 3 extraction from `message_handler.py`. It owns deterministic/common info detection and replies, active-booking reference info, info-during-form composition, `reply_already_asks()` and "append next question after info" decisions. `message_handler.py` keeps wrappers and callback builders so existing call sites remain stable.
- Reserve TTL is now settings-driven and defaults to 30 minutes. Client-facing payment/reserve texts read `settings.hold_ttl_minutes`; payment confirmation copy also states that the advance payment is refundable when cancellation happens no later than 7 days before the booking date.
- Unpaid reserved hold corrections are separate from paid reschedule. When the client changes date/time/duration while there is exactly one active unpaid hold, the handler cancels the old hold, supersedes old pending payments, rechecks availability, creates a new hold and sends a new payment link.
- `payments.status='superseded'` is a local safety state for obsolete pending links. A late paid status/webhook for a superseded link can be recorded for manual review/admin notification, but it does not automatically finalize a booking for the old slot.
- `payment_status_runner` can auto-resend payment links for active holds: at roughly 10 and 20 minutes after the last pending link, while the hold is still alive. It creates a fresh payment intent, sends the client the new link, and only then marks the previous pending payment superseded.
- Time parsing now keeps PM context for phrases like `4 или 5 вечера`, rejects guest-count ranges as time, and supports "until midnight" corrections (`до 12 ночи`) relative to an existing start time.

## 2026-06-02 message_handler fresh/stale/new-booking flow

- `app/services/dialog/new_booking_flow.py` owns the behavior-preserving decision layer for old unfinished drafts, stale-form choice, explicit new booking in the same message, fresh starts over active/reserved/payment context, and AI-assisted fresh-start reset.
- The module exposes `NewBookingFlowCallbacks` and `NewBookingFlowResult`. Results always carry `reply`, `status`, `intent`, `current_step`, `next_step`, `form_data`; when `reply is None`, `message_handler.handle_incoming()` applies the returned conversation context and continues routing.
- Side effects stay in `message_handler.py`: assistant message writes, `conversations_repo.update_after_message()`, DB commits, payment/YCLIENTS operations and callback execution are not moved into the flow module.
- Stale reset that starts a new context uses the current-message fresh form builder, so `нет` plus a new bathhouse/gazebo request keeps the service and lets downstream routing parse date/time/duration from the same user message.
- `scripts/dialog_stress_suite.py` expectations for positive upsell selection now match the established upsell flow: selected addons are saved, the bot remains on `upsell_items`, and the form advances only after the client says no more addons.

## 2026-06-02 message_handler commit/result boundary

- `message_handler.handle_incoming()` now has a single assistant-response persistence boundary. `_commit_assistant_response()` writes the assistant message, optionally runs a `before_update` callback, then calls `conversations_repo.update_after_message()` with status/intent/current step/next step/form data.
- Inside `handle_incoming`, the local `commit_reply()` closure binds the current `conn`, `conversation` and `now`, so early routing branches return through one short helper call instead of repeating repository writes.
- The refactor is behavior-preserving: routing order is unchanged, user-message insertion stays direct, seed/stale context-only updates stay direct, and the final AI/fallback path keeps `_persist_user_profile()` between assistant message creation and conversation update.
- This is Phase 1 of [[roadmap/large-file-decomposition-plan]]. It prepares later extraction of fresh/stale, info, reference and media flows without introducing a new external API.

## 2026-06-01 live 19:09 post-booking, media and confirmation guards

- Post-booking service-list replies now resolve the current service from `active_user_bookings()` first. This protects conversations where `form_data.service_type` is stale, for example still says `bathhouse` after the actual paid booking is a gazebo. The user-facing answer becomes `Кроме вашей беседки...`; `form_data` is only a fallback when no active booking identifies a single service.
- `intent == "current_booking_question"` is DB-first. Once the post-booking classifier says the user is asking about current bookings, `message_handler` returns `_post_booking_summary()` from active bookings/holds and no longer trusts AI `reply_to_user` for the final text. This is the canonical boundary for "what bookings do I have?" questions.
- Explicit media routing recognizes general gazebo photo requests without a number (`а беседки покажете?`, `фото беседок`, `как выглядят беседки`) and returns a reply naming concrete gazebo variants. `media_for_client_message()` can then select the real `besedka*.jpg` files instead of relying on a generic phrase.
- On `awaiting_confirmation`, live abort phrases such as `я перехотел, давай нет` are treated as cancellation of an uncreated draft, not as an edit request or paid-booking cancel. The handler reuses `_abort_current_draft()`: slot fields are cleared, contact is preserved, and the next step is `service_type`.

## 2026-06-01 post-booking current-booking fallback

- `app/services/dialog/booking_context.py::active_user_bookings()` remains the shared source for current/future active bookings in post-booking summary, cancel and reschedule flows.
- The function first asks `bookings_repo.list_future_active_for_user()` and applies `filter_actual_journal_bookings()` against local YCLIENTS/cache state. It now also merges paid bookings from the current conversation when they are local active records in `created_in_yclients` or `journal_missing`.
- This fallback is intentionally limited to the current conversation and paid local bookings. It prevents a temporary stale/missing YCLIENTS-cache row from hiding a paid booking from the client, while still excluding cancelled records and unpaid drafts/holds.
- After a successful cancellation, `post_booking_flow.plain_ack_after_closed_booking()` handles `ок` and `окей` deterministically, so the bot does not ask AI to answer a closed paid conversation and does not say the cancelled booking is still fixed.

## 2026-06-01 state/text consistency hardening

- `message_handler.handle_incoming()` now runs a semantic preflight AI pass for active client dialogs before deterministic branches. The result is reused by the later main AI branch, so active form, upsell, confirmation side-question, cancel-flow and post-booking texts all get one semantic `AIResponse` understanding layer. If the provider is unavailable, the path logs `system_logs.event_type='ai_semantic_degraded'` and continues through the existing safe fallback/deterministic behavior.
- `message_handler._state_text_consistency_reply()` is a narrow canonical-state guard before the final assistant commit. It rebuilds replies from canonical state when text claims `кальян` was added without `form_data.upsell_items=["кальян"]`, or when a confirmation summary says `Допы: не нужны` while state has a different addon list. Rebuilds are logged as `state_text_consistency_rebuilt`.
- `form_patches.upsell_items_patch()` recognizes more live hookah phrasing and keep/remove patterns: `кальянчик`, `кальяна`, `калик один`, `ничего кроме кальяна`, `уберите все`, `уберите все, кальян оставьте`. Contextual `добавьте` after an upsell prompt is treated as an accept of the offered item set.
- Cancel-flow keeps refund side effects behind successful YCLIENTS deletion and local cancellation. Refund eligibility is `>= 7` calendar days; only paid refundable bookings produce `refund_required`, including partial multi-booking cancels. `payment_status_runner.notify_admin_about_refund_requests()` drains all pending refund logs in batches and marks each `admin_notified_at`.
- `scripts/live_db_hygiene_audit.py` is a read-only operational audit for regression aftermath: orphan active `bot_booking` intervals, refundable paid/cancelled bookings without refund logs, paid payments without client notification marker, regression waitlist leftovers, and unnotified refund logs.

## 2026-06-01 addon aliases and refundable cancel admin events

- `form_patches.upsell_items_patch()` treats common spoken aliases for hookah (`калик`, `калян`, `калиан`) as the canonical addon `кальян`. This keeps addon state deterministic even when AI wording says "добавлен"; the form state, confirmation summary and later booking/YCLIENTS comment all read from `upsell_items`.
- Cancel-flow now has a backend event boundary for refundable paid cancellations. If an already paid booking is cancelled and `advance_refund_allowed()` is true, the flow calls a callback that writes `system_logs.event_type='refund_required'` with booking id, client name, phone, booking summary and payment status.
- `payment_status_runner` polls these `refund_required` logs alongside other admin tasks, sends the admin chat a direct "Требуется вернуть предоплату клиенту" message, and marks `system_logs.admin_notified_at` after successful delivery. This keeps client-facing cancellation text separate from backoffice refund work.
- Duplicate refund logs are guarded by `booking_id` in the payload, so repeated cancel handling for the same booking should not spam the admin channel.

## 2026-06-01 live dialog state guards for guests, addons and post-booking service context

- `message_handler._gazebo_guest_options_shortcut()` handles mixed guest-count + gazebo-selection questions before the generic upsell/form path. If the active draft is a gazebo, no variant is selected yet, and the message contains a guest-count signal such as `нас будет 30 человек`, backend stores `guests_count`, reuses known available variants, returns capacity-filtered gazebo options and moves the state to `service_variant` instead of asking guests again.
- `form_patches.upsell_items_patch()` now supports ordinal selections from the immediately shown addon price list: first/second/small mangal set, `№1/№2`, and clear price references for 500/1000 rubles. This keeps addon selection deterministic and avoids falling through to availability or repeating the upsell question.
- `message_handler._available_services_reply()` is service-aware. After a confirmed/paid gazebo it says `Кроме вашей беседки...`; only bathhouse context uses `Помимо бани...`. The function remains informational and does not start a new booking until the user names a service/date.
- These guards follow the project rule: AI can understand free text, but backend owns state transitions for fields already requested by the form and for post-booking context that depends on local bookings/form data.

## 2026-06-01 best2info retrieval, prepayment modes and cleanup boundary

- `best2info/` remains the client-facing knowledge source, but runtime retrieval is now graph-aware. `knowledge_service` builds `KnowledgeDocument` entries with `rel_path`, content, headings and parsed `[[wikilinks]]`; scoring still uses normalized tokens/topic keywords/headings, then selected pages are expanded through one-hop outgoing and incoming links. `runtime.md` is always included.
- `best2info/index.md` is treated as the map of truth sources: prices for code come from `config/services_map.yaml`, availability comes from local DB tables (`yclients_records`, `resource_busy_intervals`, active holds/bookings), facts for natural-language answers come from `best2info`, and YCLIENTS is the external journal/source for sync.
- `scripts/lint_best2info.py` is the maintenance guard for the client wiki: broken links, orphan pages, gazebo base/discount prices, fixed service package prices and "fact without exact price" notes are checked before manual Telegram smoke.
- Prepayment now has an explicit mode boundary. Fixed mode uses `PREPAYMENT_AMOUNT_RUB` per booking/hold and is used locally for safe 1-ruble tests. Percent mode uses `PREPAYMENT_PERCENT` against the main service/package price from `services_map`; gazebo ПН-ЧТ discount is included, addons are excluded from advance payment.
- Payment link creation passes booking/hold base prices into `calculate_prepayment_amount()` only when percent mode is active. Unknown base price in percent mode raises a payment error instead of silently creating an incorrect payment.
- The 2026-06-01 bathhouse cleanup was operational DB repair, not a schema or production-flow change: failed local test booking `#1` is archived as `cancelled`, its `bot_booking` busy interval is removed, payment history remains, and a `system_logs` event records the repair.
- Regression tests that exercise waitlist notifications must isolate their own waitlist rows. The 2026-06-01 fix stubs `waitlist_repo.list_active_due` inside the test so live waitlist requests are not marked `notified` by local regression runs.

## 2026-05-31 pre-live fallback/proxy guards

- Capacity validation is now centralized in `message_handler._capacity_mismatch_reply()`: after form patches are applied, normal and exception/fallback paths run gazebo capacity first and bathhouse capacity second. This keeps fallback behavior aligned with the AI/normal path.
- Bathhouse over-capacity remains a backend state rule: if `service_type=bathhouse` and `guests_count > 15`, the handler clears only `guests_count`, keeps the rest of the draft, and asks for manual clarification/alternative instead of advancing to `event_format`.
- HTTP outbound clients use explicit trust-env policy. `Settings.http_trust_env` defaults to `False` (`HTTP_TRUST_ENV=false`), and OpenAI/OpenRouter, YCLIENTS, YooKassa and voice transcription pass it into `DefaultHttpxClient`/`httpx.Client`. This prevents a machine-level unsupported `socks4` proxy from silently breaking AI/sync/payment calls.
- Guest-count parsing now treats explicit gazebo variant references (`Беседка №2`, `номер 2`, `№2`) as object selection, not as an expected-step guest count, unless the text also has an explicit guest marker.

## 2026-05-30 waitlist and confirmation safety guards

- Waitlist remains on the existing `waitlist_requests` table. `yclients_sync_runner` can still call `notify_waitlist_matches`, but notification now passes a relevance gate first: request is active, date is not past, the client has no matching active booking/payment or active hold, recent user messages do not say the request is irrelevant, and availability is freshly confirmed after sync.
- Obsolete waitlist requests are closed as `closed`; sent notifications are marked `notified`. The bot text is normal UTF-8 Russian and does not create a new schema/table.
- Bathhouse capacity is a backend validation, not an AI prompt convention: `availability_service` blocks `bathhouse` drafts above 15 guests, and both availability/confirmation flows clear only `guests_count` and return to that step instead of creating hold/payment.
- Day-only references (`30 число`, `на 30`, `на 30-е`) use the freshest local date context from current `form_data.date` or `last_unavailable.date` when there is no explicit month. This protects follow-ups after a June discussion from falling back to the current month.
- `awaiting_confirmation` treats bare negative replies as refusal to confirm before correction patches. Only explicit addon-correction wording can change `upsell_items` at that stage.
- Neutral acknowledgements after info-answers on the upsell step do not select addons. Addons require semantic positive selection or the existing two-touch negative flow.

## 2026-05-30 live-30.05 context and availability guards

- Price routing is semantic-first when AI classifies `intent=price_question`: backend computes the price from `services_map` and the current draft, even if the user did not use exact words like `цена/стоить/сколько`. Deterministic price markers remain a fast path, not the only way to understand price intent.
- Common-info for children no longer uses broad substring `дет`; it uses word-form matching so words like `будет` cannot trigger a children-policy answer.
- Upsell replies now pass through `form_patches.classify_upsell_reply()`: `negative`, `final_negative`, `positive_selection`, `price_question`, `unclear`. First semantic negative on `upsell_items` increments `upsell_offer_count` and sends the soft second offer; a repeated/final negative writes `upsell_items=["не нужны"]` and advances by `next_question()`.
- Fixed-package services (`bathhouse`, `house`) validate selected start times against live YCLIENTS `book_times` before local hold/payment creation. Local busy intervals still matter, but a start missing from `book_times` is treated as unavailable and the bot shows available starts instead.
- If YCLIENTS `book_times` is unavailable for those fixed services, availability returns a safe non-free response rather than claiming the slot is free.
- Media selection for booking summaries now resolves gazebo photos from `service_variant`, `hold_yclients_service_id`, `yclients_service_id`, and booking-list text. This lets summaries with both `Беседка №1` and `Баня` send both images.

## 2026-05-29 live-19:02 subsequent booking boundary

- Generic new-booking detection now treats `отдельной/отдельную бронью`, `добавить отдельной` and typo `добвить отдельной` as a request to start a separate booking when a `last_discussed_service_type` exists.
- Service-exists/info routing is intentionally narrower: it answers `есть/какие варианты` questions, but does not intercept booking requests that contain date/time/same-reference or explicit additional-booking wording.
- `а какие беседки есть` can set `form_data.last_discussed_service_type="gazebo"` without changing the active draft service. A follow-up like `хочу добвить отдельной бронью` then creates a clean gazebo draft through the normal new-booking policy and preserves only contact fields.
- Post-booking common info such as mosquitoes bypasses the AI post-booking classifier and uses deterministic `price_info.policy_or_common_info_reply`, preventing invented answers.
- Bathhouse wording is aligned with `config/services_map.yaml`: not arbitrary hourly rental, but fixed YCLIENTS packages of 3, 4, 5, 6 or 7 hours.

## 2026-05-29 message_handler refactor direction

- `app/services/message_handler.py` остаётся production-координатором, но его нужно дальше уменьшать только безопасными behavior-preserving разрезами.
- Текущая проблема не в одном конкретном helper-е, а в смешении уровней: `handle_incoming` одновременно выбирает route, применяет patches, вызывает flow, пишет assistant message и обновляет conversation state.
- Целевая форма: handler загружает user/conversation/history, собирает контекст, вызывает flow по явному приоритету и одним общим helper-ом сохраняет `FlowResult`.
- Следующие безопасные разрезы зафиксированы в [[roadmap/message-handler-refactor]]: единый commit/result helper, stale/new-booking flow, info-flow, same-reference/unavailable UX и затем явный route table.
- Ключевое ограничение: AI остаётся semantic layer, backend остаётся state validator. Рефакторинг не должен превращать понимание клиента в набор одноразовых keyword-костылей.

## 2026-05-29 best3 core parity architecture

- `best3` сохраняет agent-first контракт: AI выбирает `intent/action/draft_patch`, но backend валидирует patch и выполняет только safe tools. Слоты, оплата, hold, booking и YCLIENTS остаются backend-источником правды.
- Core-parity с `best2` перенесён не через копирование веток `message_handler.py`, а через компактные правила: natural parsing, state-safe patch, service switch cleanup, info+patch, payment/current-booking routing и active/expired hold guards.
- `answer_info` в `best3` теперь может сначала безопасно применить `draft_patch`, а потом ответить из `best2info`; это закрывает mixed cases вроде `хочу беседку, а с детьми можно?`.
- Смена услуги очищает slot-поля старой заявки (`service_variant`, date/time/duration, guests, format, upsells, metadata hold), сохраняя контактные поля. Это переносит best2-правило `а я же хочу баньку` в чистый tool-layer.
- Payment/hold safety: повторная ссылка переиспользует pending payment; истёкший hold не конвертируется поздней оплатой; `get_payment_status` отвечает по `best3_payments/best3_bookings`, а не по тексту агента.

## 2026-05-29 live-1953 dialog guards

- Post-booking info about bathhouse is now deterministic before the AI post-booking classifier: backend says only that there is a bathhouse with pool, it is a separate booking, and it is not added to a gazebo as an addon.
- When a deterministic post-booking info answer mentions a service, `form_data.last_discussed_service_type` can store that service. Follow-ups like `а ее как бронировать нужно?` and generic phrases like `давайте начнем новую заявку` may use it to answer/start the intended service, but a new draft is still created through fresh-booking policy and keeps only contact fields.
- Service correction phrases like `а я же хочу баньку` are treated as a clean service switch/new draft, not as continuation of the old gazebo draft. Date, time, duration, guests, event format and upsells are cleared.
- Confirmation completion is guarded by a regression: after phone finishes a complete draft, the first reply is canonical confirmation and the next `да` creates hold/payment instead of sending a second confirmation summary.
- Paid notification text includes `booking_line_short()` lines, so the client sees date/time of the journal record in the final payment confirmation.

## 2026-05-29 live-14:29 stale/fixed-duration guards

- Stale-form protection now distinguishes "resume old draft?" from a detailed new booking request. If a message contains a new service plus concrete date/time/duration signals, the coordinator starts a clean draft through the existing new-booking policy and preserves only contact fields.
- If the user answers the stale checkpoint with `нет/не` and continues with a detailed new request in the same message, that same message is processed as the new request. The bot should not ask a second meta-question when the booking details are already present.
- Upsell refusal uses the two-touch policy: the first short/semantic refusal like `не`, `нет`, `неа`, `ничего` triggers one soft second offer; the repeated/final refusal writes `upsell_items=["не нужны"]`, then the normal `next_question()` decides the next field.
- Confirmation yes detection accepts soft affirmative forms such as `ну вроде да`, `вроде да`, `да вроде`, while still keeping non-confirmation side questions in confirmation-flow.
- `availability_service.check_availability()` validates fixed-duration services before selecting slots. If service variants define `duration_minutes`, the requested duration must match one of the allowed blocks for that weekday. Invalid duration returns a validation message instead of a slot.
- Availability/confirmation flows treat that validation message as a field error: they clear only `duration`, keep date/time/service/contact, set `current_step=duration`, and ask the client to choose one of the allowed blocks. This prevents local hold/payment creation for bathhouse durations that YCLIENTS will reject later.

## 2026-05-29 live-13:07 hold/time/payment guards

- Explicit time periods now have a backend guard: if the client writes a concrete range like `с 9 утра до 21 ночи`, `time_period_patch()`/`has_explicit_time_period()` wins over an AI duration guess that may appear because the same message also asks `можно на дольше остаться?`.
- Reserved-hold payment status handling separates real payment questions from fake/simulation requests. Phrases like `сделай будто бы я оплатил` return a safe refusal and keep the hold in `reserved`; they do not call the normal "оплата получена" route.
- Short upsell markers such as `лед` are matched by word boundaries in `form_patches`, so typos around `следующая заявка` cannot update addons accidentally.
- Generic next-booking phrases during an active hold can start a clean next draft even when the user has not yet named the service. The fresh draft preserves contact fields and clears service/date/time/duration/guests/format/upsells.

## 2026-05-28 live payment and concurrency hardening

- Telegram text/voice updates are now serialized per `channel:external_user_id` in `app/bot/telegram_bot.py`. The process can still handle different users concurrently, but two fast messages from one client cannot run two `handle_incoming` threads against the same conversation state at the same time.
- `awaiting_confirmation` has priority over fresh-start/new-booking detection. Info questions about the currently selected object, for example `а это хорошая беседка?`, stay in confirmation-flow and do not start a second booking.
- For gazebos, `next_question()` asks `guests_count` before `service_variant` when both are missing. This keeps the product rule explicit: the backend cannot recommend a gazebo as suitable until capacity is known.
- Upsell has contextual confirmation after the one-time soft push. If the bot offers a small mangal/basic set and the client replies with a vague acceptance like `ну давайте`, backend maps that acceptance to the offered set and advances to the next validated booking step.
- Paid booking finalization carries `slot_holds.yclients_service_id` and `slot_holds.yclients_staff_id` into booking/YCLIENTS helpers. Local bot busy intervals are deleted/reinserted for the booking source id before upsert, so a stale interval on the wrong gazebo resource cannot remain after repair.
- `create_missing_yclients_records()` now retries transient YCLIENTS create failures for paid bookings after 30 seconds instead of waiting 5 minutes. While the journal record is not ready, `payment_status_runner` can send one intermediate client notification that payment was received and the journal record is being закреплена; final paid notification still waits for `yclients_record_id`.

## 2026-05-28 structural AI field validation

- Semantic-router остается первым слоем понимания смысла: он может вернуть `form_data_patch` даже без явных слов-маркеров. Backend не должен превращать список слов (`чел/гостей/нас будет`) в главный route trigger.
- Для state-changing fields теперь действует structural validation: AI-only `guests_count` принимается, если он не конфликтует с текущим сообщением и шагом анкеты; отклоняется, если совпадает с числом даты (`на 30 июня` -> 30) или номером выбранной беседки (`6 беседка` -> 6), когда это поле не подтверждено текущим шагом `guests_count` или deterministic parser.
- Это сохраняет принцип "AI понимает, backend валидирует": `на 30 июня двадцать` может стать `date=2026-06-30, guests_count=20` по AI-смыслу, но `на 30 июня` не может стать `guests_count=30`.
- Тестовый слой закрепляет это через `scripts/dialog_context_suite.py`: context-suite теперь проверяет date-only poison, AI semantic guest without keyword, variant-number poison, сохранение даты при вопросе выбора и recovery после жалобы клиента.

## 2026-05-28 sequential multi-booking and clear overnight ranges

- Явный запрос `2/две беседки` с несколькими датами обрабатывается deterministic route до обычного info short-circuit: backend создаёт текущий черновик первой заявки и сохраняет остальные даты в `form_data.pending_additional_bookings`. Клиенту объясняется правило: одновременно две анкеты не заполняются, брони оформляются по очереди, чтобы не смешать дату, время, гостей и допы.
- Если клиент во время первой заявки пишет дату из `pending_additional_bookings`, backend не применяет её как patch к текущей заявке. Вместо этого бот напоминает, что эта дата запомнена для следующей брони, и возвращает клиента к текущему `current_step`/`next_step`.
- Ночные интервалы форматируются единообразно через `format_time_duration_range`: `time=11:00`, `duration=21` показываются клиенту как `с 11:00 до 08:00 следующего дня (21 час)`. Этот формат используется в confirmation, draft summary, active booking summary, hold summary, stale-form summary и availability replies.
- Gazebo option formatting теперь учитывает буднюю скидку: при известной дате ПН-ЧТ строки вариантов показывают базовую цену и цену со скидкой 50%. Обычный price-route для выбранной беседки на будний день использует тот же расчёт, а explicit discount-route остаётся отдельным knowledge-backed ответом.
- `awaiting_confirmation` correction имеет приоритет над reserved-hold glue: изменение времени/даты/варианта до создания hold остаётся в confirmation-flow. Reserved-hold handler больше не отвечает `не вижу активной предварительной заявки` для draft без active hold.

## 2026-05-28 context-first availability routing

- Сообщения, где клиент в одном тексте дает дату и гостей (`на 30 июня нас будет 20`), не должны использовать cached gazebo-selection до проверки локальной availability БД. Backend сначала применяет state-safe patch, очищает устаревшие `last_suggested_free_dates`, вызывает общий availability executor и только после этого показывает подходящие варианты.
- Date-only сообщения (`на 30 июня`) не могут заполнять `guests_count` числом даты. Если AI возвращает `guests_count` из числа даты, backend отклоняет это поле структурно: по конфликту с day/month number, а не по отсутствию конкретного слова.
- Если AI классифицирует ответ текущего шага как `answer_info`, но backend принял валидное изменение анкеты (`date`, `guests_count`, `time`, `duration`, `service_variant` и т.п.), info-route не срабатывает. Такое сообщение продолжает обычный form/availability flow.
- Для беседок `guests_count` является availability-changing field при уже известной дате: изменение гостей перезапускает проверку локального журнала и фильтр вместимости.
- Для беседок дата без гостей переводит диалог на `guests_count`: backend может показать свободные варианты по журналу, но не закрепляет и не авто-выбирает беседку до проверки вместимости.
- Recovery guard для фраз вроде `ты не спросил сколько человек` очищает ошибочно выбранный `service_variant`, `guests_count`, cached gazebo variants и возвращает клиента на шаг `guests_count`.
- Для беседок availability учитывает два слоя: свободность в журнале и вместимость. Если на выбранную дату свободны только маленькие беседки, ответ обязан явно сказать, что на эту дату варианты есть, но для указанного числа гостей не подходят, и предложить ближайшие подходящие даты.
- Поиск ближайших подходящих дат для уже выбранной недоступной даты идет вокруг выбранной даты, пропуская саму недоступную дату; общий запрос "когда свободно" по-прежнему ищет от текущей даты.
- На `awaiting_confirmation` summary/abort intent имеет приоритет над повторной availability-проверкой. Вопросы вида `что мы подтверждаем?` показывают draft-summary и сохраняют confirmation-state; `давай отменим эту заявку` очищает только черновик, не трогая оплаченные брони.
- `scripts/dialog_context_suite.py` теперь отдельный guard для связных контекстных сценариев и печатает user/bot transcript, чтобы ловить случаи, где бот "не помнит", что уже было сказано; на 2026-05-28 он покрывает 13 сценариев.

## 2026-05-28 best2info client knowledge routing

- `best2info/` введен как отдельная клиентская база знаний рядом с `best2obs/`. `best2obs` хранит память разработки, а `best2info` хранит факты, которые можно говорить клиенту: объекты, цены, допы, оплата, скидки, локация и правила.
- `knowledge_service.load_knowledge()` теперь возвращает только короткий runtime-контекст для безопасного поведения ответа: не выдумывать, не обещать свободность без availability, задавать один следующий вопрос. Для клиентских info-вопросов используется `retrieve_client_knowledge(text, form_data)`, который выбирает релевантные markdown-разделы из `best2info`.
- Основной AI-pass остается semantic-router: он определяет смысл сообщения и возможный intent/action/patch. Финальные действия выполняет backend: `answer_info` получает только найденные chunks `best2info`, `check_availability` всегда идет через локальную availability БД/YCLIENTS-cache, а анкета применяет patch только если поле валидно для текущего шага или явно сказано клиентом.
- Info-route не должен проверять свободность и не должен сам менять дату/время/гостей. Availability-route не должен брать факты из knowledge base вместо БД. Это закрепляет правило: AI понимает смысл, backend валидирует состояние, БД/YCLIENTS-cache отвечает за свободность.
- Destructive/state-changing intents имеют ранний backend priority: отказ от незавершенной заявки, отмена активной брони, перенос и вопрос о текущих бронях должны обрабатываться до upsell, availability и AI-generated текста. Пример: `давай откажемся от брони` на шаге допов очищает черновик, сохраняет контакт и возвращает `service_type`.
- Парсинг варианта беседки стал date-safe: число из даты (`на 5 июня есть беседка`) не считается номером беседки без `№` или близкого слова `беседка`; переносная фраза `беседку на 8` поддерживается в корректном reschedule/selection контексте.
- Discount-aware ответы для беседок идут до обычного price reply: если известны дата и выбранная беседка, backend считает ПН-ЧТ скидку 50% и показывает базовую/скидочную цену; если данных не хватает, отвечает общим правилом из `best2info/rules/discounts.md`.

## 2026-05-28 edge-dialog routing hardening

- Для активной анкеты и `awaiting_confirmation` summary-вопросы вида `что мы сейчас бронируем/подтверждаем` обрабатываются deterministic draft-summary: backend показывает текущий `form_data` и оставляет правильный шаг, вместо ухода в AI или reserved-hold glue.
- На `awaiting_confirmation` команда отмены еще не созданной брони (`отмени бронь, не будем`) трактуется как abort текущей заявки: очищаются slot-поля, сохраняются имя/телефон, состояние возвращается к `service_type`.
- Внутри `cancel_flow` информационные вопросы не подтверждают и не сбрасывают отмену. Вопросы про аванс/возврат используют те же cancel-тексты с 7-дневным правилом; другие известные info-вопросы отвечают из deterministic knowledge и возвращают клиента к `да/нет`.
- Отказ `нет, оставь` считается отрицательным подтверждением для cancel-flow и очищает `cancel_flow`, после чего клиент может сразу начать перенос.
- Post-booking classifier теперь отдельно различает вопросы не по теме базы отдыха/брони: отвечает коротко, не предлагает допы и не меняет бронь. Это сохраняет принцип: AI может сформулировать ответ, но backend не меняет состояние без валидного намерения.
- Новый `scripts/dialog_edge_suite.py` покрывает 12 необычных перебиваний: summary/off-topic во время анкеты, phone+info, summary/info/cancel во время подтверждения, info/off-topic/no-then-reschedule в cancel-flow, info/options в reschedule-flow и off-topic post-booking.

## 2026-05-28 current-request summary and soft handoff update

- Для вопросов о текущей/предыдущей заявке backend теперь использует порядок: активные bookings из локальной БД/YCLIENTS-cache, затем активные holds, затем draft-summary текущей анкеты. Если оформленной брони еще нет, бот не говорит только "активных броней нет", а показывает собираемую заявку и следующий недостающий шаг.
- Handoff разделен строже: разговорный мат и эмоциональная фраза сами по себе не являются конфликтом. Handoff нужен при жалобе, возврате денег, агрессии в адрес компании/бота, споре или явной просьбе подключить человека.
- Time guard в основном AI-flow принимает не только конкретное время/период, но и смысловую ссылку на прошлую бронь (`то же время`, `часы как там же`). В этом случае время и длительность подтягиваются из локальной активной брони, но текущая услуга новой анкеты не перезаписывается услугой старой брони.
- Для сервисов с `require_duration_before_availability` длительность спрашивается только после известного времени. Это защищает от перехода `time -> duration`, когда клиент написал неопределенное `ну че нибудь` и AI попытался додумать слот.

## 2026-05-28 post-booking second booking context boundary

- После оплаченной активной брони post-booking/info вопросы не должны реанимировать старый confirmation-draft. Запрос `что еще можно забронировать` отвечает справкой по услугам и оставляет состояние `reserved/payment_status`.
- Явная новая бронь поверх старого `awaiting_confirmation` разрешена, если у клиента уже есть активная оплаченная бронь. Новый draft создается через `new_booking_form_data`: сохраняются только контактные поля, а slot-поля, гости, формат, допы и вариант старой брони очищаются.
- Same-date reference поддерживает `то же число/на то же число` как ссылку на дату активной брони. Для новой услуги filter fresh-patch сохраняет только `date`, а same-time переносится только по явной ссылке на время (`то же время`, `часы как там же`), чтобы `на то же число` не тащило время/длительность.
- Cross-service info внутри активного draft сначала смотрит, не спрашивает ли клиент про другую активную услугу. Например, в draft бани вопрос про `беседку` ищет активную беседку пользователя, отвечает по ней и затем добавляет следующий вопрос текущей бани; `service_type` draft не меняется.
- Flow confirmations имеют приоритет над plain post-booking ack: `да/да да` в активном `cancel_flow/reschedule_flow/swap_reschedule_flow` доходит до своего flow handler. Cancel-flow на подтверждении доверяет `booking_id/booking_ids`, сохраненным в `form_data.cancel_flow`, даже если текущая сверка активных записей временно не вернула бронь.

## 2026-05-28 media_flow refactor slice

- Добавлен `app/services/dialog/media_flow.py`.
- В модуль вынесен explicit-photo reply: явные просьбы показать фото конкретной беседки, бани, гостевого дома или текущего выбранного варианта.
- `message_handler.py` оставляет wrapper `_explicit_photo_reply` и прокидывает `ExplicitPhotoCallbacks`, поэтому маршрутизация, parsers и проверка медиа через `media_service.media_for_client_message` остались прежними.
- AI-диалог не изменён: явный запрос фото по-прежнему deterministic и bypass AI, а обычный auto-media selection по availability-ответам остаётся в `app/services/media_service.py`.
- Проверено: `compileall`, `media/gazebo/dates`, `post_booking/payments/cancel/reschedule`, `dialog_stress_suite.py` 13/13.

## 2026-05-28 live-dialog routing fixes

- Direct free-dates lookup теперь учитывает явное `начнем новую`: старый `last_unavailable`/`awaiting_new_date` не должен сдвигать поиск ближайших дат, если клиент начинает новую анкету.
- Бюджетный подбор беседок без выбранной даты стал deterministic routing: backend может дать ориентир по цене и вместимости, но не называет варианты `свободными`, пока дата не проверена в локальном журнале.
- При mixed selection+info backend сначала применяет валидный state patch, например `Беседка №4`, затем отвечает на информационный вопрос и задаёт один следующий вопрос анкеты.
- Для `guests_count` явный `current_step`/`next_step` имеет приоритет над YAML-порядком полей, чтобы фразы вроде `я же говорил 10` не становились временем.
- Post-pause ack guard оставляет черновик на паузе и не повторяет upsell/form question после коротких реакций клиента.
- Test cleanup удаляет orphan `resource_busy_intervals.source='bot_booking'`, не связанные с локальными `bookings`, чтобы regression/live-подготовка не загрязняла локальную таблицу свободности.

## 2026-05-28 direct free-dates refactor slice

- Direct free-dates lookup вынесен из `message_handler.py` в `app/services/dialog/availability_flow.py`.
- Новый `DirectFreeDatesLookupCallbacks` сохраняет прежнюю схему: `message_handler.py` остаётся владельцем side-effect wiring, monkeypatch-friendly wrappers и текущих parsers, а availability-flow выполняет deterministic orchestration.
- Wrapper `_direct_free_dates_lookup` в `message_handler.py` сохранён, поэтому существующие вызовы и regression monkeypatch вокруг `_next_free_dates_reply` не меняются.
- Поведение осталось прежним: сервис определяется из текста, текущей анкеты или `last_unavailable`; stale-flow очищается; конкретная дата проверяется через локальную availability DB; ближайшие даты ищутся через существующий `_next_free_dates_reply`.
- Проверено: `compileall`, профильные `dates/gazebo/waitlist`, соседние `fresh/services/prices/upsell`, `post_booking/payments/cancel/reschedule`, `dialog_stress_suite.py` 13/13.

## 2026-05-27 reschedule_flow refactor slice

- Добавлен `app/services/dialog/reschedule_flow.py`.
- В модуль вынесены чистые helpers переноса: распознавание намерений переноса/обмена броней, тексты вариантов и подтверждений, парсинг multi/swap assignments, reference-фразы `то же время/та же дата`, выбор брони, сбор `form_data` для availability-check и фильтр вариантов беседок при переносе.
- Single reschedule execution также перенесён в модуль через `RescheduleExecutionCallbacks`: YCLIENTS delete/create, update booking/hold, busy interval upsert, restore old booking and handoff on unrecoverable failure.
- `message_handler.py` оставляет только тонкие wrappers там, где нужно сохранить текущую сигнатуру, например `_select_reschedule_booking(...)->...` добавляет текущий `_now_local()`.
- Grouped/swap execution переноса пока в координаторе: обмен/массовый перенос нескольких броней, rollback нескольких старых записей и финальный summary.
- После разреза обнаружена важная связь: `gazebo_capacity_by_title` нужен и обычному availability-flow, поэтому он импортируется из `reschedule_flow.py` обратно как shared helper.
- Защитные проверки после разреза: `compileall`, `reschedule`, `gazebo+reschedule`, `post_booking+cancel+payments+services`, `gazebo+post_booking+payments+cancel`, `dialog_stress_suite.py` 13/13.

## 2026-05-27 cancel-flow execution refactor slice

- `app/services/dialog/cancel_flow.py` теперь содержит не только чистые cancel helpers, но и execution-функции `start_cancel_booking_flow` / `handle_cancel_booking_flow`.
- Все внешние действия передаются через `CancelFlowCallbacks`: получение актуальных броней, чтение/отмена booking, удаление записи YCLIENTS, получение user, handoff и confirm-parsers.
- В `message_handler.py` сохранены wrappers `_start_cancel_booking_flow` / `_handle_cancel_booking_flow`, чтобы текущие вызовы, monkeypatch и tracing не ломались.
- Этот разрез behavior-preserving: AI-маршрутизация, тексты подтверждения отмены, правило аванса 7 дней, YCLIENTS deletion и handoff-сценарий оставлены прежними.
- Защитные проверки после разреза: `compileall`, `cancel`, `post_booking+payments+reschedule`, `dialog_stress_suite.py` 13/13.

## 2026-05-28 confirmation_flow refactor slice

- Добавлен `app/services/dialog/confirmation_flow.py`.
- В модуль вынесены безопасные части confirmation/hold layer: распознавание payment-status, cancel/change hold guards, side reply при финальном подтверждении, hold summary helpers, pending payment lookup, reserved hold command handler, create-hold и create-booking-from-hold.
- `handle_reserved_hold_command` работает через `ReservedHoldCallbacks`: координатор передает callbacks для active bookings, post-booking summary, start cancel/reschedule, correction patches, confirmation yes, date/service parsing, availability, payment-link creation и logging.
- Это сохраняет принцип: module содержит deterministic state/action logic, а `message_handler.py` владеет side-effect wiring, tracing wrappers и текущими monkeypatch-friendly entrypoints.
- `handle_awaiting_confirmation` теперь тоже в `confirmation_flow.py` через `AwaitingConfirmationCallbacks`: correction patch, yes/no, повторная availability-проверка, active hold conflict, 10-минутный hold, payment-link creation и side-question на подтверждении.
- `message_handler.py` оставляет только вызов flow, запись assistant message и update conversation state.
- Следующий безопасный шаг - media scheduling или дальнейшая расчистка glue-кода вокруг fresh-start/stale-form.

## 2026-05-28 reschedule/availability refactor slice

- Grouped/swap reschedule execution перенесен из `message_handler.py` в `app/services/dialog/reschedule_flow.py`.
- `message_handler.py` вызывает `execute_swap_reschedule` через `RescheduleExecutionCallbacks`, поэтому YCLIENTS delete/create, локальное обновление booking и restore при ошибке остаются явно прокинутыми callbacks.
- Добавлен `app/services/dialog/availability_flow.py`.
- В `availability_flow.py` вынесены deterministic availability replies, no-availability/waitlist replies, очистка активного слота, перенос предыдущего периода на новую дату, same-date unavailable reply, альтернативы на недоступную дату и nearest-free-dates reply.
- Availability-flow не ходит напрямую в YCLIENTS: он получает `check_availability` и `active_user_bookings` callbacks от координатора, а источник свободности остается локальная БД `yclients_records` / `resource_busy_intervals`.
- В `message_handler.py` после этого остаются main state machine, confirmation/payment orchestration, media scheduling и часть glue-кода.
- Дополнительно добавлен deterministic info short-circuit до AI для известных вопросов по базе знаний, чтобы info без анкеты не стартовало бронирование и не зависело от OpenRouter.

## 2026-05-27 post_booking_flow refactor slice

- Добавлен `app/services/dialog/post_booking_flow.py`.
- В модуль вынесены post-booking summary helpers, waitlist-decline, plain ack after closed booking, payment-status reply и safe wrapper post-booking classifier.
- `message_handler.py` оставляет тонкие wrappers там, где важно сохранить callbacks/tracing/monkeypatch: `payment_status_reply` получает `sync_payment_statuses`, `create_missing_yclients_records`; classifier получает текущий `classify_post_booking_message`.
- Cancel execution вынесен следующим отдельным разрезом; reschedule execution пока намеренно оставлен внутри координатора, потому что там есть YCLIENTS update/delete, busy intervals, availability recheck and confirmation flows.
- Защитные проверки после разреза: post_booking, payments, cancel, reschedule, fresh/services/prices/upsell и dialog stress.

## 2026-05-27 production-hardening update

- YCLIENTS sync стал двухфазным: сетевой `fetch_records` без открытой DB transaction, затем короткий `apply_records`.
- `main.py` остается единственным постоянным процессом: Telegram polling, YCLIENTS sync, payment polling, message retention и webhook server стартуют вместе.
- `screen` допустим временно, но production-цель - `systemd`/supervisor с restart policy и логами.
- Не запускать `sync_yclients_records.py --loop` параллельно с `main.py`; ручной script использовать только как `--once` recovery/diagnostics.

Backend - Python-приложение на aiogram с сервисным слоем и PostgreSQL.

## Точка входа

- `main.py` - настройка логирования и запуск `run_bot`.
- `app/bot/telegram_bot.py` - Telegram polling и фоновые задачи.

## Основные сервисы

- `app/services/message_handler.py` - главный координатор диалога; пока ещё содержит большую часть state machine.
- `app/services/dialog/confirmation_flow.py` - confirmation/hold helpers: reserved hold commands, pending payment reuse, expired hold text, confirmation side replies and hold creation wrappers.
- `app/services/dialog/formatting.py` - общее форматирование дат, длительности и сумм.
- `app/services/dialog/price_info.py` - deterministic ответы по ценам, допам и базовым правилам.
- `app/services/dialog/stale_form.py` - checkpoint старой анкеты после паузы 2+ часа.
- `app/services/dialog/routing_guards.py` - чистые guards для маршрутизации вроде запросов свободных дат.
- `app/services/dialog/form_patches.py` - чистые patch-парсеры анкеты: услуга, беседка, телефон, формат отдыха, допы, гости, имя, ссылки на прошлую бронь.
- `app/services/dialog/form_corrections.py` - коррекция имени и текст подтверждения исправленных полей.
- `app/services/dialog/cancel_flow.py` - deterministic логика отмены: распознавание, выбор брони, подтверждения, тексты результата и execution через callbacks из координатора.
- `app/services/dialog/reschedule_flow.py` - deterministic helpers переноса: routing guards, swap parsing, reference phrases, confirmation/options texts, selection and gazebo-change filters.
- `app/services/dialog/semantic_router.py` - компактный контекст для первого AI-прохода: AI понимает intent/action/fields, backend исполняет действие.
- `app/services/dialog/response_builder.py` - deterministic/fallback ответы для стандартных случаев, чтобы не отправлять клиенту внутренние инструкции.
- `app/services/dialog/performance.py` - трассировка этапов обработки сообщения и structured timing logs.
- `app/ai/ai_orchestrator.py` - вызовы AI, JSON-анализ, генерация ответов, post-booking classifier, summary.
- `app/services/booking_form_service.py` - структура анкеты и следующий вопрос.
- `app/services/availability_service.py` - проверка доступности по локальным таблицам `yclients_records` и `resource_busy_intervals`; live-запросы в YCLIENTS не используются в обычном клиентском ответе.
- `app/services/payment_service.py` - платежи ЮKassa, финализация брони после оплаты.
- `app/services/payment_status_runner.py` - polling платежей, уведомления, истекшие holds, напоминания.
- `app/services/yclients_sync_service.py` - синхронизация журнала YCLIENTS в локальные таблицы.
- `scripts/yclients_sync_status.py` - диагностика свежести YCLIENTS sync-state: `last_success_at`, возраст sync, `records_seen`, `records_upserted`, `last_error`.
- `app/services/yclients_record_service.py` - создание/удаление записей YCLIENTS и локальных busy intervals.
- `app/services/message_retention_runner.py` - сжатие старой истории и удаление сообщений.
- `app/services/media_service.py` - выбор фотографий.
- `app/services/voice_transcription_service.py` - распознавание голосовых.

## Состояние диалога

Главное состояние хранится в `conversations.form_data`.

Важные flow:

- обычная анкета бронирования;
- `stale_form_flow` после паузы 2+ часа: короткое "давайте" продолжает старую анкету, а явный запрос новой услуги или свободных дат начинает чистую анкету с сохранением контакта; явный запрос `начнем новую` + ближайшие свободные даты обходит checkpoint даже если `stale_form_flow` еще не создан;
- `cancel_flow`;
- `reschedule_flow`;
- `swap_reschedule_flow`;
- `last_unavailable` и waitlist;
- `media_state` для антиспама фото.

## Маршрутизация важных сообщений

- Информационные вопросы во время финального подтверждения обрабатываются confirmation-flow, а не post-booking classifier.
- Вопросы о ближайших свободных датах во время анкеты идут напрямую в availability по локальной таблице записей.
- Вопросы о цене в upsell-контексте отвечают по допам и возвращают клиента к выбору допов.
- Post-booking синхронизирует платежи/журнал только когда у разговора есть локальные платежи.
- В post-booking состоянии команды hold/payment обрабатываются первыми, затем AI/post-booking classifier может определить cancel/reschedule/current-booking/new-booking. Fresh-start новой анкеты запускается только после этого, чтобы свободные фразы вроде "сместим баню" не превращались в новую бронь из-за слова "баня".
- Основной AI-вызов работает как semantic-router: получает компактный context, возвращает intent/action/form_data_patch, а не пишет финальный текст. Полная база знаний подключается только для info-ответов и сложного post-booking.
- Для стандартных операций backend предпочитает шаблонный ответ: свободные варианты, один вариант, цены/предоплата/допы, payment link, successful payment, отмена, перенос, список броней, stale-form, явный запрос фото.

## План рефакторинга message_handler

- Уже вынесены: `post_booking_flow`, cancel-flow, confirmation-flow, single-reschedule execution, grouped/swap reschedule orchestration, подбор новой беседки при переносе, availability reply layer и общий availability execution для основных/fallback веток.
- Дальше выносить media scheduling и оставшийся glue-код fresh-start/stale-form; основной `handle_incoming` всё ещё крупный координатор, но его доменная логика уже заметно разнесена по `app/services/dialog/`.
- Цель: `message_handler.py` должен остаться тонким координатором, а смысл сообщения должен определяться semantic router / AI, после чего backend выполняет проверяемое действие.

## Фоновые процессы

Запускаются вместе с polling:

- YCLIENTS sync loop;
- payment status loop;
- message retention loop;
- YooKassa webhook server, если включен.

Если бот не запущен, локальная таблица свободности устаревает. Для ручной проверки использовать `scripts/yclients_sync_status.py`; для ручного обновления - `scripts/sync_yclients_records.py --once`. Direct lookup ближайших дат чувствителен к freshness `yclients_records`/`resource_busy_intervals`, поэтому перед live smoke сначала проверять `--strict`.

## Тесты

Главный локальный набор: `scripts/local_regression_suite.py`.

Покрывает диалоги бронирования, оплату, переносы, отмены, фото, цены, waitlist, summary и edge cases.

С 2026-05-26 suite можно запускать по группам через `--group`: `fresh`, `dates`, `gazebo`, `media`, `prices`, `upsell`, `time`, `payments`, `post_booking`, `services`, `waitlist`, `handoff`, `reschedule`, `cancel`, `reminder`.

С 2026-05-27 `local_regression_suite.py` и `dialog_stress_suite.py` защищены lock-файлом, чтобы параллельные прогоны не удаляли данные друг друга через общий `local_regression_%` cleanup.

## Обновление 2026-05-26

- Рефакторинг `message_handler.py` продолжен без изменения публичного поведения.
- Добавлен `app/services/dialog/booking_texts.py`: шаблоны подтверждения, оплаты, сводки броней и кратких строк брони.
- Добавлен `app/services/dialog/handoff.py`: определение активного handoff, фильтр конфликтных сообщений и создание handoff-лога.
- Добавлен `app/services/dialog/fresh_start.py`: политика, когда новая заявка должна сбросить старые поля анкеты и сохранить только контакт.
- Добавлен `app/services/dialog/booking_context.py`: получение актуальных броней пользователя, сверка с журналом/YCLIENTS, fallback на текущий conversation и summary-контекст для AI.
- Добавлены `app/services/dialog/date_parsing.py` и `app/services/dialog/time_parsing.py`: чистые парсеры дат, дней недели, времени, периодов и длительности. `time_parsing.py` также нормализует длительность в единый формат: `duration` в `form_data` хранится числом часов, даже если AI вернул строку вроде `8 часов`.
- Добавлен `app/services/dialog/gazebo_options.py`: чистая логика свободных/подходящих беседок, вместимость, авто-выбор одной беседки, форматирование вариантов.
- Добавлен `app/services/dialog/cancel_flow.py`: выбор отменяемой брони и тексты cancel-flow вынесены из координатора.
- Добавлен `app/services/dialog/semantic_router.py`: основной AI-pass получает короткий router-context вместо полной базы знаний.
- Добавлен `app/services/dialog/response_builder.py`: стандартные готовые ответы и безопасный fallback, если AI вернул внутреннюю инструкцию.
- Добавлен `app/services/dialog/performance.py`: timing logs для DB, AI, availability, payment, YCLIENTS и media этапов.
- `availability_service.py` теперь использует локальную БД как единственный источник свободности в клиентском диалоге; YCLIENTS дергается фоновым sync-процессом и финальными create/delete операциями.
- `message_handler.py` пока остается координатором, но всё больше доменной логики вынесено в `app/services/dialog/`.

## Обновление 2026-05-27

- Добавлен `app/services/dialog/form_patches.py`: из `message_handler.py` вынесены чистые парсеры service/date-independent полей анкеты: тип услуги, вариант беседки, телефон, формат, допы, гости, имя и reference-фразы к прошлой брони.
- Добавлен `app/services/dialog/form_corrections.py`: из `message_handler.py` вынесены распознавание исправления имени и сборка текста "Поняла, обновила ...".
- Старые приватные имена в `message_handler.py` сохранены импортированными алиасами, чтобы regression suite и существующие вызовы не ломались.
- Цель следующего этапа рефакторинга: отделить `reschedule_flow` и `availability_flow`, потому что это самые крупные оставшиеся зоны координатора.

## Обновление 2026-05-28

- `reschedule_flow.py` расширен grouped/swap orchestration helpers и подбором новой беседки при переносе. В `message_handler.py` остались wrappers через callbacks, чтобы не ломать существующие точки вызова и regression tests.
- `availability_flow.py` получил `AvailabilityExecutionCallbacks`, `AvailabilityExecutionResult` и `execute_availability_check`: единый deterministic исполнитель для проверки свободности по локальной БД, no-availability/waitlist, alternatives и стандартного availability reply.
- Основная AI-ветка и обе fallback-ветки используют общий availability executor. Это снижает риск, что normal/fallback сценарии будут расходиться по waitlist или reset логике.
- После разрезов прошли профильные regression-группы и `dialog_stress_suite.py` 13/13.
