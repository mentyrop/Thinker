# Мыслитель — Telegram-бот для структурирования мыслей

MVP Telegram-бота, который помогает превратить хаотичную мысль в понятное
действие по методологии: фиксируем → решаем, можно ли повлиять → делегируем /
ставим в календарь / исследуем / откладываем «додумать».

## Архитектура

```
thought_bot/
  app/
    bot/
      handlers/   start.py, menu.py, thoughts.py   # хендлеры aiogram (Router)
      keyboards/  inline.py, reply.py
      states/     thought_states.py                # FSM
      middlewares.py                               # инжект async-сессии БД
    services/
      llm_service.py        # LLM → строгий JSON (pydantic) + fallback
      calendar_service.py   # парсер даты + Google Calendar template link
      thought_processor.py  # чистая бизнес-логика (тексты, share-link)
    database/
      models.py, session.py, repositories.py
    config.py   # pydantic + python-dotenv
    main.py     # точка входа
  alembic/      # миграции
  docker-compose.yml  requirements.txt  .env.example
```

Логика дерева вопросов целиком в коде. LLM только классифицирует мысль,
переформулирует её и подсказывает первый шаг — ботом она не управляет.

## 1. Установка зависимостей

Нужен Python 3.11+.

```bash
cd thought_bot
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Поднять PostgreSQL

```bash
docker compose up -d
```

Поднимется PostgreSQL 16 на `localhost:5432` (db/user/pass = `thought_bot` /
`postgres` / `postgres`).

## 3. Переменные окружения

Скопируй пример и заполни:

```bash
cp .env.example .env
```

```env
BOT_TOKEN=               # токен от @BotFather
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/thought_bot
LLM_API_KEY=             # ключ OpenAI-совместимого API
LLM_BASE_URL=https://api.openai.com/v1   # или OpenRouter / прокси Claude
LLM_MODEL=gpt-4o-mini
```

Если `LLM_API_KEY` пустой — бот работает на детерминированном fallback-анализе.

## 4. Применить миграции

```bash
alembic upgrade head
```

(Команды Alembic запускай из папки `thought_bot`, где лежит `alembic.ini`.)

## 5. Запустить бота

```bash
python -m app.main
```

## 6. Как работает LLM JSON

`app/services/llm_service.py` отправляет мысль в `/chat/completions` с
системным промптом, который требует вернуть **только** JSON по фиксированной
схеме (`summary`, `type`, `actionable`, `can_delegate`, `calendar_candidate`,
`needs_first_step`, `needs_research`, `suggested_first_step`,
`suggested_calendar_title`, `suggested_duration_minutes`,
`suggested_note_category`, `user_question_next`).

Ответ валидируется через pydantic-модель `ThoughtAnalysis`. Если JSON
невалиден, не приходит или API недоступен — используется fallback, поэтому бот
никогда не падает из-за LLM. Результат сохраняется в колонку `llm_json` (JSONB).

## 7. Как работает Google Calendar link

OAuth в MVP нет. `calendar_service.build_google_calendar_url(...)` собирает
ссылку-шаблон:

```
https://calendar.google.com/calendar/render?action=TEMPLATE&text=<title>&dates=<start>/<end>&details=<details>
```

* `title` = `suggested_calendar_title` или `summary`;
* `details` = исходный текст + первый шаг;
* `dates` = `start/end` в формате `YYYYMMDDTHHMMSS`, длительность —
  `suggested_duration_minutes` (по умолчанию 30 мин).

Дата вводится в свободной форме: `DD.MM.YYYY HH:MM`, `завтра HH:MM`,
`сегодня HH:MM`. Событие сохраняется в таблицу `calendar_events`.

## Делегирование

Для передачи задачи формируется текст и Telegram share-ссылка
`https://t.me/share/url?text=<encoded>` (кнопка «Отправить в Telegram»).

## Дорожная карта (заложено в архитектуру)

* Голосовые: voice → transcription → тот же `process_new_thought`.
* Полноценный Google Calendar API вместо template-ссылки.
* Telegram Web App.
```
