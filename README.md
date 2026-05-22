# AI-бот бронирования (Telegram + YCLIENTS)

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/init_db.py
python scripts/test_db.py
python main.py
```

База: PostgreSQL (Beget, порт 5432). Секреты — в `.env`.

## Структура

- `main.py` — запуск Telegram polling
- `app/bot/` — адаптер Telegram
- `app/services/` — бизнес-логика сообщений
- `app/db/` — PostgreSQL и репозитории
- `information.md` — база знаний (INFO)
- `PLAN.md` — план этапов
