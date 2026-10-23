"""Агрегаты метрик здоровья с носимых устройств (таблица health_metrics).

Метрики приходят через POST /api/v1/health/metrics (api/routers/health_data.py).
ts считается UTC, к нему применяется timezone_offset пользователя — как и для
остальных журналов (еда, вода).
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from .database import get_db, get_user

logger = logging.getLogger(__name__)

_WEEKDAYS_FULL = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def add_metric(user_id: int, metric_type: str, value: float, source: str = "manual") -> None:
    """Записать метрику здоровья (ручной ввод из бота или внешний источник)."""
    conn = get_db()
    conn.execute(
        "INSERT INTO health_metrics (user_id, ts, metric_type, value, source) VALUES (?, ?, ?, ?, ?)",
        (user_id, datetime.now(timezone.utc).isoformat(), metric_type, float(value), source),
    )
    conn.commit()


def _user_tz_offset(user_id: int) -> int:
    user = get_user(user_id)
    try:
        return int(user.get("timezone_offset") or 0) if user else 0
    except (TypeError, ValueError):
        return 0


def _local_today(offset: int) -> date:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()


def get_today_metrics(user_id: int) -> dict[str, float]:
    """Последние значения метрик за локальные текущие сутки пользователя."""
    offset = _user_tz_offset(user_id)
    today = _local_today(offset).isoformat()
    rows = get_db().execute(
        """SELECT metric_type, value FROM health_metrics
           WHERE user_id = ? AND date(ts, ?) = ?
           ORDER BY ts""",
        (user_id, f"{offset:+d} minutes", today),
    ).fetchall()
    result: dict[str, float] = {}
    for row in rows:  # последняя по ts запись перезаписывает — берём свежую
        result[row["metric_type"]] = float(row["value"])
    return result


def get_metrics_summary(user_id: int, days: int = 7) -> dict[str, Any]:
    """Агрегаты за N дней: средний сон, шаги сегодня/вчера, средний пульс покоя.

    Отсутствующие данные — None (не 0), чтобы вызывающий код мог опустить строку.
    """
    offset = _user_tz_offset(user_id)
    today = _local_today(offset)
    yesterday = today - timedelta(days=1)
    first_day = today - timedelta(days=max(1, days) - 1)

    rows = get_db().execute(
        """SELECT date(ts, ?) AS day, metric_type, value FROM health_metrics
           WHERE user_id = ? AND date(ts, ?) >= ?
           ORDER BY ts""",
        (f"{offset:+d} minutes", user_id, f"{offset:+d} minutes", first_day.isoformat()),
    ).fetchall()

    steps_by_day: dict[str, float] = {}
    sleep_by_day: dict[str, float] = {}
    resting_hr_values: list[float] = []
    resting_hr_today: Optional[float] = None
    for row in rows:
        day = str(row["day"])
        metric = row["metric_type"]
        value = float(row["value"])
        if metric == "steps":
            steps_by_day[day] = steps_by_day.get(day, 0.0) + value
        elif metric == "sleep_hours":
            sleep_by_day[day] = sleep_by_day.get(day, 0.0) + value
        elif metric == "resting_heart_rate":
            resting_hr_values.append(value)
            if day == today.isoformat():
                resting_hr_today = value  # последняя по ts запись (ORDER BY ts)

    avg_sleep: Optional[float] = None
    if sleep_by_day:
        avg_sleep = round(sum(sleep_by_day.values()) / len(sleep_by_day), 1)
    avg_resting_hr: Optional[float] = None
    if resting_hr_values:
        avg_resting_hr = round(sum(resting_hr_values) / len(resting_hr_values), 1)

    return {
        "days": days,
        "steps_today": steps_by_day.get(today.isoformat()),
        "steps_yesterday": steps_by_day.get(yesterday.isoformat()),
        "avg_sleep_hours": avg_sleep,
        "sleep_last_night": sleep_by_day.get(today.isoformat()),
        "avg_resting_heart_rate": avg_resting_hr,
        "resting_hr_today": resting_hr_today,
    }


def get_weekly_health_stats(user_id: int) -> dict[str, Any]:
    """Недельные агрегаты и тренды метрик здоровья (локальные даты пользователя).

    Текущая неделя — последние 7 локальных дней включая сегодня; тренды
    сравнивают её средние с предыдущими 7 днями. Отсутствующие данные — None.
    """
    offset = _user_tz_offset(user_id)
    today = _local_today(offset)
    week_start = today - timedelta(days=6)
    prev_start = week_start - timedelta(days=7)
    modifier = f"{offset:+d} minutes"

    rows = get_db().execute(
        """SELECT date(ts, ?) AS day, metric_type, value FROM health_metrics
           WHERE user_id = ? AND date(ts, ?) >= ?""",
        (modifier, user_id, modifier, prev_start.isoformat()),
    ).fetchall()

    steps_by_day: dict[date, float] = {}
    sleep_by_day: dict[date, float] = {}
    resting_week: list[float] = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row["day"]))
        except (TypeError, ValueError):
            continue
        metric = row["metric_type"]
        value = float(row["value"])
        if metric == "steps":
            steps_by_day[day] = steps_by_day.get(day, 0.0) + value
        elif metric == "sleep_hours":
            sleep_by_day[day] = sleep_by_day.get(day, 0.0) + value
        elif metric == "resting_heart_rate" and day >= week_start:
            resting_week.append(value)

    def _avg(by_day: dict[date, float], start: date, end: date) -> Optional[float]:
        values = [value for day, value in by_day.items() if start <= day <= end]
        if not values:
            return None
        return sum(values) / len(values)

    def _trend(current: Optional[float], previous: Optional[float]) -> Optional[float]:
        if current is None or not previous:
            return None
        return round((current - previous) / previous * 100, 1)

    def _sleep_day(best: bool) -> Optional[dict[str, Any]]:
        week_days = {
            day: hours for day, hours in sleep_by_day.items() if week_start <= day <= today
        }
        if not week_days:
            return None
        day, hours = (max if best else min)(week_days.items(), key=lambda item: item[1])
        return {
            "date": day.isoformat(),
            "weekday": _WEEKDAYS_FULL[day.weekday()],
            "hours": round(hours, 1),
        }

    avg_steps = _avg(steps_by_day, week_start, today)
    avg_sleep = _avg(sleep_by_day, week_start, today)
    week_steps = [value for day, value in steps_by_day.items() if week_start <= day <= today]

    return {
        "days": 7,
        "avg_steps": round(avg_steps) if avg_steps is not None else None,
        "total_steps": round(sum(week_steps)) if week_steps else None,
        "avg_sleep_hours": round(avg_sleep, 1) if avg_sleep is not None else None,
        "avg_resting_heart_rate": (
            round(sum(resting_week) / len(resting_week), 1) if resting_week else None
        ),
        "best_sleep_day": _sleep_day(best=True),
        "worst_sleep_day": _sleep_day(best=False),
        "steps_trend_pct": _trend(avg_steps, _avg(steps_by_day, prev_start, week_start - timedelta(days=1))),
        "sleep_trend_pct": _trend(avg_sleep, _avg(sleep_by_day, prev_start, week_start - timedelta(days=1))),
    }
