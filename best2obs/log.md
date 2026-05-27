# Project Log

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
