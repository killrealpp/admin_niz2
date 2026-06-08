# Release Context Window Steps

Цель: довести `best2` до боевого MVP-релиза на сервере с `systemd`, разбив работу на шаги, каждый из которых помещается в один новый чат/контекстное окно.

Этот файл используется как маршрутный лист. В новом чате брать только один следующий шаг, доводить его до Definition of Done, обновлять `best2obs/log.md` и останавливаться. Не пытаться закрывать несколько шагов сразу, если пользователь явно не попросил.

## Общий стартовый промпт для каждого нового чата

```text
Прочитай AGENTS.md, best2obs/index.md, best2obs/log.md и best2obs/roadmap/release-context-window-steps.md.
Работаем только над Шагом N из release-context-window-steps.md.
Не переходи к следующему шагу без отдельного запроса.
Не меняй production-код, если шаг не требует этого явно.
После значимых изменений обнови best2obs/log.md, а если меняется roadmap/runbook - обнови индекс или связанные wiki-страницы.
```

Заменить `N` на номер текущего шага.

## Общие правила для всех шагов

- Перед любыми командами читать свежие `best2obs/index.md` и `best2obs/log.md`.
- Если есть DB-mutating regression или live smoke, после него выполнять cleanup + fresh sync:

```powershell
.\.venv\Scripts\python.exe scripts\clear_db.py
.\.venv\Scripts\python.exe scripts\sync_yclients_records.py --once
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
.\.venv\Scripts\python.exe scripts\live_db_hygiene_audit.py --limit 20
```

- Реальные YooKassa smoke и регистрацию webhook запускать только когда шаг прямо это требует.
- Graphify обновлять только после production-code changes через `.\best2graph\update_graph.ps1`; после wiki-only изменений не трогать.
- Root `graphify-out/cache` считать generated-шумом и не включать в релиз без отдельной сверки.
- Если внешний сбой DB/YCLIENTS/YooKassa похож на transient, сначала повторить диагностику, а не чинить бизнес-логику.

## Шаг 1. Release Inventory И Freeze

Назначение: понять точное состояние перед релизной подготовкой и заморозить scope.

В новом чате использовать общий промпт и добавить:

```text
Шаг 1: сделай release inventory и freeze. Не исправляй код, только проверь состояние, разложи dirty tree и обнови wiki.
```

Действия:

- Прочитать `best2obs/index.md`, `best2obs/log.md`, `best2obs/roadmap/pre-launch.md`, этот файл.
- Выполнить:

```powershell
git status --short
git diff --stat
git diff --name-status
git status --porcelain=v1 -- graphify-out best2graph\graphify-out
```

- Разложить изменения на группы: production-code, tests/scripts, `best2info`, `best2obs`, `best2graph`, root cache/generated.
- Проверить, нет ли неожиданных tracked deletions.
- Зафиксировать релизный freeze: до Шага 10 не начинать новый refactor `message_handler.py`, AI-speed оптимизации или large test-suite decomposition, если они не блокируют smoke.
- Обновить `best2obs/log.md` с краткой release inventory записью.

Definition of Done:

- Понятно, какие файлы уже dirty и почему.
- Нет неожиданных удалений или они явно вынесены пользователю.
- Зафиксировано: релизный scope = боевой MVP, не full hardening.

## Шаг 2. Local Baseline Gate

Назначение: подтвердить, что текущий код и знания проходят лёгкий baseline перед любыми server/release действиями.

В новом чате:

```text
Шаг 2: прогони local baseline gate. Если есть transient infra failure, повтори диагностику; если есть реальный code/test failure, остановись с отчетом.
```

Действия:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\test_db.py
.\.venv\Scripts\python.exe scripts\lint_best2info.py
.\.venv\Scripts\python.exe scripts\validate_yclients_map.py
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
git diff --check
```

Если YCLIENTS stale:

```powershell
.\.venv\Scripts\python.exe scripts\sync_yclients_records.py --once
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
```

Действия после команд:

- Записать в `best2obs/log.md`: дата, команды, результаты, `records_seen`, `last_error`, known warnings.
- Не менять production-code в этом шаге.

Definition of Done:

- Compile OK.
- DB OK.
- `best2info` lint OK.
- YCLIENTS map OK.
- YCLIENTS fresh или есть понятный blocker.
- `git diff --check` без новых проблем, кроме ожидаемых CRLF warnings.

## Шаг 3. Production Env Checklist

Назначение: подготовить точный список server `.env` значений перед деплоем.

В новом чате:

```text
Шаг 3: подготовь production env checklist. Не меняй секреты в репозитории. Сравни .env.example, config settings и roadmap, затем создай/обнови wiki-чеклист.
```

Действия:

- Открыть `.env.example`, `app/core/config.py`, `best2obs/architecture/auth.md`, `best2obs/architecture/api.md`.
- Создать или обновить `best2obs/operations/production-env-checklist.md`.
- В чеклисте явно зафиксировать production values:
  - `APP_ENV=production`
  - `APP_DEBUG=false`
  - `PREPAYMENT_MODE=percent`
  - `PREPAYMENT_PERCENT=50`
  - `YCLIENTS_SYNC_ENABLED=true`
  - `MESSAGE_SUMMARY_ENABLED=true`
  - `MESSAGE_SUMMARY_AFTER_HOURS=48`
  - `HTTP_TRUST_ENV=false`
  - `YOOKASSA_WEBHOOK_ENABLED=true`
  - `YOOKASSA_WEBHOOK_SECRET` non-empty
  - `YOOKASSA_WEBHOOK_URL=https://.../webhooks/yookassa`
  - `ADMIN_TELEGRAM_CHAT_ID` filled.
- Отдельно отметить: `PREPAYMENT_AMOUNT_RUB` не должен управлять production-суммой при `PREPAYMENT_MODE=percent`.

Проверки:

```powershell
.\.venv\Scripts\python.exe - <<'PY'
from app.core.config import get_settings
s = get_settings()
print(s.safe_summary())
PY
```

Эта проверка только показывает локальный config summary; не считать её production-проверкой.

Definition of Done:

- Есть wiki-чеклист production env.
- Нет секретов, записанных в git.
- Понятно, какие значения должен выставить сервер.

## Шаг 4. Production Runbook

Назначение: создать инструкцию запуска/остановки/диагностики, чтобы production не жил “в голове”.

В новом чате:

```text
Шаг 4: создай production runbook. Это wiki-only шаг, production-code не менять.
```

Действия:

- Создать `best2obs/operations/production-runbook.md`.
- Включить разделы:
  - pre-start checklist;
  - как проверить `.env`;
  - как запустить один `main.py`;
  - как проверить Telegram API;
  - как проверить YCLIENTS sync;
  - как проверить YooKassa webhook;
  - как остановить процесс;
  - что делать при stale sync;
  - что делать при DB timeout;
  - что делать при paid-but-journal-pending;
  - как чистить тестовые записи YCLIENTS.
- Добавить команды:

```powershell
.\.venv\Scripts\python.exe scripts\telegram_status.py
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
.\.venv\Scripts\python.exe scripts\live_db_hygiene_audit.py --limit 20
.\.venv\Scripts\python.exe scripts\db_status.py
```

- Добавить ссылку на runbook в `best2obs/index.md`.
- Обновить `best2obs/log.md`.

Definition of Done:

- Новый чат/админ может по runbook запустить, проверить и остановить бота.
- В runbook есть аварийные ветки для stale sync, DB timeout и pending payment.

## Шаг 5. Minimal Health Report

Назначение: сделать один read-only script для быстрой диагностики перед и после запуска.

В новом чате:

```text
Шаг 5: реализуй минимальный read-only scripts/live_health_report.py и покрой его безопасным smoke. Не меняй бизнес-логику.
```

Действия:

- Создать `scripts/live_health_report.py`.
- Скрипт должен только читать данные и печатать компактный report:
  - DB connectivity;
  - YCLIENTS sync freshness;
  - counts runtime tables;
  - active holds;
  - pending payments;
  - paid bookings without notification;
  - bookings with `journal_missing` или `yclients_create_error`;
  - pending `refund_required`;
  - last system errors/logs if available.
- Не делать cleanup, sync, webhook calls или любые writes.
- Добавить упоминание команды в `best2obs/operations/production-runbook.md`.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall scripts\live_health_report.py
.\.venv\Scripts\python.exe scripts\live_health_report.py
```

Definition of Done:

- Одна команда показывает, можно ли продолжать release/smoke.
- Скрипт read-only.
- Runbook ссылается на health report.

## Шаг 6. Server Deploy И systemd

Назначение: развернуть код на сервере и поднять один управляемый процесс.

В новом чате:

```text
Шаг 6: подготовь и проверь server deploy + systemd. Делай только server/deploy изменения, не меняй поведение бота.
```

Действия:

- На сервере разместить код в `/opt/best2` или другом явно выбранном каталоге.
- Создать venv и установить зависимости штатным способом проекта.
- Разместить server env file вне git, например `/etc/best2/best2.env`.
- Создать `systemd` unit:
  - `WorkingDirectory=/opt/best2`
  - `ExecStart=/opt/best2/.venv/bin/python /opt/best2/main.py`
  - `Restart=always`
  - `RestartSec=5`
  - `EnvironmentFile=/etc/best2/best2.env`
  - logs через journald.
- Убедиться, что не запущено два polling-процесса.

Проверки на сервере:

```bash
systemctl daemon-reload
systemctl start best2
systemctl status best2 --no-pager
journalctl -u best2 -n 100 --no-pager
```

Через 1-2 минуты:

```bash
/opt/best2/.venv/bin/python /opt/best2/scripts/telegram_status.py
/opt/best2/.venv/bin/python /opt/best2/scripts/yclients_sync_status.py --strict
/opt/best2/.venv/bin/python /opt/best2/scripts/live_health_report.py
```

Definition of Done:

- `systemd` держит один живой `main.py`.
- Telegram polling стартовал.
- YCLIENTS sync fresh.
- Health report без blocker-ов.

## Шаг 7. YooKassa Webhook Через HTTPS

Назначение: включить production webhook безопасно, без случайных реальных платежей.

В новом чате:

```text
Шаг 7: настрой YooKassa webhook через HTTPS/reverse proxy и зарегистрируй его только после локального hardening smoke.
```

Действия:

- Проверить application-level smoke:

```bash
/opt/best2/.venv/bin/python /opt/best2/scripts/yookassa_webhook_hardening_smoke.py
```

- Настроить reverse proxy:
  - публичный `https://DOMAIN/webhooks/yookassa`;
  - proxy на `127.0.0.1:8088`;
  - body-size limit <= `YOOKASSA_WEBHOOK_MAX_BODY_BYTES`;
  - HTTPS certificate valid;
  - внутренний `8088` не открыт наружу напрямую.
- Проверить server env:
  - `YOOKASSA_WEBHOOK_ENABLED=true`;
  - `YOOKASSA_WEBHOOK_SECRET` заполнен;
  - `YOOKASSA_WEBHOOK_URL` публичный HTTPS URL с path `/webhooks/yookassa`.
- Перезапустить service.
- Зарегистрировать webhook:

```bash
/opt/best2/.venv/bin/python /opt/best2/scripts/register_yookassa_webhook.py
```

Definition of Done:

- Webhook hardening smoke OK.
- HTTPS endpoint доступен.
- YooKassa webhook зарегистрирован для `payment.succeeded` и `payment.canceled`.
- `journalctl -u best2` не показывает webhook startup errors.

## Шаг 8. Full Automated Regression Gate

Назначение: перед живыми пользователями пройти полный автоматический набор.

В новом чате:

```text
Шаг 8: прогони full automated regression gate. Если тесты меняют БД, в конце обязательно cleanup + fresh sync.
```

Действия:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\test_db.py
.\.venv\Scripts\python.exe scripts\lint_best2info.py
.\.venv\Scripts\python.exe scripts\validate_yclients_map.py
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group fresh --group dates
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group gazebo --group media
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group prices --group upsell --group time
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group payments --group post_booking --group services --group waitlist --group handoff --group reminder
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group reschedule --group cancel
.\.venv\Scripts\python.exe scripts\dialog_context_suite.py
.\.venv\Scripts\python.exe scripts\dialog_edge_suite.py
.\.venv\Scripts\python.exe scripts\dialog_stress_suite.py
git diff --check
```

После DB-mutating checks выполнить cleanup + fresh sync из общих правил.

Действия после проверок:

- Записать результаты в `best2obs/log.md`.
- Если есть только `dialog_timing_slow`, но сценарии зелёные, записать как residual UX/performance risk, не блокер MVP.

Definition of Done:

- Все группы и suites OK.
- БД очищена после тестов.
- YCLIENTS fresh.
- Hygiene clean.

## Шаг 9. Manual Telegram Smoke

Назначение: проверить реальные клиентские маршруты в Telegram перед открытием аудитории.

В новом чате:

```text
Шаг 9: проведи ручной Telegram smoke по чеклисту. Не запускай реальные платежи без явного подтверждения в рамках smoke.
```

Перед smoke:

```powershell
.\.venv\Scripts\python.exe scripts\telegram_status.py
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
.\.venv\Scripts\python.exe scripts\live_health_report.py
```

Сценарии:

- Полная беседка: дата -> гости -> свободные варианты -> фото -> допы -> имя/телефон -> confirmation -> payment link.
- Полная баня: дата -> время/длительность -> пакеты/цена -> confirmation.
- Полный гостевой дом.
- Повторная бронь: имя/телефон сохраняются, слот-поля спрашиваются заново.
- Info внутри формы: вопрос про комаров/детей/парковку не ломает current step.
- Info внутри confirmation: вопрос, затем `да`, создаётся hold/payment.
- Два быстрых сообщения подряд от одного пользователя: порядок ответов корректный.
- Два клиента на один слот: второй получает отказ/альтернативу.
- Нет мест: waitlist создаётся и текст нормальный.
- Фото: явный запрос и автофото.
- Голосовое: транскрипция и обычная обработка.
- Отмена paid booking.
- Перенос paid booking.

После smoke:

- Проверить `scripts/live_health_report.py`.
- Если создавались тестовые записи, удалить их из YCLIENTS штатным cleanup-скриптом, затем clear_db + sync.
- Обновить `best2obs/log.md` с transcript summary и найденными блокерами.

Definition of Done:

- Все ручные маршруты прошли или для каждого blocker есть отдельная bug-запись.
- Нет тестовых записей, мешающих production.
- Health report clean.

## Шаг 10. Controlled Payment/Webhook Smoke

Назначение: проверить связку YooKassa -> webhook/polling -> booking finalization -> YCLIENTS.

В новом чате:

```text
Шаг 10: проведи controlled payment/webhook smoke. Это единственный шаг, где допустима реальная платежная ссылка, если пользователь подтвердил тестовую оплату.
```

Действия:

- Перед началом явно подтвердить у пользователя, что можно создать реальную YooKassa ссылку.
- Создать одну тестовую бронь с минимально контролируемым сценарием.
- Оплатить/симулировать только согласованный payment.
- Проверить:
  - `payments.status='paid'`;
  - `payments.payment_notified_at` заполнен;
  - `bookings.status` финальный;
  - `bookings.yclients_record_id` заполнен или есть корректный retry/journal-pending path;
  - webhook event processed idempotently;
  - клиент получил корректное сообщение;
  - admin получил нужные notifications.
- Проверить retry/fallback polling, если webhook не пришёл сразу.
- Удалить тестовую запись из YCLIENTS и очистить локальную БД после проверки.

Definition of Done:

- Payment success доходит до локальной booking и YCLIENTS.
- Нет duplicate booking/payment finalization.
- Тестовые артефакты очищены.
- `live_health_report.py` clean.

## Шаг 11. Launch Gate И Открытие Пользователей

Назначение: финальная проверка и переключение в режим реального приёма клиентов.

В новом чате:

```text
Шаг 11: проведи launch gate. Если все checks OK, зафиксируй go-live в best2obs/log.md.
```

Финальные проверки:

```bash
systemctl status best2 --no-pager
journalctl -u best2 -n 150 --no-pager
/opt/best2/.venv/bin/python /opt/best2/scripts/telegram_status.py
/opt/best2/.venv/bin/python /opt/best2/scripts/yclients_sync_status.py --strict
/opt/best2/.venv/bin/python /opt/best2/scripts/live_health_report.py
```

Проверить руками:

- Серверный `.env` production-ready.
- `PREPAYMENT_MODE=percent`.
- `YOOKASSA_WEBHOOK_ENABLED=true`.
- `ADMIN_TELEGRAM_CHAT_ID` рабочий.
- Тестовых записей в YCLIENTS нет.
- Фото в `app/images/` соответствуют объектам.
- Нет второго `main.py`.

Definition of Done:

- Все checks OK.
- Пользователи могут писать боту.
- Go-live запись добавлена в `best2obs/log.md`.
- Известные residual risks записаны отдельно: `dialog_timing_slow`, dirty tree/commit status, post-launch monitoring.

## Шаг 12. First-Day Monitoring

Назначение: первые часы после запуска не чинить вслепую, а наблюдать и фиксировать реальные проблемы.

В новом чате:

```text
Шаг 12: проведи first-day monitoring. Не делай refactor; только диагностика, точечные hotfixes при реальном blocker-е и запись наблюдений.
```

Каждые 30-60 минут в первый день:

```bash
systemctl status best2 --no-pager
journalctl -u best2 -n 200 --no-pager
/opt/best2/.venv/bin/python /opt/best2/scripts/yclients_sync_status.py --strict
/opt/best2/.venv/bin/python /opt/best2/scripts/live_health_report.py
```

Отдельно смотреть:

- `dialog_timing_slow`;
- `ai_semantic_degraded`;
- `yclients_sync_error`;
- `yclients_create_retry`;
- `payment_superseded_paid_manual_review`;
- `refund_required`;
- handoff/admin notifications.

Действия:

- Для каждого реального бага создать или обновить `best2obs/bugs/current-known-issues.md`.
- Для live-сценария, который стоит закрепить, добавить задачу в `best2obs/roadmap/dialog-regression-scenarios.md`.
- Hotfix делать только если проблема влияет на деньги, запись в YCLIENTS, отмену/перенос или массово ломает клиентский UX.

Definition of Done:

- Первый день задокументирован.
- Нет незамеченных payment/YCLIENTS failures.
- Список post-launch hardening задач обновлён.

## После MVP-релиза

Следующие работы не блокируют выход в MVP, если Шаги 1-12 закрыты:

- ускорение частых info/off-topic веток и уменьшение `dialog_timing_slow`;
- дальнейший разбор `message_handler.py`;
- разделение `scripts/local_regression_suite.py`;
- расширение `scripts/live_health_report.py` до полноценной observability;
- отдельные безопасные e2e fixtures для YCLIENTS/YooKassa.
