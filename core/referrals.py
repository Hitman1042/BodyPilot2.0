"""Реферальная система и пробный период BodyPilot."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict  # ← ДОБАВИТЬ ЭТУ СТРОКУ

from .config import settings
from .database import (
    get_db, get_user,
    get_subscription, create_subscription, update_subscription,
    add_bonus_days, activate_bonus_days,
    create_referral, get_referral_by_invited, mark_referral_paid, get_referral_list,
)
from .gamification import get_streak


def generate_referral_code(user_id: int) -> str:
    raw = f"{user_id}:{settings.REFERRAL_SECRET_SALT}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def start_trial(user_id: int) -> None:
    sub = get_subscription(user_id)
    if sub and sub.get("trial_used"):
        return

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=3)

    if sub:
        update_subscription(user_id, plan="premium",
                           expires_at=expires_at.isoformat(), trial_used=1)
    else:
        create_subscription(user_id, plan="premium",
                           expires_at=expires_at.isoformat(), trial_used=1)


def process_referral(inviter_id: int, invited_id: int) -> None:
    existing = create_referral(inviter_id, invited_id)
    if not existing:
        return

    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    add_bonus_days(inviter_id, days=5, source="referral_signup",
                   source_user_id=invited_id, expires_at=expires_at.isoformat())

    if check_subscription_active(inviter_id):
        activate_bonus_days(inviter_id)


def process_referral_payment(invited_id: int) -> None:
    ref = get_referral_by_invited(invited_id)
    if not ref or ref.get("invited_paid"):
        return

    mark_referral_paid(invited_id)
    inviter_id = ref["inviter_id"]

    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    add_bonus_days(inviter_id, days=10, source="referral_payment",
                   source_user_id=invited_id, expires_at=expires_at.isoformat())

    if check_subscription_active(inviter_id):
        activate_bonus_days(inviter_id)


def check_subscription_active(user_id: int) -> bool:
    """Проверить активна ли Premium подписка (старая + новая системы)."""
    from datetime import datetime, timezone

    # get_db() возвращает общее thread-local соединение — его НЕЛЬЗЯ закрывать
    conn = get_db()

    new_sub = conn.execute("""
        SELECT * FROM premium_subscriptions
        WHERE user_id = ? AND status IN ('trial', 'active')
    """, (user_id,)).fetchone()

    if new_sub:
        expires_at = datetime.fromisoformat(new_sub["expires_at"])
        if expires_at > datetime.now(timezone.utc):
            return True

    # ПРОВЕРЯЕМ СТАРУЮ ТАБЛИЦУ subscriptions (для совместимости)
    old_sub = conn.execute("""
        SELECT * FROM subscriptions
        WHERE user_id = ? AND plan = 'premium'
    """, (user_id,)).fetchone()

    if old_sub:
        expires_at = datetime.fromisoformat(old_sub["expires_at"])
        if expires_at > datetime.now(timezone.utc):
            return True

    return False


def get_subscription_info(user_id: int) -> dict:
    """Всегда возвращает полный словарь с ключами plan, expires_at, is_active, days_left, trial_used."""
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


def get_friend_rating(user_id: int) -> List[Dict]:
    """Рейтинг пользователя и приглашённых друзей за последние 7 локальных дней."""
    participants = [user_id]
    participants.extend(item["invited_id"] for item in get_referral_list(user_id))
    rating = []
    conn = get_db()
    for participant_id in dict.fromkeys(participants):
        profile = get_user(participant_id)
        if not profile:
            continue
        offset = int(profile.get("timezone_offset") or 0)
        today = (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()
        first_day = (today - timedelta(days=6)).isoformat()
        modifier = f"{offset:+d} minutes"
        food_days = conn.execute(
            """SELECT COUNT(DISTINCT date(logged_at, ?))
               FROM food_log_new
               WHERE user_id = ? AND date(logged_at, ?) BETWEEN ? AND ?""",
            (modifier, participant_id, modifier, first_day, today.isoformat()),
        ).fetchone()[0]
        workouts = conn.execute(
            """SELECT COUNT(*) FROM workout_sessions
               WHERE user_id = ? AND date BETWEEN ? AND ?""",
            (participant_id, first_day, today.isoformat()),
        ).fetchone()[0]
        streak = get_streak(participant_id)["current"]
        points = int(workouts) * 10 + int(food_days) * 5 + streak * 3
        rating.append({
            "user_id": participant_id,
            "username": profile.get("username") or "друг",
            "workouts": int(workouts),
            "food_days": int(food_days),
            "streak": streak,
            "points": points,
            "is_self": participant_id == user_id,
        })
    rating.sort(key=lambda item: (-item["points"], item["username"].lower()))
    return rating


# ═══════════════════════════════════════════════════════════════
# AI ЛИМИТЫ (интеграция с Premium)
# ═══════════════════════════════════════════════════════════════

AI_LIMITS = {
    "ai_analyze_food": {"count": 1, "period": "week"},
    "ai_analyze_workout": {"count": 1, "period": "week"},
    "ai_photo": {"count": 1, "period": "day"},
    "ai_chat": {"count": 3, "period": "week"},
    "ai_search": {"count": 0, "period": "unlimited"},
}


def _is_admin_user(user_id: int) -> bool:
    """Админ по числовому ID (TELEGRAM_ADMIN_USER_IDS) — безлимитный доступ."""
    from core.config import settings
    raw = settings.TELEGRAM_ADMIN_USER_IDS or ""
    return str(user_id) in [x.strip() for x in raw.split(",") if x.strip()]


def get_ai_limit(user_id: int, feature: str) -> Dict:
    """Получить лимит для AI-функции."""
    from core.database import get_db
    from core.config import settings
    from datetime import datetime, timedelta, timezone

    # Лимиты отключены глобально (бета) или пользователь — админ
    if not settings.AI_LIMITS_ENABLED or _is_admin_user(user_id):
        return {
            "is_premium": True,
            "limit": 0,
            "used": 0,
            "remaining": 999,
            "reset_at": None,
            "can_use": True
        }

    # Premium = безлимит
    if check_subscription_active(user_id):
        return {
            "is_premium": True,
            "limit": 0,
            "used": 0,
            "remaining": 999,
            "reset_at": None,
            "can_use": True
        }

    if feature not in AI_LIMITS:
        return {"can_use": False, "error": "Неизвестная функция"}

    limit_config = AI_LIMITS[feature]

    if limit_config["period"] == "unlimited":
        return {
            "is_premium": False,
            "limit": 0,
            "used": 0,
            "remaining": 999,
            "reset_at": None,
            "can_use": True
        }

    # Вычисляем дату сброса
    now = datetime.now(timezone.utc)

    if limit_config["period"] == "day":
        reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif limit_config["period"] == "week":
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
    else:
        reset_at = now + timedelta(days=1)

    # Общее thread-local соединение: не закрывать и не менять row_factory
    conn = get_db()

    limit_record = conn.execute("""
        SELECT * FROM ai_usage_limits
        WHERE user_id = ? AND feature = ? AND reset_at = ?
    """, (user_id, feature, reset_at.isoformat())).fetchone()

    if not limit_record:
        conn.execute("""
            INSERT INTO ai_usage_limits (user_id, feature, used_count, limit_count, reset_at)
            VALUES (?, ?, 0, ?, ?)
        """, (user_id, feature, limit_config["count"], reset_at.isoformat()))
        conn.commit()
        used = 0
    else:
        used = limit_record["used_count"]

    limit = limit_config["count"]
    remaining = max(0, limit - used)

    return {
        "is_premium": False,
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "reset_at": reset_at.isoformat(),
        "can_use": remaining > 0
    }


def use_ai_feature(user_id: int, feature: str) -> bool:
    """Зафиксировать использование AI-функции."""
    from core.database import get_db
    from core.config import settings
    from datetime import datetime, timedelta, timezone

    if not settings.AI_LIMITS_ENABLED:
        return True

    if _is_admin_user(user_id):
        return True

    if check_subscription_active(user_id):
        return True

    limit_info = get_ai_limit(user_id, feature)

    if not limit_info["can_use"]:
        return False

    now = datetime.now(timezone.utc)
    limit_config = AI_LIMITS.get(feature, {"period": "day"})

    if limit_config["period"] == "day":
        reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif limit_config["period"] == "week":
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
    else:
        reset_at = now + timedelta(days=1)

    conn = get_db()

    try:
        conn.execute("""
            INSERT INTO ai_usage_limits (user_id, feature, used_count, limit_count, reset_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(user_id, feature, reset_at) DO UPDATE SET
                used_count = used_count + 1,
                updated_at = datetime('now')
        """, (user_id, feature, AI_LIMITS.get(feature, {}).get("count", 0), reset_at.isoformat()))

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        return False