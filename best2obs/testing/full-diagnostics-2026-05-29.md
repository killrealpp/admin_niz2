# Full Diagnostics 2026-05-29

Цель: полный диагностический прогон проекта после серии live-dialog фиксов и расширения regression suites.

## Срез Проекта

- Файлов в репозитории: 171.
- Python-файлов в `app/`: 75.
- `app/services/message_handler.py`: 5447 строк; это всё ещё главный технический долг и зона риска при точечных правках.
- Тестовые entrypoints: `scripts/test_db.py`, `scripts/dialog_regression_smoke.py`, `scripts/local_regression_suite.py`, `scripts/dialog_context_suite.py`, `scripts/dialog_edge_suite.py`, `scripts/dialog_stress_suite.py`.
- Дополнительные smoke/операционные проверки: `scripts/yookassa_webhook_hardening_smoke.py`, `scripts/validate_yclients_map.py`, `scripts/yclients_smoke.py`, `scripts/yclients_sync_status.py --strict`.

## Операционная Диагностика

| Проверка | Статус | Детали |
|---|---:|---|
| PostgreSQL connection | OK | `db_status.py` подключился к `default_db`, схема `public`. |
| DB counts | OK | `users=2`, `conversations=2`, `messages=108`, `slot_holds=2`, `bookings=1`, `yclients_records=130`, `resource_busy_intervals=132`, `system_logs=0`. |
| Telegram bot API | OK | `@fnsmvsvmpvpovbot`, webhook пустой, `pending_update_count=0`. |
| YCLIENTS sync freshness | FIXED/OK | В начале strict был stale (`age_seconds=28528`). Выполнен `sync_yclients_records.py --once`; финальный strict fresh: `records_seen=125`, `records_upserted=125`, `last_error=None`. |
| YCLIENTS service/staff map | OK with retries | `validate_yclients_map.py`: `checked_configured_pairs=29`, `live_book_services=29`, `unmapped_live_services=none`. Во время проверки были transient SSL handshake timeout, retry помог. |
| YCLIENTS GET smoke | OK | `yclients_smoke.py` получил live services/staff. |
| YooKassa webhook hardening | OK | Локальный smoke webhook-защиты прошёл. |

## Тесты

| Команда | Статус | Итог |
|---|---:|---|
| `python -m compileall app scripts` | OK | Код компилируется после всех правок. |
| `scripts/test_db.py` | OK | DB smoke создал и удалил тестового пользователя/диалог. |
| `scripts/yookassa_webhook_hardening_smoke.py` | OK | Проверены secret/body/path guards webhook runner. |
| `scripts/validate_yclients_map.py` | OK | Live YCLIENTS ids соответствуют `services_map.yaml`. |
| `scripts/yclients_smoke.py` | OK | Live services/staff читаются через API. |
| `scripts/local_regression_suite.py` | OK | Полный regression suite прошёл. |
| `scripts/dialog_context_suite.py` | OK, 14/14 | Live/context сценарии держат дату, гостей, confirmation и вторую бронь. |
| `scripts/dialog_edge_suite.py` | OK, 14/14 | Edge interruptions не ломают form/confirmation/cancel/reschedule/post-booking. |
| `scripts/dialog_stress_suite.py` | OK, 13/13 | Живые формулировки, опечатки, отказы, переносы, info и фото проходят. |
| `scripts/dialog_regression_smoke.py` | OK after harness fix | Legacy smoke починен и прошёл. |
| `scripts/yclients_sync_status.py --strict` | OK | Финальный sync свежий: `age_seconds=212`, `records_seen=125`, `last_error=None`. |

## Исправлено Во Время Диагностики

- `scripts/dialog_regression_smoke.py` cleanup теперь удаляет `waitlist_requests` перед удалением `conversations`; иначе был FK-fail на старых тестовых данных.
- `scripts/dialog_regression_smoke.py` переведён с `now=2026-05-20` на `now=2026-05-29`, чтобы availability не считала свежий sync "будущим/протухшим" относительно фиксированной даты smoke.
- Устаревшие assertions legacy-smoke обновлены под текущие корректные ответы: info-вопрос на confirmation может отвечать коротко про мангал без слова `напишите`, а вопрос про бани может содержать форму `бани`.

## Не Запускалось

- `scripts/yookassa_smoke.py` не запускался, потому что создаёт реальную платёжную ссылку на 1 рубль во внешней YooKassa. Это не destructive, но оставляет внешний pending payment и лучше запускать как отдельный live payment smoke.
- `clear_db.py`, `init_db.py`, `register_yookassa_webhook.py`, cleanup/admin скрипты не запускались как production-mutating/destructive.

## Остаточные Риски

- YCLIENTS API периодически даёт transient SSL handshake timeout; retry сейчас спасает, но это внешний infra-риск.
- `yclients_sync_interval_seconds=5`, а availability считает sync свежим максимум 600 секунд. Если bot/sync runner выключен дольше 10 минут, strict и availability freshness снова будут падать.
- В regression/stress логах остаются `dialog_timing_slow` примерно 5-9 секунд на AI semantic/post-booking ветках. Функционально зелёно, UX-скорость под наблюдением.
- `message_handler.py` остаётся крупным координатором; дальнейший рефакторинг делать только маленькими behavior-preserving срезами после зелёных suites.
