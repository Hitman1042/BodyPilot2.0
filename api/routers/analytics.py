"""Рекорды, кривые нагрузки и календарь активности Mini App."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_current_user_id
from api.deps import get_db
from api.schemas import CalendarDayOut, CalendarOut, LoadOut, PersonalRecordsOut
from core.database import get_user
from core.load import get_current_freshness, get_load_curves
from core.records import get_personal_records

router = APIRouter(prefix="/api/v1", tags=["analytics"])


@router.get("/records", response_model=PersonalRecordsOut)
def records(user_id: int = Depends(get_current_user_id)) -> PersonalRecordsOut:
    return PersonalRecordsOut(**get_personal_records(user_id))


@router.get("/analytics/load", response_model=LoadOut)
def load_analytics(
    weeks: int = Query(default=8, ge=1, le=52),
    user_id: int = Depends(get_current_user_id),
) -> LoadOut:
    return LoadOut(
        weeks=weeks,
        days=get_load_curves(user_id, weeks),
        current=get_current_freshness(user_id),
    )


def _local_rows(
    user_id: int,
    table: str,
    timestamp: str,
    value: str,
    offset: int,
    cutoff: str,
    metric_filter: str = "",
) -> list:
    return get_db().execute(
        f"""SELECT date({timestamp}, ?) AS day, SUM({value}) AS value, COUNT(*) AS entries
            FROM {table}
            WHERE user_id = ? AND {timestamp} >= ? {metric_filter}
            GROUP BY day""",
        (f"{offset:+d} minutes", user_id, cutoff),
    ).fetchall()


@router.get("/analytics/calendar", response_model=CalendarOut)
def activity_calendar(
    month: str = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    user_id: int = Depends(get_current_user_id),
) -> CalendarOut:
    user = get_user(user_id) or {}
    offset = int(user.get("timezone_offset") or 0)
    if month is None:
        month = (datetime.utcnow() + timedelta(minutes=offset)).strftime("%Y-%m")
    try:
        first_day = datetime.strptime(month, "%Y-%m").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="month must be a valid YYYY-MM") from exc
    last_day = first_day.replace(day=calendar.monthrange(first_day.year, first_day.month)[1])
    cutoff = (first_day - timedelta(days=1)).isoformat()

    food = {}
    for row in _local_rows(user_id, "food_log_new", "logged_at", "calories", offset, cutoff):
        if row["day"] and first_day.isoformat() <= row["day"] <= last_day.isoformat():
            food[row["day"]] = {
                "calories": float(row["value"] or 0),
                "has_food": bool(row["entries"]),
            }
    steps = {}
    for row in _local_rows(
        user_id, "health_metrics", "ts", "value", offset, cutoff, "AND metric_type = 'steps'"
    ):
        if row["day"] and first_day.isoformat() <= row["day"] <= last_day.isoformat():
            steps[row["day"]] = int(round(float(row["value"] or 0)))
    water = {}
    for row in _local_rows(user_id, "water_log", "logged_at", "amount_ml", offset, cutoff):
        if row["day"] and first_day.isoformat() <= row["day"] <= last_day.isoformat():
            water[row["day"]] = int(round(float(row["value"] or 0)))
    workout_rows = get_db().execute(
        """SELECT date, COUNT(*) AS sessions FROM workout_sessions
           WHERE user_id = ? AND date >= ? AND date <= ? GROUP BY date""",
        (user_id, first_day.isoformat(), last_day.isoformat()),
    ).fetchall()
    workouts = {row["date"]: bool(row["sessions"]) for row in workout_rows}

    days = []
    for day_number in range(1, last_day.day + 1):
        day = date(first_day.year, first_day.month, day_number).isoformat()
        days.append(CalendarDayOut(
            date=day,
            has_food=food.get(day, {}).get("has_food", False),
            has_workout=workouts.get(day, False),
            steps=steps.get(day),
            water_ml=water.get(day, 0),
            calories=food.get(day, {}).get("calories", 0.0),
        ))
    return CalendarOut(month=month, days=days)
