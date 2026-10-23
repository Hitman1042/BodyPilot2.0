"""Ручной ввод метрик здоровья (шаги/сон) — запись и попадание в агрегаты."""

from core.health_data import add_metric, get_metrics_summary, get_today_metrics


def test_add_metric_and_today(db_conn, test_user):
    add_metric(test_user, "steps", 8430, source="manual")
    add_metric(test_user, "sleep_hours", 7.5, source="manual")

    today = get_today_metrics(test_user)
    assert today["steps"] == 8430
    assert today["sleep_hours"] == 7.5


def test_summary_includes_manual(db_conn, test_user):
    add_metric(test_user, "steps", 5000, source="manual")

    summary = get_metrics_summary(test_user, days=7)
    assert summary["steps_today"] >= 5000
    assert summary["avg_sleep_hours"] is not None


def test_metrics_isolated_between_users(db_conn, test_user):
    other = 999000001
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (other, "other_user"),
    )
    db_conn.commit()

    add_metric(other, "steps", 12345, source="manual")
    mine = get_today_metrics(test_user)
    assert mine.get("steps", 0) < 12345
