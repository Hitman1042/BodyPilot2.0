# Деплой BodyPilot 2.0 на VPS

Пошаговая инструкция для Ubuntu/Debian. Время: ~20–30 минут (+ сборка образа на слабом VPS до 10 минут).

## Что получится

- Telegram-бот (polling) — контейнер `bot`
- REST API + Mini App — контейнер `api`
- HTTPS с авто-сертификатом Let's Encrypt — контейнер `caddy`
- Данные (SQLite, логи) — на диске сервера, переживают обновления

## Шаг 0. Подготовка (5 минут)

1. **DNS**: в панели регистратора домена создай A-запись:
   `твой-домен.com → <IP сервера>` (жди 5–30 минут распространения).
2. **Порты**: на VPS (и в файрволе провайдера) открыты `80` и `443`.
3. **Репозиторий**: код на GitHub (приватный репозиторий) — либо зальёшь файлы вручную (шаг 2б).

## Шаг 1. Docker на сервере

```bash
ssh root@<IP-сервера>
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version
```

## Шаг 2. Код на сервере

Вариант А — git (рекомендуется):
```bash
git clone https://github.com/<твой-логин>/bodypilot.git
cd bodypilot
```

Вариант Б — вручную с локальной машины (PowerShell/cmd на Windows):
```cmd
scp -r C:\Users\vlad-\Downloads\BodyPilot2.0-main root@<IP>:/root/bodypilot
ssh root@<IP> "cd /root/bodypilot && ls"
```
(`.gitignore`/`.dockerignore` не дадут уехать лишнему, но `.env` создадим на сервере отдельно.)

## Шаг 3. Конфигурация `.env`

```bash
cp .env.example .env
nano .env
```

Обязательные:
```
TELEGRAM_BOT_TOKEN=<токен от @BotFather>
GEMINI_API_KEY=<ключ Google AI Studio>
DOMAIN=твой-домен.com
MINIAPP_URL=https://твой-домен.com/app
```

Рекомендуемые:
```
TELEGRAM_ADMIN_USERNAME=<твой username без @>
TELEGRAM_ADMIN_USER_IDS=<твой числовой ID>
ADMIN_PASSWORD=<сложный пароль админки>
ADMIN_API_KEY=<случайная строка для /api/v1/admin/*>
REFERRAL_SECRET_SALT=<любая случайная строка>
AI_LIMITS_ENABLED=false
```

## Шаг 4. (Опционально) Перенос существующей БД

Если хочешь сохранить пользователей с dev-машины:
```cmd
:: с локальной машины, при остановленном боте
scp C:\Users\vlad-\Downloads\BodyPilot2.0-main\data\bodypilot.db root@<IP>:/root/bodypilot/data/bodypilot.db
```
Если нет — БД создастся пустой, миграции и сиды применятся сами.

## Шаг 5. Запуск

```bash
docker compose up -d --build
docker compose ps          # все 3 сервиса Up (healthy)
docker compose logs -f bot # Ctrl+C для выхода
```

Первая сборка 3–10 минут (ставятся matplotlib и зависимости).

## Шаг 6. Проверка

```bash
curl https://твой-домен.com/health          # {"status":"ok","db":"ok"}
curl https://твой-домен.com/app/            # HTML Mini App
curl https://твой-домен.com/api/v1/profile  # 401 — авторизация работает
```

В Telegram боту: `/start` → «🤖 AI-коуч» → «📱 Приложение» → открывается Mini App по HTTPS.

## Обновление кода

```bash
git pull              # или scp новых файлов
docker compose up -d --build
```

## Полезные команды

```bash
docker compose logs -f api        # логи API
docker compose restart bot        # перезапуск бота
docker compose down               # остановить всё
docker compose up -d              # поднять обратно (без пересборки)
du -sh data/                      # размер БД
```

## Бэкап БД (рекомендуется)

Раз в сутки, cron на сервере:
```bash
echo '0 4 * * * cp /root/bodypilot/data/bodypilot.db /root/backups/bodypilot-$(date +\%F).db' | crontab -
mkdir -p /root/backups
```

## Если что-то не работает

| Симптом | Причина | Решение |
|---|---|---|
| Caddy не стартует | DNS не указывает на сервер / порты закрыты | `dig твой-домен.com`, проверить файрвол |
| `ERR_CERT` в браузере | сертификат ещё не выдан | подожди 1–2 мин, `docker compose logs caddy` |
| Mini App белый экран | неверный MINIAPP_URL | должен быть `https://<домен>/app`, перезапуск: `docker compose up -d` |
| Бот не отвечает | нет токена/сети | `docker compose logs bot` |
| 401 в приложении | открыто не через бота | открывай только кнопкой из Telegram |
