"""Удаление тренировок и метрик здоровья через AI-инструменты."""

from core.ai.tools import execute_tool
from core.database import get_db
from core.health_data import add_metric


def test_delete_workout_session(test_user):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO workout_sessions (user_id, date, type, duration_min) VALUES (?, date('now'), 'strength', 45)",
        (test_user,),
    )
    conn.commit()
    session_id = cur.lastrowid

    result = execute_tool(test_user, "delete_workout_session", {})
    assert result["ok"] is True
    assert result["deleted_session_id"] == session_id

    left = conn.execute(
        "SELECT COUNT(*) FROM workout_sessions WHERE id = ?", (session_id,)
    ).fetchone()[0]
    assert left == 0


def test_delete_workout_session_not_found(db_conn):
    other = 999000002
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (other, "no_workouts"),
    )
    db_conn.commit()
    result = execute_tool(other, "delete_workout_session", {})
    assert "error" in result


def test_delete_health_metric_sleep(test_user):
    add_metric(test_user, "sleep_hours", 7.5, source="manual")
    result = execute_tool(test_user, "delete_health_metric", {"metric_type": "sleep_hours"})
    assert result["ok"] is True

    conn = get_db()
    left = conn.execute(
        "SELECT COUNT(*) FROM health_metrics WHERE user_id = ? AND metric_type = 'sleep_hours'",
        (test_user,),
    ).fetchone()[0]
    assert left == 0


def test_delete_health_metric_steps(test_user):
    add_metric(test_user, "steps", 5000, source="manual")
    result = execute_tool(test_user, "delete_health_metric", {"metric_type": "steps"})
    assert result["ok"] is True


def test_delete_health_metric_not_found(test_user):
    result = execute_tool(test_user, "delete_health_metric", {"metric_type": "steps"})
    assert "error" in result


def test_delete_health_metric_validation(test_user):
    result = execute_tool(test_user, "delete_health_metric", {"metric_type": "unknown_metric"})
    assert "error" in result
