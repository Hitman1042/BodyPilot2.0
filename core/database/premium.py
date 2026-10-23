"""Операции с Premium подпиской."""

from .connection import get_db
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List


# ═══════════════════════════════════════════════════════════════
# PREMIUM ПОДПИСКИ
# ═══════════════════════════════════════════════════════════════

def get_subscription(user_id: int) -> Optional[Dict]:
    """Получить подписку пользователя."""
    # Общее thread-local соединение: не закрывать и не менять row_factory
    conn = get_db()

    subscription = conn.execute("""
        SELECT * FROM premium_subscriptions
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    return dict(subscription) if subscription else None


def is_premium(user_id: int) -> bool:
    """Проверить активна ли Premium подписка."""
    subscription = get_subscription(user_id)

    if not subscription:
        return False

    if subscription["status"] not in ("trial", "active"):
        return False

    expires_at = datetime.fromisoformat(subscription["expires_at"])
    return expires_at > datetime.now(timezone.utc)


def activate_premium(
        user_id: int,
        days: int,
        source: str = "purchase",
        extend: bool = False,
) -> Dict:
    """
    Активировать Premium подписку.

    Args:
        user_id: ID пользователя
        days: Количество дней
        source: new_user, referral, promo, return, purchase
        extend: Продлить текущую (True) или заменить (False)

    Returns:
        {"success": bool, "expires_at": str, "message": str}
    """
    conn = get_db()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=days)

    # Проверяем текущую подписку
    current = get_subscription(user_id)

    if current and extend:
        # Продлеваем от текущей даты истечения
        current_expires = datetime.fromisoformat(current["expires_at"])
        if current_expires > now:
            expires_at = current_expires + timedelta(days=days)

    try:
        conn.execute("""
            INSERT INTO premium_subscriptions 
            (user_id, status, started_at, expires_at, trial_days, source)
            VALUES (?, 'active', ?, ?, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                status = 'active',
                expires_at = ?,
                source = ?,
                updated_at = datetime('now')
        """, (user_id, now.isoformat(), expires_at.isoformat(), source,
              expires_at.isoformat(), source))

        conn.commit()

        return {
            "success": True,
            "expires_at": expires_at.isoformat(),
            "message": f"Premium активирован на {days} дн."
        }

    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": str(e)
        }


def cancel_premium(user_id: int) -> bool:
    """Отменить Premium подписку."""
    conn = get_db()

    try:
        conn.execute("""
            UPDATE premium_subscriptions
            SET status = 'cancelled', updated_at = datetime('now')
            WHERE user_id = ?
        """, (user_id,))

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        return False


# ═══════════════════════════════════════════════════════════════
# AI ЛИМИТЫ
# ═══════════════════════════════════════════════════════════════

# Лимиты для Free пользователей
AI_LIMITS = {
    "ai_analyze_food": {"count": 1, "period": "week"},  # 1 раз в неделю
    "ai_analyze_workout": {"count": 1, "period": "week"},  # 1 раз в неделю
    "ai_photo": {"count": 1, "period": "day"},  # 1 раз в день
    "ai_chat": {"count": 3, "period": "week"},  # 3 вопроса в неделю
    "ai_search": {"count": 0, "period": "unlimited"},  # Безлимит (всегда)
}


def get_ai_limit(user_id: int, feature: str) -> Dict:
    """
    Получить лимит для AI-функции.

    Returns:
        {
            "is_premium": bool,
            "limit": int,
            "used": int,
            "remaining": int,
            "reset_at": str,
            "can_use": bool
        }
    """
    from .premium import is_premium

    # Premium = безлимит
    if is_premium(user_id):
        return {
            "is_premium": True,
            "limit": 0,  # 0 = безлимит
            "used": 0,
            "remaining": 999,
            "reset_at": None,
            "can_use": True
        }

    # Получаем лимиты для функции
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
        # Сброс каждый понедельник
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
    else:
        reset_at = now + timedelta(days=1)

    # Получаем или создаём запись о лимите
    conn = get_db()

    limit_record = conn.execute("""
        SELECT * FROM ai_usage_limits
        WHERE user_id = ? AND feature = ? AND reset_at = ?
    """, (user_id, feature, reset_at.isoformat())).fetchone()

    if not limit_record:
        # Создаём новую запись
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


def use_ai_feature(user_id: int, feature: str, is_premium_user: bool = False) -> bool:
    """
    Зафиксировать использование AI-функции.

    Returns:
        True если успешно, False если лимит исчерпан
    """
    # Premium не считает лимиты
    if is_premium_user:
        return True

    # Проверяем доступность
    limit_info = get_ai_limit(user_id, feature)

    if not limit_info["can_use"]:
        return False

    # Вычисляем дату сброса
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

    # Увеличиваем счётчик
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


def log_premium_feature(user_id: int, feature: str, details: str = None):
    """Записать использование Premium-функции в лог."""
    conn = get_db()

    try:
        conn.execute("""
            INSERT INTO premium_features_log (user_id, feature, details)
            VALUES (?, ?, ?)
        """, (user_id, feature, details))

        conn.commit()

    except Exception as e:
        conn.rollback()


# ═══════════════════════════════════════════════════════════════
# ТРИАЛЫ ЗА ВОЗВРАТ
# ═══════════════════════════════════════════════════════════════

def check_return_trial(user_id: int, days_inactive: int) -> Optional[Dict]:
    """
    Проверить доступен ли триал за возврат.

    Args:
        user_id: ID пользователя
        days_inactive: Дней неактивности (3, 7, 14)

    Returns:
        {"trial_days": int, "expires_at": str} или None
    """
    conn = get_db()

    # Проверяем не использовал ли уже
    existing = conn.execute("""
        SELECT * FROM return_trials
        WHERE user_id = ? AND days_inactive = ?
    """, (user_id, days_inactive)).fetchone()

    if existing:
        return None

    # Определяем количество дней триала
    trial_days_map = {3: 1, 7: 3, 14: 7}
    trial_days = trial_days_map.get(days_inactive, 0)

    if trial_days == 0:
        return None

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=trial_days)

    # Создаём запись
    try:
        conn.execute("""
            INSERT INTO return_trials (user_id, days_inactive, trial_days, expires_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, days_inactive, trial_days, expires_at.isoformat()))

        conn.commit()

        return {
            "trial_days": trial_days,
            "expires_at": expires_at.isoformat()
        }

    except Exception as e:
        conn.rollback()
        return None


def claim_return_trial(user_id: int, days_inactive: int) -> Dict:
    """
    Активировать триал за возврат.

    Returns:
        {"success": bool, "message": str}
    """
    conn = get_db()

    # Проверяем доступность
    trial = conn.execute("""
        SELECT * FROM return_trials
        WHERE user_id = ? AND days_inactive = ? AND used = FALSE
    """, (user_id, days_inactive)).fetchone()

    if not trial:
        return {"success": False, "message": "Триал недоступен"}

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    expires_at = datetime.fromisoformat(trial["expires_at"])

    # Активируем Premium
    from .premium import activate_premium

    result = activate_premium(
        user_id=user_id,
        days=trial["trial_days"],
        source="return",
        extend=False
    )

    if result["success"]:
        # Помечаем триал как использованный
        conn.execute("""
            UPDATE return_trials
            SET used = TRUE
            WHERE id = ?
        """, (trial["id"],))
        conn.commit()

    return result


def get_last_activity(user_id: int) -> Optional[datetime]:
    """Получить дату последней активности пользователя."""
    conn = get_db()

    # Проверяем последнюю запись в food_log_new
    last_food = conn.execute("""
        SELECT MAX(logged_at) as last_at FROM food_log_new WHERE user_id = ?
    """, (user_id,)).fetchone()

    # Проверяем последнюю тренировку
    last_workout = conn.execute("""
        SELECT MAX(date) as last_at FROM workout_sessions WHERE user_id = ?
    """, (user_id,)).fetchone()

    # Проверяем последний вес
    last_weight = conn.execute("""
        SELECT MAX(created_at) as last_at FROM weight_log WHERE user_id = ?
    """, (user_id,)).fetchone()

    # Находим самую позднюю дату
    dates = []
    if last_food and last_food["last_at"]:
        dates.append(datetime.fromisoformat(last_food["last_at"]))
    if last_workout and last_workout["last_at"]:
        dates.append(datetime.fromisoformat(last_workout["last_at"]))
    if last_weight and last_weight["last_at"]:
        dates.append(datetime.fromisoformat(last_weight["last_at"]))

    if not dates:
        return None

    return max(dates)