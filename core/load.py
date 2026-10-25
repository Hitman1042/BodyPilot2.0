"""Прозрачная оценка тренировочной нагрузки и восстановления."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .database import get_db, get_user

FITNESS_TAU_DAYS = 42.0
FATIGUE_TAU_DAYS = 7.0


def session_effort(session: Mapping[str, Any]) -> float:
    """Relative Effort: длительность в минутах × интенсивность (по умолчанию 5)."""
    data = dict(session)
    try:
        duration = max(0.0, float(data.get("duration_min") or 0))
    except (TypeError, ValueError):
        duration = 0.0
    try:
        raw_intensity = data.get("intensity")
        intensity = 5.0 if raw_intensity is None else float(raw_intensity)
    except (TypeError, ValueError):
        intensity = 5.0
    return duration * intensity


def _local_today(user_id: int) -> datetime.date:
    user = get_user(user_id) or {}
    offset = int(user.get("timezone_offset") or 0)
    return (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()


def get_load_curves(user_id: int, weeks: int = 8) -> list[dict[str, Any]]:
    """Дневные effort и EWMA: Fitness tau=42 дня, Fatigue tau=7 дней."""
    weeks = max(1, min(52, int(weeks)))
    today = _local_today(user_id)
    visible_days = weeks * 7
    first_visible = today - timedelta(days=visible_days - 1)
    rows = get_db().execute(
        """SELECT date, duration_min, intensity
           FROM workout_sessions
           WHERE user_id = ? AND date <= ?
           ORDER BY date, id""",
        (user_id, today.isoformat()),
    ).fetchall()
    efforts: dict[str, float] = {}
    for row in rows:
        day = str(row["date"])[:10]
        efforts[day] = efforts.get(day, 0.0) + session_effort(row)

    fitness = 0.0
    fatigue = 0.0
    fitness_alpha = 1.0 - math.exp(-1.0 / FITNESS_TAU_DAYS)
    fatigue_alpha = 1.0 - math.exp(-1.0 / FATIGUE_TAU_DAYS)
    if rows:
        first_day = min(
            datetime.fromisoformat(str(rows[0]["date"])[:10]).date(),
            first_visible,
        )
    else:
        first_day = first_visible
    result: list[dict[str, Any]] = []
    day = first_day
    while day <= today:
        effort = efforts.get(day.isoformat(), 0.0)
        fitness += fitness_alpha * (effort - fitness)
        fatigue += fatigue_alpha * (effort - fatigue)
        if day >= first_visible:
            result.append({
                "date": day.isoformat(),
                "effort": round(effort, 2),
                "fitness": round(fitness, 2),
                "fatigue": round(fatigue, 2),
                "freshness": round(fitness - fatigue, 2),
            })
        day += timedelta(days=1)
    return result


def _interpret_freshness(freshness: float) -> str:
    if freshness > 10:
        return "отличная форма, можно интенсивно"
    if freshness < -10:
        return "усталость — лёгкий день"
    return "норма"


def get_current_freshness(user_id: int) -> dict[str, Any]:
    """Текущие показатели формы и рекомендация без изменения плана тренировок."""
    curves = get_load_curves(user_id, weeks=8)
    current = curves[-1]
    first = get_db().execute(
        "SELECT MIN(date) FROM workout_sessions WHERE user_id = ?",
        (user_id,),
    ).fetchone()[0]
    history_days = 0
    if first:
        history_days = max(1, (_local_today(user_id) - datetime.fromisoformat(str(first)[:10]).date()).days + 1)
    return {
        "date": current["date"],
        "effort": current["effort"],
        "fitness": current["fitness"],
        "fatigue": current["fatigue"],
        "freshness": current["freshness"],
        "interpretation": _interpret_freshness(current["freshness"]),
        "history_days": history_days,
    }
