# Pre-launch Roadmap

## 2026-06-01 before next Telegram smoke

- Локальный `.env` временно переведен в тестовый режим `PREPAYMENT_MODE=fixed`, `PREPAYMENT_AMOUNT_RUB=1`, `PREPAYMENT_PERCENT=50`. Для production перед запуском переключить на `PREPAYMENT_MODE=percent`, оставить `PREPAYMENT_PERCENT=50`, проверить `.env` и перезапустить бот.
- Локальный артефакт бани на 30 июня закрыт: `bookings.id=1` archived/cancelled, `resource_busy_intervals` для `source='bot_booking'`, `source_record_id='1'` удален, `payments.id=2` сохранен как paid history и помечен notified. Перед Telegram smoke всё равно проверить availability после fresh sync.
- Перед ручными сценариями выполнить `scripts/sync_yclients_records.py --once`, затем `scripts/yclients_sync_status.py --strict`, `scripts/lint_best2info.py` и `scripts/validate_yclients_map.py`.
- Не запускать `scripts/yookassa_smoke.py` без намерения создать реальную внешнюю YooKassa-ссылку. Для локального smoke достаточно fixed 1 ₽ и fake-payment/regression smoke.
- Фоновые процессы сейчас не запущены, если нет active `python` process. Для живого теста запускать один процесс `main.py`; он поднимает Telegram polling, YCLIENTS sync, payment/status loop, message retention и локальный YooKassa webhook server.
- После запуска проверить, что `scripts/yclients_sync_status.py --strict` остается fresh через 1-2 минуты, а `messages/conversation_summaries` ведут себя ожидаемо после 48h retention window.

## 2026-05-31 pre-live fallback/proxy follow-up

- Закрыто 2026-05-31: `bathhouse blocks large group` больше не доходит до `event_format` ни в normal path, ни в fallback/AI-unavailable path; общий capacity guard очищает `guests_count` для бани больше 15 гостей и возвращает клиента к ручному уточнению/выбору альтернативы.
- Закрыто 2026-05-31: постоянная proxy-политика добавлена через `HTTP_TRUST_ENV=false`; OpenAI/OpenRouter, YCLIENTS, YooKassa и voice transcription не доверяют системному `socks4://127.0.0.1:10808` по умолчанию. One-shot YCLIENTS sync прошёл без `NO_PROXY`.
- Закрыто 2026-05-31: локальный `.env` переведён на `PREPAYMENT_AMOUNT_RUB=2000`; smoke fake-payment тоже проверяет сумму `2000.00 ₽`.
- Закрыто 2026-05-31: smoke больше не зависит от hard-coded `Беседка №2`, ищет любой свободный подходящий слот и дополнительно защищает баг `давай беседку номер 2` -> `guests_count=2`.
- Остаётся операционная привычка перед Telegram smoke/live: сначала `scripts/yclients_sync_status.py --strict`; если stale по возрасту, выполнить `scripts/sync_yclients_records.py --once`, потому что long regression прогон может занять больше freshness-порога.

## 2026-05-28 after live payment/confirmation hardening

- Перед следующим Telegram smoke помнить: бот сейчас выключен по просьбе. При запуске payment runner должен отправить финальное paid-подтверждение по payment `17`, потому что запись YCLIENTS уже создана, а `payment_notified_at` ещё `NULL`.
- Обязательный smoke после запуска: `нет` на допах -> soft push -> `ну давайте` должен добавить `базовый мангальный набор` и спросить телефон, без повторного `Что подготовить`.
- Обязательный smoke на confirmation: после summary `Всё верно? Подтверждаете бронь?` написать `а комары у вас есть?`, затем `а это хорошая беседка?`, затем `да`. Ожидаемо: оба info-вопроса отвечают по смыслу, состояние остаётся `awaiting_confirmation`, `да` создаёт hold/payment link.
- Обязательный payment smoke: при transient ошибке YCLIENTS create клиент должен получить промежуточное `Оплата поступила, закрепляю запись в журнале`, а retry должен создать YCLIENTS без ручного вмешательства. Проверить по `bookings.yclients_record_id`, `yclients_create_error`, `payments.payment_notified_at`.
- Обязательный concurrency smoke: быстро отправить два сообщения подряд в одном чате; в логах не должно быть двух параллельных state transitions для одного `external_user_id`, ответы должны идти в порядке обработки.
- После этих user-facing фиксов можно возвращаться к refactor `message_handler.py`, но только после live smoke и с ботом запущенным одним процессом `main.py`.

## 2026-05-28 after structural AI field validation

- Перед live smoke проверить новую ключевую пару: `нужна беседка` -> `на 30 июня` должен спросить гостей, а не выбрать №1; `нужна беседка` -> `на 30 июня двадцать` может принять 20 гостей через AI-смысл и показать подходящие варианты.
- Проверить live: `29 мая 6 беседка` должен выбрать Беседку №6 и спросить гостей, а не записать 6 гостей.
- Проверить live: `а какой у меня выбор есть?` после даты должен помнить дату и объяснять, что для нормального выбора нужно количество гостей.
- Для дальнейших правок не возвращать keyword-trigger как основной механизм: слова допустимы только как fallback/parser для явных формулировок, но route/accept/reject должны опираться на AI intent, текущий шаг и структурную валидацию conflict fields.
- Regression baseline после этой правки: `compileall`; `dialog_context_suite.py`; три блока `local_regression_suite.py` (`gazebo/dates/prices/upsell/time/fresh`, `services/post_booking/payments/cancel/reschedule`, `media/waitlist/handoff/reminder`); `dialog_edge_suite.py`; `dialog_stress_suite.py`.

## 2026-05-28 after date-only/guest-poison fix

- Live-кейс `нужна беседка` -> `на 30 июня` закрыт: бот не должен превращать 30 июня в 30 гостей и не должен авто-выбирать `Беседку №1` до вопроса о количестве гостей.
- Новый обязательный Telegram smoke: `привет, нужна беседка` -> `на 30 июня` -> ожидаемо бот фиксирует 30 июня, показывает/помнит свободные варианты и спрашивает `Сколько вас будет человек?`; `а какой у меня выбор есть?` должен помнить 30 июня и снова уточнить гостей, а не просить дату заново.
- Recovery smoke: если состояние уже испорчено или клиент пишет `ты же даже не спросил сколько человек`, бот должен признать, что гости не уточнены, очистить выбранную беседку и спросить количество гостей.
- Для live smoke из-за локальной DNS-проблемы можно временно запускать диагностические команды с `DB_HOST=95.214.62.243` и `DB_SSLMODE=verify-ca`, но `.env` не менять. На production лучше решить DNS/host resolution штатно, чтобы не ослаблять `verify-full`.
- Перед ручным тестом снова проверить `scripts/yclients_sync_status.py --strict`; если stale, выполнить `scripts/sync_yclients_records.py --once`.
- Следующий UX-фокус: ускорять частые off-topic/info ветки внутри формы. Функционально состояние сохраняется, но `dialog_timing_slow` всё ещё встречается на AI semantic примерно 6-15 секунд.

## 2026-05-28 after two-gazebo live-dialog fix

- Закрыт smoke-блок из последнего Telegram-чата: `2 беседки на 02.06 и 19.06 + мангал/угли`, `19.06 на 13` во время первой заявки, `сколько стоит?` на будний день, `время поменяй с 11 до 08`, `активыне заявки`.
- Перед следующим ручным Telegram smoke проверить: первая реплика про две беседки должна отвечать и на info-часть, и на booking-часть; бот должен сказать, что оформляем по очереди, начать с 2 июня и помнить 19 июня как следующую дату.
- Проверить live: после выбора времени `11:00` итоговая сводка должна писать `до 08:00 следующего дня`, а не просто `11:00-08:00` без пояснения.
- Проверить live: обычный вопрос про цену выбранной беседки на ПН-ЧТ должен показывать скидку 50%, не только базовую цену.
- После этих user-facing фиксов можно возвращаться к refactor `message_handler.py`, но только маленькими behavior-preserving шагами. Следующие безопасные цели остаются: media scheduling/glue и fresh-start/stale-form glue.

## 2026-05-28 after context availability fix

- Live-кейс `беседку` -> `на 30 июня нас будет 20` закрыт: backend не должен отвечать из старого/пустого gazebo-cache, а обязан проверить локальный журнал и показать подходящие по вместимости варианты.
- Новый обязательный smoke перед Telegram-тестом: `на 30 июня нас будет 20`; ожидаемо для свежей БД сейчас: подходящие `Беседка №1`, `Беседка №8`, `Беседка №3`, `Крытая беседка`, без фразы `75 дней не нашла`.
- Второй smoke: если на дату свободны только маленькие беседки, бот должен написать, что на эту дату они не подходят по вместимости, и предложить ближайшую подходящую дату, не теряя `guests_count=20`.
- Третий smoke: на финальном подтверждении написать `а что мы подтверждаем?`, затем `давай отменим эту заявку`; ожидаемо: сначала summary черновика, затем abort черновика с сохранением контакта.
- Для будущих правок запускать `scripts/dialog_context_suite.py` вместе с `dialog_edge_suite.py` и `dialog_stress_suite.py`, потому что он ловит именно потерю контекста между сообщениями.
- Перед каждым live smoke по availability проверять `scripts/yclients_sync_status.py --strict`; если stale, выполнить `scripts/sync_yclients_records.py --once`. Сегодня stale-cache был подтверждён (`age_seconds=1676`) и обновлён до fresh.

## 2026-05-28 after refusal-routing fix

- Живой кейс `давай откажемся от брони` на шаге допов закрыт: backend теперь воспринимает это как отказ от незавершенной заявки, а не как продолжение availability/upsell.
- Важно для следующих правок: AI должен читать и понимать весь текст, но backend обязан иметь ранние приоритеты для destructive/state-changing intents: cancel/abort/reschedule/current-booking должны проходить до info/availability/upsell.
- В следующем Telegram smoke проверить: после предложения допов написать `давай откажемся от брони`; ожидаемый ответ - заявка не оформляется, контакт сохраняется, бот не говорит `свободно` и не предлагает допы.

## 2026-05-28 after best2info/live 6093 fixes

- `best2info` создан и подключен как клиентская база знаний для info-вопросов. Перед новыми изменениями не смешивать ее с `best2obs`: `best2obs` - память разработки, `best2info` - факты для клиента.
- Live-регрессии 6093 закрыты: 20 гостей, ближайшие подходящие даты, скидка ПН-ЧТ для беседок, уточнение конкретной даты и сохранение `time/duration/event_format` после допов.
- Перед реальным Telegram smoke по availability обязательно проверить свежесть YCLIENTS cache: `scripts/yclients_sync_status.py --strict`; если stale, выполнить `scripts/sync_yclients_records.py --once`.
- Ручной smoke для следующей проверки: `на 5 июня есть беседка` -> `20 чел` -> `так в итоге 20 человек влезит` -> `только эта свободна на 5 июня` -> `а на 8 июня свободно` -> вопрос про скидку на Беседку №1; затем отдельный state smoke `18,00` -> `на 5` -> `встреча однокласников` -> `кальян давайте`.
- После этих фиксов можно возвращаться к refactor `message_handler.py`: следующий безопасный срез - оставшийся media scheduling/glue или fresh-start/stale-form glue. Делать маленькими behavior-preserving шагами и повторять `compileall`, профильные regression-группы, соседние `post_booking/payments/cancel/reschedule`, `dialog_edge_suite.py` и `dialog_stress_suite.py`.

## 2026-05-28 before returning to message_handler refactor

- Edge-dialog interruptions are now covered by `scripts/dialog_edge_suite.py` 12/12: summary/off-topic during form, summary/info/cancel during confirmation, info/off-topic/no-then-reschedule during cancel, info/options during reschedule, and off-topic post-booking.
- User-facing fixes from the latest Telegram dialog are closed in code and tests: draft-summary for unfinished booking, soft handoff for emotional language, guard against AI-invented time/duration, and same-time reference for a second service.
- Before the next real Telegram smoke, check YCLIENTS freshness with `scripts/yclients_sync_status.py --strict`; if stale, run `scripts/sync_yclients_records.py --once`.
- Smoke prompts to recheck manually: "а че у меня по брони которую я хотел забронировать", then "ну че нибудь"; "что мы сейчас бронируем"; "отмени бронь, не будем" on confirmation; cancel-flow "а аванс возвращается?" then "нет, оставь"; "бля будем зажигать" on event-format step; second service "баньку тем же днем что и беседка" then "часы как там же"; one paid reschedule with "на денек позже, часы те же".
- Next refactor can return to remaining media scheduling/glue or fresh-start/stale-form glue. Keep changes behavior-preserving and rerun `compileall`, profile regression groups, neighboring `post_booking/payments/cancel/reschedule`, and `dialog_stress_suite.py`.

## 2026-05-27 next refactor step

- Post-booking low-risk helpers вынесены.
- Cancel-flow execution вынесен через callbacks для `delete_yclients_record_for_booking`, `bookings_repo` operations and handoff replies.
- Reschedule-flow продолжен: чистые helpers/тексты/selection/swap parsing, single execution, grouped/swap execution, grouped/swap orchestration и подбор новой беседки при переносе вынесены в `app/services/dialog/reschedule_flow.py`.
- Availability-flow продолжен: deterministic ответы, waitlist/no-availability, ближайшие свободные даты и общий availability executor вынесены в `app/services/dialog/availability_flow.py` через callbacks.
- Confirmation-flow вынесен: reserved/hold commands, side reply, pending payment reuse, hold creation helpers and awaiting-confirmation execution находятся в `app/services/dialog/confirmation_flow.py` через callbacks.
- Direct free-dates lookup вынесен в `availability_flow.py`; explicit photo reply вынесен в `media_flow.py`. Следующий безопасный шаг: оставшийся media scheduling/glue или расчистка glue-кода fresh-start/stale-form, только маленькими behavior-preserving разрезами.
- После каждого микрошагa повторять: `compileall`, профильную группу, соседние `post_booking/payments/cancel/reschedule`, затем `dialog_stress_suite.py`.

## 2026-05-27 webhook follow-up

- Application-level YooKassa webhook hardening сделан: secret, production fail-fast, body-size limit, smoke-тест.
- Перед публичным включением остаётся серверная часть: reverse proxy, HTTPS, firewall/body limits, затем регистрация `YOOKASSA_WEBHOOK_URL` в ЮKassa.
- Проверка: `python scripts/yookassa_webhook_hardening_smoke.py`.

## 2026-05-27 next production steps

- Production smoke с новым atomic hold/payment flow: два клиента на один объект/дату, повторное подтверждение оплаты, provider failure/retry.
- На сервере запускать один постоянный процесс `main.py`; `screen` можно временно, целевой вариант - `systemd`/supervisor.
- Проверить серверный `.env`: `MESSAGE_SUMMARY_AFTER_HOURS=48`, `YCLIENTS_SYNC_ENABLED=true`, корректная частота sync.
- YooKassa webhook включать наружу только через reverse proxy/HTTPS/secret/body-size limit.
- Следующий refactor: аккуратно резать grouped/swap reschedule execution через callbacks или переходить к `availability_flow`.

## Обязательно проверить

- Полный живой сценарий беседки: дата, гости, подходящие свободные варианты, фото, допы, телефон, оплата, подтверждение.
- Полный живой сценарий бани.
- Полный живой сценарий гостевого дома.
- Повторная бронь: имя и телефон сохраняются, остальные поля спрашиваются заново.
- Пауза 2+ часа: бот спрашивает продолжать старую анкету или новую.
- Отмена оплаченной брони: предупреждение про аванс, ожидание подтверждения, удаление/статус в журнале.
- Перенос оплаченной брони: объект, дата, время, смена беседки, подтверждения `да`, `да да`, `+`.
- Ситуация двух клиентов на один слот: второй получает отказ после первого hold.
- Отсутствие мест: waitlist создается, уведомление при освобождении не выглядит странно.
- Фото: автоотправка после даты+гостей, явный запрос фото, фото после оплаты.
- Голосовые: распознавание и обработка как обычного текста.
- Информационные вопросы: ответы берутся из базы знаний.

## Технические проверки

- `python -m compileall app scripts`.
- `python scripts/local_regression_suite.py --group fresh --group dates`.
- `python scripts/local_regression_suite.py --group gazebo --group media`.
- `python scripts/local_regression_suite.py --group prices --group upsell --group time`.
- `python scripts/local_regression_suite.py --group payments --group post_booking --group services --group waitlist --group handoff --group reminder`.
- `python scripts/local_regression_suite.py --group reschedule --group cancel`.
- `python scripts/validate_yclients_map.py`.
- `python scripts/db_status.py`.
- Smoke YCLIENTS и ЮKassa на безопасных тестовых данных.
- Проверить по логам `dialog_timing_slow`, что долгие живые ответы не упираются в нестабильный `db.connect`/`db.work`.

## Рефакторинг перед релизом

- Довынести из `message_handler.py` крупные сценарии: оставшийся media scheduling/glue и fresh-start/stale-form glue. Direct free-dates lookup, explicit photo reply, post-booking helpers, cancel-flow execution, confirmation-flow, single/grouped/swap reschedule layer, reschedule gazebo-change options и availability execution уже вынесены.
- После каждого выноса прогонять точечные регрессии и фиксировать поведение в `local_regression_suite.py`.
- Добавить per-test timeout и ускорить fixture/cleanup в regression suite. Длительность каждого check уже печатается.

## Перед production

- Настроить публичный webhook ЮKassa.
- Проверить `.env` на сервере.
- Проверить `YCLIENTS_SYNC_ENABLED` и частоту синка.
- Проверить, что `yclients_records` и `resource_busy_intervals` регулярно обновляются фоновым sync; клиентский availability теперь зависит от этих таблиц и не делает live fallback в YCLIENTS.
- Проверить, что тестовые заявки удалены из YCLIENTS.
- Проверить, что фото в `app/images/` соответствуют названиям объектов.
- Проверить admin chat и формат handoff-уведомлений.

## Позже

- Улучшить observability: отдельный health dashboard или команды диагностики.
- Разделить большой `message_handler.py` на модули по сценариям.
- Добавить отдельные e2e fixtures для YCLIENTS/ЮKassa без риска реальных записей.

## Текущий следующий шаг

- После live-чата `conversation_id=6093` перед возвратом к refactor нужно закрыть user-facing регрессии: expected-step parsing `20 чел` должен побеждать AI info-классификацию; уточнение конкретной даты на `awaiting_new_date` не должно листать `last_suggested_free_dates`; ответы по скидкам для беседок должны идти через discount-aware/knowledge path; AI-текст не должен переводить клиента к допам, если backend-состояние еще ждёт время/длительность/формат.
- После live-чата 2026-05-28 закрыты user-facing ошибки free-dates/stale-form glue, double-question after info, mixed selection+info, expected-step parsing для гостей и post-pause ack. Local regression, stress-suite и ручной live-like прогон прошли; перед реальным Telegram smoke обязательно проверить `scripts/yclients_sync_status.py --strict` или вручную обновить `scripts/sync_yclients_records.py --once`.
- Следующий крупный разрез: оставшийся media scheduling/glue или fresh-start/stale-form glue. Дробить на чистые texts/helpers, затем callbacks для side effects, сохранить wrappers в `message_handler.py`, прогнать `compileall`, профильные группы, `post_booking/payments/cancel/reschedule` и `dialog_stress_suite.py`.
- После semantic-router правки в живом тесте проверить свободные формулировки: "хочу баню", "а когда свободно для 10 человек", "поменяем на поменьше", "сколько стоит решетка", "беседка и баня".
- Перед этим использовать групповые регрессии: summary броней, отмена с подтверждением, перенос с заменой беседки, перенос с `да/да да/+`, и вопрос по цене/инфо внутри активного flow.
- После fresh-start правки обязательно в живом тесте проверить: старая анкета с беседкой и гостями -> сообщение "хочу баню" -> бот спрашивает дату бани и не использует старых гостей/дату.
- После semantic reschedule правки обязательно в живом тесте проверить: оплаченная баня -> "давайте сместим баню на 26 июня на то же время" -> бот предлагает подтвердить перенос, а не начинает новую анкету.
