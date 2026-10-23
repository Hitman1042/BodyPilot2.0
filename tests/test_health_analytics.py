"""Недельная аналитика метрик здоровья: агрегаты, графики, сон в адаптации, API."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.charts import chart_sleep, chart_steps
from core.health_data import get_weekly_health_stats
from core.training_service import get_adaptation_factors, save_workout_feedback

HEALTH_API_KEY = "test-key-health-analytics"


def _make_user(db_conn, user_id: int, name: str) -> None:
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, name),
    )
    db_conn.execute("UPDATE users SET timezone_offset = 0 WHERE user_id = ?", (user_id,))
    db_conn.commit()


def _add_metric(db_conn, user_id: int, metric: str, value: float, day) -> None:
    db_conn.execute(
        """INSERT INTO health_metrics (user_id, ts, metric_type, value, source)
           VALUES (?, ?, ?, ?, 'test')""",
        (user_id, f"{day.isoformat()}T12:00:00+00:00", metric, float(value)),
    )


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ── Недельные агрегаты и тренды ─────────────────────────────────────────

def test_weekly_stats_averages_and_trend(db_conn):
    user_id = 930001
    _make_user(db_conn, user_id, "wa_stats")
    today = datetime.now(timezone.utc).date()
    # Текущая неделя: 3 дня данных
    for i in range(3):
        day = today - timedelta(days=i)
        _add_metric(db_conn, user_id, "steps", 9000 + i * 1000, day)
        _add_metric(db_conn, user_id, "sleep_hours", 6.5 + i, day)
        _add_metric(db_conn, user_id, "resting_heart_rate", 60, day)
    # Предыдущая неделя: вдвое меньше шагов, сон 5 ч
    for i in range(3):
        day = today - timedelta(days=7 + i)
        _add_metric(db_conn, user_id, "steps", 4500 + i * 500, day)
        _add_metric(db_conn, user_id, "sleep_hours", 5.0, day)
    db_conn.commit()

    stats = get_weekly_health_stats(user_id)
    assert stats["days"] == 7
    assert stats["avg_steps"] == 10000
    assert stats["total_steps"] == 30000
    assert stats["avg_sleep_hours"] == 7.5
    assert stats["avg_resting_heart_rate"] == 60
    assert stats["steps_trend_pct"] == pytest.approx(100.0)
    assert stats["sleep_trend_pct"] == pytest.approx(50.0)
    assert stats["best_sleep_day"]["hours"] == 8.5
    assert stats["worst_sleep_day"]["hours"] == 6.5
    assert stats["best_sleep_day"]["date"] == (today - timedelta(days=2)).isoformat()


def test_weekly_stats_no_data(db_conn):
    user_id = 930002
    _make_user(db_conn, user_id, "wa_empty")
    stats = get_weekly_health_stats(user_id)
    assert stats["avg_steps"] is None
    assert stats["total_steps"] is None
    assert stats["avg_sleep_hours"] is None
    assert stats["avg_resting_heart_rate"] is None
    assert stats["best_sleep_day"] is None
    assert stats["worst_sleep_day"] is None
    assert stats["steps_trend_pct"] is None
    assert stats["sleep_trend_pct"] is None


# ── Графики шагов и сна ─────────────────────────────────────────────────

def test_steps_and_sleep_charts_valid_png(db_conn):
    user_id = 930003
    _make_user(db_conn, user_id, "wa_charts")
    today = datetime.now(timezone.utc).date()
    for i in range(3):
        day = today - timedelta(days=i)
        _add_metric(db_conn, user_id, "steps", 8000 + i * 500, day)
        _add_metric(db_conn, user_id, "sleep_hours", 7.0 + i * 0.5, day)
    db_conn.commit()

    for png in (chart_steps(user_id), chart_sleep(user_id)):
        assert png is not None
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(png) > 10_000


def test_charts_none_with_less_than_two_days(db_conn):
    user_id = 930004
    _make_user(db_conn, user_id, "wa_one_day")
    today = datetime.now(timezone.utc).date()
    _add_metric(db_conn, user_id, "steps", 5000, today)
    _add_metric(db_conn, user_id, "sleep_hours", 7.5, today)
    db_conn.commit()

    assert chart_steps(user_id) is None
    assert chart_sleep(user_id) is None


# ── Сон в адаптации тренировки ──────────────────────────────────────────

def test_sleep_under_6h_reduces_load(db_conn):
    user_id = 930005
    _make_user(db_conn, user_id, "wa_sleep6")
    today = datetime.now(timezone.utc).date()
    _add_metric(db_conn, user_id, "sleep_hours", 5.5, today)
    db_conn.commit()

    factors = get_adaptation_factors(user_id)
    assert factors["load_multiplier"] == pytest.approx(0.92)
    assert "мало сна" in factors["note"]


def test_sleep_under_5h_reduces_load_harder(db_conn):
    user_id = 930006
    _make_user(db_conn, user_id, "wa_sleep5")
    today = datetime.now(timezone.utc).date()
    _add_metric(db_conn, user_id, "sleep_hours", 4.5, today)
    db_conn.commit()

    factors = get_adaptation_factors(user_id)
    assert factors["load_multiplier"] == pytest.approx(0.85)
    assert "сильный недосып" in factors["note"]


def test_sleep_combines_with_feedback(db_conn):
    user_id = 930007
    _make_user(db_conn, user_id, "wa_combo")
    save_workout_feedback(user_id, difficulty=5, soreness=4, energy=2)
    today = datetime.now(timezone.utc).date()
    _add_metric(db_conn, user_id, "sleep_hours", 5.5, today)
    db_conn.commit()

    factors = get_adaptation_factors(user_id)
    assert factors["load_multiplier"] == pytest.approx(0.88 * 0.92)
    assert "высокая нагрузка" in factors["note"]
    assert "мало сна" in factors["note"]


def test_no_sleep_data_no_change(db_conn):
    user_id = 930008
    _make_user(db_conn, user_id, "wa_nosleep")

    factors = get_adaptation_factors(user_id)
    assert factors["load_multiplier"] == 1.0
    assert factors["note"] == ""
    assert factors["feedback"] is None

    save_workout_feedback(user_id, difficulty=5, soreness=4, energy=2)
    factors = get_adaptation_factors(user_id)
    assert factors["load_multiplier"] == pytest.approx(0.88)
    assert "сон" not in factors["note"]


# ── API /health/summary ─────────────────────────────────────────────────

def test_health_summary_requires_auth(client):
    assert client.get("/api/v1/health/summary").status_code == 401


def test_health_summary_ok(client, db_conn):
    user_id = 930009
    _make_user(db_conn, user_id, "wa_api")
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
        (HEALTH_API_KEY, user_id, "pytest"),
    )
    today = datetime.now(timezone.utc).date()
    _add_metric(db_conn, user_id, "steps", 7000, today)
    _add_metric(db_conn, user_id, "sleep_hours", 7.0, today)
    db_conn.commit()

    resp = client.get(
        "/api/v1/health/summary?days=7",
        headers={"X-API-Key": HEALTH_API_KEY},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 7
    assert body["steps_today"] == 7000
    assert body["sleep_last_night"] == 7.0
    assert body["avg_sleep_hours"] == 7.0
    assert body["avg_steps"] == 7000
    assert body["total_steps"] == 7000
    assert body["steps_trend_pct"] is None
    assert body["best_sleep_day"]["hours"] == 7.0
