# AGENTS.md — BodyPilot 2.0 (контекст проекта для ИИ-агентов)

> Этот файл — единая точка входа для работы с проектом. Читай его вместо обхода всех файлов.
> **Правило: после каждого изменения кода обновляй этот файл (актуальные цифры, новые модули, новые правила).**
> Последнее обновление: 2026-10-25 (239 тестов, SCHEMA_VERSION=23).

## 1. Что это

Фитнес/питание-ассистент: Telegram-бот + REST API + Telegram Mini App.
AI-коуч (Gemini) понимает свободный текст и голос, записывает еду/тренировки, меняет планы под пользователя.
Геймификация (стрик, ачивки, челленджи), дайджесты, напоминания, метрики с часов.

**Стек:** Python 3.12, aiogram 3.29, FastAPI + uvicorn, SQLite (WAL, чистый sqlite3, без ORM), Google Gemini (REST через aiohttp), Vue 3 через CDN (Mini App, без сборки), matplotlib (графики PNG).

## 2. Команды (Windows, Git Bash)

```bash
py -3.12 -m bot.main                 # бот (python в PATH нет, только launcher py)
py -3.12 -m uvicorn api.main:app --port 8000   # API + Mini App (/app)
py -3.12 -m pytest -q                # тесты (239 на момент записи)
py -3.12 -m compileall bot core api -q         # проверка синтаксиса
py -3.12 -X utf8 -c "..."            # вывод кириллицы/эмодзи в консоли (иначе cp1251 падает)
```

Проверка после любых правок: compileall + `import bot.main, api.main` + pytest (должны быть зелёные).

## 3. Карта проекта

```
bot/
  main.py              # вход: init_database(), middleware, роутеры, scheduler, MenuButton Mini App
  logging_config.py    # ротация логов logs/botpilot.log, UTF-8 консоль
  handlers/            # ~25 роутеров (см. §5)
  keyboards/           # main_menu.py (6 reply-кнопок), inline_menus.py (подменю)
  middleware/          # throttling (антиспам), db_session, premium_check
core/
  config.py            # pydantic-settings Settings из .env (см. §8)
  database/
    connection.py      # get_db(): thread-local SQLite, PRAGMA WAL/foreign_keys
    migrations.py      # run_migrations, SCHEMA_VERSION=23, _migrate_v1..v23
    ...                # subscriptions, stats, workout, weight, progress_photos
  nutrition_tracker.py # ДНЕВНИК ЕДЫ (food_log_new, food_products) + локальные даты
  nutrition_calc.py    # BMR Mifflin-St Jeor, TDEE, цель ×0.85/1.0/1.10, БЖУ г/кг, вода
  training_service.py  # генератор тренировок (6 модулей), адаптация по фидбеку, сну и здоровью
  records.py           # личные рекорды веса/повторов/тоннажа, шагов и белка + детектор PR
  load.py              # effort=мин×интенсивность; Fitness/Fatigue EWMA tau=42/7, Freshness
  safety.py            # health_conditions, авто-возраст 60/70+, фильтр упражнений и load_cap
  plans.py             # план питания (с фильтром food_exclusions + allergies)
  preferences.py       # user_preferences: home/gym, инвентарь, исключения еды
  gamification.py      # стрик, 11 достижений, вода (water_log)
  challenges.py        # 3 челленджа, прогресс вычисляется из данных
  digest.py            # утренний дайджест (вчера + правила + 1 AI-вызов)
  scheduler.py         # APScheduler: дайджест, чек-ин 21:00, отчёт Вс 20:00, советы, напоминания
  reminders.py         # отбор пользователей для напоминаний (no_food/workout/reactivation/photo)
  weekly_report.py     # отчёт за неделю + AI-комментарий + блок Fitness/Freshness
  charts.py            # matplotlib PNG: вес, калории, тренировки, шаги, сон, форма 8 недель
  health_data.py       # health_metrics (часы): add_metric, агрегаты, тренды недели
  referrals.py         # подписки, AI-лимиты (AI_LIMITS_ENABLED=false на бету)
  social.py            # друзья по referrals, приватная лента, Kudos, групповой прогресс
  ai/
    gemini_client.py   # GeminiClient: _request (fallback-цепочка моделей), vision, voice, chat_with_tools
    tools.py           # 21 function-calling tool (см. §6)
    context.py         # build_user_context: профиль+нормы+сегодня+сон+здоровье+предпочтения
    chat_history.py    # история диалога + append_event (события еды/тренировок)
    ai_router.py       # кэш → 1672 шаблона → full_ai (бесплатные ответы без API)
    food_recognition.py# классификация фото dish/label/receipt/other + запись
    text_markers.py    # has_food_intent («съел», «выпил», «на обед»...)
api/
  main.py              # FastAPI app + mount /app (webapp статика) + /docs
  auth.py              # initData (Mini App) / X-API-Key / X-Admin-Key
  schemas.py           # pydantic-схемы (точные имена полей для фронта!)
  routers/             # health, profile, onboarding, nutrition, workouts, stats, plans, water,
                       # health_data, chat (текст+голос), challenges, progress, admin, analytics, social
webapp/                # Mini App: Vue 3, 5 вкладок + онбординг и админка; голосовой коуч,
                       # загрузка фото, рекорды, нагрузка, календарь, друзья и челленджи
tests/                 # pytest; conftest.py = временная БД (env DATABASE_PATH до импорта core)
scripts/               # debug_*.py (бывшие ручные тесты), maintenance/
data/                  # bodypilot.db (НЕ коммитить), init_exercises/init_meals (сиды)
Dockerfile, docker-compose.yml (bot+api+caddy), Caddyfile, DEPLOY.md, README.md
```

## 4. База данных

- Миграции идемпотентные, через `PRAGMA user_version`; применяются автоматически при `get_db()` и при старте бота.
- Новая таблица = `_migrate_vN` + `SCHEMA_VERSION+=1` + вызов в `run_migrations` + добавить таблицу в `tests/test_migrations.py::EXPECTED_TABLES`.
- **SCHEMA_VERSION=23**: users, food_log_new, food_products, workout_*, exercises, sports,
  premium_subscriptions, ai_usage_limits, ai_knowledge_base, ai_question_templates,
  api_keys, health_metrics, workout_feedback, daily_checkins, achievements, water_log,
  report_log, challenges, tip_log, reminder_log, progress_photos, user_preferences,
  health_conditions, user_health_conditions, kudos.
- Старые таблицы food_log/food_items — мёртвые (данные перенесены миграцией v11), не использовать.
- **ЗАПРЕТ**: нельзя делать `conn.close()` и подменять `row_factory` на общем thread-local соединении (была эпидемия багов). Нужен dict — `dict(row)` локально.
- Тесты на копии БД или временной (conftest), прод-БД не трогать без необходимости.

## 5. Бот: ключевые правила

- **Порядок роутеров в main.py важен**: `delete_flow_router` (удаление еды текстом «удали/отмени») — сразу после menu_router, РАНЬШЕ всех FSM; команды/FSM/меню дальше, `smart_input_router` — ПОСЛЕДНИЙ (ловит весь свободный текст и голос).
- **smart_input.py**: свободный текст → маркеры еды → коуч напрямую; несколько строк (список блюд) → коуч сразу (log_food_batch, НЕ склеивать в одну карточку); распознаватель может вернуть dict ИЛИ list — оба нормализуются; иначе recognize_food_from_text → карточка ✅/✏️/❌; не еда → кэш/шаблоны → коуч. Голос → transcribe_voice → коуч (не карточка одного блюда!).
- Главное меню (6 кнопок): Еда, Тренировки, Прогресс, AI-коуч, Приложение, Профиль. Тексты в `MAIN_MENU_BUTTONS` (keyboards/main_menu.py) — используются для FSM-эскейпа.
- **callback.message.from_user = БОТ**, реальный пользователь — `callback.from_user`. Все callback→cmd вызовы передают user_id явно.
- `callback.answer()` — ПЕРВЫМ, до долгих операций (AI/БД), иначе «query is too old».
- Все сообщения в parse_mode=HTML: пользовательский ввод, ответы AI и внешние API — через `html.escape()`. Угловые скобки в текстах-примерах — `&lt;...&gt;`.
- Локальные даты пользователя: `timezone_offset` (минуты). В nutrition_tracker есть `_local_today`, `_day_expr`, `_local_now_hm` — используй их, не `date.today()`. `logged_at` в БД — UTC.
- AI-лимиты выключены (`AI_LIMITS_ENABLED=false`); админ (TELEGRAM_ADMIN_USER_IDS) безлимитен всегда.
- Регистрация: profile.py, 7 шагов + «пропустить всё остальное»; кнопки меню/команды во время FSM прерывают регистрацию.
- /records и кнопка «🏆 Рекорды» в Прогрессе; новые PR отправляются после опроса фидбека. /stats показывает активные дни (еда или тренировка) за 7 дней.
- «👥 Друзья» в «⚙️ Профиль» (`bot/handlers/social.py`): 5 событий ленты, Kudos с уведомлением и групповые челленджи. Друзья — только обе стороны referrals; Kudos проверяет владельца события и повтор запрещён UNIQUE.

## 6. AI-архитектура

- **Модели**: `GEMINI_MODEL` (основная, сейчас gemini-3.5-flash-lite) + `GEMINI_MODELS` (fallback: 3.1-flash-lite, 3.8-flash, 3.7-flash, 3.6-flash). Квоты Google — ПО КАЖДОЙ МОДЕЛИ, при 429/5xx клиент переключается. Итого ~1000 RPD.
- **Сеть**: сессии с `trust_env=True` (системный прокси Windows), иначе «User location is not supported».
- **chat_with_tools(user_id, question, history)**: system_instruction = CHAT_TOOLS_SYSTEM_INSTRUCTION + COACH_PERSONA + build_user_context. До 3 раундов function calling. Ответы персональные — НЕ кэшировать в общий ai_knowledge_base.
- **21 tool** (core/ai/tools.py): log_food, log_food_batch (до 10 позиций), log_water (вода мл), join_challenge (вступить в челлендж), delete_food_entry, delete_workout_session (последняя/за дату, с подходами), delete_health_metric (сон/шаги/пульс/вес за день), adjust_last_food_entry (×N / новый вес), get_today_nutrition, get_nutrition_history, log_weight, log_health_metric (шаги/сон/пульс/вес за любой день, перезапись manual/chat), update_profile (цель/активность/вес/рост/возраст/аллергии/город/время дайджеста/таймзона/вид спорта), get_workout_plan_today, get_weekly_stats, log_workout_done, set_training_preferences (сразу перегенерирует план), regenerate_workout_plan, set_health_condition (ограничения здоровья + безопасная перегенерация), set_food_preferences / regenerate_meal_plan. Точный список см. TOOL_DECLARATIONS.
- Валидация аргументов — обязательна в execute_tool (модель ошибается).
- Дешёвые пути: ai_router (кэш/шаблоны) бесплатно; дайджест/чек-ин — правила + максимум 1 AI-вызов.

## 7. API + Mini App

- Авторизация: `X-Telegram-Init-Data` (HMAC по токену бота) или `X-API-Key` (таблица api_keys); админ — `X-Admin-Key`.
- Mini App = webapp/ на том же origin (`/app`). Фронт шлёт initData в каждом запросе; 401 → экран «открой через бота».
- 5 вкладок: День, Дневник, Прогресс, Планы, Коуч. Поля ответов — строго по api/schemas.py.
- На вкладке «День» карточка «⌚ Активность» имеет кнопку «＋ Записать» — ручной ввод шагов/сна/пульса за сегодня или вчера (POST /api/v1/health/metrics).
- Аналитика: GET /api/v1/records, /api/v1/analytics/load?weeks=8, /api/v1/analytics/calendar?month=YYYY-MM. В Прогрессе — рекорды, Chart.js Fitness/Fatigue/Freshness и месячный календарь.
- Соцмеханики: GET /api/v1/social/feed, POST /api/v1/social/kudos, GET /api/v1/social/challenge/{code}; в Прогрессе — лента друзей, 👏 и групповой прогресс.
- Голос коуча: POST `/api/v1/chat/voice` (multipart audio до 20 МБ, ogg/webm/mp4/mpeg, таймаут 90 с) → transcript + answer + tools_used. В Mini App MediaRecorder пишет до 60 с.
- Онбординг: GET `/api/v1/profile` → 404 открывает визард; POST `/api/v1/onboarding` создаёт профиль, считает нормы и запускает trial.
- Фото прогресса: POST `/api/v1/progress/photos` (multipart photo, weight_kg?, note?) → Telegram sendPhoto → сохранение file_id; GET `/api/v1/progress/photos/{id}/file` — прокси с кэшем 1ч. Для multipart нужен пакет python-multipart.
- Админка: `is_admin` в ProfileOut по TELEGRAM_ADMIN_USER_IDS; GET `/api/v1/admin/metrics` и POST `/api/v1/admin/grant_premium` только с X-Admin-Key. Ключ в Mini App хранится в sessionStorage.
- `MINIAPP_URL` в .env включает: кнопку в главном меню, /app, MenuButton при старте бота. Пусто = скрыто.
- Пользовательский API-ключ для часов: команда /api_key (name='user-self').

## 8. Конфиг (.env / core/config.py)

Обязательные: TELEGRAM_BOT_TOKEN, GEMINI_API_KEY. Деплой: DOMAIN, MINIAPP_URL.
Прочие: TELEGRAM_ADMIN_USERNAME, TELEGRAM_ADMIN_USER_IDS, ADMIN_PASSWORD, ADMIN_API_KEY,
DATABASE_PATH, GEMINI_MODEL, GEMINI_MODELS, LOG_LEVEL, AI_LIMITS_ENABLED,
REFERRAL_SECRET_SALT, FATSECRET_CLIENT_ID/SECRET (не используются), WGER_API_TOKEN,
OPENAI_API_KEY (не используется), WATCH_SYNC_IOS_LINK, DIGEST_CHECK_INTERVAL_MINUTES.
`.env.example` — актуальный список; `.env` НЕ читать/не печатать (секреты).

## 9. Деплой

DEPLOY.md — пошагово. `docker compose up -d --build` → bot + api + caddy (авто-HTTPS).
`docker compose config -q` — валидация (нужен DOMAIN=...).
Данные: volumes ./data, ./logs. iOS Shortcuts для часов: рецепт в истории/README (WATCH_SYNC_IOS_LINK).

## 10. Известные ограничения / что не трогать без нужды

- Часы: полноценная автосинхронизация только через iOS Shortcuts / внешние мосты; Health Connect — будущее нативное приложение. OAuth-провайдеры (Fitbit/Withings) — следующий этап.
- workouts_per_week сохраняется, но дневной генератор частоту не использует.
- core/database/premium.py — НЕ мёртвый код, а заготовка под монетизацию (сейчас не подключён к живому коду; НЕ удалять, НЕ «вычищать»). Доделываем при запуске платной подписки. Модель: первые пользователи беты — бесплатно (с рефералкой для привлечения), новые пользователи позже — платная подписка в боте и Mini App. AI-лимиты на бету выключены (AI_LIMITS_ENABLED=false); при включении монетизации вернуть лимиты и оплату (Telegram Stars / внешняя).
- Отладочные команды /debug_plan, /test_plan, /check_exercises — только админам.
- Файлы bot/handlers/ai_food.py и food_tracker.py могли иметь CRLF — при Edit несовпадение old_string править через python-патч, аккуратно.

## 11. Workflow для агента

1. Прочитай этот файл; конкретные файлы открывай точечно по задаче.
2. Правки → compileall + imports + pytest (все зелёные).
3. Новая таблица/настройка/роутер/кнопка — проверь связанные места (миграции, main.py, клавиатуры, тесты).
4. **Обнови AGENTS.md** (что добавлено, новые цифры тестов, SCHEMA_VERSION, дату).
