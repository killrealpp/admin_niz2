# Large File Decomposition Plan

Цель: разгрузить самые крупные файлы проекта без изменения поведения бота. План нужен на будущее, потому что сейчас живое тестирование Telegram недоступно, а любые разрезы должны идти только после зелёного baseline.

## Текущее Состояние

- `app/services/message_handler.py` - около 6400 строк. Главный координатор диалога: routing, state guards, AI patch, info, availability, confirmation, post-booking, media, cancel/reschedule, payment glue.
- `scripts/local_regression_suite.py` - около 7800 строк. Главный regression-набор: fixtures, helpers, все группы проверок и runner в одном файле.
- Graphify показывает `message_handler.py` как центральный узел рядом с `confirmation_flow.py`, `availability_flow.py`, `reschedule_flow.py`, `payment_service.py`, `payment_status_runner.py`, `media_service.py` и regression suites.

## Принципы

- Не делать большой переписанный PR. Только маленькие behavior-preserving slices.
- Каждый slice сначала должен иметь понятную границу и тестовый baseline.
- AI остаётся semantic layer, backend остаётся state validator.
- Payment, YCLIENTS, cancel/reschedule side effects выносить только через явные callbacks или сервисные функции.
- После каждого slice прогонять профильные regression-группы и соседние flow.

## Phase 0 - Baseline Перед Рефакторингом

Перед любым кодовым разрезом:

```powershell
python -m compileall app scripts
python scripts/sync_yclients_records.py --once
python scripts/yclients_sync_status.py --strict
python scripts/lint_best2info.py
python scripts/validate_yclients_map.py
python scripts/dialog_context_suite.py
python scripts/dialog_edge_suite.py
python scripts/dialog_stress_suite.py
```

Потом обновить Graphify:

```powershell
.\best2graph\update_graph.ps1
```

## Phase 1 - `message_handler.py`: Commit/Result Boundary

Первый безопасный разрез - убрать повторяющееся сохранение результата.

Статус 2026-06-02: реализовано кодом. В `message_handler.py` добавлен `_commit_assistant_response()` и локальный `commit_reply()`; повторяющиеся assistant-message commits заменены на helper. Синтаксис и легкие проверки зелёные, Graphify обновлен. DB-зависимый Phase 1 regression нужно повторить после восстановления PostgreSQL-соединения: текущий запуск `dialog_context_suite.py` и `test_db.py` упирается в timeout к `95.214.62.243:5432`.

Сделать:

- ввести единый `FlowResult` или внутренний helper сохранения ответа;
- централизовать запись assistant message;
- централизовать `conversations_repo.update_after_message`;
- не менять порядок routing.

Проверки:

- `dialog_context_suite.py`
- `dialog_edge_suite.py`
- `dialog_stress_suite.py`
- `local_regression_suite.py --group payments --group post_booking --group fresh`

## Phase 2 - `message_handler.py`: Fresh/Stale/New Booking Flow

Статус 2026-06-02: реализовано кодом. Логика вынесена в `app/services/dialog/new_booking_flow.py`; handler сохранил ownership над side effects и persistence. Проверки Phase 2 зелёные: `test_db.py`, `dialog_context_suite.py` 19/19, `dialog_edge_suite.py` 15/15, `dialog_stress_suite.py` 13/13, `local_regression_suite.py --group fresh --group services --group post_booking --group payments`, плюс lightweight baseline и Graphify update.

Вынести в отдельный модуль логику:

- old draft после паузы;
- `нет` + новая заявка в том же сообщении;
- новая услуга поверх старого draft;
- новая заявка поверх active hold;
- сохранение только контакта при fresh-start.

Кандидат: `app/services/dialog/new_booking_flow.py`.

Риск: наследование старых даты, гостей, услуги, допов. Поэтому рядом гонять `fresh`, `services`, `post_booking`, `payments`.

## Phase 3 - `message_handler.py`: Info Flow

Следующий возможный срез после Phase 2. Не начинать в том же рабочем заходе; перед стартом снова выполнить lightweight baseline и убедиться, что DB-dependent regression остаётся зелёным.

Статус 2026-06-02: реализовано кодом. `app/services/dialog/info_flow.py` владеет common/deterministic info helpers, active-booking reference info, info-during-form и reply/next-question guards; `message_handler.py` оставляет тонкие wrappers и callback-builders, side effects/persistence остаются в handler. Проверки зелёные: `compileall`, `lint_best2info.py`, `validate_yclients_map.py`, `test_db.py`, context 19/19, edge 15/15, stress 13/13, targeted local regression по prices/time/payments/post_booking/services/upsell. Подробности: [[log]].

Вынести информационные ответы, которые не должны менять состояние анкеты:

- common info;
- price/info side replies;
- info внутри формы;
- info внутри confirmation/cancel/reschedule, если это уже не покрыто flow-модулями;
- возврат к текущему вопросу анкеты после info-ответа.

Кандидат: `app/services/dialog/info_flow.py`.

Правило: info-flow не меняет `service_type`, дату, время, гостей, допы и выбранный объект, кроме явно разрешённого state-safe patch текущего шага.

## Phase 4 - `message_handler.py`: Reference/Unavailable Flow

Вынести same-date/same-time references:

- `тем же днем`;
- `часы как там же`;
- `как у беседки`;
- недоступность скопированного слота;
- сохранение понятного UX, чтобы бот не выглядел забывшим дату/время.

Кандидат: `app/services/dialog/reference_flow.py`.

Перед кодом нужен red-first сценарий: оплаченная беседка -> новая баня тем же днем/тем же временем -> слот бани недоступен -> бот продолжает текущую баню, а не сбрасывает заявку.

## Phase 5 - `message_handler.py`: Media Scheduling Glue

Оставшийся media glue вынести ближе к `media_service.py` или отдельному `dialog/media_flow.py`.

Сделать:

- явный фото-запрос;
- auto-media после даты/гостей;
- антиспам `media_state`;
- фото нескольких броней в summary.

Проверки: `media`, `gazebo`, `post_booking`, `dialog_stress_suite.py`.

## Phase 6 - `local_regression_suite.py`: Разделить Suite

Второй большой файл лучше резать после стабилизации handler-slices.

Целевая структура:

```text
scripts/regression/
  __init__.py
  runner.py
  fixtures.py
  helpers.py
  checks_fresh.py
  checks_dates.py
  checks_gazebo.py
  checks_services.py
  checks_prices.py
  checks_upsell.py
  checks_time.py
  checks_payments.py
  checks_post_booking.py
  checks_cancel.py
  checks_reschedule.py
  checks_media.py
  checks_waitlist.py
```

Сохранить внешний интерфейс:

```powershell
python scripts/local_regression_suite.py --group fresh --group dates
```

Старый файл сначала должен стать thin wrapper, который вызывает новый runner.

Порядок разрезов:

1. Вынести `Check`, lock, общие helpers и cleanup в `helpers.py` / `fixtures.py`.
2. Вынести по одной группе checks за раз.
3. После каждого выноса запускать только эту группу и соседние группы.
4. В конце оставить `local_regression_suite.py` как совместимый entrypoint.

## Phase 7 - Smaller Service Cleanup

После двух главных файлов можно смотреть:

- `availability_service.py` - разделить fixed-service validation, gazebo capacity, local busy lookup.
- `payment_service.py` - отделить prepayment calculation, YooKassa link creation, paid finalization.
- `payment_status_runner.py` - отделить expired holds, paid sync, reminders.
- `media_service.py` - отделить service/variant resolution от отправки/выбора файлов.

Это делать только если Graphify и тесты показывают реальную сложность, а не ради красоты.

## Definition Of Done

Первый рубеж:

- `message_handler.py` меньше 4000 строк;
- `handle_incoming` заметно короче и читает flow по приоритетам;
- `local_regression_suite.py` ещё может быть большим, но helper/fixtures уже вынесены;
- все текущие suites зелёные.

Финальный рубеж:

- `message_handler.py` меньше 2500 строк;
- `local_regression_suite.py` является thin wrapper;
- новые regression-группы лежат в отдельных файлах;
- Graphify обновлён после разрезов;
- `best2obs/testing/dialog-test-matrix.md` отражает новые или перенесённые сценарии.

## Не Делать

- Не менять production-поведение без теста.
- Не удалять старые wrappers, пока regression не подтвердил совместимость.
- Не запускать реальные YooKassa smoke без явного решения.
- Не смешивать `best2obs` и `best2info`.
- Не превращать semantic understanding в набор keyword-only правил.
