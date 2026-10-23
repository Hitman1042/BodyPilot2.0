"""Конфигурация BodyPilot через pydantic-settings (явный путь к .env)."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Настройки приложения, загружаются из .env в корне проекта."""

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_USERNAME: str = "hitman1042"
    TELEGRAM_ADMIN_USER_IDS: str = ""
    TELEGRAM_COMMAND_MODE: str = "full"

    # База данных
    DATABASE_PATH: str = str(PROJECT_ROOT / "data" / "bodypilot.db")

    # API-ключи
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # Gemini: основная модель + цепочка fallback (квоты RPD считаются по каждой
    # модели отдельно — при 429 переключаемся на следующую)
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_MODELS: str = (
        "gemini-3.1-flash-lite,gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash"
    )
    WGER_API_TOKEN: str = ""

    # FatSecret Platform API
    FATSECRET_CLIENT_ID: str = ""
    FATSECRET_CLIENT_SECRET: str = ""

    # Реферальная система
    REFERRAL_SECRET_SALT: str = "bodypilot_ref_secret_change_me"

    # Админка
    ADMIN_PASSWORD: str = ""

    # Логирование
    LOG_LEVEL: str = "INFO"

    # AI-лимиты: False = выключены для всех (режим бета-теста)
    AI_LIMITS_ENABLED: bool = False

    # Ссылка на готовую команду Shortcuts (iOS) для автосинхронизации часов
    WATCH_SYNC_IOS_LINK: str = ""

    # Планировщик
    DIGEST_CHECK_INTERVAL_MINUTES: int = 1

    # Web API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    ADMIN_API_KEY: str = ""  # ключ для /api/v1/admin/* (заголовок X-Admin-Key)

    # Telegram Mini App: https-URL веб-приложения (пусто = фича скрыта)
    MINIAPP_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),  # ← теперь всегда читается из корня проекта
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()