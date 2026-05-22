# ТЗ для Cursor: AI-автоадминистратор бронирования базы отдыха

## 0. Цель проекта

Создать Python-проект автоадминистратора для базы отдыха, который на первом этапе работает через Telegram, далее расширяется на MAX и ВКонтакте.

Автоадминистратор должен:

1. Принимать сообщения клиентов.
2. Создавать или находить пользователя в БД.
3. Создавать или продолжать активный диалог.
4. Хранить историю сообщений.
5. Через AI понимать намерение клиента и обновлять анкету бронирования.
6. Проверять свободные даты и время через YCLIENTS API.
7. Собирать данные для бронирования.
8. Ставить временный резерв, чтобы не предлагать слот другим клиентам.
9. После подтверждения создавать бронь в YCLIENTS.
10. Логировать все действия и ошибки.
11. Передавать человеку спорные или опасные случаи.

Архитектурный принцип:

> AI понимает клиента и формирует структурированный JSON. Python-код выполняет процесс. YCLIENTS хранит финальную бронь. База данных хранит пользователей, диалоги, сообщения, резервы и техническое состояние.

---

## 1. Что сейчас есть в исходной логике

Пользователь описал текущую логику:

1. Будет создана база данных на Beget.
2. Доступы будут храниться в `.env`.
3. Первый канал — Telegram.
4. Позже добавить MAX.
5. Проект должен быть не n8n workflow, а набор Python-скриптов и markdown-файлов.
6. При каждом сообщении нужно:
   - получить `external_id`, имя, текст, время;
   - найти или создать пользователя;
   - найти активную conversation;
   - передать сообщение, историю и `form_data` в AI;
   - определить intent;
   - обновить `form_data`;
   - задать следующий вопрос, проверить доступность или ответить по базе знаний.
7. Нужно хранить:
   - `users`;
   - `conversations`;
   - `messages`;
   - будущую таблицу для броней/резервов.
8. Нужно сделать изменяемые markdown-файлы с вопросами анкеты, промптами и описаниями объектов.

---

## 2. Главные недочеты в текущей логике

### 2.1. Intent смешан с действием

Сейчас `CHECK_AVAILABILITY` описан как intent, но по смыслу это не только намерение клиента, а действие системы.

Проблема:

- клиент может хотеть бронь (`BOOKING`), но действие системы должно быть `CHECK_AVAILABILITY`;
- клиент может просто спросить: “А 17 числа баня свободна?” — intent будет `CHECK_AVAILABILITY_REQUEST`, а действие тоже `check_availability`;
- клиент может ответить коротко “17 мая”, и это не новый intent, а обновление поля `date` + действие `check_availability`, если уже есть `service_type`.

Решение:

Разделить:

- `intent` — что хочет клиент;
- `action` — что должна сделать система сейчас;
- `current_step` / `next_step` — стадия диалога;
- `form_data` — собранные данные.

Пример:

```json
{
  "intent": "booking_request",
  "action": "check_availability",
  "current_step": "collecting_date",
  "next_step": "offer_available_slots",
  "changed_fields": ["date"],
  "form_data": {
    "service_type": "bathhouse",
    "date": "2026-05-17"
  }
}
```

---

### 2.2. Нет отдельного слоя защиты от дублей и гонок

Если два клиента одновременно выбирают один и тот же слот, нельзя полагаться только на AI или `form_data`.

Решение:

Добавить таблицу `slot_holds` — временные резервы.

Логика:

1. Клиент выбрал дату, время и объект.
2. Система проверяет YCLIENTS.
3. Система проверяет свои активные `slot_holds`.
4. Если свободно — создает hold на 10–15 минут.
5. Другим клиентам этот слот уже считается занятым.
6. Перед созданием финальной брони система повторно проверяет YCLIENTS и hold.
7. После успешной брони hold переводится в `converted` или удаляется.

---

### 2.3. Нет явного финального подтверждения

Нельзя создавать бронь сразу после сбора анкеты. Нужно финальное подтверждение клиента.

Решение:

Добавить шаг:

`awaiting_final_confirmation`

Пример ответа:

> Проверил: баня на 17 мая в 18:00 предварительно доступна. Подтвердить бронь на Кирилл, телефон +7..., 6 гостей?

Только после ответа “да”, “подтверждаю”, “бронь” запускаем `create_booking`.

---

### 2.4. Нет нормального статуса conversation

Нужны не только `active/inactive`, а более точные статусы.

Рекомендуемые статусы:

- `active` — идет диалог;
- `waiting_user` — бот задал вопрос и ждет ответ;
- `checking_availability` — идет проверка;
- `awaiting_confirmation` — слот найден, ждем подтверждение;
- `booking_in_progress` — создается бронь;
- `booked` — бронь создана;
- `expired` — диалог устарел;
- `cancelled` — клиент отказался;
- `handoff` — передано администратору;
- `error` — техническая ошибка.

---

### 2.5. Ошибки в названиях полей

В исходном описании есть опечатки:

- `externed_id` → `external_id`;
- `lfst_seen_at` → `last_seen_at`;
- `next_ster` → `next_step`;
- `conversion` → лучше `conversation`;
- `CHECK_AVIALABILYTY` → `check_availability`.

Нужно сразу заложить правильные имена, иначе Cursor и код будут путаться.

---

### 2.6. Анкету лучше хранить не только в markdown

Вопросы анкеты можно описать в markdown для человека, но для кода лучше использовать YAML/JSON.

Решение:

- `docs/booking_questions.md` — понятное описание анкеты для AI и человека;
- `config/booking_form.yaml` — машинно-читаемая структура полей, порядка вопросов и обязательности.

Так Cursor сможет строить код не по свободному тексту, а по структуре.

---

## 3. Рекомендуемая архитектура проекта

```text
project/
  .env.example
  README.md
  requirements.txt
  main.py

  app/
    bot/
      telegram_bot.py
      max_bot.py
      router.py

    core/
      config.py
      logger.py
      time_utils.py
      validators.py
      constants.py

    db/
      connection.py
      migrations/
        001_init.sql
      repositories/
        users_repo.py
        conversations_repo.py
        messages_repo.py
        slot_holds_repo.py
        bookings_repo.py
        logs_repo.py

    ai/
      openai_client.py
      prompt_loader.py
      ai_orchestrator.py
      schemas.py

    services/
      conversation_service.py
      message_service.py
      booking_form_service.py
      availability_service.py
      hold_service.py
      booking_service.py
      knowledge_service.py
      handoff_service.py

    integrations/
      yclients_client.py
      telegram_client.py
      payment_client.py

    prompts/
      system_prompt.md
      intent_classifier.md
      booking_dialog.md
      info_answer.md
      response_generator.md
      handoff_rules.md

    knowledge/
      company.md
      objects.md
      prices.md
      rules.md
      faq.md

  config/
    booking_form.yaml
    services_map.yaml
    channels.yaml

  tests/
    test_ai_parser.py
    test_conversation_flow.py
    test_availability.py
    test_holds.py
    test_booking_creation.py
```

---

## 4. Переменные окружения `.env`

Создать `.env.example`:

```env
# APP
APP_ENV=local
APP_DEBUG=true
APP_TIMEZONE=Europe/Moscow
SESSION_TTL_HOURS=72
HOLD_TTL_MINUTES=15

# DATABASE
DB_HOST=localhost
DB_PORT=3306
DB_NAME=booking_bot
DB_USER=booking_user
DB_PASSWORD=change_me
DB_CHARSET=utf8mb4

# TELEGRAM
TELEGRAM_BOT_TOKEN=change_me
TELEGRAM_WEBHOOK_URL=

# MAX - на будущее
MAX_BOT_TOKEN=
MAX_WEBHOOK_SECRET=

# VK - на будущее
VK_GROUP_TOKEN=
VK_CONFIRMATION_TOKEN=
VK_SECRET_KEY=

# OPENAI / OPENCLOW
AI_PROVIDER=openai
OPENAI_API_KEY=change_me
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TEMPERATURE=0.2

# YCLIENTS
YCLIENTS_BASE_URL=https://api.yclients.com/api/v1
YCLIENTS_PARTNER_TOKEN=change_me
YCLIENTS_USER_TOKEN=change_me
YCLIENTS_COMPANY_ID=change_me

# PAYMENTS - позже
PAYMENT_PROVIDER=
PAYMENT_SHOP_ID=
PAYMENT_SECRET_KEY=
PAYMENT_SUCCESS_URL=
PAYMENT_FAIL_URL=

# ADMIN
ADMIN_TELEGRAM_CHAT_ID=change_me

# LOGS
LOG_LEVEL=INFO
```

Важно:

- настоящий `.env` не коммитить;
- коммитить только `.env.example`;
- API-ключи не писать в markdown-файлы и промпты.

---

## 5. База данных

### 5.1. `users`

```sql
CREATE TABLE users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  channel VARCHAR(32) NOT NULL,
  external_id VARCHAR(128) NOT NULL,
  name VARCHAR(255),
  phone VARCHAR(32),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_channel_external_id (channel, external_id)
);
```

---

### 5.2. `conversations`

```sql
CREATE TABLE conversations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  channel VARCHAR(32) NOT NULL,
  intent VARCHAR(64),
  current_step VARCHAR(64),
  next_step VARCHAR(64),
  status VARCHAR(64) NOT NULL DEFAULT 'active',
  form_data JSON NOT NULL,
  last_message_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id),
  INDEX idx_user_status_time (user_id, status, last_message_time)
);
```

Начальный `form_data`:

```json
{
  "date": null,
  "time": null,
  "duration": null,
  "phone": null,
  "client_name": null,
  "preferences": null,
  "event_format": null,
  "guests_count": null,
  "service_type": null,
  "upsell_items": [],
  "comment": null,
  "payment_status": "not_required_yet"
}
```

---

### 5.3. `messages`

```sql
CREATE TABLE messages (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  sender VARCHAR(32) NOT NULL,
  text TEXT NOT NULL,
  raw_payload JSON,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id),
  INDEX idx_conversation_created (conversation_id, created_at)
);
```

`sender`:

- `user`;
- `assistant`;
- `system`;
- `admin`.

---

### 5.4. `slot_holds`

```sql
CREATE TABLE slot_holds (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  service_type VARCHAR(64) NOT NULL,
  yclients_service_id VARCHAR(64),
  date DATE NOT NULL,
  time TIME NOT NULL,
  duration_minutes INT,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  expires_at DATETIME NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  INDEX idx_slot_lookup (service_type, date, time, status, expires_at)
);
```

Статусы:

- `active`;
- `expired`;
- `converted`;
- `cancelled`.

---

### 5.5. `bookings`

```sql
CREATE TABLE bookings (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  slot_hold_id BIGINT,
  yclients_record_id VARCHAR(128),
  service_type VARCHAR(64) NOT NULL,
  date DATE NOT NULL,
  time TIME NOT NULL,
  duration_minutes INT,
  client_name VARCHAR(255) NOT NULL,
  phone VARCHAR(32) NOT NULL,
  guests_count INT,
  event_format VARCHAR(128),
  preferences TEXT,
  upsell_items JSON,
  status VARCHAR(64) NOT NULL DEFAULT 'created',
  payment_status VARCHAR(64) NOT NULL DEFAULT 'not_paid',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (slot_hold_id) REFERENCES slot_holds(id)
);
```

---

### 5.6. `system_logs`

```sql
CREATE TABLE system_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  conversation_id BIGINT,
  level VARCHAR(32) NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  message TEXT,
  payload JSON,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. `config/booking_form.yaml`

```yaml
fields:
  - key: service_type
    label: "Что планируете: беседка, баня, дом, беседка + баня?"
    required_for_availability: true
    required_for_booking: true
    type: enum
    allowed_values: [bathhouse, gazebo, warm_gazebo, summer_gazebo, house, gazebo_bathhouse]

  - key: date
    label: "На какую дату планируете отдых?"
    required_for_availability: true
    required_for_booking: true
    type: date

  - key: time
    label: "На какое время или на какой период?"
    required_for_availability: false
    required_for_booking: true
    type: time

  - key: duration
    label: "На сколько часов хотите забронировать?"
    required_for_availability: false
    required_for_booking: true
    type: duration

  - key: guests_count
    label: "Сколько примерно гостей?"
    required_for_availability: false
    required_for_booking: true
    type: integer

  - key: event_format
    label: "Какой формат отдыха: день рождения, семейный отдых, компания, свадьба, тихий отдых?"
    required_for_availability: false
    required_for_booking: false
    type: string

  - key: preferences
    label: "Что важно: у воды, детям удобно, побольше места, тише, рядом мангал, оформление?"
    required_for_availability: false
    required_for_booking: false
    type: string

  - key: client_name
    label: "Как вас зовут?"
    required_for_availability: false
    required_for_booking: true
    type: string

  - key: phone
    label: "Телефон для бронирования?"
    required_for_availability: false
    required_for_booking: true
    type: phone

  - key: upsell_items
    label: "Нужны допы: уголь, розжиг, решетка, лед, посуда, кальян, продление, уборка?"
    required_for_availability: false
    required_for_booking: false
    type: list
```

---

## 7. Нормальная логика обработки сообщения

### 7.1. Вход

Каждое входящее сообщение приводим к единому виду:

```json
{
  "channel": "telegram",
  "external_user_id": "123456789",
  "user_name": "Кирилл",
  "text": "Хочу баню 17 мая вечером",
  "message_time": "2026-05-15T12:00:00+03:00",
  "raw_payload": {}
}
```

---

### 7.2. Алгоритм

1. Получить сообщение из Telegram.
2. Найти или создать пользователя по `channel + external_id`.
3. Найти активную conversation:
   - `status IN ('active', 'waiting_user', 'awaiting_confirmation')`;
   - `last_message_time <= 72 часов`.
4. Если conversation нет — создать новую.
5. Сохранить сообщение пользователя в `messages`.
6. Собрать контекст:
   - текущее сообщение;
   - последние N сообщений;
   - текущий `form_data`;
   - текущий `current_step`;
   - дата и время сейчас;
   - доступные объекты из `knowledge/objects.md`;
   - правила анкеты из `config/booking_form.yaml`.
7. Передать контекст в AI.
8. Получить строго JSON.
9. Провалидировать JSON.
10. Обновить `form_data`.
11. Выполнить `action`:
    - `ask_next_question`;
    - `answer_info`;
    - `check_availability`;
    - `hold_slot`;
    - `ask_final_confirmation`;
    - `create_booking`;
    - `handoff_to_human`.
12. Сохранить ответ ассистента в `messages`.
13. Обновить conversation.
14. Отправить ответ клиенту.
15. При ошибке — лог + уведомление администратора.

---

## 8. JSON-ответ AI

AI должен возвращать только JSON без markdown.

```json
{
  "intent": "booking_request",
  "confidence": 0.92,
  "action": "check_availability",
  "current_step": "collecting_booking_data",
  "next_step": "offer_available_slots",
  "changed_fields": ["service_type", "date", "time"],
  "form_data_patch": {
    "service_type": "bathhouse",
    "date": "2026-05-17",
    "time": "18:00",
    "duration": null,
    "guests_count": null,
    "event_format": null,
    "preferences": null,
    "client_name": null,
    "phone": null,
    "upsell_items": []
  },
  "missing_fields": ["duration", "guests_count", "client_name", "phone"],
  "needs_clarification": false,
  "clarification_question": null,
  "reply_to_user": "Проверю баню на 17 мая вечером и подскажу свободные варианты.",
  "handoff_to_human": false,
  "handoff_reason": null
}
```

---

## 9. Intent

Рекомендуемые intent:

- `booking_request` — клиент хочет забронировать или подбирает вариант;
- `availability_question` — клиент спрашивает, свободна ли дата/время/объект;
- `price_question` — клиент спрашивает цену;
- `object_selection_help` — клиент не знает, что выбрать;
- `company_info` — вопрос о базе, правилах, адресе, условиях;
- `change_booking` — перенос брони;
- `cancel_booking` — отмена брони;
- `payment_question` — вопрос по оплате/предоплате;
- `human_request` — просит администратора;
- `other` — другое.

---

## 10. Action

Рекомендуемые action:

- `ask_next_question` — задать следующий вопрос анкеты;
- `answer_info` — ответить по базе знаний;
- `check_availability` — проверить свободные слоты;
- `offer_slots` — предложить найденные варианты;
- `hold_slot` — поставить временный резерв;
- `ask_final_confirmation` — попросить финальное подтверждение;
- `create_booking` — создать запись в YCLIENTS;
- `handoff_to_human` — передать человеку;
- `reset_conversation` — начать новый диалог;
- `send_error_message` — мягко сообщить об ошибке.

---

## 11. Правила проверки доступности

Проверку доступности делать, если:

1. Есть `service_type` и `date`.
2. Клиент спрашивает про свободную дату/время.
3. Клиент добавил или изменил дату, время или объект.
4. Клиент написал короткий ответ, но из истории понятно, что он отвечает на вопрос про дату/время/объект.

Примеры:

История:

> Бот: Какая дата интересует для бани?

Клиент:

> 19 мая

Результат:

```json
{
  "intent": "availability_question",
  "action": "check_availability",
  "changed_fields": ["date"]
}
```

История:

> Клиент: Хочу беседку

Клиент:

> В субботу вечером

Результат:

```json
{
  "intent": "booking_request",
  "action": "check_availability",
  "changed_fields": ["date", "time"]
}
```

---

## 12. Логика временного резерва

Когда создаем hold:

1. Клиент выбрал конкретный объект, дату, время.
2. Система проверила YCLIENTS.
3. Система проверила активные holds.
4. Слот свободен.
5. Создаем `slot_holds.status = active`.
6. `expires_at = now + HOLD_TTL_MINUTES`.
7. Сообщаем клиенту:

> Предварительно держу этот вариант на 15 минут. Подтвердить бронь?

Если клиент подтвердил:

1. Повторно проверить YCLIENTS.
2. Повторно проверить hold.
3. Создать бронь.
4. Обновить hold: `converted`.
5. Обновить conversation: `booked`.

Если время вышло:

1. Hold становится `expired`.
2. При следующем сообщении клиента заново проверяем слот.

---

## 13. YCLIENTS-интеграция

Нужен отдельный клиент `app/integrations/yclients_client.py`.

Минимальные методы:

```python
class YClientsClient:
    def get_services(self):
        pass

    def get_staff(self):
        pass

    def check_available_slots(self, service_id: str, date: str):
        pass

    def create_record(self, payload: dict):
        pass

    def get_record(self, record_id: str):
        pass

    def cancel_record(self, record_id: str):
        pass
```

Важно:

- точные endpoints и формат payload проверить по актуальной документации YCLIENTS;
- не зашивать `service_id` в код;
- хранить соответствие наших объектов и услуг YCLIENTS в `config/services_map.yaml`.

Пример `config/services_map.yaml`:

```yaml
bathhouse:
  title: "Баня"
  yclients_service_id: "CHANGE_ME"
  default_duration_minutes: 120

summer_gazebo:
  title: "Летняя беседка"
  yclients_service_id: "CHANGE_ME"
  default_duration_minutes: 180

warm_gazebo:
  title: "Теплая беседка"
  yclients_service_id: "CHANGE_ME"
  default_duration_minutes: 180

house:
  title: "Дом"
  yclients_service_id: "CHANGE_ME"
  default_duration_minutes: 1440
```

---

## 14. Markdown-файлы для AI

### 14.1. `app/prompts/system_prompt.md`

Содержит роль AI:

- ты AI-администратор базы отдыха;
- не создаешь бронь сам;
- не обещаешь свободные даты без проверки;
- возвращаешь структурированный JSON;
- учитываешь историю, `form_data`, текущее время;
- если уверенность ниже 0.75 — задаешь уточнение или передаешь человеку.

---

### 14.2. `app/prompts/intent_classifier.md`

Содержит правила определения:

- intent;
- action;
- changed_fields;
- missing_fields;
- handoff.

---

### 14.3. `app/prompts/booking_dialog.md`

Содержит правила ведения анкеты:

- задавать один короткий вопрос;
- не перегружать клиента;
- не спрашивать то, что уже есть;
- если клиент изменил дату/время/объект — обновить `form_data` и проверить заново;
- если данных достаточно — переходить к проверке/подтверждению.

---

### 14.4. `app/prompts/info_answer.md`

Содержит правила ответа по базе знаний:

- отвечать только на основе `knowledge/*.md`;
- если данных нет — честно сказать, что уточнит администратор;
- не придумывать цены, адреса, условия, скидки.

---

### 14.5. `app/knowledge/objects.md`

Описание каждого объекта:

- название;
- вместимость;
- особенности;
- когда рекомендовать;
- ограничения;
- что уточнять;
- какие допы подходят.

---

### 14.6. `app/knowledge/prices.md`

Прайс:

- объект;
- будни/выходные;
- длительность;
- минимальное время;
- допы;
- предоплата;
- залог;
- условия отмены.

Если прайс часто меняется, лучше позже перенести его в таблицу БД или Google Sheet, а markdown использовать как резервную базу знаний.

---

## 15. Пример системного промпта

Файл: `app/prompts/system_prompt.md`

```md
Ты AI-администратор базы отдыха.

Твоя задача — понять сообщение клиента, историю диалога и текущую анкету form_data.

Ты НЕ проверяешь наличие сам.
Ты НЕ создаешь бронь сам.
Ты НЕ обещаешь, что дата свободна, пока система не передала тебе результат проверки.
Ты НЕ придумываешь цены и условия.

Ты возвращаешь только JSON по заданной схеме.

Главные правила:
1. Анализируй текущее сообщение вместе с историей и form_data.
2. Если клиент добавил или изменил дату, время или объект, укажи это в changed_fields.
3. Если есть service_type и date, а клиент спрашивает доступность или отвечает на вопрос про дату — action должен быть check_availability.
4. Если данных не хватает — action ask_next_question.
5. Задавай только один короткий уточняющий вопрос.
6. Если confidence ниже 0.75 — не запускай опасные действия, задай уточнение или handoff_to_human.
7. Финальную бронь можно создавать только после явного подтверждения клиента.
8. Все относительные даты переводи в YYYY-MM-DD с учетом current_datetime.
9. Если клиент изменил дату/время/объект, старый слот нужно считать неактуальным.
10. Не спорь с клиентом и не используй канцелярит.
```

---

## 16. Где нужен AI

AI нужен для:

1. Понимания intent.
2. Извлечения даты из фраз “завтра”, “в субботу”, “на выходных”.
3. Извлечения объекта: баня, дом, беседка, теплая/летняя беседка.
4. Извлечения количества гостей.
5. Понимания формата мероприятия.
6. Обновления `form_data_patch`.
7. Определения недостающих полей.
8. Формирования короткого человеческого ответа.
9. Ответов по базе знаний.
10. Определения, когда нужен человек.

---

## 17. Где нужны жесткие правила

Жесткими правилами, не AI:

1. Поиск/создание пользователя.
2. Поиск активной conversation.
3. Таймаут 72 часа.
4. Сохранение сообщений.
5. Валидация JSON от AI.
6. Проверка обязательных полей.
7. Проверка доступности в YCLIENTS.
8. Проверка своих временных резервов.
9. Создание временного резерва.
10. Повторная проверка перед бронью.
11. Создание брони в YCLIENTS.
12. Логирование.
13. Уведомление администратора.
14. Обработка ошибок API.
15. Проверка статуса оплаты.

---

## 18. Обработка ошибок

### 18.1. AI вернул невалидный JSON

Действия:

1. Записать ошибку в `system_logs`.
2. Повторить запрос один раз с repair-промптом.
3. Если снова ошибка — handoff.

Ответ клиенту:

> Уточню у администратора и вернусь с ответом.

---

### 18.2. YCLIENTS недоступен

Действия:

1. Записать ошибку.
2. Уведомить администратора.
3. Не обещать бронь.

Ответ клиенту:

> Сейчас не получается проверить расписание автоматически. Передам администратору, он уточнит свободное время.

---

### 18.3. Слот был свободен, но перед бронью стал занят

Ответ клиенту:

> Этот вариант уже заняли. Могу подобрать ближайшее свободное время.

Действия:

1. Снять hold.
2. Снова проверить альтернативы.
3. Предложить 2–3 варианта.

---

### 18.4. Клиент изменил дату/время/объект

Действия:

1. Обновить `form_data`.
2. Старый hold отменить.
3. Проверить заново.

---

## 19. Handoff человеку

Передавать администратору, если:

1. Клиент злится или конфликтует.
2. Нужна скидка или нестандартные условия.
3. Клиент хочет отмену/возврат денег.
4. Не хватает данных, но клиент не отвечает понятно.
5. AI confidence ниже 0.75 и вопрос важный.
6. Ошибка YCLIENTS/API.
7. Клиент просит человека.
8. Событие крупное или нестандартное: свадьба, корпоратив, много гостей.
9. Нет подходящего объекта.

---

## 20. План работ для Cursor

### Этап 1. Каркас проекта

1. Создать структуру папок.
2. Добавить `.env.example`.
3. Добавить `requirements.txt`.
4. Добавить `config.py` для чтения env.
5. Добавить logger.

### Этап 2. База данных

1. Создать миграцию `001_init.sql`.
2. Создать таблицы:
   - `users`;
   - `conversations`;
   - `messages`;
   - `slot_holds`;
   - `bookings`;
   - `system_logs`.
3. Написать repositories.
4. Проверить подключение к Beget DB.

### Этап 3. Telegram

1. Подключить Telegram bot token.
2. Сделать polling или webhook.
3. Нормализовать входящие сообщения.
4. Сохранять пользователя и сообщение.
5. Отправлять простой тестовый ответ.

### Этап 4. Conversation engine

1. Реализовать поиск активной conversation.
2. Реализовать создание новой conversation.
3. Реализовать TTL 72 часа.
4. Реализовать сбор истории сообщений.
5. Реализовать обновление `form_data`.

### Этап 5. AI слой

1. Создать prompt loader.
2. Создать AI client.
3. Создать JSON schema.
4. Реализовать вызов AI.
5. Реализовать валидацию ответа.
6. Реализовать fallback при ошибке JSON.

### Этап 6. Анкета

1. Создать `config/booking_form.yaml`.
2. Реализовать определение missing fields.
3. Реализовать next question.
4. Проверить короткие ответы клиента: “17 мая”, “вечером”, “6 человек”.

### Этап 7. YCLIENTS

1. Создать `yclients_client.py`.
2. Проверить авторизацию.
3. Получить список услуг.
4. Сопоставить услуги с `services_map.yaml`.
5. Реализовать проверку слотов.
6. Реализовать создание записи.
7. Реализовать обработку ошибок.

### Этап 8. Holds

1. Создать логику временного резерва.
2. Проверять active holds перед предложением слота.
3. Автоматически истекать старые holds.
4. Отменять hold при изменении даты/времени/объекта.
5. Конвертировать hold в booking.

### Этап 9. Финальная бронь

1. Проверить обязательные поля.
2. Попросить финальное подтверждение.
3. Повторно проверить доступность.
4. Создать бронь в YCLIENTS.
5. Сохранить `yclients_record_id`.
6. Отправить подтверждение клиенту.
7. Уведомить администратора.

### Этап 10. База знаний

1. Перенести информацию о компании в markdown.
2. Создать `objects.md`.
3. Создать `prices.md`.
4. Создать `rules.md`.
5. Создать `faq.md`.
6. Настроить ответы INFO только по этим файлам.

### Этап 11. Тесты

1. Тест первого сообщения.
2. Тест продолжения диалога.
3. Тест короткого ответа.
4. Тест смены даты.
5. Тест проверки доступности.
6. Тест hold.
7. Тест создания брони.
8. Тест ошибки YCLIENTS.
9. Тест handoff.

---

## 21. Минимальный MVP

MVP должен уметь:

1. Работать в Telegram.
2. Создавать пользователя.
3. Создавать conversation.
4. Сохранять сообщения.
5. Собирать поля:
   - `service_type`;
   - `date`;
   - `time`;
   - `guests_count`;
   - `client_name`;
   - `phone`.
6. Проверять доступность через YCLIENTS.
7. Предлагать свободные варианты.
8. Ставить временный hold.
9. Просить подтверждение.
10. Создавать бронь.
11. Уведомлять администратора.

---

## 22. Что нужно уточнить перед разработкой

1. Какая БД на Beget: MySQL или PostgreSQL?
2. Есть ли API-доступ YCLIENTS и какие токены доступны?
3. Как в YCLIENTS называются услуги: баня, дом, беседки?
4. Есть ли сотрудники/ресурсы, к которым привязаны записи?
5. Как YCLIENTS хранит длительность аренды?
6. Нужно ли создавать клиента в YCLIENTS отдельно или запись создает клиента автоматически?
7. Нужна ли предоплата до создания брони или после?
8. Какой срок временного резерва: 10, 15 или 30 минут?
9. Какие условия отмены?
10. Где будет храниться актуальный прайс?

---

## 23. Что делать дальше

1. В Cursor создать проект по структуре из раздела 3.
2. Создать `.env.example`.
3. Создать SQL-миграцию из раздела 5.
4. Создать markdown-промпты из раздела 14–15.
5. Реализовать Telegram MVP без YCLIENTS: пользователь → conversation → messages → AI JSON → ответ.
6. Потом подключить YCLIENTS check availability.
7. После этого добавить holds и создание брони.

---

## 24. Критерии готовности первой версии

Первая версия считается готовой, если сценарий работает полностью:

1. Клиент пишет: “Хочу баню на 17 мая вечером”.
2. Бот понимает объект и дату.
3. Бот проверяет YCLIENTS.
4. Бот предлагает свободное время.
5. Клиент выбирает время.
6. Бот собирает имя, телефон, гостей.
7. Бот просит финальное подтверждение.
8. Клиент подтверждает.
9. Система повторно проверяет слот.
10. Система создает бронь в YCLIENTS.
11. Клиент получает подтверждение.
12. Администратор получает уведомление.
13. Все сообщения и действия сохранены в БД.
