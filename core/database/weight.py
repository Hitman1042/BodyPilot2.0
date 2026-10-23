"""Операции с весом."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .connection import get_db


def log_weight(user_id: int, weight_kg: float) -> int:
    """Записать вес."""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO weight_log (user_id, weight_kg) VALUES (?, ?)",
        (user_id, weight_kg),
    )
    conn.commit()
    return cur.lastrowid or 0


def get_weight_log(user_id: int, days: int = 30) -> list[dict[str, Any]]:
    """Получить лог веса за последние N дней."""
    conn = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM weight_log WHERE user_id = ? AND logged_at >= ? ORDER BY logged_at DESC",
        (user_id, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def get_weight_history(user_id: int, days: int = 30) -> list[dict[str, Any]]:
    """Получить историю веса по дням."""
    conn = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT DATE(logged_at) as day, weight_kg "
        "FROM weight_log WHERE user_id = ? AND logged_at >= ? "
        "ORDER BY day",
        (user_id, cutoff),
    ).fetchall()
    return [{"day": r["day"], "weight": r["weight_kg"]} for r in rows]


def get_weight_history_local(user_id: int, days: int = 30) -> list[dict[str, Any]]:
    """История веса по локальным датам пользователя (учитывает timezone_offset).

    Последняя запись дня, отсортировано по дате: [{"date", "weight_kg"}].
    """
    conn = get_db()
    row = conn.execute(
        "SELECT timezone_offset FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    offset = int(row["timezone_offset"] or 0) if row else 0
    modifier = f"{offset:+d} minutes"
    cutoff = (
        datetime.now(timezone.utc) + timedelta(minutes=offset) - timedelta(days=days)
    ).date().isoformat()
    rows = conn.execute(
        "SELECT date(logged_at, ?) AS day, weight_kg, MAX(id) "
        "FROM weight_log WHERE user_id = ? AND date(logged_at, ?) >= ? "
        "GROUP BY day ORDER BY day",
        (modifier, user_id, modifier, cutoff),
    ).fetchall()
    return [{"date": r["day"], "weight_kg": r["weight_kg"]} for r in rows]