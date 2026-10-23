"""Статистика и утилиты."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .connection import get_db
from .workout import get_weekly_tonnage


def get_stats_for_days(user_id: int, days: int = 7) -> dict[str, Any]:
    """Получить статистику за последние N дней."""
    conn = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cals = conn.execute(
        "SELECT COALESCE(SUM(calories), 0), AVG(calories) FROM food_log_new WHERE user_id = ? AND logged_at >= ?",
        (user_id, cutoff),
    ).fetchone()
    total_cal, avg_cal = float(cals[0]), float(cals[1] or 0)
    prot = conn.execute(
        "SELECT COALESCE(SUM(protein_g), 0), AVG(protein_g) FROM food_log_new WHERE user_id = ? AND logged_at >= ?",
        (user_id, cutoff),
    ).fetchone()
    w_cnt = conn.execute(
        "SELECT COUNT(DISTINCT DATE(date)) FROM workout_sessions WHERE user_id = ? AND date >= ?",
        (user_id, cutoff),
    ).fetchone()[0]
    last_w = conn.execute(
        "SELECT weight_kg FROM weight_log WHERE user_id = ? ORDER BY logged_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    first_w = conn.execute(
        "SELECT weight_kg FROM weight_log WHERE user_id = ? AND logged_at >= ? ORDER BY logged_at ASC LIMIT 1",
        (user_id, cutoff),
    ).fetchone()
    tonnage = conn.execute(
        """SELECT COALESCE(SUM(ws.weight_kg * ws.reps), 0)
           FROM workout_sets ws
           JOIN workout_exercises we ON we.id = ws.workout_exercise_id
           JOIN workout_sessions w ON w.id = we.session_id
           WHERE w.user_id = ? AND w.date >= ?""",
        (user_id, cutoff),
    ).fetchone()[0]
    return {
        "days": days,
        "total_calories": round(total_cal, 1),
        "avg_daily_calories": round(avg_cal, 1),
        "total_protein_g": round(float(prot[0]), 1),
        "workout_days": int(w_cnt),
        "current_weight_kg": float(last_w[0]) if last_w else None,
        "weight_change_kg": round(float(last_w[0]) - float(first_w[0]), 1) if last_w and first_w else None,
        "tonnage": round(float(tonnage), 1),
    }


def get_weekly_stats(user_id: int) -> dict[str, Any]:
    """Получить недельную статистику."""
    stats = get_stats_for_days(user_id, days=7)
    stats.pop("days", None)
    stats["weekly_tonnage"] = stats.pop("tonnage")
    return stats


def get_users_due_for_digest() -> list[dict[str, Any]]:
    """Получить пользователей, которым пора отправить дайджест."""
    conn = get_db()
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT * FROM users WHERE preferred_time IS NOT NULL AND preferred_time != ''"
    ).fetchall()
    candidates: list[tuple[dict[str, Any], datetime]] = []
    for r in rows:
        u = dict(r)
        try:
            pref = u.get("preferred_time", "07:00")
            hour, minute = map(int, pref.split(":"))
            user_now = now + timedelta(minutes=u.get("timezone_offset", 0))
            if user_now.hour == hour and abs(user_now.minute - minute) <= 2:
                candidates.append((u, user_now))
        except (ValueError, TypeError):
            continue
    due: list[dict[str, Any]] = []
    for u, user_now in candidates:
        user_date = user_now.date().isoformat()
        existing = conn.execute(
            "SELECT id FROM daily_plans WHERE user_id = ? AND plan_date = ? "
            "AND delivery_status IN ('sent_to_host', 'delivered')",
            (u["user_id"], user_date),
        ).fetchone()
        if not existing:
            due.append(u)
    return due