"""Настройка логирования для BodyPilot бота."""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler


def setup_logging(log_file: str = "logs/botpilot.log", level: int = logging.DEBUG) -> None:
    """Настроить логирование в файл и консоль.

    Args:
        log_file: Путь к файлу логов
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
    """
    # Создаём папку для логов
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Настраиваем формат
    log_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Получаем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Очищаем старые обработчики
    root_logger.handlers.clear()

    # === Файловый обработчик (с ротацией) ===
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,  # Хранить 3 старых файла
        encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    # === Консольный обработчик (UTF-8, чтобы эмодзи не роняли лог на cp1251) ===
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)  # В консоль только важное
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)

    # Логгер для отладки
    logging.getLogger("aiogram").setLevel(logging.WARNING)  # Скрыть логи aiogram
    logging.getLogger("aiohttp").setLevel(logging.WARNING)  # Скрыть логи aiohttp

    logging.info("📝 Логирование настроено: файл=%s, уровень=%s", log_file, logging.getLevelName(level))