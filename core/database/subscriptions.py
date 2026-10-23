"""Операции с подписками."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .connection import get_db


def get_subscription(user_id: int) -> dict[str, Any] | None:
    """Получить подписку пользователя."""
    conn = get_db()
    row = conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_subscription(
    user_id: int,
    plan: str = "free",
    expires_at: str | None = None,
    trial_used: int = 0
) -> None:
    """Создать подписку."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO subscriptions (user_id, plan, expires_at, trial_used, updated_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (user_id, plan, expires_at, trial_used),
    )
    conn.commit()


def update_subscription(user_id: int, **kwargs: Any) -> None:
    """Обновить подписку."""
    allowed: set[str] = {"plan", "expires_at", "trial_used"}
    updates: dict[str, Any] = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    sets = ", ".join(f"{k} = ?" for k in updates.keys())
    vals = list(updates.values()) + [user_id]
    conn = get_db()
    conn.execute(f"UPDATE subscriptions SET {sets} WHERE user_id = ?", vals)
    conn.commit()


def check_subscription_active(user_id: int) -> bool:
    """Проверить активность подписки."""
    sub = get_subscription(user_id)
    if not sub or sub["plan"] != "premium":
        return False
    if sub["expires_at"]:
        expire_dt = datetime.fromisoformat(sub["expires_at"])
        if expire_dt <= datetime.now(timezone.utc):
            return False
    return True


def get_subscription_info(user_id: int) -> dict[str, Any]:
    """Получить информацию о подписке."""
    sub = get_subscription(user_id)
    if not sub:
        return {
            "plan": "free",
            "expires_at": None,
            "is_active": False,
            "days_left": 0,
            "trial_used": False,
        }
    is_active = check_subscription_active(user_id)
    days_left = 0
    if sub.get("expires_at") and is_active:
        expire_dt = datetime.fromisoformat(sub["expires_at"])
        delta = expire_dt - datetime.now(timezone.utc)
        days_left = delta.days
    return {
        "plan": sub.get("plan", "free"),
        "expires_at": sub.get("expires_at"),
        "is_active": is_active,
        "days_left": max(0, days_left),
        "trial_used": bool(sub.get("trial_used", False)),
    }