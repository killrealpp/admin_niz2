# Scenario Test Run 2026-05-29

Цель: пройти сценарные диалоги от стандартных happy-path до нестандартных stress cases и зафиксировать, что успешно работает.

## Итог

- Статус сценарного прогона: OK.
- Успешно пройдено: 4/4 scenario suites и полный `local_regression_suite.py`.
- Непрошедшие сценарии: нет.
- Перед стартом выполнен `sync_yclients_records.py --once`; стартовый strict был fresh: `records_seen=125`, `last_error=None`.
- После длинного regression-прогона strict ожидаемо стал stale (`age_seconds=961`, лимит 600), затем выполнен повторный sync; финальный strict fresh: `records_seen=125`, `last_error=None`.

## Команды

| Порядок | Команда | Статус | Назначение |
|---:|---|---:|---|
| 1 | `scripts/sync_yclients_records.py --once` | OK | Обновить локальный YCLIENTS-cache перед сценариями с availability. |
| 2 | `scripts/yclients_sync_status.py --strict` | OK | Подтвердить свежесть cache перед стартом. |
| 3 | `scripts/dialog_regression_smoke.py` | OK | Стандартный happy-path бронирования беседки, confirmation и fake-payment hold. |
| 4 | `scripts/dialog_context_suite.py` | OK, 14/14 | Контекстные live-like сценарии: дата, гости, активная заявка, две брони, live-135. |
| 5 | `scripts/dialog_edge_suite.py` | OK, 14/14 | Перебивания анкеты, confirmation, cancel/reschedule и post-booking edge cases. |
| 6 | `scripts/dialog_stress_suite.py` | OK, 13/13 | Нестандартные живые формулировки, опечатки, сленг, выборочные отмены. |
| 7 | `scripts/local_regression_suite.py` | OK | Широкий набор regression checks по fresh/services/dates/gazebo/upsell/payments/cancel/reschedule/media/waitlist/reminder. |
| 8 | `scripts/yclients_sync_status.py --strict` | STALE then OK | После длинного прогона cache устарел; после повторного sync strict снова OK. |

## Стандартные Сценарии

| Сценарий | Suite | Статус | Что проверено |
|---|---|---:|---|
| Запрос беседки -> дата -> выбор вариантов -> гости -> выбор беседки | `dialog_regression_smoke.py` | OK | Бот предлагает свободные варианты, просит гостей до закрепления, сохраняет выбранную беседку. |
| Info-вопрос про парковку внутри анкеты | `dialog_regression_smoke.py` | OK | Ответ про парковку не сбивает текущий шаг анкеты. |
| Первый отказ от допов | `dialog_regression_smoke.py` | OK | Бот делает мягкий второй заход и не закрывает upsell слишком рано. |
| Второй отказ от допов -> имя -> телефон -> confirmation | `dialog_regression_smoke.py` | OK | Анкета доходит до подтверждения без потери полей. |
| Правка имени на confirmation | `dialog_regression_smoke.py` | OK | Бот уточняет и обновляет имя, затем возвращает summary. |
| Info-вопрос про мангал на confirmation | `dialog_regression_smoke.py` | OK | Ответ не сбрасывает `awaiting_confirmation`. |
| Подтверждение -> fake payment hold | `dialog_regression_smoke.py` | OK | Создаётся hold и fake payment-link без создания booking до оплаты. |
| Правка имени в reserved-hold | `dialog_regression_smoke.py` | OK | Резерв остаётся активным, hold не отменяется. |
| Post-booking вопрос про баню | `dialog_regression_smoke.py` | OK | Бот отвечает про баню, не ломая текущий reserved state. |

## Контекстные Live-Like Сценарии

| Сценарий | Suite | Статус | Что проверено |
|---|---|---:|---|
| `на 30 июня нас будет 20` | `dialog_context_suite.py` | OK | Дата+гости идут в availability, варианты фильтруются по вместимости. |
| На дату свободны только маленькие беседки | `dialog_context_suite.py` | OK | Бот не предлагает тесные варианты и ищет ближайшие подходящие даты. |
| `на 30 июня` без гостей | `dialog_context_suite.py` | OK | Дата не превращается в `30 гостей`; следующий шаг — гости. |
| `на 30 июня двадцать` | `dialog_context_suite.py` | OK | AI-смысл гостей принимается без зависимости от слов `человек/гостей`. |
| `29 мая 6 беседка` | `dialog_context_suite.py` | OK | Номер беседки не становится гостями или временем. |
| `а какой у меня выбор есть?` после даты | `dialog_context_suite.py` | OK | Бот помнит дату и просит гостей, не спрашивает дату заново. |
| Жалоба, что бот не спросил гостей | `dialog_context_suite.py` | OK | Recovery очищает испорченный выбор и возвращает шаг гостей. |
| Info-вопрос про скидку | `dialog_context_suite.py` | OK | Скидка отвечает по текущей выбранной беседке, шаг времени сохраняется. |
| Summary на confirmation и отмена draft | `dialog_context_suite.py` | OK | Summary показывает черновик, abort чистит только незавершённую заявку. |
| Две беседки на разные даты | `dialog_context_suite.py` | OK | Очередь заявок сохраняет вторую дату отдельно. |
| Вторая дата из очереди во время первой заявки | `dialog_context_suite.py` | OK | Вторая дата не перезаписывает первую заявку. |
| Цена со скидкой для будней | `dialog_context_suite.py` | OK | Обычный вопрос о цене учитывает скидку 50%. |
| Правка времени на confirmation + опечатка summary | `dialog_context_suite.py` | OK | Correction-flow и fuzzy summary держат черновик. |
| Live-135: оплаченная беседка -> новая баня -> вопрос про беседку | `dialog_context_suite.py` | OK | Вторая бронь бани берёт дату беседки, вопрос про беседку не меняет текущую услугу. |

## Edge-Сценарии

| Сценарий | Suite | Статус | Что проверено |
|---|---|---:|---|
| `что мы сейчас бронируем?` внутри анкеты | `dialog_edge_suite.py` | OK | Бот показывает текущий черновик. |
| Посторонний вопрос внутри анкеты | `dialog_edge_suite.py` | OK | Состояние и шаг анкеты не портятся. |
| Телефон + info-вопрос в одном сообщении | `dialog_edge_suite.py` | OK | Телефон сохраняется, info-ответ даётся, следующий шаг не теряется. |
| Отказ от брони на шаге допов | `dialog_edge_suite.py` | OK | Draft очищается, контакт сохраняется. |
| Дети/собака/парковка без анкеты | `dialog_edge_suite.py` | OK | Бот отвечает по базе знаний и не стартует бронь. |
| `какую бронь подтверждаем?` | `dialog_edge_suite.py` | OK | Confirmation summary показывает текущую заявку. |
| Info-вопрос на confirmation, затем `да` | `dialog_edge_suite.py` | OK | Info не сбрасывает confirmation, `да` создаёт hold/payment link. |
| Отмена ещё не созданной заявки на confirmation | `dialog_edge_suite.py` | OK | Черновик сбрасывается без создания брони. |
| Info-вопрос внутри cancel-flow | `dialog_edge_suite.py` | OK | Cancel-flow не сбрасывается. |
| Посторонний вопрос внутри cancel-flow | `dialog_edge_suite.py` | OK | Посторонний текст не подтверждает отмену. |
| `нет, оставь`, затем перенос | `dialog_edge_suite.py` | OK | Cancel-flow закрывается, reschedule-flow стартует корректно. |
| Info-вопрос внутри reschedule-flow | `dialog_edge_suite.py` | OK | Перенос не сбрасывается, новая дата принимается после info. |
| Вопрос про варианты переноса | `dialog_edge_suite.py` | OK | Бот объясняет перенос одной/нескольких броней. |
| Посторонний post-booking вопрос | `dialog_edge_suite.py` | OK | Активная бронь не меняется. |

## Нестандартные Stress-Сценарии

| Сценарий | Suite | Статус | Что проверено |
|---|---|---:|---|
| Опечатка `подешелве` в бюджетном подборе | `dialog_stress_suite.py` | OK | Бот выбирает самые дешёвые подходящие варианты. |
| Два живых отказа от допов | `dialog_stress_suite.py` | OK | Первый отказ даёт мягкий upsell, второй закрывает допы. |
| Вопрос цены допов, затем выбор набора | `dialog_stress_suite.py` | OK | Цены не добавляют допы автоматически, явный выбор сохраняется. |
| Цена воды/льда + просьба добавить | `dialog_stress_suite.py` | OK | Бот отвечает по цене и сохраняет выбранные допы. |
| Вторая услуга: баня тем же днём и теми же часами | `dialog_stress_suite.py` | OK | Дата/время берутся из активной беседки, услуга остаётся баней. |
| Сленговый вопрос `что на мне висит` | `dialog_stress_suite.py` | OK | Бот показывает список активных броней из БД. |
| Выборочная отмена: баню убрать, беседку не трогать | `dialog_stress_suite.py` | OK | Cancel-flow выбирает только баню. |
| Перенос `на денек позже, часы те же` | `dialog_stress_suite.py` | OK | Бот переносит дату и сохраняет время. |
| Info-вопрос про 30 человек внутри бани + пауза | `dialog_stress_suite.py` | OK | Контекст бани сохраняется, draft ставится на паузу. |
| Info-вопросы без анкеты: комары, веники, адрес, парковка | `dialog_stress_suite.py` | OK | Бот отвечает по базе и не стартует бронь. |
| Живой отказ `забей, не оформляем` | `dialog_stress_suite.py` | OK | Draft отменяется, контакт сохраняется. |
| Явный запрос фото без даты | `dialog_stress_suite.py` | OK | Бот отправляет фото конкретной беседки без запуска анкеты. |
| Принудительный выбор беседки, вместимость, цены допов, `Дя` | `dialog_stress_suite.py` | OK | Вместимость проверяется, цены не сбивают шаг, typo-confirm отменяет бронь. |

## Широкие Regression-Сценарии

Полный `scripts/local_regression_suite.py` прошёл OK. Он дополнительно покрывает:

- fresh/new booking и сброс старых slot-полей;
- payments/holds: retry payment link, expired hold, existing payment link, concurrent hold conflict, payment intent retry;
- services/date/gazebo/time parsing;
- live capacity/date scenarios;
- mixed selection+info;
- upsell and addon persistence;
- post-booking summary and active bookings;
- cancel/reschedule/reminder flows;
- media/photo routing;
- waitlist/handoff safeguards;
- same-date/same-time second-service references;
- price/info replies from `best2info`.

## Непрошедшие Сценарии

Непрошедших сценариев в этом прогоне нет.

## Наблюдения

- В логах сохраняются `dialog_timing_slow` на AI semantic/post-booking ветках, обычно 5-10 секунд. Это UX/performance-риск, не функциональный fail.
- После длинного `local_regression_suite.py` YCLIENTS-cache стал stale из-за лимита 600 секунд; повторный `sync_yclients_records.py --once` вернул strict в OK.
- `dialog_regression_smoke.py` использует fake payment link и не создаёт реальную оплату.

## Дополнение По Live-1953

- После нового live-чата добавлены и проверены regression-сценарии: `имя заменим на IVAN`, `а если бы нас было 10`, `если что там на месте возьмем`, `телефон -> да`, paid notification с датой/временем, post-booking info про баню, generic `давайте начнем новую заявку` после вопроса про баню и `а я же хочу баньку`.
- Профильный прогон после добавления confirmation/pronoun-follow-up тестов: `local_regression_suite.py --group services --group payments --group upsell` - OK.

## Дополнение По Paraphrase-Пакету

- Для проверки, что фиксы не завязаны на одну конкретную фразу, добавлены batch-парафразы: `а если нас 10`, `для 10 человек`, `если будет 10 человек`; `на месте возьмем/возьмём`, `там на месте уже разберемся`; `имя заменим/поменяем`, `замени имя`, `фио измени`; две цепочки post-booking про баню и новую бронь.
- Прогон поймал один реальный недочёт: `фио измени на IVAN` не попадало в name-correction parser из-за узкого prefilter. После исправления `local_regression_suite.py --group post_booking` прошёл OK.
- Итоговый профиль: `python -m compileall app scripts` OK; `local_regression_suite.py --group services --group gazebo --group upsell --group post_booking --group payments` завершился `EXIT=0`, без `FAIL`, `Traceback` и `AssertionError`.
- Бот не запускался.
