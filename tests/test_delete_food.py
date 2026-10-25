

def test_delete_food_entry_by_name(test_user):
    from core.ai.tools import execute_tool

    execute_tool(test_user, "log_food", {
        "product_name": "Курица варёная филе", "weight_g": 100,
        "calories": 110, "protein_g": 20, "fat_g": 2, "carbs_g": 0,
        "meal_type": "lunch",
    })
    result = execute_tool(test_user, "delete_food_entry", {"product_name": "курица"})
    assert result["ok"] is True
    assert "Курица варёная филе" in result["summary"]
    assert "110" in result["summary"]


def test_delete_food_entry_latest(test_user):
    from core.ai.tools import execute_tool
    from core.nutrition_tracker import get_food_log_today

    execute_tool(test_user, "log_food", {
        "product_name": "Яблоко", "weight_g": 150,
        "calories": 80, "protein_g": 0.5, "fat_g": 0.3, "carbs_g": 20,
        "meal_type": "snack",
    })
    before = get_food_log_today(test_user)
    result = execute_tool(test_user, "delete_food_entry", {})
    assert result["ok"] is True
    after = get_food_log_today(test_user)
    assert len(after) == len(before) - 1


def test_delete_food_entry_not_found(test_user):
    from core.ai.tools import execute_tool

    result = execute_tool(test_user, "delete_food_entry", {"product_name": "несуществующепродукт"})
    assert "error" in result
