# Project Hardening Master Plan

Цель: превратить `best2` из рабочего, но нервного live-бота в более предсказуемую систему: меньше большой ручной маршрутизации, дешевле проверки, устойчивее интеграции, понятнее production-запуск.

Этот файл написан как стартовая инструкция для нового чата. Его можно открыть после `best2obs/index.md` и `best2obs/log.md` и идти по фазам сверху вниз.

## Контекст На 2026-06-03

- Production-код уже содержит много незакоммиченных изменений последних live-fix пакетов.
- `message_handler.py` всё ещё главный координатор диалога, около 5966 строк; `handle_incoming()` начинается около строки 4730.
- `local_regression_suite.py` около 8360 строк и умеет запускать группы, но не отдельные named-case проверки.
- Внешние зависимости остаются источником нестабильности: PostgreSQL, YCLIENTS, YooKassa, Telegram, OpenRouter/OpenAI.
- Правильная Graphify-карта лежит в `best2graph/graphify-out/graph.json`; root `graphify-out/cache` может содержать старые generated/untracked cache-файлы и не должен смешиваться с рабочей картой.
- Последние банные live-сценарии проверены по одному без реального LLM-провайдера и зелёные.

## Главные Минусы, Которые Этот План Закрывает

1. Большой `message_handler.py` и высокая цена точечных правок.
2. Большой `local_regression_suite.py`, отсутствие удобного single-case runner.
3. Медленные/дорогие AI semantic ветки и `dialog_timing_slow`.
4. Хрупкость вокруг PostgreSQL/YCLIENTS/YooKassa и stale cache.
5. Много ручных операционных шагов перед live smoke.
6. Несколько источников правды: `services_map`, `best2info`, тексты в коде, локальная БД, YCLIENTS.
7. Не до конца production-ready webhook/process/observability.
8. Graphify полезен, но его update уже ломал карту при incremental/doc-only сценарии.
9. Рабочее дерево грязное, сложно отделять пользовательские изменения, generated artifacts и текущий пакет.

## Общие Правила Работы

- Не менять production-код без явного запроса.
- Перед каждым кодовым этапом читать:
  - `best2obs/index.md`
  - `best2obs/log.md`
  - этот файл
  - релевантные страницы из `best2obs/bugs/`, `best2obs/architecture/`, `best2obs/testing/`
- Для архитектуры/refactor сначала спрашивать Graphify, затем открывать конкретные файлы.
- Не запускать `graphify codex install`.
- После значимых изменений кода обновлять карту через `.\best2graph\update_graph.ps1`, но если менялась только wiki, карту не трогать.
- Любой DB-mutating regression завершать очисткой и fresh sync:

```powershell
.\.venv\Scripts\python.exe scripts\clear_db.py
.\.venv\Scripts\python.exe scripts\sync_yclients_records.py --once
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
.\.venv\Scripts\python.exe scripts\live_db_hygiene_audit.py --limit 20
```

- Реальные YooKassa smoke не запускать без отдельного решения, потому что они создают внешние ссылки.
- Если тест упал на `psycopg2.OperationalError`, SSL EOF, DB timeout или YCLIENTS transient, сначала повторить короткую диагностику, а не чинить бизнес-логику наугад.

## Фаза 0. Стабилизация Перед Любой Работой

Цель: понять, что уже изменено, что можно трогать, и есть ли рабочий baseline.

### 0.1. Прочитать память

```powershell
Get-Content .\best2obs\index.md -Encoding UTF8 -TotalCount 120
Get-Content .\best2obs\log.md -Encoding UTF8 -TotalCount 160
Get-Content .\best2obs\bugs\current-known-issues.md -Encoding UTF8 -TotalCount 220
Get-Content .\best2obs\roadmap\pre-launch.md -Encoding UTF8 -TotalCount 220
```

Ожидаемо:

- понятно, какой пакет был последним;
- понятно, какие проверки уже зелёные;
- понятно, есть ли открытый live-баг или это refactor/улучшение.

### 0.2. Посмотреть рабочее дерево

```powershell
git status --short
git diff --stat
git diff --name-status
```

Разделить изменения на группы:

- production-код;
- tests/scripts;
- `best2info`;
- `best2obs`;
- `best2graph`;
- root `graphify-out/cache`;
- случайные/generated artifacts.

Стоп-условие: если есть неожиданные удаления или изменения неясного происхождения, сначала описать их пользователю. Не откатывать чужие изменения.

### 0.3. Проверить базовую БД и sync

```powershell
.\.venv\Scripts\python.exe scripts\test_db.py
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
```

Если sync stale:

```powershell
.\.venv\Scripts\python.exe scripts\sync_yclients_records.py --once
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
```

Если `test_db.py` падает на внешний timeout:

- записать это как verification blocker;
- не начинать крупный refactor;
- можно делать только docs/wiki или чисто локальные parser/unit изменения без DB.

### 0.4. Лёгкий baseline

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\lint_best2info.py
.\.venv\Scripts\python.exe scripts\validate_yclients_map.py
git diff --check
```

Ожидаемо:

- compile OK;
- lint/map OK;
- `git diff --check` максимум с обычными CRLF warnings.

## Фаза 1. Привести В Порядок Рабочее Дерево И Артефакты

Цель: новый чат должен начать с понятной рабочей поверхности.

### 1.1. Зафиксировать, что такое root `graphify-out`

Проблема: правильная карта проекта лежит в `best2graph/graphify-out`, а root `graphify-out/cache` уже засорялся при случайном `graphify update .`.

Шаги:

1. Проверить статус:

```powershell
git status --porcelain=v1 -- graphify-out best2graph\graphify-out
```

2. Не удалять pre-existing untracked cache-файлы, если они были до текущего захода.
3. Не запускать root `graphify update .` ради проекта.
4. Для кода использовать только:

```powershell
.\best2graph\update_graph.ps1
.\best2graph\.venv\Scripts\graphify.exe query "QUESTION" --graph .\best2graph\graphify-out\graph.json --budget 1200
```

### 1.2. Сделать статус-памятку для пользователя

Если пользователь попросит продолжать код:

- сначала назвать, что в tree уже dirty;
- сказать, какие файлы будут изменяться;
- не чистить root cache без отдельной необходимости;
- не запускать Graphify после чисто wiki-изменений.

### 1.3. Definition of Done фазы

- Нет неожиданных tracked deletions.
- `best2graph/graphify-out/GRAPH_REPORT.md` показывает code map, не doc-only.
- Graphify query находит `message_handler.py`.
- Root generated мусор не путается с рабочей картой.

## Фаза 2. Дешёвые Single-Scenario Проверки

Цель: проверять живые фразы по одной, без запуска огромных групп и без реальных LLM-запросов.

### 2.0. Статус 2026-06-03

- Первый срез реализован в `scripts/local_regression_suite.py`: добавлены `RegressionCase`, `--case`, `--list-cases`, `--fake-ai`, `--real-ai`.
- Fake AI остаётся default; real AI включается только явным `--real-ai` или старым `BEST2_REGRESSION_REAL_AI`.
- В registry перенесены первые частые live-cases по бане, ценам и payment text; старые `--group` продолжают работать и используют registry для перенесённых сценариев.
- Проверено: `--list-cases`, `--case "bathhouse pool included info during form"`, `--case "bathhouse 500 follow-up manual admin" --fake-ai`, `--case "bathhouse ten hour price formula"`, `--group services`.
- Следующий срез: расширить registry на остальные частые live-cases и затем начинать Фазу 4 с выноса runner/fixtures, не ломая совместимый entrypoint.

### 2.1. Что сейчас не так

`scripts/local_regression_suite.py` умеет только:

```powershell
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group services
```

Минус: если нужно проверить один live-сценарий, приходится гонять группу, тратить время, трогать БД и ждать внешние зависимости.

### 2.2. Целевое поведение

Добавить named-case runner:

```powershell
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --case "bathhouse pool included info during form"
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --list-cases
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --case "bathhouse 500 follow-up manual admin" --fake-ai
```

По умолчанию:

- fake AI включён;
- реальные YooKassa/YCLIENTS side effects застаблены;
- после run можно опционально выполнить cleanup.

### 2.3. Пошаговая реализация

1. Открыть Graphify:

```powershell
.\best2graph\.venv\Scripts\graphify.exe query "How local_regression_suite registers and runs checks" --graph .\best2graph\graphify-out\graph.json --budget 1200
```

2. Открыть `scripts/local_regression_suite.py` вокруг:
   - `Check`
   - `TEST_GROUPS`
   - `main()`
   - `run()`
   - `_cleanup()`

3. Добавить структуру `RegressionCase`:

```python
@dataclass(frozen=True)
class RegressionCase:
    group: str
    name: str
    factory: Callable[[datetime], Check]
```

4. Не переписывать все тесты сразу. Сначала собрать registry рядом с текущим `run()`:

```python
REGRESSION_CASES = [
    RegressionCase("services", "bathhouse blocks 500 without unavailable alternatives", _test_bathhouse_blocks_500_without_unavailable_alternatives),
]
```

5. Добавить `--case` и `--list-cases`.
6. В старом group-run временно оставить текущие `run("group", lambda: ...)`, чтобы не ломать поведение.
7. Перенести 5-10 самых частых live cases в registry.
8. После стабилизации заменить group-run на проход по registry.

### 2.4. Проверки

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --list-cases
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --case "bathhouse pool included info during form"
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group services
git diff --check
```

После DB-mutating checks:

```powershell
.\.venv\Scripts\python.exe scripts\clear_db.py
.\.venv\Scripts\python.exe scripts\sync_yclients_records.py --once
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
.\.venv\Scripts\python.exe scripts\live_db_hygiene_audit.py --limit 20
```

### 2.5. Definition of Done

- Можно запустить один сценарий по имени.
- Можно вывести список сценариев.
- Fake AI по умолчанию не делает реальных LLM-запросов.
- Старые `--group` работают как раньше.
- Новый live-сценарий добавляется в одно место.

## Фаза 3. Уменьшить `message_handler.py`

Цель: сократить главный риск регрессий: большой coordinator с пересекающимися ветками.

### 3.0. Статус 2026-06-03

- Фаза 3 начата с маленького behavior-preserving среза fresh/new-booking helper extraction. `new_booking_flow.py` теперь содержит pure helpers для additional/generic/new booking predicates, reuse `last_discussed_service_type`, fresh form builder, immediate fresh-start reply и AI fresh patch builder.
- `message_handler.py` оставляет wrappers и side effects; размер уменьшен примерно `5936 -> 5837` строк. Проверки зелёные: groups `fresh/services/post_booking/payments`, context 19/19, edge 15/15, stress 13/13. Graphify восстановлен full extract (`1800 nodes`, `7458 edges`, `84 communities`).
- Следующий разумный срез Фазы 3: продолжить Slice A вокруг fresh/stale glue или перейти к Slice B media scheduling, но только маленькими behavior-preserving шагами с тем же regression набором.

### 3.1. Принципы разреза

- Только behavior-preserving slices.
- Не переносить side effects внутрь чистых flow-модулей без callbacks.
- `message_handler.py` может оставлять wrappers, чтобы старые tests/monkeypatch не ломались.
- Каждый slice должен иметь свой targeted regression.
- После каждого slice обновлять Graphify.

### 3.2. Метрики перед началом

```powershell
(Get-Content .\app\services\message_handler.py | Measure-Object -Line).Lines
rg -n "def handle_incoming|def _ai_first_patch|def _capacity_mismatch_reply" app/services/message_handler.py
```

Записать в `best2obs/log.md`:

- сколько строк было;
- какой slice планируется;
- какие проверки будут обязательны.

### 3.3. Slice A: fresh-start/stale-form glue

Уже есть `app/services/dialog/new_booking_flow.py`, но в `message_handler.py` всё ещё остаётся glue вокруг свежего старта, старого draft, новой услуги поверх старого контекста.

Шаги:

1. Graphify query:

```powershell
.\best2graph\.venv\Scripts\graphify.exe query "fresh stale new booking flow wrappers in message_handler and new_booking_flow" --graph .\best2graph\graphify-out\graph.json --budget 1600
```

2. Открыть:
   - `app/services/message_handler.py`
   - `app/services/dialog/new_booking_flow.py`
   - `app/services/dialog/stale_form.py`
   - `scripts/local_regression_suite.py` group `fresh`

3. Найти оставшиеся helper-ветки fresh/stale в `message_handler.py`.
4. Вынести только чистую decision/orchestration часть в `new_booking_flow.py`.
5. Side effects оставить в callbacks:
   - update conversation;
   - assistant commit;
   - DB writes;
   - payment/YCLIENTS touchpoints.
6. Сохранить wrappers в `message_handler.py`.

Проверки:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group fresh --group services --group post_booking --group payments
.\.venv\Scripts\python.exe scripts\dialog_context_suite.py
.\.venv\Scripts\python.exe scripts\dialog_edge_suite.py
.\.venv\Scripts\python.exe scripts\dialog_stress_suite.py
git diff --check
.\best2graph\update_graph.ps1
```

Стоп-условия:

- старая анкета наследует дату/гостей в новую услугу;
- `нет + новая заявка` теряет текущую услугу;
- paid booking начинает отменяться/сбрасываться при новой заявке.

### 3.4. Slice B: media scheduling glue

Проблема: фото и media scheduling исторически пересекались с summary, explicit photo, gazebo selection и post-booking.

Целевой модуль:

- расширить `app/services/dialog/media_flow.py` или создать `app/services/dialog/media_scheduling_flow.py`.

Шаги:

1. Graphify query:

```powershell
.\best2graph\.venv\Scripts\graphify.exe query "media scheduling explicit photo auto media booking summary in message_handler media_flow media_service" --graph .\best2graph\graphify-out\graph.json --budget 1600
```

2. Открыть:
   - `app/services/message_handler.py`
   - `app/services/dialog/media_flow.py`
   - `app/services/media_service.py`
   - `scripts/local_regression_suite.py` group `media`

3. Выписать все места, где handler решает отправлять/планировать фото.
4. Разделить:
   - чистое решение: надо ли фото;
   - выбор media target;
   - side effect отправки.
5. Вынести чистое решение в media-flow.
6. Оставить Telegram/file side effects в handler/bot layer.

Проверки:

```powershell
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group media --group gazebo --group post_booking
.\.venv\Scripts\python.exe scripts\dialog_context_suite.py
.\.venv\Scripts\python.exe scripts\dialog_edge_suite.py
.\.venv\Scripts\python.exe scripts\dialog_stress_suite.py
```

Manual smoke после запуска:

- `а беседки покажете?`
- дата + гости по беседке, ожидается автофото;
- после оплаты спросить фото;
- summary двух броней, где есть беседка.

### 3.5. Slice C: reference/unavailable flow

Проблема: фразы вроде `тем же днем`, `часы как там же`, `как у беседки` требуют аккуратного копирования контекста. Если слот недоступен, бот может выглядеть так, будто потерял дату/время.

Целевой модуль:

```text
app/services/dialog/reference_flow.py
```

Шаги:

1. Сначала red-first test:
   - paid gazebo exists;
   - user starts bathhouse second booking;
   - asks same date/time;
   - copied bathhouse slot unavailable;
   - reply says which copied slot is unavailable and asks new time/duration without losing bathhouse draft.

2. Graphify query:

```powershell
.\best2graph\.venv\Scripts\graphify.exe query "same date same time reference unavailable second service flow" --graph .\best2graph\graphify-out\graph.json --budget 1600
```

3. Extract pure helpers:
   - detect reference phrase;
   - resolve source booking/hold;
   - apply reference to target draft;
   - build unavailable copied-slot reply.

4. Keep DB access and availability execution in callbacks/service layer.

Проверки:

```powershell
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group services --group time --group post_booking
.\.venv\Scripts\python.exe scripts\dialog_stress_suite.py
```

### 3.6. Slice D: final state/action priority table

Цель: сделать `handle_incoming()` читаемым по приоритетам.

Вынести в документ/кодовую структуру порядок:

1. incoming user message persisted;
2. conversation lock/context;
3. destructive intents: cancel/abort/reschedule/current-booking;
4. active payment/hold handling;
5. active confirmation side questions;
6. active form expected-step parsing;
7. info side replies;
8. availability;
9. AI semantic fallback;
10. assistant commit.

Не менять поведение сразу. Сначала добавить комментарий/док в `architecture/backend.md`, потом маленькими PR/slices приблизить код.

### 3.7. Definition of Done для фазы 3

- `message_handler.py` меньше 4500 строк.
- `handle_incoming()` не содержит длинных доменных веток media/fresh/reference.
- Для каждого вынесенного flow есть отдельный модуль и regression coverage.
- Graphify показывает меньше связей от `message_handler.py` к деталям сценариев.

## Фаза 4. Разделить `local_regression_suite.py`

Цель: ускорить работу и уменьшить риск сломать тестовый раннер.

### 4.1. Целевая структура

```text
scripts/regression/
  __init__.py
  runner.py
  registry.py
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
  checks_handoff.py
  checks_reminder.py
```

`scripts/local_regression_suite.py` должен остаться совместимым entrypoint.

### 4.2. Порядок

1. Сначала реализовать Phase 2 single-case runner.
2. Вынести `Check`, lock, `_cleanup`, `_send`, `_latest_state`, `_base_form` в `fixtures.py`/`helpers.py`.
3. Оставить thin imports в старом файле.
4. Вынести одну маленькую группу, например `prices`.
5. Проверить:

```powershell
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --group prices
.\.venv\Scripts\python.exe scripts\local_regression_suite.py --case "bathhouse ten hour price formula"
```

6. Затем выносить группы по одной:
   - `time`
   - `services`
   - `upsell`
   - `fresh`
   - `media`
   - `post_booking`
   - `payments`
   - `cancel`
   - `reschedule`
   - остальные.

### 4.3. Не Делать

- Не менять fixtures одновременно с переносом многих групп.
- Не переименовывать test names без причины.
- Не менять DB cleanup semantics.
- Не запускать real AI по умолчанию.

### 4.4. Definition of Done

- `local_regression_suite.py` меньше 500 строк.
- `--group` и `--case` работают.
- Время каждой проверки печатается.
- Можно запускать один live regression без большого набора.

## Фаза 5. Ускорить И Удешевить AI Ветки

Цель: меньше `dialog_timing_slow`, меньше real AI вызовов, меньше стоимости ручных проверок.

### 5.1. Сначала собрать данные

Добавить или использовать существующие логи:

- `dialog_timing_slow`;
- duration по шагам `db.pool.checkout`, `db.work`, `ai.semantic`, `availability`, `commit`;
- event_type для degraded AI.

Команды поиска:

```powershell
rg -n "dialog_timing_slow|ai_semantic_degraded|state_text_consistency_rebuilt" app scripts best2obs
```

### 5.2. Сделать список частых fast-path вопросов

Кандидаты:

- парковка;
- дети;
- животные;
- комары;
- бассейн;
- алкоголь в бане;
- цена допов;
- что сейчас бронируем;
- фото;
- что ещё можно забронировать.

Правило: deterministic short-circuit должен быть безопасен и не менять state, если это info-вопрос.

### 5.3. Порядок внедрения

1. Для каждой частой фразы добавить single-case regression.
2. Только потом добавить deterministic helper.
3. Проверить, что state не меняется.
4. Проверить, что reply возвращает текущий вопрос анкеты.
5. Проверить, что real AI не вызывался, если test monkeypatch ставит fail-on-call.

### 5.4. Cost Controls

Добавить в test tools:

- fake AI by default;
- explicit `--real-ai` only when пользователь просит;
- warning перед real AI smoke;
- счетчик вызовов AI в regression output.

### 5.5. Definition of Done

- Частые info/off-topic ветки отвечают быстро.
- `dialog_timing_slow` больше не появляется на стандартных info-фразах.
- Real AI нужен только для сложного semantic parsing, а не для простых FAQ.

## Фаза 6. Укрепить Интеграции И Availability

Цель: чтобы внешние сбои не превращались в ложные ответы клиенту.

### 6.1. PostgreSQL

Минусы:

- DB timeout/SSL EOF уже случались во время проверок.
- Long regression может падать из-за внешнего слоя, а не из-за бизнес-логики.

План:

1. Добавить отдельный DB health script, если текущих мало:
   - pool init;
   - direct connect;
   - simple select;
   - transaction test;
   - SSL mode/host info.

2. В regression runner отличать:
   - assertion failure;
   - infrastructure failure.

3. Для infra failure печатать:
   - command to retry;
   - last successful sync;
   - whether DB port reachable.

4. Не чинить routing при infra failure без повторного воспроизведения.

### 6.2. YCLIENTS sync

Минусы:

- availability зависит от локальных tables;
- stale cache может дать неправильный UX;
- fixed services требуют `book_times`.

План:

1. Перед live smoke всегда:

```powershell
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
```

2. Если stale:

```powershell
.\.venv\Scripts\python.exe scripts\sync_yclients_records.py --once
```

3. Добавить/усилить monitoring:
   - age_seconds;
   - records_seen;
   - last_error;
   - next scheduled sync;
   - number of `resource_busy_intervals`.

4. Добавить alert/admin notice, если sync stale дольше N минут.
5. Для availability replies избегать фразы `свободно`, если fixed-service live validation недоступен.

### 6.3. YooKassa

Минусы:

- public webhook требует reverse proxy/HTTPS/body limits;
- без webhook подтверждение зависит от polling/следующего сообщения;
- smoke может создать реальную ссылку.

План:

1. Проверить `.env`:
   - production prepayment mode;
   - amount/percent;
   - webhook secret;
   - webhook URL.

2. На сервере настроить:
   - reverse proxy;
   - HTTPS;
   - request body limit;
   - firewall;
   - systemd service.

3. Прогнать application-level smoke:

```powershell
.\.venv\Scripts\python.exe scripts\yookassa_webhook_hardening_smoke.py
```

4. Реальный YooKassa smoke только по отдельному разрешению.

### 6.4. Telegram process

Минусы:

- важно запускать один `main.py`;
- параллельные updates уже были риском;
- background loops завязаны на один процесс.

План:

1. Перед запуском:

```powershell
Get-Process | Where-Object { $_.ProcessName -like "*python*" }
```

2. Запустить один процесс.
3. Проверить через 1-2 минуты:

```powershell
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
```

4. В live smoke отправить два сообщения подряд и проверить порядок ответов.

## Фаза 7. Источники Правды И Knowledge Hygiene

Цель: цены, услуги и правила не должны расходиться между кодом, `best2info`, `.env` и YCLIENTS.

### 7.1. Текущие источники

- `config/services_map.yaml` - service ids, staff ids, durations, prices.
- `best2info/` - клиентская база знаний для natural replies.
- `best2obs/` - память разработки, не клиентские факты.
- YCLIENTS - внешний журнал и source for sync.
- Локальная БД - runtime state and availability cache.
- `.env` - режим предоплаты, tokens, sync settings.

### 7.2. План

1. Продолжать запускать:

```powershell
.\.venv\Scripts\python.exe scripts\lint_best2info.py
.\.venv\Scripts\python.exe scripts\validate_yclients_map.py
```

2. Добавить, если ещё нет:
   - check, что цены из `best2info/prices/*.md` не расходятся с `services_map`;
   - check, что bathhouse package text совпадает с config;
   - check, что `.env.example` production-safe и не содержит test-only дефолтов.

3. Перед изменением цены:
   - сначала `services_map`;
   - затем `best2info/prices`;
   - затем regression price checks;
   - затем `best2obs/log`.

### 7.3. Definition of Done

- Один script ловит расхождение цен/пакетов.
- `best2info` не содержит orphan/битых ссылок.
- Runtime replies не берут availability из knowledge text.

## Фаза 8. Production Runbook

Цель: убрать “магическую ручную последовательность” из головы.

### 8.1. Создать runbook

Файл:

```text
best2obs/operations/production-runbook.md
```

Если папки нет, создать.

Содержание:

- как проверить `.env`;
- как запустить один `main.py`;
- как проверить YCLIENTS sync;
- как проверить YooKassa webhook;
- как остановить процесс;
- что делать при stale sync;
- что делать при DB timeout;
- что делать при paid-but-journal-pending;
- что делать при тестовой записи в YCLIENTS.

### 8.2. Минимальный health checklist

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\test_db.py
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
.\.venv\Scripts\python.exe scripts\live_db_hygiene_audit.py --limit 20
.\.venv\Scripts\python.exe scripts\lint_best2info.py
.\.venv\Scripts\python.exe scripts\validate_yclients_map.py
```

### 8.3. Manual smoke list

Держать коротким:

1. Полная беседка: дата, гости, варианты, фото, допы, телефон, оплата.
2. Полная баня.
3. Гостевой дом.
4. Повторная бронь с сохраненным телефоном.
5. Отмена оплаченной брони.
6. Перенос оплаченной брони.
7. Два клиента на один слот.
8. Waitlist.
9. Голосовое.
10. Инфо-вопрос внутри активной формы.

Каждый smoke - по одному сообщению, ждать ответ.

## Фаза 9. Observability И Диагностика

Цель: быстро понимать, что сломалось: AI, DB, YCLIENTS, payment, state routing или Telegram.

### 9.1. События, которые нужно видеть

- `dialog_timing_slow`
- `ai_semantic_degraded`
- `state_text_consistency_rebuilt`
- `yclients_sync_error`
- `yclients_create_retry`
- `payment_superseded_paid_manual_review`
- `refund_required`
- `waitlist_notified`
- `availability_cache_stale`

### 9.2. План

1. Проверить текущие `system_logs`.
2. Сделать read-only script:

```text
scripts/live_health_report.py
```

Он должен показывать:

- sync freshness;
- active holds;
- pending payments;
- journal_missing bookings;
- refund_required;
- last errors;
- slow dialog counts за N часов;
- DB hygiene audit summary.

3. Добавить admin command или отдельный script output для ручной диагностики.
4. Не делать frontend dashboard до стабилизации runbook.

### 9.3. Definition of Done

- Можно одной командой понять, жив ли бот.
- Можно отличить stale sync от бизнес-багa.
- Slow responses видны без ручного поиска по логам.

## Фаза 10. Production Readiness

Цель: безопасно включать live без постоянной ручной тревоги.

### 10.1. Перед production

Проверить:

- `.env` production values;
- `PREPAYMENT_MODE`;
- `PREPAYMENT_PERCENT` или fixed amount;
- `YCLIENTS_SYNC_ENABLED=true`;
- sync interval;
- Telegram token;
- YooKassa credentials;
- webhook secret;
- admin chat id;
- `HTTP_TRUST_ENV=false`;
- фото в `app/images/`;
- отсутствие тестовых записей в YCLIENTS.

### 10.2. Серверный запуск

Цель: systemd/supervisor, не ручной `screen`.

План:

1. Один service для `main.py`.
2. Restart policy.
3. Environment file.
4. Log rotation.
5. Health check after start.
6. Убедиться, что не стартуют два polling процесса.

### 10.3. YooKassa webhook

1. Reverse proxy.
2. HTTPS.
3. Body size limit.
4. Secret validation.
5. Smoke webhook.
6. Fallback polling остаётся как страховка.

### 10.4. Production smoke

Делать только после clean DB/YCLIENTS state.

Smoke:

- обычная беседка с оплатой;
- баня с фиксированным пакетом;
- попытка занять тот же слот вторым клиентом;
- отмена paid booking в refundable window;
- перенос paid booking;
- post-booking question;
- admin refund notification.

## Фаза 11. Commit/Release Discipline

Цель: не терять контроль над изменениями.

### 11.1. Перед каждым новым пакетом

```powershell
git status --short
git diff --stat
```

В чате сказать:

- какие файлы уже dirty;
- какие файлы планируется менять;
- какие изменения не трогаются.

### 11.2. После каждого пакета

1. Прогнать нужные проверки.
2. Очистить DB после DB-mutating tests.
3. Обновить `best2obs/log.md`.
4. Обновить `best2obs/index.md`, если вывод важен будущим агентам.
5. Если code changed:

```powershell
.\best2graph\update_graph.ps1
```

6. Проверить:

```powershell
git diff --check
git status --short
```

### 11.3. Commit recommendation

Если пользователь попросит commit:

- делать маленькие commits по смыслу;
- не включать случайный root `graphify-out/cache`, если это не осознанно;
- не смешивать production fix, wiki update и generated graph без понимания.

## Рекомендуемый Порядок Для Следующего Чата

Если пользователь хочет сразу улучшать проект, начинать так:

1. Прочитать `best2obs/index.md`, `best2obs/log.md`, этот файл.
2. Сделать `git status --short`.
3. Сделать lightweight baseline:

```powershell
.\.venv\Scripts\python.exe -m compileall app scripts
.\.venv\Scripts\python.exe scripts\lint_best2info.py
.\.venv\Scripts\python.exe scripts\validate_yclients_map.py
.\.venv\Scripts\python.exe scripts\yclients_sync_status.py --strict
```

4. Если baseline OK, первым кодовым улучшением делать **Фазу 2: single-scenario runner**.
5. После single-scenario runner переходить к **Фазе 3 Slice A: fresh-start/stale-form glue**.
6. Не начинать production webhook или большой `message_handler` разрез, пока single-case runner не готов.

## Готовый Prompt Для Нового Чата

```text
Прочитай AGENTS.md, best2obs/index.md, best2obs/log.md и best2obs/roadmap/project-hardening-master-plan.md.
Не меняй production-код без моего явного подтверждения.
Сначала сделай baseline/status, потом начни с Фазы 2: добавить single-scenario runner для local_regression_suite.py с fake AI по умолчанию.
После каждого DB-mutating теста чисти БД и восстанавливай YCLIENTS sync.
```

## Definition Of Done Для Всего Плана

- Есть single-case regression runner.
- `message_handler.py` уменьшен минимум до 4500 строк, затем целевой рубеж меньше 3000 строк.
- `local_regression_suite.py` стал thin wrapper или хотя бы разделён по группам.
- Частые info/off-topic вопросы не ходят в real AI.
- Перед live smoke есть один понятный runbook.
- YCLIENTS/YooKassa/DB failures диагностируются отдельно от бизнес-регрессий.
- Graphify обновляется только правильным `best2graph` workflow и не превращается в doc-only карту.
- `best2obs` всегда содержит актуальный log/index после значимых изменений.
