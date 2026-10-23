"""Стрики, достижения и учёт воды без обращений к AI."""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .database import get_db, get_user
from .nutrition_calc import suggest_water_intake

logger = logging.getLogger(__name__)

STREAK_LOOKBACK_DAYS = 60

ACHIEVEMENTS: Dict[str, Dict[str, str]] = {
    "first_food": {
        "code": "first_food",
        "name": "Первая запись в дневнике",
        "emoji": "🍽️",
    },
    "first_workout": {
        "code": "first_workout",
        "name": "Первая тренировка",
        "emoji": "🏋️",
    },
    "first_weight": {
        "code": "first_weight",
        "name": "Первое взвешивание",
        "emoji": "⚖️",
    },
    "streak_3": {
        "code": "streak_3",
        "name": "Серия 3 дня",
        "emoji": "🔥",
    },
    "streak_7": {
        "code": "streak_7",
        "name": "Серия 7 дней",
        "emoji": "🔥",
    },
    "streak_14": {
        "code": "streak_14",
        "name": "Серия 14 дней",
        "emoji": "🔥",
    },
    "streak_30": {
        "code": "streak_30",
        "name": "Серия 30 дней",
        "emoji": "🏅",
    },
    "workouts_5": {
        "code": "workouts_5",
        "name": "5 тренировок",
        "emoji": "💪",
    },
    "workouts_10": {
        "code": "workouts_10",
        "name": "10 тренировок",
        "emoji": "💪",
    },
    "food_week": {
        "code": "food_week",
        "name": "Неделя дневника питания",
        "emoji": "📔",
    },
    "water_2l": {
        "code": "water_2l",
        "name": "2 литра воды за день",
        "emoji": "💧",
    },
}

_STREAK_ACHIEVEMENTS = {
    "streak_3": 3,
    "streak_7": 7,
    "streak_14": 14,
    "streak_30": 30,
    "food_week": 7,
}


def _timezone_offset(user_id: int) -> int:
    user = get_user(user_id)
    return int(user.get("timezone_offset") or 0) if user else 0


def _local_today(user_id: int, offset: Optional[int] = None) -> date:
    tz_offset = _timezone_offset(user_id) if offset is None else offset
    return (datetime.now(timezone.utc) + timedelta(minutes=tz_offset)).date()


def _offset_modifier(offset: int) -> str:
    return f"{offset:+d} minutes"


def _food_dates(user_id: int, offset: int, today: date) -> set[date]:
    first_day = today - timedelta(days=STREAK_LOOKBACK_DAYS - 1)
    cutoff = (first_day - timedelta(days=1)).isoformat()
    rows = get_db().execute(
        """SELECT DISTINCT date(logged_at, ?) AS day
           FROM food_log_new
           WHERE user_id = ? AND logged_at >= ?
           ORDER BY day""",
        (_offset_modifier(offset), user_id, cutoff),
    ).fetchall()

    days: set[date] = set()
    for row in rows:
        try:
            day = date.fromisoformat(row["day"])
        except (TypeError, ValueError):
            continue
        if first_day <= day <= today:
            days.add(day)
    return days


def get_streak(user_id: int) -> Dict[str, int]:
    """Текущая и лучшая серии дней с записями еды по локальным датам."""
    offset = _timezone_offset(user_id)
    today = _local_today(user_id, offset)
    days = _food_dates(user_id, offset, today)

    cursor = today if today in days else today - timedelta(days=1)
    current = 0
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)

    best = 0
    run = 0
    previous: Optional[date] = None
    for day in sorted(days):
        run = run + 1 if previous == day - timedelta(days=1) else 1
        best = max(best, run)
        previous = day

    return {"current": current, "best": best}


def _days_word(value: int) -> str:
    if 11 <= value % 100 <= 14:
        return "дней"
    if value % 10 == 1:
        return "день"
    if 2 <= value % 10 <= 4:
        return "дня"
    return "дней"


def format_streak_text(user_id: int) -> str:
    """Строка для дайджеста; пустая, если серия короче двух дней."""
    streak = get_streak(user_id)
    current = streak["current"]
    if current < 2:
        return ""
    return f"🔥 Серия: {current} {_days_word(current)} (рекорд {streak['best']})"


def evaluate_achievements(user_id: int, streak: Optional[Dict[str, int]] = None) -> set[str]:
    """Коды достижений, чьи условия выполняются на реальных данных пользователя.

    Используется и при выдаче новых достижений, и при аудите уже выданных
    (scripts/maintenance/fix_achievements.py) — логика всегда одна.
    """
    conn = get_db()
    qualified: set[str] = set()

    metrics = conn.execute(
        """SELECT
               (SELECT COUNT(*) FROM food_log_new WHERE user_id = :user_id) AS food_count,
               (SELECT COUNT(*) FROM workout_sessions WHERE user_id = :user_id) AS workout_count,
               (SELECT COUNT(*) FROM weight_log WHERE user_id = :user_id) AS weight_count""",
        {"user_id": user_id},
    ).fetchone()
    food_count = int(metrics["food_count"] or 0)
    workout_count = int(metrics["workout_count"] or 0)
    weight_count = int(metrics["weight_count"] or 0)

    if food_count >= 1:
        qualified.add("first_food")
    if workout_count >= 1:
        qualified.add("first_workout")
    if weight_count >= 1:
        qualified.add("first_weight")
    if workout_count >= 5:
        qualified.add("workouts_5")
    if workout_count >= 10:
        qualified.add("workouts_10")

    streak = streak if streak is not None else get_streak(user_id)
    for code, required_days in _STREAK_ACHIEVEMENTS.items():
        if streak["best"] >= required_days:
            qualified.add(code)

    offset = _timezone_offset(user_id)
    water_day = conn.execute(
        """SELECT date(logged_at, ?) AS day
           FROM water_log
           WHERE user_id = ?
           GROUP BY day
           HAVING SUM(amount_ml) >= 2000
           LIMIT 1""",
        (_offset_modifier(offset), user_id),
    ).fetchone()
    if water_day:
        qualified.add("water_2l")

    return qualified


def _check_and_unlock(user_id: int, streak: Optional[Dict[str, int]] = None) -> List[Dict[str, str]]:
    conn = get_db()
    unlocked = {
        row["code"]
        for row in conn.execute(
            "SELECT code FROM achievements WHERE user_id = ?", (user_id,)
        ).fetchall()
    }
    pending = [code for code in ACHIEVEMENTS if code not in unlocked]
    if not pending:
        return []

    qualified = evaluate_achievements(user_id, streak=streak)

    newly_unlocked: List[Dict[str, str]] = []
    for code in pending:
        if code not in qualified:
            continue
        cursor = conn.execute(
            "INSERT OR IGNORE INTO achievements (user_id, code) VALUES (?, ?)",
            (user_id, code),
        )
        if cursor.rowcount == 1:
            newly_unlocked.append(ACHIEVEMENTS[code].copy())
    conn.commit()
    return newly_unlocked


def _achievement_text(achievement: Dict[str, str]) -> str:
    return (
        f"🏆 Достижение разблокировано: "
        f"{achievement['emoji']} {achievement['name']}"
    )


def _achievements_text(achievements: List[Dict[str, str]]) -> str:
    """Одно сообщение на пачку достижений вместо повторяющихся строк."""
    if len(achievements) == 1:
        return _achievement_text(achievements[0])
    lines = ["🏆 Новые достижения:"]
    lines.extend(f"• {item['emoji']} {item['name']}" for item in achievements)
    return "\n".join(lines)


async def _send_achievements(bot: Any, chat_id: int, achievements: List[Dict[str, str]]) -> None:
    try:
        await bot.send_message(chat_id, _achievements_text(achievements))
    except Exception as exc:
        logger.warning("Не удалось отправить достижение пользователю %s: %s", chat_id, exc)


def check_and_unlock_achievements(
        user_id: int, bot: Any = None, chat_id: Optional[int] = None
) -> List[Dict[str, str]]:
    """Выдать новые достижения и вернуть их; при bot/chat_id также уведомить."""
    newly_unlocked = _check_and_unlock(user_id)
    if newly_unlocked and bot is not None and chat_id is not None:
        coroutine = _send_achievements(bot, chat_id, newly_unlocked)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coroutine)
        else:
            loop.create_task(coroutine)
    return newly_unlocked


async def notify_progress(message: Any, user_id: int, show_streak: bool = True) -> None:
    """Отправить короткое уведомление о серии и новых достижениях."""
    try:
        streak = get_streak(user_id)
        newly_unlocked = _check_and_unlock(user_id, streak=streak)
        from .challenges import check_challenges

        challenge_updates = check_challenges(user_id)
        lines = []
        current = streak["current"]
        if show_streak and current >= 2:
            lines.append(f"🔥 Серия: {current} {_days_word(current)}")
        if newly_unlocked:
            lines.append(_achievements_text(newly_unlocked))
        lines.extend(
            f"🏆 Челлендж «{item['name']}» выполнен!"
            for item in challenge_updates
            if item["status"] == "completed"
        )
        if lines:
            await message.answer("\n".join(lines))
    except Exception as exc:
        logger.warning("Не удалось отправить прогресс пользователю %s: %s", user_id, exc)


def add_water(user_id: int, amount_ml: int) -> int:
    """Добавить воду и вернуть ID записи."""
    amount = int(amount_ml)
    if amount <= 0:
        raise ValueError("amount_ml должен быть положительным")
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO water_log (user_id, amount_ml) VALUES (?, ?)",
        (user_id, amount),
    )
    conn.commit()
    return cursor.lastrowid


def get_today_water(user_id: int) -> int:
    """Сумма воды за локальные текущие сутки пользователя в миллилитрах."""
    offset = _timezone_offset(user_id)
    today = _local_today(user_id, offset).isoformat()
    row = get_db().execute(
        """SELECT COALESCE(SUM(amount_ml), 0) AS total
           FROM water_log
           WHERE user_id = ? AND date(logged_at, ?) = ?""",
        (user_id, _offset_modifier(offset), today),
    ).fetchone()
    return int(row["total"] or 0)


def get_water_target(user_id: int) -> int:
    """Дневная норма воды пользователя в миллилитрах."""
    user = get_user(user_id) or {}
    weight = float(user.get("weight_kg") or 70)
    activity = user.get("activity") or "moderate"
    litres = suggest_water_intake(weight, activity)
    return int(round(litres * 1000))
