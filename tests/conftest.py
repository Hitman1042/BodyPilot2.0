"""Общая конфигурация pytest: тесты работают на временной БД.

Переменная DATABASE_PATH выставляется ДО импорта core.config
(pydantic-settings: env-переменные имеют приоритет над .env),
поэтому продакшн data/bodypilot.db тесты не трогают.
"""

import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="bodypilot_test_")
os.environ["DATABASE_PATH"] = os.path.join(_TMPDIR, "test.db")

import pytest

from core.database.connection import get_db


@pytest.fixture(scope="session")
def db_conn():
    """Соединение с временной тестовой БД (миграции применяются автоматически)."""
    return get_db()


@pytest.fixture(scope="session")
def test_user(db_conn):
    """Тестовый пользователь user_id=1."""
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (1, "testuser"),
    )
    db_conn.commit()
    return 1
