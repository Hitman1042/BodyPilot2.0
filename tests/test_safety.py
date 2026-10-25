"""Медицинские ограничения: правила, фильтр упражнений и AI-tool."""

import pytest

from core.ai.tools import execute_tool
from core.safety import get_safety_rules, is_exercise_allowed
from core.training_service import generate_daily_workout_plan


def _user(db_conn, user_id: int, age: int = 30) -> int:
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, age) VALUES (?, ?, ?)",
        (user_id, f"safety_{user_id}", age),
    )
    db_conn.execute("UPDATE users SET age = ? WHERE user_id = ?", (age, user_id))
    db_conn.commit()
    return user_id


def _set_condition(db_conn, user_id: int, code: str, active: int = 1) -> None:
    db_conn.execute(
        """INSERT INTO user_health_conditions
           (user_id, condition_code, severity, is_active)
           VALUES (?, ?, 2, ?)
           ON CONFLICT(user_id, condition_code) DO UPDATE SET is_active = excluded.is_active""",
        (user_id, code, active),
    )
    db_conn.commit()


@pytest.fixture(autouse=True)
def safety_exercises(db_conn):
    marker = "Безопасная спокойная ходьба safety 0"
    if db_conn.execute("SELECT 1 FROM exercises WHERE name = ?", (marker,)).fetchone():
        return

    rows = []
    for index in range(4):
        rows.extend([
            (f"Безопасная спокойная ходьба safety {index}", "cardiovascular", "cardio",
             "bodyweight", '{"movement_pattern":"walk","difficulty":1}', "warmup"),
            (f"Мягкая мобилизация safety {index}", "mobility_dynamic", "stretching",
             "bodyweight", '{"movement_pattern":"mobility","difficulty":1}', "mobility"),
            (f"Спокойная растяжка safety {index}", "stretch_static", "stretching",
             "bodyweight", '{"movement_pattern":"static_stretch","difficulty":1}', "cool_down"),
        ])
    for muscle in ("full_body", "legs", "lats", "chest"):
        rows.append((
            f"Безопасное движение safety {muscle}", muscle, "strength", "bodyweight",
            '{"movement_pattern":"hinge","difficulty":3}', "special",
        ))
    rows.extend([
        ("Ягодичный мост safety", "glutes", "strength", "bodyweight",
         '{"movement_pattern":"bridge","difficulty":2}', "accessory"),
        ("Движение руками сидя safety", "biceps", "strength", "bodyweight",
         '{"movement_pattern":"curl","difficulty":2}', "accessory"),
        ("Мягкое движение плечами safety", "front_delt", "strength", "bodyweight",
         '{"movement_pattern":"raise","difficulty":1}', "accessory"),
    ])
    db_conn.executemany(
        """INSERT INTO exercises
           (name, muscle_group, type, equipment, description, category, is_custom)
           VALUES (?, ?, ?, ?, ?, ?, 0)""",
        rows,
    )
    db_conn.commit()


def test_knee_rules(db_conn):
    user_id = _user(db_conn, 9101)
    _set_condition(db_conn, user_id, "knee_pain")

    rules = get_safety_rules(user_id)

    assert "squat" in rules["excluded_patterns"]
    assert "присед" in rules["excluded_patterns"]
    assert rules["load_cap"] == 1.0
    assert rules["condition_names"] == ["Колени"]


def test_age_and_hypertension_rules(db_conn):
    user_id = _user(db_conn, 9102, age=65)
    _set_condition(db_conn, user_id, "hypertension")

    rules = get_safety_rules(user_id)

    assert rules["load_cap"] == 0.9
    assert rules["impact_forbidden"] is True
    assert rules["condition_names"] == ["Гипертония", "Возраст 60+"]


def test_knee_exercise_filter(db_conn):
    user_id = _user(db_conn, 9103)
    _set_condition(db_conn, user_id, "knee_pain")
    rules = get_safety_rules(user_id)

    assert not is_exercise_allowed(
        {"name": "Приседания", "muscle_group": "legs", "pattern": "squat"}, rules
    )
    assert is_exercise_allowed(
        {"name": "Ягодичный мост", "muscle_group": "glutes", "pattern": "bridge"}, rules
    )


def test_senior_impact_filter(db_conn):
    user_id = _user(db_conn, 9104, age=60)
    rules = get_safety_rules(user_id)

    assert not is_exercise_allowed(
        {"name": "Бёрпи", "muscle_group": "full_body", "pattern": "burpee"}, rules
    )


def test_pregnancy_excludes_crunches(db_conn):
    user_id = _user(db_conn, 9105)
    _set_condition(db_conn, user_id, "pregnancy")
    rules = get_safety_rules(user_id)

    assert not is_exercise_allowed(
        {"name": "Скручивания", "muscle_group": "core", "pattern": "crunch"}, rules
    )


def test_set_health_condition_upserts_and_regenerates(db_conn):
    user_id = _user(db_conn, 9106)

    first = execute_tool(user_id, "set_health_condition", {
        "condition_code": "knee_pain", "severity": 2,
    })
    second = execute_tool(user_id, "set_health_condition", {
        "condition_code": "knee_pain", "severity": 3,
    })

    assert first["ok"] is True
    assert "без приседаний и выпадов" in first["summary"]
    assert "не является медицинской рекомендацией" in first["summary"]
    assert "disclaimer" not in second
    assert second["plan_exercises"] > 0
    row = db_conn.execute(
        """SELECT severity, is_active FROM user_health_conditions
           WHERE user_id = ? AND condition_code = 'knee_pain'""",
        (user_id,),
    ).fetchone()
    assert dict(row) == {"severity": 3, "is_active": 1}

    plan = generate_daily_workout_plan(user_id)
    assert plan["exercises"]
    assert all(is_exercise_allowed(exercise, get_safety_rules(user_id))
               for exercise in plan["exercises"])
    assert "щадящий режим: Колени" in plan["note"]

    removed = execute_tool(user_id, "set_health_condition", {
        "condition_code": "knee_pain", "active": False,
    })
    assert removed["ok"] is True
    assert removed["active"] is False
    assert get_safety_rules(user_id)["excluded_patterns"] == set()


def test_set_health_condition_rejects_unknown_code(db_conn):
    user_id = _user(db_conn, 9107)
    result = execute_tool(user_id, "set_health_condition", {"condition_code": "unknown"})
    assert "error" in result


def test_plan_not_empty_under_strict_conditions(db_conn):
    user_id = _user(db_conn, 9108)
    for code in (
        "knee_pain", "lower_back_pain", "shoulder_injury", "wrist_injury",
        "pregnancy", "senior_70",
    ):
        _set_condition(db_conn, user_id, code)

    plan = generate_daily_workout_plan(user_id, force_refresh=True)
    rules = get_safety_rules(user_id)

    assert plan["exercises"]
    assert all(is_exercise_allowed(exercise, rules) for exercise in plan["exercises"])


def test_load_cap_multiplies_adaptation(db_conn):
    user_id = _user(db_conn, 9109, age=65)

    plan = generate_daily_workout_plan(
        user_id, force_refresh=True,
        adaptation={"load_multiplier": 0.9, "note": "мало сна"},
    )

    assert plan["adaptation"]["load_multiplier"] == pytest.approx(0.81)
    assert "мало сна" in plan["adaptation"]["note"]
    assert "щадящий режим: Возраст 60+" in plan["adaptation"]["note"]


def test_health_conditions_in_coach_context(db_conn):
    user_id = _user(db_conn, 9110)
    _set_condition(db_conn, user_id, "diabetes_type2")

    from core.ai.context import build_user_context

    context = build_user_context(user_id)
    assert "Здоровье/ограничения: Диабет 2 типа; возраст: 30 лет" in context
