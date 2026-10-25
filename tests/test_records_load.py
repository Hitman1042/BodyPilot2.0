"""Личные рекорды, Relative Effort и кривые Fitness/Fatigue/Freshness."""

import math
from datetime import date

import pytest

from core.charts import chart_fitness
from core.load import (
    _interpret_freshness,
    get_current_freshness,
    get_load_curves,
    session_effort,
)
from core.records import check_new_records, get_personal_records


@pytest.fixture
def records_user(db_conn):
    user_id = 930001
    for table in ("health_metrics", "food_log_new"):
        db_conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    db_conn.execute("DELETE FROM workout_sessions WHERE user_id = ?", (user_id,))
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, "records_user"),
    )
    db_conn.commit()
    return user_id


def _session(db_conn, user_id, day, weight, reps, duration=45, intensity=7):
    cursor = db_conn.execute(
        """INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date)
           VALUES (?, 'strength', ?, ?, ?)""",
        (user_id, duration, intensity, day),
    )
    session_id = cursor.lastrowid
    cursor = db_conn.execute(
        "INSERT INTO workout_exercises (session_id, custom_exercise_name) VALUES (?, 'Жим лёжа')",
        (session_id,),
    )
    db_conn.execute(
        """INSERT INTO workout_sets (workout_exercise_id, set_number, reps, weight_kg)
           VALUES (?, 1, ?, ?)""",
        (cursor.lastrowid, reps, weight),
    )
    db_conn.commit()
    return session_id


def test_personal_records_and_new_pr_detection(records_user, db_conn):
    first_id = _session(db_conn, records_user, "2026-10-01", 50, 10)
    assert check_new_records(records_user, first_id)
    second_id = _session(db_conn, records_user, "2026-10-03", 60, 12, duration=60)

    records = get_personal_records(records_user)
    exercise = next(item for item in records["exercises"] if item["name"] == "Жим лёжа")
    assert exercise["max_weight_kg"] == 60
    assert exercise["max_weight_date"] == "2026-10-03"
    assert exercise["max_reps"] == 12
    assert records["session_tonnage"]["value_kg"] == 720
    assert records["session_duration"]["value_min"] == 60
    messages = check_new_records(records_user, second_id)
    assert "🏆 Новый рекорд: Жим лёжа 60 кг!" in messages
    assert any("12" in message for message in messages)
    assert any("720" in message for message in messages)

    same_id = _session(db_conn, records_user, "2026-10-04", 60, 12, duration=60)
    assert check_new_records(records_user, same_id) == []


def test_daily_steps_and_protein_records(records_user, db_conn):
    for day, steps in (("2026-10-01", 8000), ("2026-10-02", 12000)):
        db_conn.execute(
            "INSERT INTO health_metrics (user_id, ts, metric_type, value) VALUES (?, ?, 'steps', ?)",
            (records_user, f"{day} 12:00:00", steps),
        )
    for day, protein in (("2026-10-01", 90), ("2026-10-02", 140)):
        db_conn.execute(
            """INSERT INTO food_log_new
               (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g, meal_time, logged_at)
               VALUES (?, 'Еда', 100, 500, ?, 10, 30, '12:00', ?)""",
            (records_user, protein, f"{day} 12:00:00"),
        )
    db_conn.commit()
    records = get_personal_records(records_user)
    assert records["steps"] == {"value": 12000, "date": "2026-10-02"}
    assert records["protein"] == {"value_g": 140, "date": "2026-10-02"}


def test_effort_formula_and_default_intensity():
    assert session_effort({"duration_min": 60, "intensity": 8}) == 480
    assert session_effort({"duration_min": 30, "intensity": None}) == 150


def test_load_curves_ewma_and_interpretations(records_user, db_conn, monkeypatch):
    db_conn.execute("DELETE FROM workout_sessions WHERE user_id = ?", (records_user,))
    db_conn.execute(
        """INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date)
           VALUES (?, 'strength', 60, 8, '2026-10-25')""",
        (records_user,),
    )
    db_conn.commit()
    monkeypatch.setattr("core.load._local_today", lambda _: date(2026, 10, 25))

    curves = get_load_curves(records_user, weeks=1)
    assert len(curves) == 7
    assert all(point["effort"] == 0 for point in curves[:-1])
    current = curves[-1]
    assert current["effort"] == 480
    assert current["fitness"] == pytest.approx(480 * (1 - math.exp(-1 / 42)), abs=0.01)
    assert current["fatigue"] == pytest.approx(480 * (1 - math.exp(-1 / 7)), abs=0.01)
    assert current["freshness"] == pytest.approx(current["fitness"] - current["fatigue"], abs=0.01)
    assert get_load_curves(records_user, weeks=1) == curves
    assert get_current_freshness(records_user)["interpretation"] == "усталость — лёгкий день"
    assert _interpret_freshness(10) == "норма"
    assert _interpret_freshness(-10) == "норма"
    assert _interpret_freshness(11) == "отличная форма, можно интенсивно"
    assert chart_fitness(records_user).startswith(b"\x89PNG\r\n\x1a\n")
