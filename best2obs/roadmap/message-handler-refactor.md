# Message Handler Refactor Plan

Цель: уменьшить `app/services/message_handler.py` без потери текущего поведения. Handler должен стать координатором, а не местом, где одновременно живут routing, patch parsing, info-ответы, availability, confirmation, cancel/reschedule, payment и сохранение состояния.

## Состояние На 2026-05-29

- `message_handler.py` занимает примерно 5.7k строк.
- Самый крупный фрагмент - `handle_incoming`: около 2k строк маршрутизации и сохранения результата.
- Уже вынесены крупные flow-модули:
  - `dialog/confirmation_flow.py`
  - `dialog/cancel_flow.py`
  - `dialog/reschedule_flow.py`
  - `dialog/availability_flow.py`
  - `dialog/post_booking_flow.py`
  - `dialog/media_flow.py`
  - `dialog/price_info.py`
  - `dialog/form_patches.py`
  - `dialog/stale_form.py`
- Последние live-баги чаще возникали на границах flow: old draft -> new booking, active/expired hold -> new request, info-question inside draft, same-date/same-time reference, unavailable slot cleanup.

## Главный Принцип

Не переносить "мозг" из AI в keyword-костыли. Сохраняем текущий принцип:

- AI понимает смысл сообщения и может предложить intent/action/patch.
- Backend валидирует состояние, права перехода и опасные действия.
- БД/YCLIENTS-cache является источником истины по броням, оплатам и свободности.
- `message_handler.py` только выбирает flow, вызывает его и сохраняет результат.

## Целевая Форма

`handle_incoming` должен читаться как короткая последовательность:

1. Загрузить user/conversation/history.
2. Сохранить user message.
3. Собрать `HandlerContext`.
4. Последовательно попробовать flow-обработчики по приоритету.
5. Получить `FlowResult`.
6. Одним helper-ом сохранить assistant message и conversation state.

Все flow должны возвращать одинаковый результат:

- `reply`
- `status`
- `current_step`
- `next_step`
- `form_data`
- optional metadata для media/payment/admin side effects, если понадобится

## Безопасные Разрезы

### Slice 1 - Commit/Result Helper

Ввести единый helper сохранения результата внутри `message_handler.py` или маленького `dialog/coordinator.py`:

- сохраняет assistant message;
- вызывает `conversations_repo.update_after_message`;
- возвращает reply;
- не меняет порядок routing.

Ожидаемый эффект: минус повторяющийся boilerplate, меньше риска, что один route сохранит `next_step`, а другой забудет.

Проверки:

- `python -m compileall app scripts`
- `scripts/dialog_context_suite.py`
- `scripts/dialog_edge_suite.py`
- `scripts/dialog_stress_suite.py`
- targeted `local_regression_suite.py --group fresh --group payments --group post_booking`

### Slice 2 - Stale/New Booking Flow

Вынести из handler логику:

- `stale_form_flow`;
- `should_offer_stale_form_choice`;
- "нет + новая заявка в том же сообщении";
- generic next booking поверх active hold;
- fresh draft with contact-only preservation.

Кандидат модуля: `app/services/dialog/new_booking_flow.py` или расширение `stale_form.py`.

Почему это важно: большинство live-регрессий про "бот подтянул старую беседку/гостей/допы в новую баню" живут именно здесь.

### Slice 3 - Info Flow

Вынести deterministic info routing:

- `_looks_like_info_question`;
- `_deterministic_info_reply`;
- `_answer_info_during_form`;
- `_active_booking_reference_info_reply`;
- `_append_current_service_question`;
- price/media/policy side replies, где они не меняют состояние.

Кандидат модуля: `app/services/dialog/info_flow.py`.

Правило: info-flow не должен менять `service_type`, дату, время, гостей или допы, кроме явно разрешённого state-safe patch текущего шага.

### Slice 4 - Same-Reference + Unavailable UX

Перед кодом добавить red-first сценарий:

- есть активная оплаченная беседка;
- клиент начинает баню "тем же днем";
- затем пишет "часы как там же";
- copied bathhouse slot недоступен;
- бот явно пишет, что недоступно именно это окно, но продолжает текущую баню и не выглядит так, будто забыл дату/время.

После теста решить UX:

- либо хранить `date/time/duration` в active draft вместе с `last_unavailable`;
- либо оставить поля только в `last_unavailable`, но сделать reply/current_step так, чтобы следующий ответ клиента продолжал ту же баню без повторного старта.

Кандидат модуля: `app/services/dialog/reference_flow.py`, с использованием существующих helpers из `form_patches.py` и `availability_flow.py`.

### Slice 5 - Main Route Table

После первых разрезов превратить `handle_incoming` в понятный список приоритетов:

1. reminder response;
2. stale/new booking checkpoint;
3. explicit media request;
4. existing booking command;
5. waitlist/handoff;
6. active cancel/reschedule/swap flow;
7. reserved hold / awaiting confirmation;
8. post-booking;
9. fast entry / direct free dates;
10. normal AI form flow.

Это не должен быть "магический router". Это просто явный порядок, чтобы новые баги было видно по месту.

## Что Не Делаем Сейчас

- Не переписываем `message_handler.py` одним большим PR.
- Не переносим payment/YCLIENTS side effects внутрь pure flow-модулей без callbacks.
- Не заменяем best2 на best3 внутри текущего production-кода.
- Не убираем deterministic backend guards там, где они защищают деньги, отмены, переносы, оплату и состояние заявки.

## Метрика Готовности

Первый практический рубеж:

- `handle_incoming` меньше примерно 1200 строк;
- `message_handler.py` меньше примерно 4k строк;
- все текущие suites зелёные;
- новый unavailable same-reference сценарий закрыт тестом.

Финальный желательный рубеж:

- `handle_incoming` меньше примерно 500 строк;
- вся логика маршрутов живёт в flow-модулях;
- новые live-баги добавляются сначала в `testing/dialog-test-matrix.md`, затем в suite, затем закрываются кодом.

## Обязательные Проверки После Каждого Slice

- `python -m compileall app scripts`
- `scripts/dialog_context_suite.py`
- `scripts/dialog_edge_suite.py`
- `scripts/dialog_stress_suite.py`
- релевантные группы `scripts/local_regression_suite.py`
- `scripts/yclients_sync_status.py --strict` после one-shot sync, если проверка зависит от свежей YCLIENTS-cache

