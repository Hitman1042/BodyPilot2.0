"""Операции с пользователями и чатами."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .connection import get_db
from core.config import settings


def get_user(user_id: int) -> dict[str, Any] | None:
    """Получить пользователя по ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_referral_code(code: str) -> dict[str, Any] | None:
    """Получить пользователя по реферальному коду."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE referral_code = ?", (code,)).fetchone()
    return dict(row) if row else None


def get_or_create_user(user_id: int, username: str, referral_code: str | None = None) -> dict[str, Any]:
    """Получить или создать пользователя."""
    user = get_user(user_id)
    if user:
        return user
    raw = f"{user_id}:{settings.REFERRAL_SECRET_SALT}"
    code = hashlib.sha256(raw.encode()).hexdigest()[:12]
    conn = get_db()
    conn.execute(
        "INSERT INTO users (user_id, username, referral_code) VALUES (?, ?, ?)",
        (user_id, username, code),
    )
    conn.commit()
    return get_user(user_id) or {}


def update_user(user_id: int, **kwargs: Any) -> bool:
    """Обновить данные пользователя."""
    allowed: set[str] = {
        "username", "gender", "age", "height_cm", "weight_kg",
        "goal", "activity", "allergies", "city", "timezone_offset", "preferred_time"
    }
    updates: dict[str, Any] = {
        k: v for k, v in kwargs.items() if k in allowed and v is not None
    }
    if not updates:
        return False
    if "timezone_offset" in updates:
        tz = int(updates["timezone_offset"])
        if tz < -720 or tz > 840:
            raise ValueError("timezone_offset must be between -720 and 840")
        updates["timezone_offset"] = tz
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    sets = ", ".join(f"{k} = ?" for k in updates.keys())
    vals = list(updates.values()) + [user_id]
    conn = get_db()
    conn.execute(f"UPDATE users SET {sets} WHERE user_id = ?", vals)
    conn.commit()
    return conn.total_changes > 0


def ensure_user_chat(user_id: int, chat_id: int, platform: str = "telegram") -> None:
    """Гарантировать наличие записи о чате."""
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO user_chats (user_id, chat_id, platform) VALUES (?, ?, ?)",
        (user_id, chat_id, platform),
    )
    conn.commit()


def get_user_chats(user_id: int) -> list[dict[str, Any]]:
    """Получить все чаты пользователя."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM user_chats WHERE user_id = ?", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]