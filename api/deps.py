"""Общие зависимости FastAPI."""

from __future__ import annotations

import sqlite3

from core.database import get_db as _get_db


def get_db() -> sqlite3.Connection:
    """Подключение к БД.

    core.get_db() thread-local: эндпоинты объявлены синхронными (def), FastAPI
    выполняет их в threadpool, каждый поток получает своё соединение.
    """
    return _get_db()
