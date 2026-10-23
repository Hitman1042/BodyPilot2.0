"""Бизнес-логика тренировок: планы, сессии, прогресс (ВЕРСИЯ С 6 МОДУЛЯМИ)."""

import random
import sqlite3
from datetime import date, timedelta, datetime, timezone
from typing import List, Dict, Optional

from .database import get_db

# Маппинг детальных групп мышц к основным категориям
MUSCLE_GROUP_MAP = {
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


def get_exercises_by_muscle(muscle_group: str, category: str = None,
                            allowed_equipment: tuple = None) -> List[Dict]:
    """Возвращает упражнения по группе мышц с опциональной фильтрацией по категории
    и по инвентарю (allowed_equipment — допустимые значения exercises.equipment)."""
    conn = get_db()

    equip_sql = ""
    equip_params: list = []
    if allowed_equipment is not None:
        placeholders_eq = ",".join("?" * len(allowed_equipment))
        equip_sql = f" AND COALESCE(equipment, '') IN ({placeholders_eq})"
        equip_params = list(allowed_equipment)

    if muscle_group in MUSCLE_GROUP_MAP:
        groups = MUSCLE_GROUP_MAP[muscle_group]
        placeholders = ",".join("?" * len(groups))

        if category:
            rows = conn.execute(
                f"SELECT * FROM exercises WHERE muscle_group IN ({placeholders}) AND category = ? AND is_custom = 0{equip_sql}",
                groups + [category] + equip_params
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM exercises WHERE muscle_group IN ({placeholders}) AND is_custom = 0{equip_sql}",
                groups + equip_params
            ).fetchall()
    else:
        if category:
            rows = conn.execute(
                f"SELECT * FROM exercises WHERE muscle_group = ? AND category = ? AND is_custom = 0{equip_sql}",
                (muscle_group, category) + tuple(equip_params)
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM exercises WHERE muscle_group = ? AND is_custom = 0{equip_sql}",
                (muscle_group,) + tuple(equip_params)
            ).fetchall()

    return [dict(r) for r in rows]


def get_exercises_by_category(category: str, limit: int = None,
                              allowed_equipment: tuple = None) -> List[Dict]:
    """Возвращает упражнения по категории (опционально — только с разрешённым инвентарём)."""
    conn = get_db()
    query = "SELECT * FROM exercises WHERE category = ? AND is_custom = 0"
    params = [category]

    if allowed_equipment is not None:
        placeholders_eq = ",".join("?" * len(allowed_equipment))
        query += f" AND COALESCE(equipment, '') IN ({placeholders_eq})"
        params += list(allowed_equipment)

    query += " ORDER BY RANDOM()"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_custom_exercises(user_id: int) -> List[Dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM exercises WHERE added_by = ? AND is_custom = 1",
        (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_exercise(name: str, muscle_group: str, ex_type: str,
                 equipment: str = "", description: str = "",
                 category: str = "accessory", is_custom: bool = False, added_by: int = None) -> int:
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO exercises (name, muscle_group, type, equipment, description, category, is_custom, added_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, muscle_group, ex_type, equipment, description, category, int(is_custom), added_by)
    )
    conn.commit()
    return cur.lastrowid


def _get_difficulty(exercise: Dict) -> int:
    """Извлекает difficulty из description (JSON)."""
    try:
        import json
        desc = json.loads(exercise.get("description", "{}") or "{}")
        return desc.get("difficulty", 3)
    except (json.JSONDecodeError, TypeError):
        return 3


def _group_by_modules(exercises: List[Dict]) -> Dict[str, List[Dict]]:
    """Группирует упражнения по модулям (категориям)."""
    modules = {"warmup": [], "mobility": [], "special": [], "strength": [], "accessory": [], "cool_down": []}

    for ex in exercises:
        category = ex.get("category", "accessory")
        if category in modules:
            modules[category].append(ex)

    return modules


def generate_daily_workout_plan(user_id: int, target_date: date = None,
                                force_refresh: bool = False,
                                adaptation: Dict = None) -> Dict:
    """
    Генерирует тренировку по спортивной науке с 6 модулями.

    adaptation — результат get_adaptation_factors(); если не передан,
    вычисляется по последнему опросу самочувствия пользователя.
    """
    if target_date is None:
        target_date = date.today()

    if adaptation is None:
        adaptation = get_adaptation_factors(user_id)

    conn = get_db()

    # Предпочтения пользователя (место/инвентарь/длительность)
    from .preferences import get_preferences, is_bodyweight_only, BODYWEIGHT_EQUIPMENT

    prefs = get_preferences(user_id)
    allowed_eq = BODYWEIGHT_EQUIPMENT if is_bodyweight_only(prefs) else None

    def pick_category(category: str, limit: int = 10) -> List[Dict]:
        items = get_exercises_by_category(category, limit=limit, allowed_equipment=allowed_eq)
        if not items and allowed_eq is not None:
            # Фолбэк: без фильтра, чтобы план не остался пустым
            items = get_exercises_by_category(category, limit=limit)
        return items

    def pick_muscle(mg: str, category: str) -> List[Dict]:
        items = get_exercises_by_muscle(mg, category=category, allowed_equipment=allowed_eq)
        if not items and allowed_eq is not None:
            # Та же группа мышц из другого модуля, но всё ещё без инвентаря
            items = get_exercises_by_muscle(mg, allowed_equipment=allowed_eq)
        if not items and allowed_eq is not None:
            # Последний фолбэк: без фильтра, чтобы план не остался пустым
            items = get_exercises_by_muscle(mg, category=category)
        return items

    # Длительность тренировки масштабирует объём (база ~60 мин)
    duration_pref = prefs.get("workout_duration_min") or 0
    scale = max(0.5, min(1.5, duration_pref / 60)) if duration_pref else 1.0
    warmup_n = max(1, round(3 * scale))
    mobility_n = max(1, round(3 * scale))
    special_n = max(1, round(2 * scale))
    strength_n = max(1, round(3 * scale))
    accessory_n = max(1, round(2 * scale))
    cool_down_n = max(1, round(3 * scale))

    # Проверяем кэш
    if not force_refresh:
        plan_row = conn.execute(
            "SELECT * FROM daily_workout_plans WHERE user_id = ? AND date = ?",
            (user_id, target_date.isoformat())
        ).fetchone()

        if plan_row:
            plan_id = plan_row["id"]
            exercises = conn.execute(
                """SELECT pe.*, e.name, e.muscle_group, e.type, e.equipment, e.category
                   FROM plan_exercises pe
                   JOIN exercises e ON e.id = pe.exercise_id
                   WHERE pe.plan_id = ? ORDER BY pe.sort_order""",
                (plan_id,)
            ).fetchall()
            return {"plan_id": plan_id, "date": target_date.isoformat(),
                    "exercises": [dict(e) for e in exercises], "adaptation": adaptation}

    # Получаем профиль пользователя
    user = conn.execute("SELECT goal, activity FROM users WHERE user_id = ?", (user_id,)).fetchone()
    goal = user["goal"] if user else "maintain"

    # Seed для воспроизводимости
    # Уникальный seed для каждого дня + пользователя + времени (чтобы при force_refresh был новый)
    import time
    time_component = int(time.time()) if force_refresh else 0
    seed_str = f"{user_id}_{target_date}_{time_component}"
    rng = random.Random(hash(seed_str) % (10 ** 9))

    # МОДУЛЬ 1: Разминка (кардио)
    warmup_exercises = pick_category("warmup", limit=10)
    warmup_selected = rng.sample(warmup_exercises, min(warmup_n, len(warmup_exercises))) if warmup_exercises else []

    # МОДУЛЬ 2: Мобилизация
    mobility_exercises = pick_category("mobility", limit=10)
    mobility_selected = rng.sample(mobility_exercises, min(mobility_n, len(mobility_exercises))) if mobility_exercises else []

    # МОДУЛЬ 3: Специальная разминка
    special_selected = []
    muscle_groups = ["chest", "back", "legs", "shoulders"]
    rng.shuffle(muscle_groups)

    for mg in muscle_groups[:special_n]:
        exercises = pick_muscle(mg, category="special")
        if exercises:
            easy_exercises = [e for e in exercises if _get_difficulty(e) <= 2]
            if easy_exercises:
                special_selected.append(rng.choice(easy_exercises))
            elif exercises:
                special_selected.append(rng.choice(exercises))

    # МОДУЛЬ 4: Основная сила — 3-4 упражнения
    strength_selected = []
    priority_groups = ["legs", "back", "chest"] if goal == "gain" else ["full_body", "legs", "back"]
    rng.shuffle(priority_groups)

    for mg in priority_groups[:strength_n]:
        exercises = pick_muscle(mg, category="special")
        if exercises:
            hard_exercises = [e for e in exercises if _get_difficulty(e) >= 3]
            if hard_exercises:
                strength_selected.append(rng.choice(hard_exercises))
            elif exercises:
                strength_selected.append(rng.choice(exercises))

    # МОДУЛЬ 5: ОФП — 2-3 упражнения
    accessory_selected = []
    accessory_groups = ["core", "arms", "shoulders"]
    rng.shuffle(accessory_groups)

    for mg in accessory_groups[:accessory_n]:
        exercises = pick_muscle(mg, category="accessory")
        if exercises:
            accessory_selected.append(rng.choice(exercises))

    # МОДУЛЬ 6: Заминка
    cool_down_exercises = pick_category("cool_down", limit=10)
    cool_down_selected = rng.sample(cool_down_exercises,
                                    min(cool_down_n, len(cool_down_exercises))) if cool_down_exercises else []

    # СБОРКА ПЛАНА
    plan_exercises = []
    sort_order = 1

    # Настройки подходов/повторов
    if goal == "gain":
        strength_sets, strength_reps_min, strength_reps_max = 4, 6, 10
        accessory_sets, accessory_reps_min, accessory_reps_max = 3, 10, 15
    elif goal == "lose":
        strength_sets, strength_reps_min, strength_reps_max = 3, 12, 15
        accessory_sets, accessory_reps_min, accessory_reps_max = 3, 15, 20
    else:
        strength_sets, strength_reps_min, strength_reps_max = 3, 8, 12
        accessory_sets, accessory_reps_min, accessory_reps_max = 3, 12, 15

    # Адаптация по опросу самочувствия (rule-based, без AI)
    load_mult = float(adaptation.get("load_multiplier", 1.0))
    rest_bonus = 0
    if load_mult < 1.0:
        # Восстановление: минус подход, меньше повторов, больше отдыха
        strength_sets = max(2, strength_sets - 1)
        accessory_sets = max(2, accessory_sets - 1)
        strength_reps_min = max(1, round(strength_reps_min * load_mult))
        strength_reps_max = max(strength_reps_min, round(strength_reps_max * load_mult))
        accessory_reps_min = max(1, round(accessory_reps_min * load_mult))
        accessory_reps_max = max(accessory_reps_min, round(accessory_reps_max * load_mult))
        rest_bonus = 15
    elif load_mult > 1.0:
        # Прошлая тренировка лёгкая и энергия высокая: прогрессия чуть агрессивнее
        strength_reps_max = round(strength_reps_max * load_mult)
        accessory_reps_max = round(accessory_reps_max * load_mult)

    # Модуль 1: Разминка
    for ex in warmup_selected:
        plan_exercises.append({
            "exercise_id": ex["id"], "name": ex["name"], "muscle_group": ex["muscle_group"],
            "category": "warmup", "sets": 1, "reps_min": 5, "reps_max": 10,
            "duration_min": 2, "weight_kg": None, "rest_sec": 30, "sort_order": sort_order,
        })
        sort_order += 1

    # Модуль 2: Мобилизация
    for ex in mobility_selected:
        plan_exercises.append({
            "exercise_id": ex["id"], "name": ex["name"], "muscle_group": ex["muscle_group"],
            "category": "mobility", "sets": 2, "reps_min": 10, "reps_max": 15,
            "weight_kg": None, "rest_sec": 30, "sort_order": sort_order,
        })
        sort_order += 1

    # Модуль 3: Специальная разминка
    for ex in special_selected:
        plan_exercises.append({
            "exercise_id": ex["id"], "name": ex["name"], "muscle_group": ex["muscle_group"],
            "category": "special", "sets": 2, "reps_min": 8, "reps_max": 12,
            "weight_kg": 0, "rest_sec": 60, "sort_order": sort_order,
        })
        sort_order += 1

    # Модуль 4: Основная сила
    for ex in strength_selected:
        plan_exercises.append({
            "exercise_id": ex["id"], "name": ex["name"], "muscle_group": ex["muscle_group"],
            "category": "strength", "sets": strength_sets, "reps_min": strength_reps_min,
            "reps_max": strength_reps_max, "weight_kg": None, "rest_sec": 90 + rest_bonus, "sort_order": sort_order,
        })
        sort_order += 1

    # Модуль 5: ОФП
    for ex in accessory_selected:
        plan_exercises.append({
            "exercise_id": ex["id"], "name": ex["name"], "muscle_group": ex["muscle_group"],
            "category": "accessory", "sets": accessory_sets, "reps_min": accessory_reps_min,
            "reps_max": accessory_reps_max, "weight_kg": None, "rest_sec": 60 + rest_bonus, "sort_order": sort_order,
        })
        sort_order += 1

    # Модуль 6: Заминка
    for ex in cool_down_selected:
        plan_exercises.append({
            "exercise_id": ex["id"], "name": ex["name"], "muscle_group": ex["muscle_group"],
            "category": "cool_down", "sets": 1, "reps_min": 30, "reps_max": 60,
            "duration_min": 1, "weight_kg": None, "rest_sec": 0, "sort_order": sort_order,
            "note": "Удерживать " + str(rng.randint(30, 60)) + " сек",
        })
        sort_order += 1

    # СОХРАНЕНИЕ В БД
    conn.execute("DELETE FROM daily_workout_plans WHERE user_id = ? AND date = ?", (user_id, target_date.isoformat()))
    conn.execute("INSERT INTO daily_workout_plans (user_id, date, is_active) VALUES (?, ?, 1)",
                 (user_id, target_date.isoformat()))
    plan_id = conn.execute("SELECT id FROM daily_workout_plans WHERE user_id = ? AND date = ?",
                           (user_id, target_date.isoformat())).fetchone()["id"]
    conn.execute("DELETE FROM plan_exercises WHERE plan_id = ?", (plan_id,))

    for i, pe in enumerate(plan_exercises):
        conn.execute(
            """INSERT INTO plan_exercises (plan_id, exercise_id, sort_order, sets, reps_min, reps_max, rest_sec) VALUES (?,?,?,?,?,?,?)""",
            (plan_id, pe["exercise_id"], pe["sort_order"], pe["sets"], pe["reps_min"], pe["reps_max"], pe["rest_sec"])
        )

    conn.commit()

    return {"plan_id": plan_id, "date": target_date.isoformat(), "exercises": plan_exercises,
            "modules": _group_by_modules(plan_exercises), "adaptation": adaptation}


# ── Опрос самочувствия и адаптация нагрузки ──────────────────────────────

def save_workout_feedback(user_id: int, session_id: int = None, difficulty: int = None,
                          soreness: int = None, energy: int = None, comment: str = "") -> int:
    """Сохраняет ответ опроса самочувствия после тренировки (оценки 1–5)."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO workout_feedback (user_id, session_id, feedback_date, difficulty, soreness, energy, comment)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, session_id, date.today().isoformat(), difficulty, soreness, energy, comment)
    )
    conn.commit()
    return cur.lastrowid


def get_last_feedback(user_id: int) -> Optional[Dict]:
    """Последний ответ опроса самочувствия пользователя (или None)."""
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM workout_feedback WHERE user_id = ?
           ORDER BY feedback_date DESC, id DESC LIMIT 1""",
        (user_id,)
    ).fetchone()
    return dict(row) if row else None


def get_adaptation_factors(user_id: int) -> Dict:
    """Правила адаптации следующей тренировки по опросу самочувствия и сну.

    - difficulty >= 4 или soreness >= 4 → снижение нагрузки (~12%) + больше отдыха
    - difficulty <= 2 и soreness <= 2 и energy >= 4 → прогрессия чуть агрессивнее (+8% повторов)
    - сон прошлой ночью < 6 ч → ×0.92; < 5 ч → ×0.85 (перемножается с feedback-правилами)
    - иначе → обычный план
    """
    try:
        fb = get_last_feedback(user_id)
    except sqlite3.OperationalError:
        fb = None  # таблицы ещё нет (старая БД без миграции v13)

    multiplier = 1.0
    notes: List[str] = []

    if fb:
        difficulty = fb.get("difficulty") or 3
        soreness = fb.get("soreness") or 1
        energy = fb.get("energy") or 3

        if difficulty >= 4 or soreness >= 4:
            multiplier *= 0.88
            notes.append("вчера была высокая нагрузка — сегодня легче, восстановление")
        elif difficulty <= 2 and soreness <= 2 and energy >= 4:
            multiplier *= 1.08
            notes.append(
                "прошлая тренировка далась легко, энергия высокая — немного усиливаем прогрессию"
            )

    # Сон прошлой ночью (метрика sleep_hours за локальное сегодня пользователя)
    sleep_hours = None
    try:
        from .health_data import get_today_metrics

        sleep_hours = get_today_metrics(user_id).get("sleep_hours")
    except Exception:
        sleep_hours = None
    if sleep_hours is not None:
        if sleep_hours < 5:
            multiplier *= 0.85
            notes.append("сильный недосып — восстановление важнее")
        elif sleep_hours < 6:
            multiplier *= 0.92
            notes.append("мало сна — сегодня легче")

    return {
        "load_multiplier": round(multiplier, 4),
        "note": "; ".join(notes),
        "feedback": fb,
    }


def get_daily_plan(user_id: int, target_date: date = None) -> Optional[Dict]:
    """Возвращает план на дату с группировкой по модулям."""
    if target_date is None:
        target_date = date.today()

    conn = get_db()
    plan_row = conn.execute(
        "SELECT * FROM daily_workout_plans WHERE user_id = ? AND date = ?",
        (user_id, target_date.isoformat())
    ).fetchone()

    if not plan_row:
        return None

    plan = dict(plan_row)
    exercises = conn.execute(
        """SELECT pe.*, e.name, e.muscle_group, e.type, e.equipment, e.category
           FROM plan_exercises pe
           JOIN exercises e ON e.id = pe.exercise_id
           WHERE pe.plan_id = ? ORDER BY pe.sort_order""",
        (plan["id"],)
    ).fetchall()

    plan["exercises"] = [dict(e) for e in exercises]
    plan["modules"] = _group_by_modules(plan["exercises"])

    return plan


# ── Остальные функции (без изменений) ───────────────────────────────────

def create_session(user_id: int, session_type: str, duration_min: int = None,
                   intensity: int = None, notes: str = "") -> int:
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date, notes)
           VALUES (?, ?, ?, ?, date('now'), ?)""",
        (user_id, session_type, duration_min, intensity, notes)
    )
    conn.commit()
    return cur.lastrowid


def add_exercise_to_session(session_id: int, exercise_id: int = None,
                            custom_name: str = None, sort_order: int = 0,
                            rest_sec: int = 90, notes: str = "") -> int:
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO workout_exercises (session_id, exercise_id, custom_exercise_name, sort_order, rest_sec, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, exercise_id, custom_name, sort_order, rest_sec, notes)
    )
    conn.commit()
    return cur.lastrowid


def add_set(workout_exercise_id: int, set_number: int, reps: int,
            weight_kg: float = 0, rpe: int = None) -> int:
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO workout_sets (workout_exercise_id, set_number, reps, weight_kg, rpe)
           VALUES (?, ?, ?, ?, ?)""",
        (workout_exercise_id, set_number, reps, weight_kg, rpe)
    )
    conn.commit()
    return cur.lastrowid


def get_weekly_tonnage(user_id: int) -> float:
    conn = get_db()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    row = conn.execute(
        """SELECT COALESCE(SUM(ws.weight_kg * ws.reps), 0)
           FROM workout_sets ws
           JOIN workout_exercises we ON we.id = ws.workout_exercise_id
           JOIN workout_sessions s ON s.id = we.session_id
           WHERE s.user_id = ? AND s.date >= ?""",
        (user_id, week_ago)
    ).fetchone()
    return float(row[0]) if row else 0.0


def get_session_history(user_id: int, days: int = 7) -> List[Dict]:
    conn = get_db()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    sessions = conn.execute(
        "SELECT * FROM workout_sessions WHERE user_id = ? AND date >= ? ORDER BY date DESC",
        (user_id, cutoff)
    ).fetchall()
    result = []
    for s in sessions:
        session = dict(s)
        exercises = conn.execute(
            """SELECT we.*, e.name, e.muscle_group
               FROM workout_exercises we
               LEFT JOIN exercises e ON e.id = we.exercise_id
               WHERE we.session_id = ?
               ORDER BY we.sort_order""",
            (s["id"],)
        ).fetchall()
        session["exercises"] = []
        for we in exercises:
            ex = dict(we)
            sets = conn.execute(
                "SELECT * FROM workout_sets WHERE workout_exercise_id = ? ORDER BY set_number",
                (we["id"],)
            ).fetchall()
            ex["sets"] = [dict(st) for st in sets]
            session["exercises"].append(ex)
        result.append(session)
    return result


def get_exercise_history(user_id: int, exercise_name: str, limit: int = 5) -> List[Dict]:
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
        (user_id, exercise_name, limit * 10)
    ).fetchall()
    sessions = []
    current_date = None
    current_sets = []
    for r in rows:
        if r["date"] != current_date:
            if current_sets:
                sessions.append({"date": current_date, "sets": current_sets})
            current_date = r["date"]
            current_sets = []
        current_sets.append({"set": r["set_number"], "reps": r["reps"], "weight": r["weight_kg"], "rpe": r["rpe"]})
    if current_sets:
        sessions.append({"date": current_date, "sets": current_sets})
    return sessions[:limit]


def suggest_progression(user_id: int, exercise_name: str, current_weight: float = None) -> Optional[str]:
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


def generate_weekly_workout_plan(user_id: int) -> Dict:
    """Генерирует недельный план тренировок."""
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

    days_plan = []
    for split in muscle_splits:
        exercises = []
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
        days_plan.append({"day": split["day"], "focus": split["focus"], "exercises": exercises})

    return {"goal": goal, "days": days_plan}