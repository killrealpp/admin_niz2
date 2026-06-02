# State/Text Consistency Hardening Plan

Статус 2026-06-01: риски 1-6 реализованы и проверены; пункт 7 остается отложенным. См. [[log]] за `implemented state/text consistency hardening package`.

Цель: закрыть риски рассинхронизации, когда бот написал клиенту одно, а `form_data`/БД сохранили другое. Рабочий принцип остается прежним: AI каждый раз понимает смысл входящего клиентского сообщения, а backend валидирует состояние, доступность, оплату, отмену, возвраты и допы.

Пункт 7 про большой разбор `message_handler.py` сейчас отложен. Этот пакет должен идти точечными guard-ами, сценариями и проверками вокруг текущей архитектуры, без большой декомпозиции координатора.

## Scope

1. AI-first semantic pass.
2. State/text consistency guard перед отправкой важных ответов клиенту.
3. Доработка допов, особенно разговорных фраз про кальян и смешанных price+selection сообщений.
4. Доработка отмены и возврата по границе 7 дней.
5. Админ-уведомления по возвратам и hygiene live-БД.
6. Regression coverage для semantic/state/cancel/refund/admin/live-hygiene сценариев.
7. Большой разбор `message_handler.py` не делать сейчас.

## AI-First Semantic Pass

- Для каждого входящего пользовательского сообщения в активном диалоге нужен один semantic AI-pass через текущий `AIResponse`: `intent`, `action`, `patch`, `changed_fields`.
- Deterministic branches остаются, но используют AI-result как понимание смысла, а не заменяют его keyword-only логикой.
- Если AI недоступен, оставить текущий safe fallback и логировать это как degraded path.
- Исключения: фоновые system events, payment runner notifications и другие не-клиентские события.

## State/Text Consistency Guard

Перед отправкой клиенту важные ответы нужно сверять с canonical state/БД:

- если текст говорит `кальян добавлен`, `form_data.upsell_items` должен содержать `кальян`;
- если confirmation summary показывает `Допы: не нужны`, state тоже должен содержать `["не нужны"]`;
- если ответ говорит `бронь отменена`, booking уже должен быть `cancelled`;
- если ответ говорит, что аванс можно вернуть, для paid booking должен быть создан `refund_required`.

При расхождении backend не должен отправлять AI/generated текст как есть. Ответ нужно пересобрать из canonical state или исправить state через уже существующий валидный backend path.

## Upsell Hardening

Расширить и закрепить сценарии для живых фраз:

- `кальянчик`;
- `калик один`;
- `давайте кальян`;
- `а сколько кальян`;
- `добавьте`;
- `ничего кроме кальяна`;
- `уберите все`;
- `кальян оставьте`.

Правила:

- выбранные positive допы нельзя перезаписать в `не нужны` простым последующим отказом, если клиент явно не сказал убрать уже выбранный доп;
- для mixed price+selection сначала ответить по цене, затем сохранить выбранные допы и показать следующий шаг или confirmation из state;
- summary и booking/YCLIENTS comment должны читаться из `form_data.upsell_items`, а не из свободного AI-текста.

## Cancel And Refund Hardening

Границы:

- меньше 7 дней до брони: клиенту пишем, что аванс не возвращается, admin `refund_required` не создается;
- ровно 7 дней и больше: клиенту пишем, что аванс можно вернуть, создается `refund_required`;
- несколько броней: refund event создается только для paid и refundable позиций.

Правила side effects:

- если удаление из YCLIENTS не удалось, не создавать refund event до успешной отмены; уходить в handoff как сейчас;
- admin refund notification должен быть idempotent по `booking_id`;
- существующая схема БД не меняется, для возвратов использовать текущие `system_logs` и `admin_notified_at`.

## Admin Notifications And Live DB Hygiene

- Проверить, что `payment_status_runner` отправляет все pending `refund_required` и затем ставит `admin_notified_at`.
- Добавить read-only диагностический сценарий/скрипт-аудит для live артефактов после regression:
  - active `bot_booking` interval без active booking;
  - paid/cancelled booking без нужного notification marker;
  - waitlist rows, измененные тестами;
  - `refund_required` без `admin_notified_at`.

## Regression Plan

Добавить regression tests:

- AI semantic вызывается для обычного ответа формы, upsell, confirmation-side-question, cancel-flow и post-booking.
- `AI сказал добавлено, state пустой` не проходит: ответ пересобирается из state или state фиксируется backend path-ом.
- Positive addon survives later negative: `кальян` -> имя -> телефон -> `нет` не превращает summary в `Допы: не нужны`.
- Mixed addon price+selection saves item and does not repeat old upsell question.
- Cancel refund boundary: 6 days, exactly 7 days, 8+ days.
- Multi-booking cancel: частичный refundable список создает события только нужным броням.
- Admin refund notification sends all pending logs and marks each as notified.

После реализации:

```powershell
python -m compileall app scripts
python scripts/local_regression_suite.py --group upsell
python scripts/local_regression_suite.py --group cancel
python scripts/local_regression_suite.py --group post_booking --group payments
python scripts/dialog_context_suite.py
python scripts/dialog_edge_suite.py
python scripts/dialog_stress_suite.py
```

Затем выполнить read-only live DB hygiene audit.

## Assumptions

- Backend остается источником истины: AI понимает намерение, но не решает оплату, свободность, отмену, возврат и финальное состояние.
- Пакет не должен менять схему БД.
- Большой refactor/decomposition `message_handler.py` переносится на период после полного зеленого сценарного пакета.
