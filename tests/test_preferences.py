"""Предпочтения пользователя: сохранение, влияние на планы, новые AI-tools."""

import pytest

from core.ai.tools import execute_tool
from core.database import get_db
from core.preferences import (
    DEFAULTS,
    describe_preferences,
    get_preferences,
    is_bodyweight_only,
    set_preferences,
)


@pytest.fixture()
def pref_user(db_conn):
    """Отдельный пользователь для тестов предпочтений (user_id=777)."""
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (777, "prefuser"),
    )
    db_conn.commit()
    return 777


@pytest.fixture()
def seeded_exercises(db_conn):
    """Минимальный набор упражнений: bodyweight и штанга в каждом модуле."""
    if db_conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]:
        return
    rows = []
    cats = ["warmup", "mobility", "cool_down"]
    muscles = {
        "warmup": "cardiovascular",
        "mobility": "mobility_dynamic",
        "cool_down": "stretch_static",
    }
    for cat in cats:
        for i in range(4):
            rows.append((f"Разминка своим весом {cat} {i}", muscles[cat], "cardio",
                         "bodyweight", '{"difficulty": 1}', cat))
            rows.append((f"Разминка со штангой {cat} {i}", muscles[cat], "strength",
                         "barbell", '{"difficulty": 2}', cat))
    for mg in ("quads", "lats", "chest"):
        for i in range(3):
            rows.append((f"Присед {mg} {i}", mg, "strength",
                         "bodyweight", '{"difficulty": 4}', "special"))
            rows.append((f"Присед со штангой {mg} {i}", mg, "strength",
                         "barbell", '{"difficulty": 4}', "special"))
            rows.append((f"ОФП {mg} {i}", mg, "strength",
                         "bodyweight", '{"difficulty": 2}', "accessory"))
            rows.append((f"ОФП с гантелями {mg} {i}", mg, "strength",
                         "dumbbell", '{"difficulty": 2}', "accessory"))
    for mg in ("rectus_abdominis", "biceps"):
        rows.append((f"Кор {mg}", mg, "strength", "bodyweight",
                     '{"difficulty": 2}', "accessory"))
        rows.append((f"Кор с гантелей {mg}", mg, "strength", "dumbbell",
                     '{"difficulty": 2}', "accessory"))
    db_conn.executemany(
        """INSERT INTO exercises (name, muscle_group, type, equipment, description, category, is_custom)
           VALUES (?, ?, ?, ?, ?, ?, 0)""",
        rows,
    )
    db_conn.commit()


@pytest.fixture()
def seeded_food(db_conn):
    """Продукты для плана питания: в каждой категории есть «рыба» и альтернатива."""
    if db_conn.execute(
        "SELECT COUNT(*) FROM food_products WHERE name LIKE 'Тест%'"
    ).fetchone()[0]:
        return
    rows = []
    for cat, fish, alt in (
        ("breakfast", "Тест рыба на завтрак", "Тест овсянка"),
        ("lunch", "Тест рыба на обед", "Тест гречка с курицей"),
        ("dinner", "Тест рыба на ужин", "Тест творог"),
        ("snack", "Тест рыба перекус", "Тест яблоко"),
    ):
        for name in (fish, alt):
            rows.append((name, cat, 150, 10.0, 5.0, 15.0))
    db_conn.executemany(
        """INSERT INTO food_products
           (name, category, calories_100g, protein_100g, fat_100g, carbs_100g, source)
           VALUES (?, ?, ?, ?, ?, ?, 'test')""",
        rows,
    )
    db_conn.commit()


# ── core/preferences ─────────────────────────────────────────────────────

def test_get_preferences_defaults(pref_user):
    prefs = get_preferences(pref_user)
    for key, default in DEFAULTS.items():
        assert prefs[key] == default
    assert prefs["updated_at"] is None


def test_set_preferences_upsert(pref_user):
    set_preferences(pref_user, training_place="home", equipment="без инвентаря")
    prefs = get_preferences(pref_user)
    assert prefs["training_place"] == "home"
    assert prefs["equipment"] == "без инвентаря"
    assert prefs["updated_at"]

    set_preferences(pref_user, workouts_per_week=3)
    prefs = get_preferences(pref_user)
    assert prefs["workouts_per_week"] == 3
    assert prefs["training_place"] == "home"  # не сбросилось


def test_is_bodyweight_only():
    assert is_bodyweight_only({"training_place": "home"})
    assert is_bodyweight_only({"training_place": "", "equipment": "без инвентаря"})
    assert is_bodyweight_only({"training_place": "", "equipment": "Своим весом"})
    assert not is_bodyweight_only({"training_place": "gym", "equipment": "штанга"})
    assert not is_bodyweight_only({"training_place": "", "equipment": ""})


def test_describe_preferences():
    prefs = {
        "training_place": "home", "equipment": "без инвентаря",
        "workouts_per_week": 3, "workout_duration_min": 60,
        "food_exclusions": "рыба", "food_notes": "",
    }
    text = describe_preferences(prefs)
    assert "дома" in text and "без инвентаря" in text
    assert "3 раза в неделю" in text and "60 мин" in text
    assert "рыба" in text
    assert describe_preferences(dict(DEFAULTS)) is None


def test_protein_examples_vegan(pref_user, db_conn):
    from core.preferences import protein_examples

    db_conn.execute("UPDATE users SET allergies = '' WHERE user_id = ?", (pref_user,))
    db_conn.commit()
    set_preferences(pref_user, food_exclusions="", food_notes="Я ВЕГАН")

    examples = protein_examples(pref_user)
    assert "курица" not in examples
    assert "яйца" not in examples
    assert "творог" not in examples
    assert "бобовые" in examples and "тофу" in examples


def test_protein_examples_vegetarian_keeps_eggs(pref_user, db_conn):
    from core.preferences import protein_examples

    db_conn.execute("UPDATE users SET allergies = '' WHERE user_id = ?", (pref_user,))
    db_conn.commit()
    set_preferences(pref_user, food_exclusions="", food_notes="вегетарианец")

    examples = protein_examples(pref_user)
    assert "курица" not in examples and "рыба" not in examples
    assert "яйца" in examples and "творог" in examples


def test_protein_examples_peanut_allergy(pref_user, db_conn):
    from core.preferences import protein_examples

    db_conn.execute("UPDATE users SET allergies = 'Арахис' WHERE user_id = ?", (pref_user,))
    db_conn.commit()
    set_preferences(pref_user, food_exclusions="", food_notes="")

    examples = protein_examples(pref_user)
    assert "орехи" not in examples
    assert "курица" in examples


# ── set_training_preferences: валидация и перегенерация плана ────────────

def test_tool_set_training_preferences_invalid_place(pref_user):
    result = execute_tool(pref_user, "set_training_preferences",
                          {"training_place": "mars"})
    assert "error" in result


def test_tool_set_training_preferences_invalid_numbers(pref_user):
    assert "error" in execute_tool(pref_user, "set_training_preferences",
                                   {"workouts_per_week": 9})
    assert "error" in execute_tool(pref_user, "set_training_preferences",
                                   {"workout_duration_min": 5})
    assert "error" in execute_tool(pref_user, "set_training_preferences", {})


def test_tool_set_training_preferences_regenerates_plan(pref_user, seeded_exercises):
    conn = get_db()
    today = __import__("datetime").date.today().isoformat()

    from core.training_service import generate_daily_workout_plan
    plan_before = generate_daily_workout_plan(pref_user, force_refresh=True)
    assert plan_before["exercises"], "план-фикстура пустой — мало упражнений"

    result = execute_tool(pref_user, "set_training_preferences", {
        "training_place": "home",
        "equipment": "без инвентаря",
        "workouts_per_week": 3,
        "workout_duration_min": 45,
    })
    assert result["ok"] is True
    assert "перестроен" in result["summary"]
    assert result["plan_exercises"] > 0

    prefs = get_preferences(pref_user)
    assert prefs["training_place"] == "home"
    assert prefs["workouts_per_week"] == 3
    assert prefs["workout_duration_min"] == 45

    # План в БД перегенерирован и содержит только упражнения без инвентаря
    rows = conn.execute(
        """SELECT e.equipment FROM plan_exercises pe
           JOIN daily_workout_plans dp ON dp.id = pe.plan_id
           JOIN exercises e ON e.id = pe.exercise_id
           WHERE dp.user_id = ? AND dp.date = ?""",
        (pref_user, today),
    ).fetchall()
    assert rows, "план после set_training_preferences не найден в БД"
    equipment_used = {r["equipment"] for r in rows}
    assert "barbell" not in equipment_used
    assert "dumbbell" not in equipment_used


def test_tool_regenerate_workout_plan(pref_user, seeded_exercises):
    result = execute_tool(pref_user, "regenerate_workout_plan", {})
    assert result["ok"] is True
    assert result["plan_exercises"] > 0


# ── set_food_preferences: исключения в плане питания ─────────────────────

def test_tool_set_food_preferences_excludes_product(pref_user, seeded_food):
    result = execute_tool(pref_user, "set_food_preferences",
                          {"food_exclusions": "рыба", "food_notes": "вегетарианец"})
    assert result["ok"] is True
    assert result["meal_plan_regenerated"] is True
    assert "рыба" in result["summary"]

    prefs = get_preferences(pref_user)
    assert prefs["food_exclusions"] == "рыба"
    assert prefs["food_notes"] == "вегетарианец"

    # Перегенерированный план не содержит исключённых продуктов
    from core.database import get_user
    from core.plans import generate_meal_plan

    user = get_user(pref_user)
    plan = generate_meal_plan({**user, "user_id": pref_user}, refresh=True)
    for meal in plan["meals"].values():
        assert "рыба" not in meal["name"].lower()


def test_tool_set_food_preferences_empty(pref_user):
    assert "error" in execute_tool(pref_user, "set_food_preferences", {})


def test_tool_regenerate_meal_plan(pref_user, seeded_food):
    result = execute_tool(pref_user, "regenerate_meal_plan", {})
    assert result["ok"] is True
    assert result["meals"]


# ── Контекст коуча ───────────────────────────────────────────────────────

def test_preferences_in_coach_context(pref_user):
    set_preferences(pref_user, training_place="home", equipment="без инвентаря",
                    food_exclusions="рыба")
    from core.ai.context import build_user_context

    context = build_user_context(pref_user)
    assert "Предпочтения:" in context
    assert "дома" in context and "рыба" in context
