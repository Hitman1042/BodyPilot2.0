"""«Что съесть?»: остаток КБЖУ и rule-based подбор блюд из food_products."""

import asyncio

import pytest

from core.meal_suggest import (
    get_remaining_today,
    rule_based_suggestions,
    suggest_meals,
    MIN_REMAINING_KCAL,
)
from core.nutrition_calc import get_nutrition_plan

UID = 4242


@pytest.fixture()
def suggest_user(db_conn):
    """Пользователь с заполненным профилем и продуктами в базе."""
    db_conn.execute(
        """INSERT OR REPLACE INTO users
           (user_id, username, gender, age, height_cm, weight_kg, activity, goal)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (UID, "suggestuser", "male", 30, 180, 80, "moderate", "maintain"),
    )
    db_conn.execute("DELETE FROM food_log_new WHERE user_id = ?", (UID,))
    db_conn.commit()

    products = [
        ("ТестКурица", 110, 23, 2, 0),
        ("ТестГречка", 130, 4.5, 1.6, 21),
        ("ТестШоколад", 550, 6, 35, 50),
    ]
    for name, cal, p, f, c in products:
        db_conn.execute(
            """INSERT OR IGNORE INTO food_products
               (name, calories_100g, protein_100g, fat_100g, carbs_100g, source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, cal, p, f, c, "test"),
        )
    db_conn.commit()
    return UID


def test_remaining_without_food(suggest_user):
    remaining = get_remaining_today(suggest_user)
    plan = get_nutrition_plan(suggest_user)
    assert remaining["calories"] == round(plan["target_calories"])
    assert remaining["protein_g"] == pytest.approx(plan["macros"]["protein_g"])
    assert remaining["eaten_calories"] == 0


def test_remaining_after_food(suggest_user):
    from core.nutrition_tracker import add_custom_food_entry, get_today_summary

    add_custom_food_entry(suggest_user, "Тестовая еда", 100, 500, 30, 10, 40, "lunch")
    # Сводка может кэшироваться — чистим кэш дня
    from core.database import get_db
    from datetime import date

    get_db().execute(
        "DELETE FROM daily_nutrition_summary WHERE user_id = ? AND date = ?",
        (suggest_user, date.today().isoformat()),
    )
    get_db().commit()

    assert get_today_summary(suggest_user)["total_calories"] == 500

    remaining = get_remaining_today(suggest_user)
    plan = get_nutrition_plan(suggest_user)
    assert remaining["calories"] == round(plan["target_calories"]) - 500
    assert remaining["protein_g"] == pytest.approx(plan["macros"]["protein_g"] - 30)


def test_rule_based_fits_remaining(suggest_user):
    remaining = get_remaining_today(suggest_user)
    meals = rule_based_suggestions(remaining)

    assert 1 <= len(meals) <= 3
    for meal in meals:
        assert meal["name"]
        assert meal["calories"] <= remaining["calories"]
        assert meal["calories"] > 0
        assert meal["weight_g"] >= 50

    # При дефиците белка белковые продукты идут первыми
    names = [m["name"] for m in meals]
    if "ТестКурица" in names and "ТестШоколад" in names:
        assert names.index("ТестКурица") < names.index("ТестШоколад")


def test_rule_based_exclude(suggest_user):
    remaining = get_remaining_today(suggest_user)
    meals = rule_based_suggestions(remaining, exclude=["ТестКурица"])
    assert all(m["name"] != "ТестКурица" for m in meals)


def test_rule_based_tiny_remaining(suggest_user):
    remaining = {"calories": MIN_REMAINING_KCAL - 1, "protein_g": 10,
                 "fat_g": 5, "carbs_g": 5}
    assert rule_based_suggestions(remaining) == []


def test_suggest_meals_rules_fallback(suggest_user):
    """Без AI (use_ai=False) — подбор правилами из локальной БД."""
    result = asyncio.run(suggest_meals(suggest_user, use_ai=False))
    assert result is not None
    assert result["source"] == "rules"
    assert result["remaining"]["calories"] > 0
    assert 1 <= len(result["suggestions"]) <= 3


def test_suggest_meals_unknown_user():
    assert asyncio.run(suggest_meals(99999999, use_ai=False)) is None
