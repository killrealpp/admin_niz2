# 2026-05-29 Best3 Core Parity

## Решение

Доводить `best3` до уровня `best2` через agent-first parity: переносить накопленные live-фиксы как scenario outcomes, policy rules и safe tools, а не копировать старый монолитный `message_handler.py`.

## Принципы

- AI остаётся главным в понимании диалога и выборе action.
- Backend остаётся источником правды для draft safety, availability, holds, payments, bookings и YCLIENTS.
- Сравнение с `best2` делается по outcome: поля draft, tool action, hold/payment/booking state.
- Буквальный текст ответа не является oracle, если смысл и состояние корректны.

## Scope Этого Решения

- В scope: новая бронь, info-вопросы, availability, hold/payment, paid finalization и current-booking/payment questions.
- Вне scope: полноценные cancel/reschedule/reminders/media/voice/multi-booking flows. Для них `best3` должен безопасно отвечать или отдавать handoff, не меняя оплаченные брони.

## Проверки

- `best3`: 23 unit tests, `core_parity_scenarios.py`, `shadow_compare.py`, `table_prefix_guard.py`, `compileall`, strict YCLIENTS и короткий real-AI smoke прошли.
- `best2`: `dialog_context_suite.py` 14/14 и профильный `local_regression_suite.py --group services --group gazebo --group upsell --group post_booking --group payments` прошли после внедрения.
