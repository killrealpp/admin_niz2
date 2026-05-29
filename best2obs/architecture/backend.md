# Backend

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
- Upsell refusal has a hard-negative layer for short final refusals like `не`, `no`, `нет спасибо`. Those phrases skip the soft upsell push and write `upsell_items=["не нужны"]`, then the normal `next_question()` decides the next field.
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
