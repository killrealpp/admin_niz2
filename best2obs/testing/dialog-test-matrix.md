# Dialog Test Matrix

Назначение файла: хранить понятную карту диалоговых сценариев, которые уже успешно проверены автотестами или live-like suites. Каждый новый живой сбой должен превращаться в строку здесь и, по возможности, в regression test.

Последняя полная проверка: 2026-06-01.
Последняя полная диагностика: 2026-06-01.
Последний сценарный прогон: 2026-06-01.
Последний paraphrase-профиль: 2026-05-29.
Последний live-13:07 профиль: 2026-05-29.
Последний live-14:29 профиль: 2026-05-29.
Последний live-19:02 профиль: 2026-05-29.
Последний live-30.05 профиль: 2026-05-30.
Последний pre-live fallback/proxy профиль: 2026-05-31.
Последний live-01.06 профиль: 2026-06-01.

## Ветвления Сценариев

Главная матрица остаётся входной точкой. Детальные ручные чеклисты вынесены в подветки, чтобы можно было проверять их по очереди и отмечать результат руками.

| Ветка | Чеклист | Последний авто-статус | Что внутри |
|---|---|---:|---|
| Standard | [[testing/scenarios/standard]] | OK | Базовая заявка, допы, confirmation, hold/payment, post-booking info. |
| Context/Live | [[testing/scenarios/context-live]] | OK, 17/17 + live-135/live-1953/live-14:29/live-30.05/live-01.06 regressions | Контекст даты/гостей/услуги, live-135/live-1953/live-14:29/live-30.05/live-01.06, paid/expired hold нюансы, две брони, same-date references, confirmation-no и лимит бани. |
| Edge | [[testing/scenarios/edge]] | OK, 14/14 | Перебивания анкеты, confirmation, cancel-flow, reschedule-flow, post-booking edge cases. |
| Stress | [[testing/scenarios/stress]] | OK, 13/13 | Опечатки, сленг, живые отказы, выборочная отмена, паузы, фото. |
| Broad Regression | [[testing/scenarios/broad-regression]] | OK | Широкие зоны `local_regression_suite.py`: payments, holds, pricing, media, waitlist, handoff. |
| Run Report | [[testing/scenario-run-2026-05-29]] | OK | Последний сценарный прогон от стандартных до нестандартных случаев. |
| Full Diagnostics | [[testing/full-diagnostics-2026-05-29]] | OK | Полная диагностика проекта, БД, YCLIENTS, smoke и все suites. |

## Итог Последнего Прогона

| Проверка | Статус | Что подтверждает |
|---|---:|---|
| `python -m compileall app scripts` | OK | Python-код компилируется без синтаксических ошибок. |
| `scripts/lint_best2info.py` | OK | Client-facing wiki проверяется на broken links/orphans и цены против `config/services_map.yaml`; факты без точной цены отмечаются как "уточним по факту". |
| `scripts/local_regression_suite.py` | OK | Основные regression-группы бронирования, оплаты, post-booking, отмены, переноса, цен, допов, фото, waitlist и handoff проходят полностью. |
| `scripts/dialog_context_suite.py` | OK, 17/17 | Бот держит контекст между сообщениями: дата, гости, выбранный объект, confirmation-state, вторая бронь после оплаты, лимит бани 15 гостей, `нет` на подтверждении и guest-count внутри вопроса о подборе беседки. |
| `scripts/dialog_edge_suite.py` | OK, 14/14 | Нестандартные перебивания анкеты, confirmation, cancel-flow, reschedule-flow, post-booking и info-вопросы без анкеты не ломают состояние. |
| `scripts/dialog_stress_suite.py` | OK, 13/13 | Живые разговорные формулировки, опечатки, отказы, переносы, вопросы по базе и выборочные отмены работают. |
| `scripts/dialog_regression_smoke.py` | OK | Legacy smoke ищет свободный подходящий слот, создаёт stub fake-payment без внешней YooKassa-ссылки и защищает, что номер беседки не превращается в количество гостей. |
| `scripts/dialog_regression_smoke.py` + `dialog_context_suite.py` + `dialog_edge_suite.py` + `dialog_stress_suite.py` | OK | Сценарный прогон от стандартных до нестандартных случаев прошёл без failed-сценариев. |
| `scripts/local_regression_suite.py --group services --group gazebo --group upsell --group post_booking --group payments` | OK | Paraphrase-пакет live-1953/live-135: разные формулировки имени, гостей, отказа от допов и post-booking бани проходят без наследования старого контекста. |
| `scripts/local_regression_suite.py --group fresh --group time --group upsell --group post_booking --group services` | OK | Live-14:29 пакет: stale новая баня, `не` на допах, `ну вроде да`, фиксированные блоки бани и отсутствие наследования старых полей. |
| `scripts/local_regression_suite.py --group services --group prices` | OK | Live-19:02 пакет: вопрос про беседки + `отдельной бронью` стартует чистую беседку вместо старой бани; post-booking вопрос про комаров bypass AI. |
| `scripts/local_regression_suite.py --group fresh --group post_booking --group payments --group time` | OK | Соседние route-зоны после live-19:02: stale/new booking, post-booking, hold/payment and time/duration guards не сломаны. |
| Payment regression subset после live-14:29 | OK, split 5/5 | Остаточные payment-сценарии прошли отдельно после артефакта Windows lock/long runner: expired hold resume, active hold conflict, retry payment link, phone->yes hold, paid finalize busy interval. |
| `scripts/dialog_stress_suite.py` после live-14:29 | OK, split 13/13 | Все stress-сценарии прошли при раздельном запуске; один монолитный прогон ловил transient PostgreSQL SSL/runner-lock, без failed-сценария. |
| `scripts/test_db.py` | OK | Базовый DB create/read/delete smoke проходит. |
| `scripts/yookassa_webhook_hardening_smoke.py` | OK | Локальная защита webhook runner проходит smoke. |
| `scripts/validate_yclients_map.py` | OK | `services_map.yaml` соответствует live YCLIENTS services/staff. |
| `scripts/yclients_smoke.py` | OK | Live YCLIENTS services/staff читаются через API. |
| `scripts/yclients_sync_status.py --strict` | OK | Локальный YCLIENTS-cache свежий; на последней проверке `records_seen=125`, `last_error=None`. |
| `scripts/local_regression_suite.py --group prices --group upsell --group services --group gazebo --group media --group payments` | OK | Live-30.05 пакет: цена через semantic intent, двухкасательный upsell, YCLIENTS `book_times`, 30 гостей с обрезанным словом, медиа двух броней и payment guards. |
| `scripts/local_regression_suite.py --group dates --group gazebo --group services --group upsell --group waitlist --group payments --group post_booking` | OK | Live-30.05 второй пакет: лимит бани 15 гостей, day-only дата по контексту месяца, `нет` на confirmation, нейтральный ack после info-вопроса на допах и waitlist relevance gate. |
| `scripts/dialog_context_suite.py` + `scripts/dialog_edge_suite.py` + `scripts/dialog_stress_suite.py` после live-30.05 | OK, 16/16 + 14/14 + 13/13 | Соседние контекстные, edge и stress сценарии не сломаны; добавлены context-сценарии для бани на 40 гостей и `нет` на подтверждении. |
| `scripts/yclients_sync_status.py --strict` после one-shot sync 2026-05-30 | OK | `records_seen=127`, `records_upserted=127`, `last_error=None`. |
| `scripts/yclients_sync_status.py --strict` после one-shot sync 2026-05-31 | OK | `records_seen=129`, `records_upserted=129`, `last_error=None`; `HTTP_TRUST_ENV=false` убирает системный `socks4` proxy из `httpx` клиентов. |
| `scripts/local_regression_suite.py` listed chunks + context/edge/stress 2026-05-31 | OK | Pre-live fallback/proxy пакет: bathhouse capacity в fallback, `др` как отдельное слово, friends hangout, номер беседки на шаге гостей, YCLIENTS strict и smoke зелёные. |
| Полный сценарный аудит 2026-06-01 | OK | `compileall`; все группы `local_regression_suite.py` в 3 блоках; `dialog_context_suite.py` 16/16; `dialog_edge_suite.py` 14/14; `dialog_stress_suite.py` 13/13; `dialog_regression_smoke.py` OK после one-shot YCLIENTS sync. |
| `scripts/yclients_sync_status.py --strict` после one-shot sync 2026-06-01 | OK | Первичный strict был stale (`age_seconds=34651`); после `sync_yclients_records.py --once` статус fresh, `records_seen=123`, `records_upserted=123`, `last_error=None`. |
| Safe operational smoke 2026-06-01 | OK | `test_db.py`, `validate_yclients_map.py`, `yookassa_webhook_hardening_smoke.py`, `yclients_smoke.py` прошли; `yookassa_smoke.py` не запускался, чтобы не создавать реальную внешнюю оплату. |
| Live-01.06 guest/upsell/post-booking continuation | OK | `compileall`; `dialog_context_suite.py` 17/17; `local_regression_suite.py --group upsell`; `local_regression_suite.py --group post_booking`; `dialog_edge_suite.py` 14/14; `dialog_stress_suite.py` 13/13; `lint_best2info.py` OK. |

## Успешные Live/Context Сценарии

| Сценарий | Покрытие | Статус | Что защищает |
|---|---|---:|---|
| Оплаченная беседка -> `можно еще что нибудь забронировать?` | `local_regression_suite.py`, `dialog_context_suite.py` | OK | Post-booking info не возвращает старый `awaiting_confirmation`. |
| Оплаченная беседка -> `давайте еще баню на то же число что и беседка` | `local_regression_suite.py`, `dialog_context_suite.py` | OK | Новая бронь бани берёт дату активной беседки, но не переносит старые гости/формат/допы/вариант. |
| Draft бани после оплаченной беседки -> `число такое же как у беседки` | `local_regression_suite.py` | OK | Same-date reference не превращается в info-ответ про активную беседку; дата копируется в текущую баню, следующий шаг — время. |
| Draft бани -> `а вообще норм беседка?` | `local_regression_suite.py`, `dialog_context_suite.py` | OK | Бот отвечает по активной беседке и возвращается к вопросу текущей бани. |
| Оплаченная беседка -> `а она уже активна, я вносил предоплату?` | `local_regression_suite.py` | OK | Вопрос об оплате идёт в deterministic payment-status reply и не берёт текст из старого expired hold. |
| Оплаченная беседка -> `давайте новую оформим, мне нужна баня` | `local_regression_suite.py` | OK | `мне нужна баня` не матчится как `не нужна баня`; старая беседка не отменяется, стартует новая баня. |
| Post-booking вопрос `в баньку можно будет сходить?` после оплаченной беседки | `local_regression_suite.py` | OK | Бот отвечает, что есть только баня с бассейном и она оформляется отдельной бронью, без выдуманных русской/финской сауны и без добавления к беседке как допа. |
| Post-booking info про баню -> `а ее/её как бронировать?` -> `давайте начнем новую заявку` | `local_regression_suite.py` | OK | Pronoun-follow-up отвечает по последней обсуждённой бане; batch-парафразы `а как ее оформить?`, `как её забронировать?`, `ну тогда оформим новую`, `давай новую бронь тогда` стартуют чистую баню и сохраняют только имя/телефон. |
| Старый draft бани -> `а какие беседки есть` -> `хочу добвить отдельной бронью` | `local_regression_suite.py` | OK | Ответ про беседки сохраняет обсуждаемую услугу `gazebo`; фраза с опечаткой стартует чистую отдельную беседку и не запускает validation старой бани. |
| Старый draft беседки -> `а я же хочу баньку` | `local_regression_suite.py` | OK | Явное исправление услуги на баню не наследует дату, время, длительность, гостей, формат и допы старой беседки. |
| Active hold -> `денег нет... оплачу... подождете?` | `local_regression_suite.py` | OK | Бот отвечает про 10-минутный резерв и не запускает reschedule-flow. |
| Active hold -> `а ты можешь сделать будто бы я оплатил?` | `local_regression_suite.py` | OK | Бот не отмечает оплату вручную, не пишет `Оплата получена`, сохраняет hold в `reserved` и просит дождаться реального платежа от ЮKassa. |
| Active hold -> `приступим к следующуей заявке?` | `local_regression_suite.py` | OK | Опечатка в слове `следующуей` не превращается в доп `лед`; старая заявка/hold не меняется, новая анкета стартует чисто с вопроса услуги и сохраняет только контакт. |
| Expired hold -> `я и говорю давай ее же оформлю` | `local_regression_suite.py` | OK | Бот восстанавливает прежний слот из истёкшего hold и не спрашивает дату заново. |
| Старый draft -> `я бы хотел баню на 30 июня с 9 утра до 21 ночи...` | `local_regression_suite.py` | OK | Подробная новая заявка не показывает stale-checkpoint, стартует чистую баню и не наследует старые гости/формат/допы. |
| Stale checkpoint -> `нет` + новая баня в том же сообщении | `local_regression_suite.py` | OK | Отказ от старой анкеты и новая заявка обрабатываются одним сообщением, без цикла `старая или новая?`. |
| `на 30 июня` после запроса беседки | `dialog_context_suite.py`, `local_regression_suite.py` | OK | Дата не превращается в `30 гостей`, бот спрашивает количество гостей. |
| `на 30 июня нас будет 20` | `dialog_context_suite.py`, `local_regression_suite.py` | OK | Дата и гости в одном сообщении идут в availability и фильтр вместимости. |
| `на 30 июня двадцать` | `dialog_context_suite.py` | OK | AI-смысл гостей принимается без жесткой зависимости от слов `чел/гостей`. |
| `29 мая 6 беседка` | `dialog_context_suite.py`, `dialog_stress_suite.py` | OK | Номер беседки не становится количеством гостей или временем; сначала проверяется вместимость. |
| `а если бы нас было 10 какие беседки подошли бы?` после контекста на 20 гостей | `local_regression_suite.py` | OK | Hypothetical capacity question обновляет расчёт под 10 гостей и не отвечает старым числом 20; batch-парафразы `а если нас 10`, `для 10 человек`, `если будет 10 человек` проходят тем же flow. |
| `а какой у меня выбор есть?` после даты | `dialog_context_suite.py` | OK | Бот помнит дату и просит гостей, а не спрашивает дату заново. |
| `нас будет 30 человек, какая беседка подойдет` | `dialog_context_suite.py` | OK | Бот сохраняет 30 гостей, показывает подходящие беседки и не задаёт повторно вопрос о количестве гостей. |
| Жалоба `ты же даже не спросил сколько человек` | `dialog_context_suite.py` | OK | Recovery очищает ошибочно выбранную беседку/гостей и возвращает шаг гостей. |
| `нужно 2 беседки на 02.06 и 19.06` | `dialog_context_suite.py` | OK | Две беседки оформляются последовательно, вторая дата хранится отдельно. |
| Вторая дата из очереди во время первой заявки | `dialog_context_suite.py` | OK | Дата второй брони не перезаписывает первую заявку. |
| `время тоже поменяй с 11 до 08` на confirmation | `dialog_context_suite.py` | OK | Correction-flow имеет приоритет и обновляет summary, не попадает в reserved-hold glue. |
| Опечатка `активыне заявки` | `dialog_context_suite.py` | OK | Бот показывает draft/current booking summary, а не уходит в side reply. |
| После оплаченной беседки `что еще можно забронировать?` | `dialog_context_suite.py`, `local_regression_suite.py` | OK | Бот отвечает `Кроме вашей беседки...`, не использует шаблон `Помимо бани...` и не меняет текущую бронь. |
| Баня на 40 гостей | `local_regression_suite.py`, `dialog_context_suite.py` | OK | Бот блокирует оформление бани больше 15 гостей без ручного уточнения и предлагает просторную беседку/альтернативы. |
| `на 30 число` после июньского контекста | `local_regression_suite.py` | OK | Day-only дата использует свежий месяц из текущей анкеты или `last_unavailable`, не прыгает на 30 мая. |
| `нет` на финальном подтверждении | `local_regression_suite.py`, `dialog_context_suite.py` | OK | Бот понимает отказ от подтверждения, не меняет допы и спрашивает, что изменить. |
| `ну окей` после info-вопроса на шаге допов | `local_regression_suite.py` | OK | Нейтральный ack не добавляет допы и не закрывает шаг без явного выбора/отказа. |
| Waitlist после освобождения слота | `local_regression_suite.py` | OK | Уведомление уходит только актуальному клиенту; запросы с уже закрывающей бронью/hold или отказом закрываются без сообщения. |

## Успешные Анкетные Сценарии

| Сценарий | Покрытие | Статус | Что защищает |
|---|---|---:|---|
| `просто отдыз` на шаге формата | `local_regression_suite.py` | OK | Опечатка формата сохраняется как смысловой формат отдыха. |
| Первый отказ от допов -> второй мягкий заход | `local_regression_suite.py`, `dialog_stress_suite.py` | OK | Upsell не закрывается слишком рано. |
| Второй отказ от допов | `local_regression_suite.py`, `dialog_stress_suite.py` | OK | Бот принимает `без допов` и идёт дальше. |
| `не` на шаге допов | `local_regression_suite.py` | OK | Первый короткий отказ запускает мягкий второй заход; повторный отказ закрывает допы и переводит к имени/следующему полю. |
| `ну давайте` после soft upsell | `local_regression_suite.py` | OK | В vague-accept сохраняется предложенный базовый мангальный набор. |
| `давайте первый набор` после прайса допов | `local_regression_suite.py` | OK | Бот сохраняет `мангальный набор №1` и идёт к следующему полю, не повторяя upsell-вопрос и не возвращаясь к свободности. |
| `если что там на месте возьмем` после отказа от допов | `local_regression_suite.py` | OK | Разговорный отказ остаётся `допы: не нужны`, не подставляет базовый мангальный набор; batch-парафразы `возьмем/возьмём`, `на месте возьмем если понадобится`, `там на месте уже разберемся` проходят одинаково. |
| Телефон завершил анкету -> `да` | `local_regression_suite.py` | OK | После ввода телефона бот сразу входит в confirmation; следующее `да` создаёт резерв/ссылку, а не показывает второе подтверждение заявки. |
| Confirmation -> `ну вроде да` | `local_regression_suite.py` | OK | Мягкое подтверждение создаёт hold/payment, а не просит написать строго `да`. |
| `имя заменим на IVAN` на confirmation | `local_regression_suite.py` | OK | Исправление имени берёт только `IVAN`, не сохраняет `Заменим На Ivan` и не ломает латинский uppercase; batch-парафразы `имя поменяем`, `замени имя`, `фио измени` проходят тем же общим parser. |
| `а решотка и кальян по чем?` | `local_regression_suite.py`, `dialog_stress_suite.py` | OK | Бот отвечает ценами допов и не добавляет их автоматически. |
| `а вода и лед сколько стоят? если можно, добавьте воду и лед` | `local_regression_suite.py`, `dialog_stress_suite.py` | OK | Бот отвечает по цене и сохраняет выбранные допы. |
| Телефон + info-вопрос в одном сообщении | `dialog_edge_suite.py` | OK | Телефон сохраняется, info-ответ даётся, следующий шаг не теряется. |
| `давай откажемся от брони` во время анкеты | `local_regression_suite.py`, `dialog_edge_suite.py`, `dialog_stress_suite.py` | OK | Незавершенный draft очищается, контакт сохраняется, оплаченные брони не трогаются. |
| `ну хз, я позже вам напишу` | `dialog_stress_suite.py` | OK | Draft ставится на паузу без повторного вопроса. |
| `ну че нибудь` на шаге времени | `local_regression_suite.py` | OK | AI не придумывает время/длительность без явного сигнала. |
| `с 9 утра до 21 ночи, если что можно на дольше остаться?` на шаге времени | `local_regression_suite.py` | OK | Явный период `09:00-21:00` имеет приоритет над открытым вопросом `можно подольше`; длительность остаётся 12 часов, а не 23 часа до 08:00. |
| `просто посидеть с друзьями` на шаге формата | `local_regression_suite.py` | OK | Формат сохраняется как `компания друзей`, не превращается в `день рождения`. |

## Успешные Info-Сценарии

| Сценарий | Покрытие | Статус | Что защищает |
|---|---|---:|---|
| Вопрос про парковку внутри анкеты | `local_regression_suite.py`, `dialog_edge_suite.py` | OK | Info-ответ не ломает текущий шаг анкеты. |
| Вопрос про детей внутри анкеты | `local_regression_suite.py`, `dialog_stress_suite.py` | OK | Ответ берётся из клиентской базы знаний и возвращает к текущему шагу. |
| `ну вот я хочу на 30 июня, сколько будет стоить?` после вопроса о цене | `local_regression_suite.py` | OK | Price/common-info priority: `будет` не ловится как `дети`, бот отвечает ценой и текущим следующим шагом. |
| Semantic price intent без слов `цена/стоить/сколько` | `local_regression_suite.py` | OK | Если AI понял смысл как `price_question`, backend считает цену по `services_map`, а не ищет одну конкретную фразу. |
| `а с детьми и собакой можно? парковка есть?` без анкеты | `local_regression_suite.py`, `dialog_edge_suite.py` | OK | Бот отвечает по базе знаний, не запускает бронирование и не спрашивает дату. |
| `а до утра можно отдыхать?` внутри draft беседки | `local_regression_suite.py` | OK | Бот объясняет правило до 08:00 и возвращается к текущему шагу времени, не проставляя время/длительность сам. |
| Вопрос про комаров без анкеты | `dialog_stress_suite.py` | OK | Бот отвечает по базе и не стартует бронирование. |
| Вопрос про комаров после брони/hold | `local_regression_suite.py` | OK | Ответ идёт deterministic до post-booking AI: обработка раз в неделю, природная территория, репеллент; AI не выдумывает `комаров нет`. |
| Вопрос про веники в баню без анкеты | `local_regression_suite.py`, `dialog_stress_suite.py` | OK | Бот отвечает про запрет/штраф и не задаёт вопрос анкеты. |
| Посторонний вопрос во время анкеты | `dialog_edge_suite.py` | OK | `form_data` не портится. |
| Посторонний post-booking вопрос | `dialog_edge_suite.py` | OK | Активная бронь не меняется, отмена/допы не запускаются. |
| Paid notification после оплаты | `local_regression_suite.py` | OK | Финальное сообщение об оплате содержит краткую строку брони с датой и временем, чтобы клиент понимал, какая запись создана в журнале. |

## Успешные Post-Booking, Cancel И Reschedule

| Сценарий | Покрытие | Статус | Что защищает |
|---|---|---:|---|
| `чо там на мне висит по записям` | `dialog_stress_suite.py`, `local_regression_suite.py` | OK | Сводка активных броней берётся из БД/YCLIENTS-cache. |
| `баню убери, а беседку не трогай` | `dialog_stress_suite.py` | OK | Выборочная отмена не трогает защищенную бронь. |
| Отмена оплаченной брони за 7+ дней | `local_regression_suite.py` | OK | Бот пишет, что аванс можно вернуть по правилам отмены. |
| Отмена оплаченной брони меньше чем за 7 дней | `local_regression_suite.py` | OK | Бот пишет, что аванс не возвращается по правилам. |
| Отмена всех броней | `local_regression_suite.py` | OK | Бот просит одно подтверждение и отменяет все выбранные брони. |
| `Дя` / `да да` как подтверждение | `local_regression_suite.py`, `dialog_stress_suite.py` | OK | Опечатки подтверждения закрывают нужный confirm-flow. |
| `нет, оставь` в cancel-flow | `dialog_edge_suite.py` | OK | Отмена отмены очищает `cancel_flow`; бронь остаётся активной. |
| `сдвинем баню на денек позже, часы те же` | `dialog_stress_suite.py` | OK | Перенос использует новую дату и прежнее время. |
| `да да` после предложения переноса | `local_regression_suite.py` | OK | Reschedule подтверждается и очищает `reschedule_flow`. |
| Info-вопрос внутри reschedule-flow | `dialog_edge_suite.py` | OK | Перенос не сбрасывается после информационного вопроса. |

## Успешные Availability И Pricing

| Сценарий | Покрытие | Статус | Что защищает |
|---|---|---:|---|
| На дату свободны только маленькие беседки для большой компании | `local_regression_suite.py`, `dialog_context_suite.py` | OK | Бот не предлагает тесные варианты и ищет ближайшие подходящие даты. |
| Бюджетный запрос `подешевле` | `local_regression_suite.py`, `dialog_stress_suite.py` | OK | Бот фильтрует подходящие свободные варианты по цене. |
| Будняя скидка для беседки | `local_regression_suite.py`, `dialog_context_suite.py` | OK | В цене учитывается скидка 50% ПН-ЧТ. |
| Цена беседки не считается как цена дома по часам | `local_regression_suite.py` | OK | Бот отвечает по правилам беседок. |
| Ближайшие свободные даты после unavailable | `local_regression_suite.py` | OK | Поиск свободности не использует stale suggestions. |
| Недоступный дом предлагает альтернативы на ту же дату | `local_regression_suite.py`, `dialog_stress_suite.py` | OK | Бот предлагает подходящие свободные услуги вместо тупика. |
| Баня `09:00-21:00` на 12 часов | `local_regression_suite.py` | OK | Бот не создаёт hold/payment на недопустимую длительность; сохраняет дату/время и просит выбрать фиксированный блок 3, 4, 5, 6 или 7 часов. |
| Баня/дом: выбранное время отсутствует в YCLIENTS `book_times` | `local_regression_suite.py` | OK | Backend не создаёт hold/payment и показывает доступные старты вместо локального “свободно”. |
| YCLIENTS `book_times` недоступен для фиксированной услуги | `local_regression_suite.py` | OK | Backend не говорит “свободно”, а просит повторить позже/передать админу. |
| `нас если что 30 челове` в запросе ближайших беседок | `local_regression_suite.py` | OK | Обрезанное слово всё равно даёт `guests_count=30`; маленькие беседки фильтруются до вывода. |

## Успешные Media-Сценарии

| Сценарий | Покрытие | Статус | Что защищает |
|---|---|---:|---|
| `кинь фотку 3й беседки` | `dialog_stress_suite.py`, `local_regression_suite.py` | OK | Явный запрос фото распознаёт разговорный номер беседки. |
| Фото не отправляется слишком рано без даты/гостей | `local_regression_suite.py` | OK | Auto-media не спамит до нормального контекста. |
| Явный фото-запрос bypass AI | `local_regression_suite.py` | OK | Фото отправляется deterministic route, без смены состояния анкеты. |
| Сводка двух броней: Беседка №1 + Баня | `local_regression_suite.py` | OK | Auto-media возвращает фото обеих услуг, включая `besedka1.jpg`, по тексту сводки и данным брони. |

## Правило Обновления

- Если найден новый live-баг, сначала добавить строку в этот файл со статусом `TODO` или `FAIL`.
- Затем добавить regression/context/edge/stress тест.
- После фикса поменять статус на `OK`, указать покрытие и дату последней проверки.
- Не считать сценарий закрытым, пока он не проходит автоматически или не описан как ручной smoke с датой проверки.
