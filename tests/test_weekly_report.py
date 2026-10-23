"""Еженедельный отчёт, PNG-графики и отбор получателей рассылки."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from core.charts import (
    generate_calories_chart,
    generate_weight_chart,
    generate_workouts_chart,
)
from core.scheduler import (
    _get_users_due_for_weekly_report,
    _mark_weekly_report_sent,
)
from core.weekly_report import build_weekly_report


@pytest.fixture
def report_user(db_conn):
    user_id = 920002
    for table in ("report_log", "achievements", "water_log", "food_log_new", "weight_log"):
        db_conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    db_conn.execute("DELETE FROM workout_sessions WHERE user_id = ?", (user_id,))
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, "report_user"),
    )
    db_conn.execute("UPDATE users SET timezone_offset = 0 WHERE user_id = ?", (user_id,))
    db_conn.commit()
    return user_id


def _add_food(db_conn, user_id: int, day, calories: float, protein: float) -> None:
    db_conn.execute(
        """INSERT INTO food_log_new
           (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g,
            meal_time, logged_at)
           VALUES (?, 'Тестовый продукт', 100, ?, ?, 10, 20, '12:00', ?)""",
        (user_id, calories, protein, f"{day.isoformat()} 12:00:00"),
    )


def _add_weight(db_conn, user_id: int, day, weight: float) -> None:
    db_conn.execute(
        "INSERT INTO weight_log (user_id, weight_kg, logged_at) VALUES (?, ?, ?)",
        (user_id, weight, f"{day.isoformat()} 09:00:00"),
    )


def _add_workout(db_conn, user_id: int, day, duration: int, tonnage: float) -> None:
    cursor = db_conn.execute(
        "INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date) VALUES (?, 'strength', ?, 7, ?)",
        (user_id, duration, day.isoformat()),
    )
    session_id = cursor.lastrowid
    cursor = db_conn.execute(
        "INSERT INTO workout_exercises (session_id, custom_exercise_name) VALUES (?, 'Тест')",
        (session_id,),
    )
    db_conn.execute(
        "INSERT INTO workout_sets (workout_exercise_id, set_number, reps, weight_kg) VALUES (?, 1, 1, ?)",
        (cursor.lastrowid, tonnage),
    )


def _fill_report_week(db_conn, user_id: int) -> None:
    today = datetime.now(timezone.utc).date()
    for index in range(7):
        day = today - timedelta(days=6 - index)
        _add_food(db_conn, user_id, day, 1800 + index * 100, 90 + index * 10)
    _add_weight(db_conn, user_id, today - timedelta(days=6), 73.0)
    _add_weight(db_conn, user_id, today, 72.5)
    _add_workout(db_conn, user_id, today - timedelta(days=3), 45, 500)
    _add_workout(db_conn, user_id, today - timedelta(days=1), 30, 600)
    db_conn.execute(
        "INSERT INTO achievements (user_id, code, unlocked_at) VALUES (?, 'first_food', datetime('now'))",
        (user_id,),
    )
    db_conn.commit()


def test_charts_return_valid_png(report_user, db_conn):
    _fill_report_week(db_conn, report_user)
    _add_weight(db_conn, report_user, datetime.now(timezone.utc).date() - timedelta(days=10), 74.0)
    db_conn.commit()

    for generator in (generate_weight_chart, generate_calories_chart, generate_workouts_chart):
        image = generator(report_user)
        assert image is not None
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(image) > 10_000


def test_charts_return_none_without_enough_data(db_conn):
    user_id = 920003
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, "empty_charts"),
    )
    db_conn.execute(
        "INSERT INTO weight_log (user_id, weight_kg) VALUES (?, 75.0)",
        (user_id,),
    )
    db_conn.commit()

    assert generate_weight_chart(user_id) is None
    assert generate_calories_chart(user_id) is None
    assert generate_workouts_chart(user_id) is None


def test_weekly_report_content_and_single_ai_call(report_user, db_conn, monkeypatch):
    _fill_report_week(db_conn, report_user)
    import core.weekly_report as weekly_report

    monkeypatch.setattr(weekly_report, "_build_charts", lambda _: [])

    class FakeGemini:
        calls = 0

        async def chat_answer(self, **kwargs):
            self.calls += 1
            return {"answer": "Хорошая регулярность питания. На следующей неделе сохрани этот ритм."}

    fake_gemini = FakeGemini()
    monkeypatch.setattr("core.ai.gemini_client.get_gemini_client", lambda: fake_gemini)

    report = asyncio.run(build_weekly_report(report_user))

    assert fake_gemini.calls == 1
    assert report["charts"] == []
    assert report["comment"] == "Хорошая регулярность питания. На следующей неделе сохрани этот ритм."
    assert "📅 <b>Отчёт за неделю</b>" in report["text"]
    assert "Средние калории: 2 100" in report["text"]
    assert "Суммарный тоннаж: 1 100 кг" in report["text"]
    assert "Текущая серия:</b> 7 дней" in report["text"]
    assert "Новых достижений:</b> 1" in report["text"]
    assert report["metrics"]["best_day"] is not None


def test_weekly_report_falls_back_without_ai(report_user, db_conn, monkeypatch):
    _fill_report_week(db_conn, report_user)
    import core.weekly_report as weekly_report

    monkeypatch.setattr(weekly_report, "_build_charts", lambda _: [])
    monkeypatch.setattr("core.ai.gemini_client.get_gemini_client", lambda: None)

    report = asyncio.run(build_weekly_report(report_user))

    assert "💡 <b>Комментарий:</b>" in report["text"]
    assert "Хорошая неделя" in report["comment"] or "Серия" in report["comment"]


def test_weekly_report_scheduler_activity_and_dedupe(db_conn, monkeypatch):
    import core.scheduler as scheduler

    active_user = 920004
    inactive_user = 920005
    for user_id in (active_user, inactive_user):
        db_conn.execute("DELETE FROM report_log WHERE user_id = ?", (user_id,))
        db_conn.execute("DELETE FROM food_log_new WHERE user_id = ?", (user_id,))
        db_conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
            (user_id, f"scheduler_{user_id}"),
        )
    db_conn.execute(
        """INSERT INTO food_log_new
           (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g, meal_time, logged_at)
           VALUES (?, 'Активность', 100, 500, 20, 10, 50, '12:00', '2026-10-17 12:00:00')""",
        (active_user,),
    )
    db_conn.commit()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 18, 20, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(scheduler, "datetime", FixedDateTime)
    due = _get_users_due_for_weekly_report()
    assert (active_user, "2026-10-18") in due
    assert all(user_id != inactive_user for user_id, _ in due)

    _mark_weekly_report_sent(active_user, "2026-10-18")
    due_after_mark = _get_users_due_for_weekly_report()
    assert all(user_id != active_user for user_id, _ in due_after_mark)
