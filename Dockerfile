FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода (секреты и БД исключены через .dockerignore)
COPY . .

# Папки для БД и логов (монтируются volume'ами из compose)
RUN mkdir -p data logs

# По умолчанию — бот; API переопределяется command в docker-compose.yml
CMD ["python", "-m", "bot.main"]
