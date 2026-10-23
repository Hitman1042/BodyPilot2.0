"""Умные напоминания (отбор пользователей, дедупликация) и агрегаты health_metrics."""

from datetime import date, datetime, time, timedelta, timezone

import core.reminders as reminders
from core.health_data import get_metrics_summary, get_today_metrics
from core.reminders import (
    REMINDER_NO_FOOD,
    REMINDER_REACTIVATION,
    REMINDER_WORKOUT,
    build_food_reminder_text,
    build_reactivation_text,
    get_users_due_for_food_reminder,
    get_users_due_for_reactivation,
    get_users_due_for_workout_reminder,
    mark_reminder_sent,
)

FROZEN_NOW = datetime(2026, 10, 20, 12, 1, tzinfo=timezone.utc)  # вторник


def _freeze(monkeypatch, hour: int, minute: int = 1):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 20, hour, minute, tzinfo=timezone.utc)

    monkeypatch.setattr(reminders, "datetime", FixedDateTime)


def _add_user(db_conn, user_id: int) -> None:
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, f"rem_{user_id}"),
    )
    db_conn.execute("DELETE FROM reminder_log WHERE user_id = ?", (user_id,))
    db_conn.commit()


def _add_food(db_conn, user_id: int, logged_at: str) -> None:
    db_conn.execute(
        """INSERT INTO food_log_new
           (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g, meal_time, logged_at)
           VALUES (?, 'Тест', 100, 500, 20, 10, 50, '12:00', ?)""",
        (user_id, logged_at),
    )
    db_conn.commit()


# ── «Ты сегодня ещё не записывал еду» (15:00) ─────────────────────────────

def test_food_reminder_selection(db_conn, monkeypatch):
    active_user, never_user, stale_user, fed_user = 971001, 971002, 971003, 971004
    for uid in (active_user, never_user, stale_user, fed_user):
        _add_user(db_conn, uid)
    _add_food(db_conn, active_user, "2026-10-19 12:00:00")   # активен вчера
    _add_food(db_conn, stale_user, "2026-10-14 12:00:00")    # активность 6 дней назад
    _add_food(db_conn, fed_user, "2026-10-20 08:00:00")      # еда уже записана сегодня

    _freeze(monkeypatch, 15)
    due_ids = [uid for uid, _ in get_users_due_for_food_reminder()]
    assert active_user in due_ids
    for uid in (never_user, stale_user, fed_user):
        assert uid not in due_ids

    # Не в окне 15:00 — не отправляем
    _freeze(monkeypatch, 14)
    assert all(uid != active_user for uid, _ in get_users_due_for_food_reminder())


def test_food_reminder_dedupe(db_conn, monkeypatch):
    user_id = 971005
    _add_user(db_conn, user_id)
    _add_food(db_conn, user_id, "2026-10-19 12:00:00")
    _freeze(monkeypatch, 15)

    mark_reminder_sent(user_id, REMINDER_NO_FOOD, "2026-10-20")
    mark_reminder_sent(user_id, REMINDER_NO_FOOD, "2026-10-20")  # идемпотентно
    assert all(uid != user_id for uid, _ in get_users_due_for_food_reminder())


# ── «Тренировка по плану сегодня» (17:00) ─────────────────────────────────

def test_workout_reminder_selection(db_conn, monkeypatch):
    planned_user, done_user, no_plan_user = 971006, 971007, 971008
    for uid in (planned_user, done_user, no_plan_user):
        _add_user(db_conn, uid)
    for uid in (planned_user, done_user):
        db_conn.execute(
            "INSERT OR IGNORE INTO daily_workout_plans (user_id, date, is_active) VALUES (?, '2026-10-20', 1)",
            (uid,),
        )
    db_conn.execute(
        "INSERT INTO workout_sessions (user_id, type, duration_min, date) VALUES (?, 'strength', 45, '2026-10-20')",
        (done_user,),
    )
    db_conn.commit()

    _freeze(monkeypatch, 17)
    due = get_users_due_for_workout_reminder()
    assert (planned_user, "2026-10-20") in due
    assert all(uid not in [u for u, _ in due] for uid in (done_user, no_plan_user))

    mark_reminder_sent(planned_user, REMINDER_WORKOUT, "2026-10-20")
    assert all(uid != planned_user for uid, _ in get_users_due_for_workout_reminder())


# ── «Неделя без активности» (12:00, не чаще раза в 7 дней) ───────────────

def test_reactivation_selection_and_cooldown(db_conn, monkeypatch):
    inactive_user, recent_user, never_user = 971009, 971010, 971011
    for uid in (inactive_user, recent_user, never_user):
        _add_user(db_conn, uid)
    _add_food(db_conn, inactive_user, "2026-10-13 12:00:00")  # 7 дней тишины
    _add_food(db_conn, recent_user, "2026-10-18 12:00:00")    # активность 2 дня назад

    _freeze(monkeypatch, 12)
    due = get_users_due_for_reactivation()
    assert (inactive_user, "2026-10-20") in due
    assert all(uid not in [u for u, _ in due] for uid in (recent_user, never_user))

    # Повторно — не чаще раза в 7 дней
    mark_reminder_sent(inactive_user, REMINDER_REACTIVATION, "2026-10-20")
    assert all(uid != inactive_user for uid, _ in get_users_due_for_reactivation())


def test_reactivation_text_mentions_best_streak(db_conn):
    user_id = 971012
    _add_user(db_conn, user_id)
    # Лучшая серия 3 дня (10-12 дней назад — в пределах окна стрика в 60 дней)
    for days_ago in (10, 11, 12):
        day = date.today() - timedelta(days=days_ago)
        _add_food(db_conn, user_id, f"{day.isoformat()} 12:00:00")

    text = build_reactivation_text(user_id)
    assert "Скучаем" in text
    assert "3 дня" in text
    assert build_food_reminder_text().startswith("🍽")


# ── Агрегаты метрик здоровья ──────────────────────────────────────────────

def _add_metric(db_conn, user_id: int, ts: datetime, metric_type: str, value: float) -> None:
    db_conn.execute(
        "INSERT INTO health_metrics (user_id, ts, metric_type, value, source) VALUES (?, ?, ?, ?, 'test')",
        (user_id, ts.isoformat(), metric_type, value),
    )
    db_conn.commit()


def test_health_metrics_aggregates(db_conn):
    user_id = 972001
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, "health_user"),
    )
    db_conn.execute("DELETE FROM health_metrics WHERE user_id = ?", (user_id,))
    db_conn.commit()

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    at = lambda d, h: datetime.combine(d, time(h, 0), tzinfo=timezone.utc)  # noqa: E731

    _add_metric(db_conn, user_id, at(today, 8), "steps", 5000)
    _add_metric(db_conn, user_id, at(today, 7), "resting_heart_rate", 58)
    _add_metric(db_conn, user_id, at(yesterday, 9), "steps", 8430)
    _add_metric(db_conn, user_id, at(yesterday, 7), "sleep_hours", 7.2)
    _add_metric(db_conn, user_id, at(yesterday, 8), "resting_heart_rate", 60)

    today_metrics = get_today_metrics(user_id)
    assert today_metrics.get("steps") == 5000
    assert today_metrics.get("resting_heart_rate") == 58
    assert "sleep_hours" not in today_metrics

    summary = get_metrics_summary(user_id, days=7)
    assert summary["steps_today"] == 5000
    assert summary["steps_yesterday"] == 8430
    assert summary["avg_sleep_hours"] == 7.2
    assert summary["avg_resting_heart_rate"] == 59.0


def test_health_metrics_empty_user(db_conn):
    user_id = 972002
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, "health_empty"),
    )
    db_conn.execute("DELETE FROM health_metrics WHERE user_id = ?", (user_id,))
    db_conn.commit()

    assert get_today_metrics(user_id) == {}
    summary = get_metrics_summary(user_id, days=7)
    assert summary["steps_today"] is None
    assert summary["steps_yesterday"] is None
    assert summary["avg_sleep_hours"] is None
    assert summary["avg_resting_heart_rate"] is None
