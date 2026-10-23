"""AI-инструменты (function calling): execute_tool на временной БД, без сети."""

import pytest

from core.ai.tools import execute_tool, TOOL_DECLARATIONS
from core.database import get_user
from core.nutrition_tracker import get_today_summary


def test_tool_declarations_valid():
    """Все декларации имеют имя, описание и параметры-объект."""
    names = set()
    for decl in TOOL_DECLARATIONS:
        assert decl["name"] not in names
        names.add(decl["name"])
        assert decl["description"]
        assert decl["parameters"]["type"] == "object"
    assert names == {
        "log_food", "adjust_last_food_entry", "get_today_nutrition",
        "get_nutrition_history", "log_weight", "update_profile",
        "get_workout_plan_today", "get_weekly_stats",
        "set_training_preferences", "regenerate_workout_plan",
        "set_food_preferences", "regenerate_meal_plan",
    }


def test_log_food_valid(test_user):
    result = execute_tool(test_user, "log_food", {
        "product_name": "Гречка с курицей",
        "weight_g": 200,
        "calories": 220,
        "protein_g": 18,
        "fat_g": 6,
        "carbs_g": 28,
        "meal_type": "lunch",
    })
    assert result["ok"] is True
    assert result["entry_id"] > 0
    assert "Гречка с курицей" in result["summary"]

    summary = get_today_summary(test_user)
    assert summary["total_calories"] >= 220
    assert summary["meals_count"] >= 1


def test_log_food_invalid_weight(test_user):
    result = execute_tool(test_user, "log_food", {
        "product_name": "Арбуз", "weight_g": 6000, "calories": 100,
        "protein_g": 1, "fat_g": 0, "carbs_g": 20, "meal_type": "snack",
    })
    assert "error" in result


def test_log_food_invalid_meal_type(test_user):
    result = execute_tool(test_user, "log_food", {
        "product_name": "Суп", "weight_g": 300, "calories": 150,
        "protein_g": 5, "fat_g": 3, "carbs_g": 20, "meal_type": "brunch",
    })
    assert "error" in result


def test_update_profile_forbidden_field(test_user):
    result = execute_tool(test_user, "update_profile", {
        "field": "is_premium", "value": "1",
    })
    assert "error" in result


def test_update_profile_goal_synonym(test_user):
    result = execute_tool(test_user, "update_profile", {
        "field": "goal", "value": "похудение",
    })
    assert result["ok"] is True
    assert result["value"] == "lose"
    assert get_user(test_user)["goal"] == "lose"


def test_update_profile_invalid_goal(test_user):
    result = execute_tool(test_user, "update_profile", {
        "field": "goal", "value": "стать космонавтом",
    })
    assert "error" in result


def test_log_weight_negative(test_user):
    result = execute_tool(test_user, "log_weight", {"weight_kg": -5})
    assert "error" in result


def test_log_weight_valid(test_user):
    result = execute_tool(test_user, "log_weight", {"weight_kg": 82.5})
    assert result["ok"] is True
    assert get_user(test_user)["weight_kg"] == 82.5


def test_get_today_nutrition(test_user):
    result = execute_tool(test_user, "get_today_nutrition", {})
    assert result["ok"] is True
    assert "eaten" in result and "targets" in result
    assert result["eaten"]["calories"] >= 220


def test_get_nutrition_history_days_limit(test_user):
    assert "error" in execute_tool(test_user, "get_nutrition_history", {"days": 99})
    result = execute_tool(test_user, "get_nutrition_history", {"days": 7})
    assert result["ok"] is True
    assert isinstance(result["history"], list)


def test_get_workout_plan_today(test_user):
    result = execute_tool(test_user, "get_workout_plan_today", {})
    assert result["ok"] is True


def test_get_weekly_stats(test_user):
    result = execute_tool(test_user, "get_weekly_stats", {})
    assert result["ok"] is True
    assert "total_calories" in result["stats"]


def test_unknown_tool(test_user):
    result = execute_tool(test_user, "delete_everything", {})
    assert "error" in result


def test_adjust_last_food_entry_multiplier(test_user):
    """multiplier ×2 пересчитывает вес и КБЖУ последней записи за сегодня."""
    logged = execute_tool(test_user, "log_food", {
        "product_name": "Десерт творожный", "weight_g": 70, "calories": 245,
        "protein_g": 8, "fat_g": 12, "carbs_g": 26, "meal_type": "snack",
    })
    assert logged["ok"] is True

    result = execute_tool(test_user, "adjust_last_food_entry", {"multiplier": 2.0})
    assert result["ok"] is True
    assert result["entry_id"] == logged["entry_id"]
    assert result["weight_g"] == pytest.approx(140)
    assert result["calories"] == pytest.approx(490)
    assert result["protein_g"] == pytest.approx(16)
    assert "Десерт творожный" in result["summary"]


def test_adjust_last_food_entry_new_weight(test_user):
    """new_weight_g задаёт новый вес, КБЖУ пересчитываются пропорционально."""
    execute_tool(test_user, "log_food", {
        "product_name": "Овсянка", "weight_g": 200, "calories": 300,
        "protein_g": 10, "fat_g": 6, "carbs_g": 50, "meal_type": "breakfast",
    })

    result = execute_tool(test_user, "adjust_last_food_entry", {"new_weight_g": 300})
    assert result["ok"] is True
    assert result["weight_g"] == pytest.approx(300)
    assert result["calories"] == pytest.approx(450)


def test_adjust_last_food_entry_validation(test_user):
    """Валидация: multiplier вне 0.1..10 и new_weight_g вне 1..5000 отклоняются."""
    execute_tool(test_user, "log_food", {
        "product_name": "Яблоко", "weight_g": 150, "calories": 80,
        "protein_g": 0.5, "fat_g": 0.5, "carbs_g": 20, "meal_type": "snack",
    })

    assert "error" in execute_tool(test_user, "adjust_last_food_entry", {"multiplier": 99})
    assert "error" in execute_tool(test_user, "adjust_last_food_entry", {"multiplier": 0.01})
    assert "error" in execute_tool(test_user, "adjust_last_food_entry", {"new_weight_g": 6000})
    assert "error" in execute_tool(test_user, "adjust_last_food_entry", {})


def test_food_intent_markers():
    """Детектор маркеров еды (без сети): «съел яблоко» → chat path, «погода» → обычный путь."""
    from core.ai.text_markers import has_food_intent

    assert has_food_intent("я съел яблоко")
    assert has_food_intent("выпил латте")
    assert has_food_intent("перекусил орехами")
    assert has_food_intent("поел гречку")
    assert has_food_intent("это было на завтрак")
    assert not has_food_intent("погода завтра")
    assert not has_food_intent("сколько белка мне нужно?")
    assert not has_food_intent("")
