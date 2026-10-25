"""Личные рекорды силовых тренировок и дневной активности."""

from __future__ import annotations

from typing import Any

from .database import get_db, get_user


def _workout_records(
    user_id: int,
    *,
    only_session_id: int | None = None,
    exclude_session_id: int | None = None,
) -> dict[str, Any]:
    clauses = ["s.user_id = ?"]
    params: list[Any] = [user_id]
    if only_session_id is not None:
        clauses.append("s.id = ?")
        params.append(only_session_id)
    if exclude_session_id is not None:
        clauses.append("s.id != ?")
        params.append(exclude_session_id)
    where = " AND ".join(clauses)
    conn = get_db()
    rows = conn.execute(
        f"""SELECT s.id AS session_id, s.date, we.exercise_id,
                   COALESCE(e.name, we.custom_exercise_name, 'Упражнение') AS name,
                   ws.reps, ws.weight_kg
            FROM workout_sessions s
            JOIN workout_exercises we ON we.session_id = s.id
            JOIN workout_sets ws ON ws.workout_exercise_id = we.id
            LEFT JOIN exercises e ON e.id = we.exercise_id
            WHERE {where}
            ORDER BY s.date, s.id, we.id, ws.set_number, ws.id""",
        params,
    ).fetchall()
    sessions = conn.execute(
        f"""SELECT s.id, s.date, s.duration_min,
                   COALESCE(SUM(ws.weight_kg * ws.reps), 0) AS tonnage_kg
            FROM workout_sessions s
            LEFT JOIN workout_exercises we ON we.session_id = s.id
            LEFT JOIN workout_sets ws ON ws.workout_exercise_id = we.id
            WHERE {where}
            GROUP BY s.id, s.date, s.duration_min
            ORDER BY s.date, s.id""",
        params,
    ).fetchall()

    exercises: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        name = str(row["name"] or "Упражнение").strip() or "Упражнение"
        key = (
            "id", int(row["exercise_id"])
        ) if row["exercise_id"] is not None else ("custom", name.casefold())
        if key not in exercises:
            exercises[key] = {
                "exercise_id": row["exercise_id"],
                "name": name,
                "max_weight_kg": None,
                "max_weight_date": None,
                "max_reps": None,
                "max_reps_date": None,
            }
        record = exercises[key]
        weight = float(row["weight_kg"] or 0)
        reps = int(row["reps"] or 0)
        if weight > 0 and (record["max_weight_kg"] is None or weight > record["max_weight_kg"]):
            record["max_weight_kg"] = weight
            record["max_weight_date"] = row["date"]
        if reps > 0 and (record["max_reps"] is None or reps > record["max_reps"]):
            record["max_reps"] = reps
            record["max_reps_date"] = row["date"]

    best_tonnage = None
    best_duration = None
    for row in sessions:
        tonnage = float(row["tonnage_kg"] or 0)
        duration = int(row["duration_min"] or 0)
        if tonnage > 0 and (best_tonnage is None or tonnage > best_tonnage["value_kg"]):
            best_tonnage = {
                "value_kg": tonnage,
                "date": row["date"],
                "session_id": row["id"],
            }
        if duration > 0 and (best_duration is None or duration > best_duration["value_min"]):
            best_duration = {
                "value_min": duration,
                "date": row["date"],
                "session_id": row["id"],
            }
    return {
        "exercises": sorted(exercises.values(), key=lambda item: item["name"].casefold()),
        "session_tonnage": best_tonnage,
        "session_duration": best_duration,
    }


def _best_day(
    user_id: int,
    table: str,
    timestamp_column: str,
    value_expression: str,
    offset: int,
    metric_filter: str = "",
) -> dict[str, Any] | None:
    rows = get_db().execute(
        f"""SELECT date({timestamp_column}, ?) AS day, SUM({value_expression}) AS value
            FROM {table}
            WHERE user_id = ? {metric_filter}
            GROUP BY day
            ORDER BY day""",
        (f"{offset:+d} minutes", user_id),
    ).fetchall()
    best = None
    for row in rows:
        value = float(row["value"] or 0)
        if value > 0 and (best is None or value > best["value"]):
            best = {"value": value, "date": row["day"]}
    return best


def get_personal_records(user_id: int) -> dict[str, Any]:
    """Рекорды по упражнениям, сессиям, шагам и белку за локальный день."""
    result = _workout_records(user_id)
    user = get_user(user_id) or {}
    offset = int(user.get("timezone_offset") or 0)
    steps = _best_day(
        user_id, "health_metrics", "ts", "value", offset, "AND metric_type = 'steps'"
    )
    protein = _best_day(
        user_id, "food_log_new", "logged_at", "protein_g", offset,
        # Отсекаем мусорные записи (штрих-код вместо граммов и т.п.),
        # чтобы рекорд не был аномальным
        "AND weight_g <= 5000 AND calories <= 15000 AND protein_g <= 1000",
    )
    result["steps"] = (
        {"value": int(round(steps["value"])), "date": steps["date"]} if steps else None
    )
    result["protein"] = (
        {"value_g": protein["value"], "date": protein["date"]} if protein else None
    )
    return result


def check_new_records(user_id: int, session_id: int) -> list[str]:
    """Тексты рекордов, которые сессия установила строго выше прошлых результатов."""
    current = _workout_records(user_id, only_session_id=session_id)
    owned = get_db().execute(
        "SELECT 1 FROM workout_sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()
    if not owned:
        return []
    previous = _workout_records(user_id, exclude_session_id=session_id)
    previous_exercises = {
        (
            ("id", int(item["exercise_id"]))
            if item["exercise_id"] is not None
            else ("custom", item["name"].casefold())
        ): item
        for item in previous["exercises"]
    }
    messages: list[str] = []
    for item in current["exercises"]:
        key = (
            ("id", int(item["exercise_id"]))
            if item["exercise_id"] is not None
            else ("custom", item["name"].casefold())
        )
        old = previous_exercises.get(key, {})
        weight = item["max_weight_kg"]
        if weight is not None and (old.get("max_weight_kg") is None or weight > old["max_weight_kg"]):
            messages.append(f"🏆 Новый рекорд: {item['name']} {weight:g} кг!")
        reps = item["max_reps"]
        if reps is not None and (old.get("max_reps") is None or reps > old["max_reps"]):
            messages.append(f"🏆 Новый рекорд повторений: {item['name']} — {reps}!")
    tonnage = current["session_tonnage"]
    old_tonnage = previous["session_tonnage"]
    if tonnage and (old_tonnage is None or tonnage["value_kg"] > old_tonnage["value_kg"]):
        messages.append(f"🏆 Новый рекорд тоннажа тренировки: {tonnage['value_kg']:g} кг!")
    return messages
