# BodyPilot 2.0

Умный персональный помощник здоровья: питание, тренировки, вес, аналитика и ИИ-советы.
Состоит из **Telegram-бота** и **REST API** (FastAPI) — фундамент для будущих Telegram Mini App,
сайта/приложения и интеграций (включая метрики с носимых устройств).

## Стек

- Python 3.12
- aiogram 3 — Telegram-бот
- FastAPI + uvicorn — HTTP API (`/docs` — Swagger UI)
- SQLite (WAL) — база данных, миграции через `PRAGMA user_version`
- Google Gemini — ИИ-функции (ответы, планы, анализ)

## Быстрый старт (локально, Windows/Linux)

```bash
# 1. Виртуальное окружение
py -3.12 -m venv .venv          # Linux/macOS: python3 -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate

# 2. Зависимости
pip install -r requirements.txt

# 3. Конфигурация
cp .env.example .env            # заполнить TELEGRAM_BOT_TOKEN и GEMINI_API_KEY

# 4. Запуск бота
python -m bot.main

# 5. Запуск API (второй терминал)
uvicorn api.main:app --host 0.0.0.0 --port 8000
# Документация API: http://localhost:8000/docs
# Проверка живости:  curl http://localhost:8000/health
```

База `data/bodypilot.db` и таблицы создаются автоматически при первом запуске.

## Деплой на VPS (Docker)

Полная пошаговая инструкция с HTTPS (Caddy + Let's Encrypt), DNS, бэкапами и таблицей типичных проблем — в **[DEPLOY.md](DEPLOY.md)**.

Кратко:

```bash
# 1. Docker (Ubuntu/Debian)
curl -fsSL https://get.docker.com | sh

# 2. Код и конфигурация
git clone <repo-url> bodypilot && cd bodypilot
cp .env.example .env
nano .env                       # TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, DOMAIN, MINIAPP_URL

# 3. Запуск (3 сервиса: bot + api + caddy с авто-HTTPS)
docker compose up -d --build

# 4. Проверка
docker compose ps                              # все Up (healthy)
curl https://<домен>/health                    # {"status":"ok","db":"ok"}
```

Обновление после изменений кода: `git pull && docker compose up -d --build`.
Данные персистентны: `./data` (SQLite) и `./logs` монтируются с хоста.
`.env` и файл БД в образ не попадают (см. `.dockerignore`).

## Переменные окружения

Полный список с комментариями — в `.env.example`.

| Переменная | Обязательна | Назначение |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | да | токен бота от @BotFather |
| `GEMINI_API_KEY` | да (для ИИ) | ключ Google AI Studio |
| `GEMINI_MODEL` | нет | основная модель Gemini (по умолчанию `gemini-3.5-flash-lite`) |
| `GEMINI_MODELS` | нет | fallback-цепочка моделей через запятую (при исчерпании квоты) |
| `ADMIN_API_KEY` | нет | ключ для `/api/v1/admin/*` (пусто = админ-API отключён) |
| `DATABASE_PATH` | нет | путь к SQLite (по умолчанию `data/bodypilot.db`) |
| `API_HOST` / `API_PORT` | нет | адрес API (по умолчанию `0.0.0.0:8000`) |
| `MINIAPP_URL` | нет | https-URL Mini App (пусто = фича скрыта) |
| `LOG_LEVEL` | нет | `DEBUG`/`INFO`/`WARNING`/`ERROR` |
| `OPENAI_API_KEY`, `WGER_API_TOKEN`, `FATSECRET_CLIENT_ID/SECRET` | нет | доп. интеграции |
| `TELEGRAM_ADMIN_USER_IDS`, `TELEGRAM_ADMIN_USERNAME` | нет | админы бота |
| `REFERRAL_SECRET_SALT` | нет | соль реферальных ссылок (сменить в проде!) |
| `ADMIN_PASSWORD` | нет | пароль веб-админки бота |
| `DIGEST_CHECK_INTERVAL_MINUTES` | нет | интервал планировщика дайджестов |

## Команды бота (основные)

- **Профиль:** `/start`, `/register`, `/profile`, `/set_sport`, `/my_sport`
- **Питание:** `/add_food`, `/food_today`, `/search_food`, `/barcode`, `/meal_plan`, `/nutrition_plan`
- **Тренировки:** `/start_workout`, `/workout_plan`, `/workout_history`, `/add_exercise`, `/search_exercise`, `/progress`
- **Вес и статистика:** `/log_weight`, `/stats`
- **ИИ:** `/ai`, `/ai_plan`, `/ai_analyze`, `/ai_advice`, `/ai_workout`
- **Дайджесты:** `/set_digest_time`, `/set_city`, `/digest_now`, `/weather`
- **Premium и рефералы:** `/premium`, `/subscribe`, `/ref`, `/referrals`, `/bonus`
- **Прочее:** `/help`, `/myid`, `/api_key` (личный ключ для интеграции часов)

## API

Базовый URL: `http://<host>:8000`, документация: `/docs`.

- `GET /health` — healthcheck (без авторизации)
- `GET/PATCH /api/v1/profile` — профиль
- `GET /api/v1/nutrition/today|/log|/summary`, `POST /api/v1/nutrition/log` — питание
- `GET /api/v1/workouts/plan/today`, `GET /api/v1/workouts/history` — тренировки
- `GET /api/v1/stats?days=7` — статистика
- `POST/GET /api/v1/health/metrics` — метрики с носимых устройств
- `GET /api/v1/admin/metrics` — админ-метрики (заголовок `X-Admin-Key`)

Авторизация пользователя: заголовок `X-Telegram-Init-Data` (Mini App) или `X-API-Key` (интеграции).

## Mini App (веб-приложение)

BodyPilot включает **Telegram Mini App** — веб-интерфейс (`webapp/index.html`, отдаётся API
по пути `/app`), который открывается прямо внутри Telegram: питание, тренировки и прогресс
без команд бота.

В боте приложение доступно тремя способами:

- кнопка «📱 Приложение» в подменю «🤖 AI-коуч»;
- команда `/app`;
- Menu Button (кнопка слева от поля ввода в чате).

Все три появляются, только когда задана переменная `MINIAPP_URL`. Без неё фича скрыта —
кнопка «📱 Приложение» в меню отвечает «Приложение скоро появится».

### Локальный запуск через ngrok

Telegram открывает Mini App только по **https**, поэтому для разработки нужен туннель:

```bash
# 1. Запусти API
uvicorn api.main:app --host 0.0.0.0 --port 8000

# 2. Подними туннель (второй терминал)
ngrok http 8000
# ngrok покажет публичный URL вида https://xxxx-xx-xx.ngrok-free.app

# 3. Пропиши URL с суффиксом /app в .env
MINIAPP_URL=https://xxxx-xx-xx.ngrok-free.app/app

# 4. Перезапусти API (если менял .env) и бота
python -m bot.main
```

После перезапуска бота в подменю «🤖 AI-коуч» появится web_app-кнопка «📱 Приложение»,
а слева от поля ввода — Menu Button.

**Отладка:** веб-инспектор ngrok доступен на `http://localhost:4040` — там видны все
запросы, которые Mini App шлёт в API (удобно смотреть `X-Telegram-Init-Data` и ответы).

**BotFather не нужен:** inline web_app-кнопки и `set_chat_menu_button` работают без
регистрации Mini App в BotFather — достаточно https-URL. Регистрация в BotFather
(`/newapp`) потребуется только для прямой ссылки `t.me/bot/app` и кастомного имени.

## Интеграция с часами (шаги, сон, пульс)

Метрики с носимых устройств принимает `POST /api/v1/health/metrics`. Чтобы получить
личный ключ, отправь боту команду `/api_key` — ключ привязан к твоему аккаунту,
`user_id` в запросе указывать не нужно. Дальше метрики можно слать из IFTTT,
Apple Shortcuts, Tasker и т.п.:

```bash
curl -X POST http://<host>:8000/api/v1/health/metrics \
  -H "X-API-Key: <твой_ключ_из_/api_key>" \
  -H "Content-Type: application/json" \
  -d '{"metrics": [{"ts": "2026-10-21T08:00:00", "metric_type": "steps", "value": 8430, "source": "watch"}]}'
```

Формат: `{"metrics": [{"ts": "<ISO 8601>", "metric_type": "...", "value": <число>, "source": "<необязательно>"}]}`,
за раз до 500 метрик. Допустимые `metric_type`: `steps`, `heart_rate`, `resting_heart_rate`,
`sleep_hours`, `weight`, `calories_burned`, `distance_km`, `active_minutes`, `floors_climbed`,
`blood_oxygen`, `body_fat_pct`, `water_ml`.

Данные за вчера/сегодня автоматически попадают в утренний дайджест строкой вида
`⌚ Сон: 7.2 ч, шаги вчера: 8 430, пульс покоя: 58`. Посмотреть сырые данные можно через
`GET /api/v1/health/metrics?metric_type=steps&days=7` (с тем же ключом).

## Структура проекта

```
bot/    — Telegram-бот (aiogram): handlers, keyboards, middleware
core/   — бизнес-логика: database (SQLite+миграции), nutrition, training, ai, config
api/    — REST API (FastAPI): main, auth, schemas, routers/
data/   — SQLite-база и сиды (volume в Docker)
logs/   — логи (volume в Docker)
```

## Примечание

Проект в бете: оплата не подключена, Premium выдаётся администратором вручную.
