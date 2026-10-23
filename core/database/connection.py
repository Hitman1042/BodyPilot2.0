"""Подключение к SQLite и управление миграциями."""

from __future__ import annotations

import pathlib
import sqlite3
import threading
from typing import Any

from core.config import settings

_LOCAL = threading.local()


def get_db() -> sqlite3.Connection:
    """Получить подключение к БД (thread-safe)."""
    db_path = pathlib.Path(settings.DATABASE_PATH)
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        try:
            if conn.execute("PRAGMA database_list").fetchone()[2] == str(db_path.resolve()):
                return conn
        except sqlite3.ProgrammingError:
            pass
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    _LOCAL.conn = conn
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Проверить и применить миграции."""
    from .migrations import run_migrations
    run_migrations(conn)


def init_database() -> None:
    """Инициализировать БД (вызывается при старте)."""
    conn = get_db()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64 MB
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.commit()