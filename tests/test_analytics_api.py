"""API рекордов, нагрузки и календаря активности."""

import pytest
from fastapi.testclient import TestClient

from api.main import app

API_KEY = "test-key-analytics-0001"
USER_ID = 930003


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def analytics_key(db_conn):
    for table in ("health_metrics", "water_log", "food_log_new"):
        db_conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (USER_ID,))
    db_conn.execute("DELETE FROM workout_sessions WHERE user_id = ?", (USER_ID,))
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 180)",
        (USER_ID, "analytics_user"),
    )
    db_conn.execute("UPDATE users SET timezone_offset = 180 WHERE user_id = ?", (USER_ID,))
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, 'pytest-analytics')",
        (API_KEY, USER_ID),
    )
    db_conn.commit()
    return API_KEY


def test_analytics_endpoints_require_auth(client):
    assert client.get("/api/v1/records").status_code == 401
    assert client.get("/api/v1/analytics/load").status_code == 401
    assert client.get("/api/v1/analytics/calendar?month=2026-10").status_code == 401


def test_calendar_marks_food_workout_health_and_empty_days(client, analytics_key, db_conn):
    db_conn.execute(
        """INSERT INTO food_log_new
           (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g, meal_time, logged_at)
           VALUES (?, 'Поздний ужин', 100, 450, 30, 12, 40, '00:30', '2026-10-02 21:30:00')""",
        (USER_ID,),
    )
    db_conn.execute(
        "INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date) VALUES (?, 'strength', 45, 7, '2026-10-02')",
        (USER_ID,),
    )
    db_conn.execute(
        "INSERT INTO health_metrics (user_id, ts, metric_type, value) VALUES (?, '2026-10-02 12:00:00', 'steps', 9000)",
        (USER_ID,),
    )
    db_conn.execute(
        "INSERT INTO water_log (user_id, amount_ml, logged_at) VALUES (?, 750, '2026-10-02 12:00:00')",
        (USER_ID,),
    )
    db_conn.commit()

    response = client.get(
        "/api/v1/analytics/calendar?month=2026-10",
        headers={"X-API-Key": analytics_key},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["month"] == "2026-10"
    assert len(body["days"]) == 31
    days = {item["date"]: item for item in body["days"]}
    assert days["2026-10-02"] == {
        "date": "2026-10-02",
        "has_food": False,
        "has_workout": True,
        "steps": 9000,
        "water_ml": 750,
        "calories": 0.0,
    }
    assert days["2026-10-03"]["has_food"] is True
    assert days["2026-10-03"]["calories"] == 450
    assert days["2026-10-04"] == {
        "date": "2026-10-04",
        "has_food": False,
        "has_workout": False,
        "steps": None,
        "water_ml": 0,
        "calories": 0.0,
    }


def test_records_load_and_invalid_month(client, analytics_key):
    headers = {"X-API-Key": analytics_key}
    records = client.get("/api/v1/records", headers=headers)
    assert records.status_code == 200
    assert "exercises" in records.json()

    load = client.get("/api/v1/analytics/load?weeks=8", headers=headers)
    assert load.status_code == 200
    assert len(load.json()["days"]) == 56
    assert load.json()["current"]["interpretation"] in {
        "отличная форма, можно интенсивно", "норма", "усталость — лёгкий день"
    }
    assert client.get(
        "/api/v1/analytics/calendar?month=2026-13", headers=headers
    ).status_code == 422
