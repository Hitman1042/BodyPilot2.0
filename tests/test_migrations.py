"""Миграции БД: чистая база, идемпотентность, сидинг."""

import sqlite3

from core.database.migrations import SCHEMA_VERSION, run_migrations

EXPECTED_TABLES = {
    "users",
    "food_log",
    "food_log_new",
    "food_products",
    "weight_log",
    "workout_sessions",
    "exercises",
    "sports",
    "premium_subscriptions",
    "ai_usage_limits",
    "ai_knowledge_base",
    "ai_question_templates",
    "api_keys",
    "health_metrics",
    "achievements",
    "water_log",
    "report_log",
    "challenges",
    "tip_log",
    "reminder_log",
    "progress_photos",
    "user_preferences",
    "health_conditions",
    "user_health_conditions",
    "kudos",
}


def _fresh_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "fresh.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {r[0] for r in rows}


def test_migrations_set_schema_version(tmp_path):
    conn = _fresh_db(tmp_path)
    run_migrations(conn)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


def test_migrations_create_all_tables(tmp_path):
    conn = _fresh_db(tmp_path)
    run_migrations(conn)
    missing = EXPECTED_TABLES - _table_names(conn)
    assert not missing, f"Нет таблиц: {missing}"


def test_migrations_idempotent(tmp_path):
    conn = _fresh_db(tmp_path)
    run_migrations(conn)
    run_migrations(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert EXPECTED_TABLES <= _table_names(conn)


def test_seed_data(tmp_path):
    conn = _fresh_db(tmp_path)
    run_migrations(conn)
    templates = conn.execute("SELECT COUNT(*) FROM ai_question_templates").fetchone()[0]
    assert templates > 0, "Шаблоны ИИ-вопросов не засеяны"
    sports = conn.execute("SELECT COUNT(*) FROM sports").fetchone()[0]
    assert sports == 10
    conditions = conn.execute("SELECT COUNT(*) FROM health_conditions").fetchone()[0]
    assert conditions == 15
