"""Операции с тренировками и упражнениями."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .connection import get_db

MUSCLE_GROUP_MAP: dict[str, list[str]] = {
    "chest": ["chest_upper", "chest_middle", "chest_lower", "chest"],
    "back": ["lats", "upper_back", "middle_back", "lower_back", "traps", "rear_delt", "back"],
    "legs": ["quads", "hamstrings", "glutes", "adductors", "calves", "legs_general", "hip_flexors", "legs"],
    "shoulders": ["front_delt", "middle_delt", "rear_delt", "deltoid", "shoulders"],
    "core": ["rectus_abdominis", "obliques", "transversus_abdominis", "abdominis", "core", "spine_mobilization"],
    "arms": ["biceps", "triceps", "brachialis", "brachioradialis", "forearms"],
    "cardio": ["cardiovascular"],
    "full_body": ["full_body", "full_body_posterior", "full_body_stability", "full_body_coordination"],
    "stretching": ["stretch_static", "stretch_active", "mobility_dynamic"],
}


def get_exercises_by_muscle(muscle_group: str) -> list[dict[str, Any]]:
    """Получить упражнения по группе мышц."""
    conn = get_db()
    if muscle_group in MUSCLE_GROUP_MAP:
        groups = MUSCLE_GROUP_MAP[muscle_group]
        placeholders = ",".join("?" * len(groups))
        rows = conn.execute(
            f"SELECT * FROM exercises WHERE muscle_group IN ({placeholders}) AND is_custom = 0",
            groups,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM exercises WHERE muscle_group = ? AND is_custom = 0",
            (muscle_group,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_custom_exercises(user_id: int) -> list[dict[str, Any]]:
    """Получить пользовательские упражнения."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM exercises WHERE added_by = ? AND is_custom = 1",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_exercise(
    name: str,
    muscle_group: str,
    ex_type: str,
    equipment: str = "",
    description: str = "",
    is_custom: bool = False,
    added_by: int | None = None
) -> int:
    """Добавить упражнение."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO exercises (name, muscle_group, type, equipment, description, is_custom, added_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (name, muscle_group, ex_type, equipment, description, int(is_custom), added_by),
    )
    conn.commit()
    return cur.lastrowid


def create_session(
    user_id: int,
    session_type: str,
    duration_min: int | None = None,
    intensity: int | None = None,
    notes: str = ""
) -> int:
    """Создать сессию тренировки."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date, notes)
           VALUES (?, ?, ?, ?, date('now'), ?)""",
        (user_id, session_type, duration_min, intensity, notes),
    )
    conn.commit()
    return cur.lastrowid


def add_exercise_to_session(
    session_id: int,
    exercise_id: int | None = None,
    custom_name: str | None = None,
    sort_order: int = 0,
    rest_sec: int = 90,
    notes: str = ""
) -> int:
    """Добавить упражнение в сессию."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO workout_exercises (session_id, exercise_id, custom_exercise_name, sort_order, rest_sec, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, exercise_id, custom_name, sort_order, rest_sec, notes),
    )
    conn.commit()
    return cur.lastrowid


def add_set(
    workout_exercise_id: int,
    set_number: int,
    reps: int,
    weight_kg: float = 0,
    rpe: int | None = None
) -> int:
    """Добавить подход к упражнению."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO workout_sets (workout_exercise_id, set_number, reps, weight_kg, rpe)
           VALUES (?, ?, ?, ?, ?)""",
        (workout_exercise_id, set_number, reps, weight_kg, rpe),
    )
    conn.commit()
    return cur.lastrowid


def generate_daily_workout_plan(
    user_id: int,
    target_date: date | None = None,
    force_refresh: bool = False
) -> dict[str, Any]:
    """Сгенерировать дневной план тренировки."""
    if target_date is None:
        target_date = date.today()
    conn = get_db()
    if not force_refresh:
        plan_row = conn.execute(
            "SELECT * FROM daily_workout_plans WHERE user_id = ? AND date = ?",
            (user_id, target_date.isoformat()),
        ).fetchone()
        if plan_row:
            plan_id = plan_row["id"]
            exercises = conn.execute(
                """SELECT pe.*, e.name, e.muscle_group, e.type, e.equipment
                   FROM plan_exercises pe
                   JOIN exercises e ON e.id = pe.exercise_id
                   WHERE pe.plan_id = ? ORDER BY pe.sort_order""",
                (plan_id,),
            ).fetchall()
            return {
                "plan_id": plan_id,
                "date": target_date.isoformat(),
                "exercises": [dict(e) for e in exercises],
            }
    user = conn.execute("SELECT goal FROM users WHERE user_id = ?", (user_id,)).fetchone()
    goal = user["goal"] if user else "maintain"
    muscle_groups = ["chest", "back", "legs", "shoulders", "core"]
    rng = random.Random(hash(f"{user_id}_{target_date}_{'refresh' if force_refresh else 'init'}") % (10**9))
    plan_exercises: list[dict[str, Any]] = []
    for mg in muscle_groups:
        exercises = get_exercises_by_muscle(mg)
        if not exercises:
            continue
        chosen = rng.sample(exercises, min(2, len(exercises)))
        for ex in chosen:
            sets, reps_min, reps_max = (
                (4, 8, 10) if goal == "gain" else (3, 12, 15) if goal == "lose" else (3, 8, 12)
            )
            plan_exercises.append({
                "exercise_id": ex["id"],
                "name": ex["name"],
                "muscle_group": ex["muscle_group"],
                "sets": sets,
                "reps_min": reps_min,
                "reps_max": reps_max,
                "weight_kg": None,
                "rest_sec": 90,
            })
    conn.execute(
        "DELETE FROM daily_workout_plans WHERE user_id = ? AND date = ?",
        (user_id, target_date.isoformat()),
    )
    conn.execute(
        "INSERT INTO daily_workout_plans (user_id, date, is_active) VALUES (?, ?, 1)",
        (user_id, target_date.isoformat()),
    )
    plan_id = conn.execute(
        "SELECT id FROM daily_workout_plans WHERE user_id = ? AND date = ?",
        (user_id, target_date.isoformat()),
    ).fetchone()["id"]
    conn.execute("DELETE FROM plan_exercises WHERE plan_id = ?", (plan_id,))
    for i, pe in enumerate(plan_exercises):
        conn.execute(
            "INSERT INTO plan_exercises (plan_id, exercise_id, sort_order, sets, reps_min, reps_max, rest_sec) VALUES (?,?,?,?,?,?,?)",
            (plan_id, pe["exercise_id"], i + 1, pe["sets"], pe["reps_min"], pe["reps_max"], pe["rest_sec"]),
        )
    conn.commit()
    return {
        "plan_id": plan_id,
        "date": target_date.isoformat(),
        "exercises": plan_exercises,
    }


def get_daily_plan(user_id: int, target_date: date | None = None) -> dict[str, Any] | None:
    """Получить дневной план."""
    if target_date is None:
        target_date = date.today()
    conn = get_db()
    plan_row = conn.execute(
        "SELECT * FROM daily_workout_plans WHERE user_id = ? AND date = ?",
        (user_id, target_date.isoformat()),
    ).fetchone()
    if not plan_row:
        return None
    plan = dict(plan_row)
    exercises = conn.execute(
        """SELECT pe.*, e.name, e.muscle_group, e.type, e.equipment
           FROM plan_exercises pe
           JOIN exercises e ON e.id = pe.exercise_id
           WHERE pe.plan_id = ?
           ORDER BY pe.sort_order""",
        (plan["id"],),
    ).fetchall()
    plan["exercises"] = [dict(e) for e in exercises]
    return plan


def get_session_history(user_id: int, days: int = 7) -> list[dict[str, Any]]:
    """Получить историю сессий."""
    conn = get_db()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    sessions = conn.execute(
        "SELECT * FROM workout_sessions WHERE user_id = ? AND date >= ? ORDER BY date DESC",
        (user_id, cutoff),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for s in sessions:
        session = dict(s)
        exercises = conn.execute(
            """SELECT we.*, e.name, e.muscle_group
               FROM workout_exercises we
               LEFT JOIN exercises e ON e.id = we.exercise_id
               WHERE we.session_id = ?
               ORDER BY we.sort_order""",
            (s["id"],),
        ).fetchall()
        session["exercises"] = []
        for we in exercises:
            ex = dict(we)
            sets = conn.execute(
                "SELECT * FROM workout_sets WHERE workout_exercise_id = ? ORDER BY set_number",
                (we["id"],),
            ).fetchall()
            ex["sets"] = [dict(st) for st in sets]
            session["exercises"].append(ex)
        result.append(session)
    return result


def get_workout_log(user_id: int, days: int = 7) -> list[dict[str, Any]]:
    """Получить лог тренировок (старая таблица workout_log)."""
    conn = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = conn.execute(
            "SELECT * FROM workout_log WHERE user_id = ? AND performed_at >= ? ORDER BY performed_at DESC",
            (user_id, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_weekly_tonnage(user_id: int) -> float:
    """Получить тоннаж за неделю."""
    conn = get_db()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    row = conn.execute(
        """SELECT COALESCE(SUM(ws.weight_kg * ws.reps), 0)
           FROM workout_sets ws
           JOIN workout_exercises we ON we.id = ws.workout_exercise_id
           JOIN workout_sessions s ON s.id = we.session_id
           WHERE s.user_id = ? AND s.date >= ?""",
        (user_id, week_ago),
    ).fetchone()
    return float(row[0]) if row else 0.0


def get_exercise_history(
    user_id: int,
    exercise_name: str,
    limit: int = 5
) -> list[dict[str, Any]]:
    """Получить историю упражнения."""
    conn = get_db()
    rows = conn.execute(
        """SELECT s.date, we.id as we_id, ws.set_number, ws.reps, ws.weight_kg, ws.rpe
           FROM workout_sessions s
           JOIN workout_exercises we ON we.session_id = s.id
           JOIN workout_sets ws ON ws.workout_exercise_id = we.id
           JOIN exercises e ON e.id = we.exercise_id
           WHERE s.user_id = ? AND e.name = ?
           ORDER BY s.date DESC, we.id, ws.set_number
           LIMIT ?""",
        (user_id, exercise_name, limit * 10),
    ).fetchall()
    sessions: list[dict[str, Any]] = []
    current_date = None
    current_sets: list[dict[str, Any]] = []
    for r in rows:
        if r["date"] != current_date:
            if current_sets:
                sessions.append({"date": current_date, "sets": current_sets})
            current_date = r["date"]
            current_sets = []
        current_sets.append({
            "set": r["set_number"],
            "reps": r["reps"],
            "weight": r["weight_kg"],
            "rpe": r["rpe"],
        })
    if current_sets:
        sessions.append({"date": current_date, "sets": current_sets})
    return sessions[:limit]


def suggest_progression(
    user_id: int,
    exercise_name: str,
    current_weight: float | None = None
) -> str | None:
    """Предложить прогрессию весов."""
    sessions = get_exercise_history(user_id, exercise_name, limit=3)
    if len(sessions) < 2:
        return None
    last_two = sessions[:2]
    ready = True
    for sess in last_two:
        if not all(s["reps"] >= 10 for s in sess["sets"]):
            ready = False
            break
    if not ready:
        return None
    last_weight = max(s["weight"] for s in last_two[0]["sets"]) if last_two[0]["sets"] else 0
    if last_weight <= 0:
        return None
    increase = 2.5 if last_weight < 50 else 5.0
    return f"🔥 Вы уверенно делаете {exercise_name} с весом {last_weight} кг. Попробуйте увеличить до {last_weight + increase} кг!"


def generate_weekly_workout_plan(user_id: int) -> dict[str, Any]:
    """Сгенерировать недельный план."""
    conn = get_db()
    user = conn.execute("SELECT goal FROM users WHERE user_id = ?", (user_id,)).fetchone()
    goal = user["goal"] if user else "maintain"
    if goal == "lose":
        muscle_splits = [
            {"day": "Пн", "focus": "Кардио + Пресс", "groups": ["cardio", "core"]},
            {"day": "Вт", "focus": "Ноги + Кардио", "groups": ["legs", "cardio"]},
            {"day": "Ср", "focus": "Отдых", "groups": []},
            {"day": "Чт", "focus": "Руки + Кардио", "groups": ["arms", "cardio"]},
            {"day": "Пт", "focus": "Спина + Пресс", "groups": ["back", "core"]},
            {"day": "Сб", "focus": "Активный отдых", "groups": ["stretching"]},
            {"day": "Вс", "focus": "Кардио", "groups": ["cardio"]},
        ]
    elif goal == "gain":
        muscle_splits = [
            {"day": "Пн", "focus": "Грудь + Трицепс", "groups": ["chest", "arms"]},
            {"day": "Вт", "focus": "Спина + Бицепс", "groups": ["back", "arms"]},
            {"day": "Ср", "focus": "Отдых", "groups": []},
            {"day": "Чт", "focus": "Ноги + Плечи", "groups": ["legs", "shoulders"]},
            {"day": "Пт", "focus": "Грудь + Спина", "groups": ["chest", "back"]},
            {"day": "Сб", "focus": "Руки + Пресс", "groups": ["arms", "core"]},
            {"day": "Вс", "focus": "Отдых", "groups": []},
        ]
    else:
        muscle_splits = [
            {"day": "Пн", "focus": "Фулбоди", "groups": ["full_body"]},
            {"day": "Вт", "focus": "Кардио + Пресс", "groups": ["cardio", "core"]},
            {"day": "Ср", "focus": "Отдых", "groups": []},
            {"day": "Чт", "focus": "Фулбоди", "groups": ["full_body"]},
            {"day": "Пт", "focus": "Кардио + Растяжка", "groups": ["cardio", "stretching"]},
            {"day": "Сб", "focus": "Активный отдых", "groups": ["stretching"]},
            {"day": "Вс", "focus": "Отдых", "groups": []},
        ]
    days_plan: list[dict[str, Any]] = []
    for split in muscle_splits:
        exercises: list[dict[str, Any]] = []
        for mg in split["groups"]:
            ex_list = get_exercises_by_muscle(mg)
            if ex_list:
                chosen = random.sample(ex_list, min(2, len(ex_list)))
                for ex in chosen:
                    exercises.append({
                        "name": ex["name"],
                        "sets": 3 if goal != "gain" else 4,
                        "reps": "12-15" if goal == "lose" else "8-10" if goal == "gain" else "10-12",
                    })
        days_plan.append({
            "day": split["day"],
            "focus": split["focus"],
            "exercises": exercises,
        })
    return {"goal": goal, "days": days_plan}


def get_tonnage_history(user_id: int, days: int = 30) -> list[dict[str, Any]]:
    """Получить историю тоннажа по дням."""
    conn = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT s.date as day, COALESCE(SUM(ws.weight_kg * ws.reps), 0) as tonnage "
        "FROM workout_sessions s "
        "LEFT JOIN workout_exercises we ON we.session_id = s.id "
        "LEFT JOIN workout_sets ws ON ws.workout_exercise_id = we.id "
        "WHERE s.user_id = ? AND s.date >= ? "
        "GROUP BY day ORDER BY day",
        (user_id, cutoff),
    ).fetchall()
    return [{"day": r["day"], "tonnage": r["tonnage"]} for r in rows]