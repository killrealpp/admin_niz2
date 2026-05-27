# best2 Project Memory

Это Obsidian-память проекта `best2`: Telegram-бота бронирования с AI, YCLIENTS, ЮKassa, PostgreSQL и фоновыми синками.

## Быстрые ссылки

- [[log]] - журнал важных изменений и анализов.
- [[architecture/overview]] - общий обзор системы и потоков.
- [[architecture/frontend]] - пользовательские интерфейсы и точки входа.
- [[architecture/backend]] - backend-модули, сервисы и фоновые процессы.
- [[architecture/database]] - таблицы PostgreSQL и назначение данных.
- [[architecture/auth]] - секреты, внешние токены и модель доступа.
- [[architecture/api]] - внешние API и интеграции.
- [[roadmap/pre-launch]] - проверки и задачи перед релизом.
- [[roadmap/dialog-regression-scenarios]] - живые и автоматические сценарии, которые защищают диалог от повторяющихся ошибок.
- [[bugs/current-known-issues]] - текущие риски, слабые места и наблюдаемые баги.
- [[prompts/codex-workflow]] - команды для дальнейшей работы с Codex и памятью.
- [[prompts/llm-wiki-method]] - правила LLM Wiki: ingest, query, lint, index/log.
- [[decisions/2026-05-26-use-llm-wiki]] - решение вести `best2obs` как LLM Wiki.
- [[decisions/2026-05-27-dialog-state-policy]] - правило: AI понимает смысл, backend валидирует состояние и переходы анкеты.
- [[daily/2026-05-26-scenario-check]] - отчет о самостоятельной проверке сценариев после последних правок.
- [[daily/2026-05-27-project-review]] - обзор проекта senior Python-разработчиком: логика, сильные стороны, риски, что исправлять и удалять.

## Рабочее правило

Перед изменениями читать этот файл и [[log]]. После значимых изменений обновлять память: log, architecture, decisions, roadmap или bugs по смыслу.
