"""Операции с рефералами и бонусами."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .connection import get_db
from .subscriptions import get_subscription, create_subscription, update_subscription, check_subscription_active


def add_bonus_days(
    user_id: int,
    days: int,
    source: str,
    source_user_id: int | None,
    expires_at: str
) -> int:
    """Добавить бонусные дни."""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO bonus_days (user_id, days, source, source_user_id, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, days, source, source_user_id, expires_at),
    )
    conn.commit()
    return cur.lastrowid or 0


def activate_bonus_days(user_id: int) -> int:
    """Активировать бонусные дни."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT id, days FROM bonus_days WHERE user_id = ? AND activated = 0 AND expires_at > ?",
        (user_id, now),
    ).fetchall()
    total_days = sum(r["days"] for r in rows)
    if total_days == 0:
        return 0
    conn.execute(
        "UPDATE bonus_days SET activated = 1 WHERE user_id = ? AND activated = 0 AND expires_at > ?",
        (user_id, now),
    )
    sub = get_subscription(user_id)
    if sub and sub["plan"] == "premium" and sub["expires_at"]:
        current_expire = datetime.fromisoformat(sub["expires_at"])
        if current_expire < datetime.now(timezone.utc):
            current_expire = datetime.now(timezone.utc)
        new_expire = current_expire + timedelta(days=total_days)
        update_subscription(user_id, expires_at=new_expire.isoformat())
    else:
        new_expire = datetime.now(timezone.utc) + timedelta(days=total_days)
        if sub:
            update_subscription(user_id, plan="premium", expires_at=new_expire.isoformat())
        else:
            create_subscription(user_id, plan="premium", expires_at=new_expire.isoformat())
    conn.commit()
    return total_days


def cleanup_expired_bonus_days() -> int:
    """Удалить просроченные бонусные дни."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "DELETE FROM bonus_days WHERE activated = 0 AND expires_at <= ?",
        (now,),
    )
    conn.commit()
    return cur.rowcount


def get_bonus_balance(user_id: int) -> int:
    """Получить баланс бонусных дней."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(days), 0) FROM bonus_days "
        "WHERE user_id = ? AND activated = 0 AND expires_at > ?",
        (user_id, now),
    ).fetchone()
    return int(row[0]) if row else 0


def create_referral(inviter_id: int, invited_id: int) -> bool:
    """Создать реферальную связь."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO referrals (inviter_id, invited_id) VALUES (?, ?)",
            (inviter_id, invited_id),
        )
        conn.commit()
        return conn.total_changes > 0
    except Exception:
        return False


def get_referral(inviter_id: int, invited_id: int) -> dict[str, Any] | None:
    """Получить реферальную связь."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM referrals WHERE inviter_id = ? AND invited_id = ?",
        (inviter_id, invited_id),
    ).fetchone()
    return dict(row) if row else None


def get_referral_by_invited(invited_id: int) -> dict[str, Any] | None:
    """Получить реферала по приглашённому."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM referrals WHERE invited_id = ?",
        (invited_id,),
    ).fetchone()
    return dict(row) if row else None


def mark_referral_paid(invited_id: int) -> None:
    """Отметить реферала как оплатившего."""
    conn = get_db()
    conn.execute(
        "UPDATE referrals SET invited_paid = 1 WHERE invited_id = ?",
        (invited_id,),
    )
    conn.commit()


def get_referral_list(inviter_id: int) -> list[dict[str, Any]]:
    """Получить список приглашённых."""
    conn = get_db()
    rows = conn.execute(
        "SELECT r.invited_id, r.invited_paid, r.created_at, u.username "
        "FROM referrals r JOIN users u ON u.user_id = r.invited_id "
        "WHERE r.inviter_id = ?",
        (inviter_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def process_referral_payment(invited_id: int) -> None:
    """Обработать оплату рефералом."""
    ref = get_referral_by_invited(invited_id)
    if not ref or ref.get("invited_paid"):
        return
    mark_referral_paid(invited_id)
    inviter_id = ref["inviter_id"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=30).isoformat()
    add_bonus_days(inviter_id, days=10, source="referral_payment", source_user_id=invited_id, expires_at=expires_at)
    if check_subscription_active(inviter_id):
        activate_bonus_days(inviter_id)