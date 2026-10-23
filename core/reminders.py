"""Умные напоминания: отбор пользователей и тексты (без спама, только по делу).

Логика отбора синхронная (SQLite), вызывается из планировщика через
run_in_executor. Защита от дублей — таблица reminder_log (миграция v19).
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .database import get_db

logger = logging.getLogger(__name__)

REMINDER_NO_FOOD = "no_food_today"
REMINDER_WORKOUT = "workout_today"
REMINDER_REACTIVATION = "reactivation"
REMINDER_PROGRESS_PHOTO = "progress_photo"

FOOD_REMINDER_HOUR = 15
WORKOUT_REMINDER_HOUR = 17
REACTIVATION_HOUR = 12
PROGRESS_PHOTO_HOUR = 11
FOOD_REMINDER_ACTIVE_DAYS = 3
REACTIVATION_INACTIVE_DAYS = 5
REACTIVATION_COOLDOWN_DAYS = 7
PROGRESS_PHOTO_INTERVAL_DAYS = 14
PROGRESS_PHOTO_ACTIVE_DAYS = 7

_MODULE_NAMES = {
    "warmup": "разминка",
    "mobility": "мобилити",
    "special": "спец. упражнения",
    "strength": "сила",
    "accessory": "дополнительные",
    "cool_down": "заминка",
}


def _iter_users_local_now() -> list[tuple[int, int, datetime]]:
    """(user_id, смещение часового пояса в минутах, локальное «сейчас»)."""
    conn = get_db()
    now = datetime.now(timezone.utc)
    result: list[tuple[int, int, datetime]] = []
    for row in conn.execute("SELECT user_id, timezone_offset FROM users").fetchall():
        user = dict(row)
        try:
            offset = int(user.get("timezone_offset") or 0)
        except (TypeError, ValueError):
            continue
        result.append((user["user_id"], offset, now + timedelta(minutes=offset)))
    return result


def _in_window(user_now: datetime, hour: int) -> bool:
    """Попадание в окно отправки: заданный час, первые 2 минуты."""
    return user_now.hour == hour and user_now.minute <= 2


def _offset_modifier(offset: int) -> str:
    return f"{offset:+d} minutes"


def _last_activity_date(conn, user_id: int, offset: int) -> Optional[date]:
    """Последняя локальная дата любой активности: еда, тренировка или вес."""
    modifier = _offset_modifier(offset)
    candidates = []
    row = conn.execute(
        "SELECT MAX(date(logged_at, ?)) AS day FROM food_log_new WHERE user_id = ?",
        (modifier, user_id),
    ).fetchone()
    candidates.append(row["day"] if row else None)
    row = conn.execute(
        "SELECT MAX(date) AS day FROM workout_sessions WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    candidates.append(row["day"] if row else None)
    row = conn.execute(
        "SELECT MAX(date(logged_at, ?)) AS day FROM weight_log WHERE user_id = ?",
        (modifier, user_id),
    ).fetchone()
    candidates.append(row["day"] if row else None)

    days: list[date] = []
    for raw in candidates:
        if not raw:
            continue
        try:
            days.append(date.fromisoformat(str(raw)))
        except (TypeError, ValueError):
            continue
    return max(days) if days else None


def reminder_sent_today(user_id: int, reminder_type: str, sent_date: str) -> bool:
    """Напоминание этого типа уже отправляли в указанную локальную дату."""
    row = get_db().execute(
        "SELECT id FROM reminder_log WHERE user_id = ? AND reminder_type = ? AND sent_date = ?",
        (user_id, reminder_type, sent_date),
    ).fetchone()
    return row is not None


def mark_reminder_sent(user_id: int, reminder_type: str, sent_date: str) -> None:
    """Отметить отправку напоминания (идемпотентно, UNIQUE в reminder_log)."""
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO reminder_log (user_id, reminder_type, sent_date) VALUES (?, ?, ?)",
        (user_id, reminder_type, sent_date),
    )
    conn.commit()


def get_users_due_for_food_reminder() -> list[tuple[int, str]]:
    """15:00 локального: еды за сегодня нет, но была активность за последние 3 дня.

    Совсем неактивных не трогаем — пусть лучше вернутся сами.
    """
    conn = get_db()
    due: list[tuple[int, str]] = []
    for user_id, offset, user_now in _iter_users_local_now():
        if not _in_window(user_now, FOOD_REMINDER_HOUR):
            continue
        today = user_now.date().isoformat()
        if reminder_sent_today(user_id, REMINDER_NO_FOOD, today):
            continue
        has_food = conn.execute(
            "SELECT id FROM food_log_new WHERE user_id = ? AND date(logged_at, ?) = ? LIMIT 1",
            (user_id, _offset_modifier(offset), today),
        ).fetchone()
        if has_food:
            continue
        last_activity = _last_activity_date(conn, user_id, offset)
        if last_activity is None:
            continue
        if (user_now.date() - last_activity).days > FOOD_REMINDER_ACTIVE_DAYS:
            continue
        due.append((user_id, today))
    return due


def get_users_due_for_workout_reminder() -> list[tuple[int, str]]:
    """17:00 локального: на сегодня есть активный план, но тренировки ещё не было."""
    conn = get_db()
    due: list[tuple[int, str]] = []
    for user_id, _offset, user_now in _iter_users_local_now():
        if not _in_window(user_now, WORKOUT_REMINDER_HOUR):
            continue
        today = user_now.date().isoformat()
        if reminder_sent_today(user_id, REMINDER_WORKOUT, today):
            continue
        has_plan = conn.execute(
            "SELECT id FROM daily_workout_plans WHERE user_id = ? AND date = ? AND is_active = 1 LIMIT 1",
            (user_id, today),
        ).fetchone()
        if not has_plan:
            continue
        has_session = conn.execute(
            "SELECT id FROM workout_sessions WHERE user_id = ? AND date = ? LIMIT 1",
            (user_id, today),
        ).fetchone()
        if has_session:
            continue
        due.append((user_id, today))
    return due


def get_users_due_for_reactivation() -> list[tuple[int, str]]:
    """12:00 локального: тишина 5+ дней, но пользователь раньше был активен.

    Не чаще одного раза в 7 дней на пользователя.
    """
    conn = get_db()
    due: list[tuple[int, str]] = []
    for user_id, offset, user_now in _iter_users_local_now():
        if not _in_window(user_now, REACTIVATION_HOUR):
            continue
        today = user_now.date()
        last_activity = _last_activity_date(conn, user_id, offset)
        if last_activity is None:
            continue  # никогда не был активен — не о чем напоминать
        if (today - last_activity).days < REACTIVATION_INACTIVE_DAYS:
            continue
        row = conn.execute(
            "SELECT MAX(sent_date) AS last_sent FROM reminder_log "
            "WHERE user_id = ? AND reminder_type = ?",
            (user_id, REMINDER_REACTIVATION),
        ).fetchone()
        if row and row["last_sent"]:
            try:
                last_sent = date.fromisoformat(str(row["last_sent"]))
                if (today - last_sent).days < REACTIVATION_COOLDOWN_DAYS:
                    continue
            except (TypeError, ValueError):
                pass
        due.append((user_id, today.isoformat()))
    return due


def get_users_due_for_progress_photo_reminder() -> list[tuple[int, str]]:
    """11:00 локального: активен за последнюю неделю, фото-напоминание не чаще
    раза в 14 дней (по MAX(sent_date) из reminder_log)."""
    conn = get_db()
    due: list[tuple[int, str]] = []
    for user_id, offset, user_now in _iter_users_local_now():
        if not _in_window(user_now, PROGRESS_PHOTO_HOUR):
            continue
        today = user_now.date()
        last_activity = _last_activity_date(conn, user_id, offset)
        if last_activity is None:
            continue
        if (today - last_activity).days > PROGRESS_PHOTO_ACTIVE_DAYS:
            continue
        row = conn.execute(
            "SELECT MAX(sent_date) AS last_sent FROM reminder_log "
            "WHERE user_id = ? AND reminder_type = ?",
            (user_id, REMINDER_PROGRESS_PHOTO),
        ).fetchone()
        if row and row["last_sent"]:
            try:
                last_sent = date.fromisoformat(str(row["last_sent"]))
                if (today - last_sent).days < PROGRESS_PHOTO_INTERVAL_DAYS:
                    continue
            except (TypeError, ValueError):
                pass
        due.append((user_id, today.isoformat()))
    return due


def build_progress_photo_text() -> str:
    return (
        "📸 Две недели прошло — время фото прогресса! "
        "Раздел «📊 Прогресс» → «📸 Фото прогресса». "
        "Фото видишь только ты."
    )


def build_food_reminder_text() -> str:
    return (
        "🍽 Привет! Сегодня ещё нет записей о еде. Всё в порядке? "
        "Просто напиши, что съел — я запишу."
    )


def build_workout_reminder_text(user_id: int, day: str) -> str:
    """«Сегодня по плану тренировка: [модули кратко]» — только чтение плана."""
    modules_text = ""
    try:
        from .training_service import get_daily_plan

        plan = get_daily_plan(user_id, date.fromisoformat(day))
        if plan:
            names = [
                _MODULE_NAMES[module]
                for module, exercises in (plan.get("modules") or {}).items()
                if exercises and module in _MODULE_NAMES
            ]
            if names:
                modules_text = ": " + ", ".join(names)
    except Exception as e:
        logger.warning(f"Напоминание о тренировке: план не прочитан ({user_id}): {e}")
    return f"💪 Сегодня по плану тренировка{modules_text}. Получится?"


def build_reactivation_text(user_id: int) -> str:
    """Возврат после перерыва: упоминаем лучшую серию, если она была."""
    streak_part = ""
    try:
        from .gamification import get_streak

        best = int(get_streak(user_id).get("best") or 0)
        if best >= 2:
            streak_part = f" Серия у тебя была {best} {_days_word(best)} —"
    except Exception as e:
        logger.warning(f"Напоминание о возврате: серия не получена ({user_id}): {e}")
    return (
        "👋 Скучаем! За неделю перерыва прогресс не теряется."
        f"{streak_part} вернёмся? Один приём пищи — и ты в игре."
    )


def _days_word(value: int) -> str:
    if 11 <= value % 100 <= 14:
        return "дней"
    if value % 10 == 1:
        return "день"
    if 2 <= value % 10 <= 4:
        return "дня"
    return "дней"
