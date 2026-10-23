"""Челленджи пользователя с вычисляемым прогрессом."""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .database import get_db, get_user
from .nutrition_calc import get_nutrition_plan

CHALLENGES: Dict[str, Dict[str, Any]] = {
    "food_30": {
        "code": "food_30",
        "name": "30 дней дневника",
        "description": "Записывай питание каждый день без пропусков.",
        "condition": "Каждый день есть хотя бы одна запись еды",
        "target_days": 30,
        "target": 30,
        "unit": "дней",
        "metric": "food_days",
    },
    "workout_12": {
        "code": "workout_12",
        "name": "12 тренировок за 30 дней",
        "description": "Проведи 12 тренировок в течение 30 дней.",
        "condition": "12 записанных тренировок за период",
        "target_days": 30,
        "target": 12,
        "unit": "тренировок",
        "metric": "workouts",
    },
    "calorie_week": {
        "code": "calorie_week",
        "name": "7 дней в норме калорий",
        "description": "Неделя питания в пределах 90–110% дневной нормы.",
        "condition": "Калории каждого дня в пределах 90–110% нормы",
        "target_days": 7,
        "target": 7,
        "unit": "дней",
        "metric": "calorie_days",
    },
}


def _user_context(user_id: int) -> Optional[tuple[dict, int, date]]:
    user = get_user(user_id)
    if not user:
        return None
    offset = int(user.get("timezone_offset") or 0)
    today = (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()
    return user, offset, today


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _bounds(row: dict, offset: int, today: date) -> tuple[date, date, date]:
    started_at = _parse_utc(row["started_at"])
    start = (started_at + timedelta(minutes=offset)).date()
    end = start + timedelta(days=int(row["target_days"]) - 1)
    current_end = min(today, end)
    return start, end, current_end


def _dates_in_range(start: date, end: date) -> List[date]:
    if end < start:
        return []
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def _offset_modifier(offset: int) -> str:
    return f"{offset:+d} minutes"


def _food_by_day(user_id: int, offset: int, start: date, end: date) -> Dict[date, Dict[str, float]]:
    if end < start:
        return {}
    rows = get_db().execute(
        """SELECT date(logged_at, ?) AS day,
                  COUNT(*) AS entries,
                  COALESCE(SUM(calories), 0) AS calories
           FROM food_log_new
           WHERE user_id = ? AND date(logged_at, ?) BETWEEN ? AND ?
           GROUP BY day""",
        (_offset_modifier(offset), user_id, _offset_modifier(offset),
         start.isoformat(), end.isoformat()),
    ).fetchall()
    result = {}
    for row in rows:
        try:
            day = date.fromisoformat(row["day"])
        except (TypeError, ValueError):
            continue
        result[day] = {
            "entries": int(row["entries"] or 0),
            "calories": float(row["calories"] or 0),
        }
    return result


def _workout_days(user_id: int, start: date, end: date) -> list[date]:
    if end < start:
        return []
    rows = get_db().execute(
        """SELECT date(date) AS day
           FROM workout_sessions
           WHERE user_id = ? AND date BETWEEN ? AND ?""",
        (user_id, start.isoformat(), end.isoformat()),
    ).fetchall()
    result = []
    for row in rows:
        try:
            result.append(date.fromisoformat(row["day"]))
        except (TypeError, ValueError):
            continue
    return result


def _streak_from_start(days: set[date], start: date, end: date) -> int:
    current = 0
    for day in _dates_in_range(start, end):
        if day not in days:
            break
        current += 1
    return current


def _streak_ending(days: set[date], today: date, end: date) -> int:
    cursor = min(today, end)
    if cursor not in days:
        cursor -= timedelta(days=1)
    current = 0
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)
    return current


def _evaluate_food(row: dict, user_id: int, offset: int, today: date) -> Dict[str, Any]:
    start, end, current_end = _bounds(row, offset, today)
    days = set(_food_by_day(user_id, offset, start, current_end))
    required_end = min(today - timedelta(days=1), end)
    failed = any(day not in days for day in _dates_in_range(start, required_end))
    current = _streak_from_start(days, start, current_end)
    status = "active"
    if current >= int(row["target_days"]):
        status = "completed"
    elif failed or today > end:
        status = "failed"
    return {"current": current, "streak_days": current, "status": status}


def _evaluate_calories(row: dict, user_id: int, offset: int, today: date) -> Dict[str, Any]:
    start, end, current_end = _bounds(row, offset, today)
    daily = _food_by_day(user_id, offset, start, current_end)
    plan = get_nutrition_plan(user_id)
    target = float(plan.get("target_calories") or 0)
    low, high = target * 0.9, target * 1.1

    required_end = min(today - timedelta(days=1), end)
    failed = target <= 0 or any(
        not low <= daily.get(day, {}).get("calories", 0) <= high
        for day in _dates_in_range(start, required_end)
    )
    current = 0
    if target > 0:
        for day in _dates_in_range(start, current_end):
            calories = daily.get(day, {}).get("calories", 0)
            if not low <= calories <= high:
                break
            current += 1
    status = "active"
    if current >= int(row["target_days"]):
        status = "completed"
    elif failed or today > end:
        status = "failed"
    return {"current": current, "streak_days": current, "status": status}


def _evaluate_workouts(row: dict, user_id: int, offset: int, today: date) -> Dict[str, Any]:
    start, end, current_end = _bounds(row, offset, today)
    days = _workout_days(user_id, start, current_end)
    current = len(days)
    status = "active"
    if current >= CHALLENGES[row["code"]]["target"]:
        status = "completed"
    elif today > end:
        status = "failed"
    return {
        "current": current,
        "streak_days": _streak_ending(set(days), today, end),
        "status": status,
    }


def _evaluate(row: dict, user_id: int, offset: int, today: date) -> Dict[str, Any]:
    code = row["code"]
    if code == "food_30":
        progress = _evaluate_food(row, user_id, offset, today)
    elif code == "workout_12":
        progress = _evaluate_workouts(row, user_id, offset, today)
    else:
        progress = _evaluate_calories(row, user_id, offset, today)

    start, end, _ = _bounds(row, offset, today)
    catalog = CHALLENGES[code]
    progress.update({
        "challenge_id": row["id"],
        "code": code,
        "name": catalog["name"],
        "description": catalog["description"],
        "condition": catalog["condition"],
        "target": catalog["target"],
        "target_days": int(row["target_days"]),
        "unit": catalog["unit"],
        "started_at": row["started_at"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    })
    if row["status"] in ("completed", "failed"):
        progress["status"] = row["status"]
    return progress


def join_challenge(user_id: int, code: str) -> Dict[str, Any]:
    """Подключить пользователя к челленджу; повторный вход в активный идемпотентен."""
    if code not in CHALLENGES:
        raise ValueError("Неизвестный челлендж")
    if not get_user(user_id):
        raise ValueError("Пользователь не найден")

    conn = get_db()
    active = conn.execute(
        """SELECT * FROM challenges
           WHERE user_id = ? AND code = ? AND status = 'active'
           ORDER BY id DESC LIMIT 1""",
        (user_id, code),
    ).fetchone()
    if not active:
        catalog = CHALLENGES[code]
        conn.execute(
            "INSERT INTO challenges (user_id, code, target_days) VALUES (?, ?, ?)",
            (user_id, code, catalog["target_days"]),
        )
        conn.commit()
    return get_challenge_progress(user_id, code)


def check_challenges(user_id: int) -> List[Dict[str, Any]]:
    """Проверить активные челленджи и вернуть только новые completed/failed."""
    context = _user_context(user_id)
    if not context:
        return []
    _, offset, today = context
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM challenges WHERE user_id = ? AND status = 'active' ORDER BY id",
        (user_id,),
    ).fetchall()
    changed = []
    for raw_row in rows:
        row = dict(raw_row)
        if row["code"] not in CHALLENGES:
            continue
        progress = _evaluate(row, user_id, offset, today)
        if progress["status"] == "active":
            continue
        cursor = conn.execute(
            """UPDATE challenges
               SET status = ?, completed_at = datetime('now')
               WHERE id = ? AND status = 'active'""",
            (progress["status"], row["id"]),
        )
        if cursor.rowcount == 1:
            changed.append(progress)
    conn.commit()
    return changed


def get_active_challenges(user_id: int) -> List[Dict[str, Any]]:
    """Активные челленджи с актуальным вычисленным прогрессом."""
    check_challenges(user_id)
    context = _user_context(user_id)
    if not context:
        return []
    _, offset, today = context
    rows = get_db().execute(
        "SELECT * FROM challenges WHERE user_id = ? AND status = 'active' ORDER BY started_at",
        (user_id,),
    ).fetchall()
    return [_evaluate(dict(row), user_id, offset, today) for row in rows if row["code"] in CHALLENGES]


def get_challenge_progress(user_id: int, code: str) -> Dict[str, Any]:
    """Прогресс по коду; возвращает status='not_joined', если пользователь не участвовал."""
    if code not in CHALLENGES:
        raise ValueError("Неизвестный челлендж")
    context = _user_context(user_id)
    catalog = CHALLENGES[code]
    if not context:
        raise ValueError("Пользователь не найден")
    _, offset, today = context
    row = get_db().execute(
        """SELECT * FROM challenges
           WHERE user_id = ? AND code = ?
           ORDER BY started_at DESC, id DESC LIMIT 1""",
        (user_id, code),
    ).fetchone()
    if not row:
        return {
            "code": code,
            "name": catalog["name"],
            "description": catalog["description"],
            "condition": catalog["condition"],
            "current": 0,
            "target": catalog["target"],
            "streak_days": 0,
            "status": "not_joined",
            "target_days": catalog["target_days"],
            "unit": catalog["unit"],
        }
    return _evaluate(dict(row), user_id, offset, today)
