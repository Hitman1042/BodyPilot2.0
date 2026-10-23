"""Операции с планами питания и тренировок."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .connection import get_db


def save_plan(
    user_id: int,
    plan_date: str,
    meal_plan: dict[str, Any],
    workout_plan: dict[str, Any]
) -> None:
    """Сохранить дневной план."""
    conn = get_db()
    conn.execute(
        """INSERT INTO daily_plans (user_id, plan_date, meal_plan, workout_plan)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, plan_date) DO UPDATE SET
               meal_plan = excluded.meal_plan,
               workout_plan = excluded.workout_plan""",
        (user_id, plan_date, json.dumps(meal_plan), json.dumps(workout_plan)),
    )
    conn.commit()


def mark_plan_sent(user_id: int, plan_date: str) -> None:
    """Отметить план как отправленный."""
    conn = get_db()
    conn.execute(
        "INSERT INTO daily_plans (user_id, plan_date, meal_plan, workout_plan, sent_at, delivery_status) "
        "VALUES (?, ?, '{}', '{}', datetime('now'), 'sent_to_host') "
        "ON CONFLICT(user_id, plan_date) DO UPDATE SET "
        "sent_at = datetime('now'), delivery_status = 'sent_to_host'",
        (user_id, plan_date),
    )
    conn.commit()


def get_plan(user_id: int, plan_date: str) -> dict[str, Any] | None:
    """Получить план на дату."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM daily_plans WHERE user_id = ? AND plan_date = ?",
        (user_id, plan_date),
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    for field in ("meal_plan", "workout_plan"):
        try:
            result[field] = json.loads(result.get(field) or "{}")
        except (json.JSONDecodeError, TypeError):
            result[field] = {}
    return result


def get_pending_digests(since_minutes: int = 10) -> list[dict[str, Any]]:
    """Получить планы, ожидающие отправки."""
    conn = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
    rows = conn.execute(
        """SELECT dp.*, u.preferred_time, u.timezone_offset
           FROM daily_plans dp
           JOIN users u ON u.user_id = dp.user_id
           WHERE dp.delivery_status = 'sent_to_host'
             AND dp.sent_at IS NOT NULL
             AND dp.sent_at < ?""",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def confirm_digest_delivery(user_id: int, plan_date: str, status: str = "delivered") -> None:
    """Подтвердить доставку дайджеста."""
    conn = get_db()
    conn.execute(
        "UPDATE daily_plans SET delivery_status = ? WHERE user_id = ? AND plan_date = ?",
        (status, user_id, plan_date),
    )
    conn.commit()