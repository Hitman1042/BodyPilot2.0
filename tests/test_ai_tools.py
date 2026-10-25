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
        "log_food", "log_food_batch", "log_water", "join_challenge", "delete_food_entry", "delete_workout_session",
        "delete_health_metric", "adjust_last_food_entry", "get_today_nutrition",
        "get_nutrition_history", "log_weight", "log_health_metric", "update_profile",
        "get_workout_plan_today", "log_workout_done", "get_weekly_stats",
        "set_training_preferences", "regenerate_workout_plan", "set_health_condition",
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


def test_log_health_metric_yesterday_is_replaced(test_user, db_conn):
    from datetime import datetime, timedelta

    from core.health_data import _local_today

    db_conn.execute("UPDATE users SET timezone_offset = 180 WHERE user_id = ?", (test_user,))
    db_conn.execute("DELETE FROM health_metrics WHERE user_id = ? AND metric_type = 'steps'", (test_user,))
    db_conn.commit()

    execute_tool(test_user, "log_health_metric", {
        "metric_type": "steps", "value": 7000, "date": "yesterday",
    })
    result = execute_tool(test_user, "log_health_metric", {
        "metric_type": "steps", "value": 8400, "date": "yesterday",
    })

    assert result["ok"] is True
    assert result["summary"] == "Обновил шаги за вчера: 8 400"
    yesterday = (_local_today(180) - timedelta(days=1)).isoformat()
    rows = db_conn.execute(
        """SELECT ts, value, source FROM health_metrics
           WHERE user_id = ? AND metric_type = 'steps'
             AND date(ts, '+180 minutes') = ?""",
        (test_user, yesterday),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["value"] == 8400 and rows[0]["source"] == "chat"
    assert datetime.fromisoformat(rows[0]["ts"]).hour == 9  # 12:00 при UTC+3


def test_log_health_metric_sleep_now(test_user):
    result = execute_tool(test_user, "log_health_metric", {
        "metric_type": "sleep_hours", "value": 7.5,
    })
    assert result["ok"] is True
    assert result["summary"] == "Записал сон: 7.5 ч"


@pytest.mark.parametrize("args", [
    {"metric_type": "unknown", "value": 10},
    {"metric_type": "steps", "value": 0},
    {"metric_type": "steps", "value": 100001},
    {"metric_type": "sleep_hours", "value": 0.4},
    {"metric_type": "sleep_hours", "value": 25},
    {"metric_type": "resting_heart_rate", "value": 29},
    {"metric_type": "weight", "value": 401},
    {"metric_type": "steps", "value": 100, "date": "31.12.2025"},
])
def test_log_health_metric_validation(test_user, args):
    assert "error" in execute_tool(test_user, "log_health_metric", args)


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


def test_log_food_batch_valid(test_user):
    """3 валидные позиции → 3 записи, summary содержит сумму ккал."""
    result = execute_tool(test_user, "log_food_batch", {
        "items": [
            {"product_name": "Омлет из двух яиц", "weight_g": 150, "calories": 210,
             "protein_g": 13, "fat_g": 15, "carbs_g": 2, "meal_type": "breakfast"},
            {"product_name": "Гречка с курицей", "weight_g": 300, "calories": 480,
             "protein_g": 35, "fat_g": 12, "carbs_g": 55, "meal_type": "lunch"},
            {"product_name": "Творог 5%", "weight_g": 200, "calories": 240,
             "protein_g": 34, "fat_g": 10, "carbs_g": 6, "meal_type": "dinner"},
        ],
    })
    assert result["ok"] is True
    assert result["logged_count"] == 3
    assert len(result["entry_ids"]) == 3
    assert result["total_calories"] == pytest.approx(930)
    assert "930" in result["summary"]
    assert "Омлет из двух яиц" in result["summary"]

    summary = get_today_summary(test_user)
    assert summary["total_calories"] >= 930
    assert summary["meals_count"] >= 3


def test_log_food_batch_partial_invalid(test_user):
    """Невалидная позиция отклоняется, остальные записываются."""
    before = get_today_summary(test_user)["meals_count"]
    result = execute_tool(test_user, "log_food_batch", {
        "items": [
            {"product_name": "Яблоко", "weight_g": 150, "calories": 80,
             "protein_g": 0.5, "fat_g": 0.5, "carbs_g": 20, "meal_type": "snack"},
            {"product_name": "Битый арбуз", "weight_g": 99999, "calories": 100,
             "protein_g": 1, "fat_g": 0, "carbs_g": 20, "meal_type": "snack"},
        ],
    })
    assert result["ok"] is True
    assert result["logged_count"] == 1
    assert len(result["rejected"]) == 1
    assert "Битый арбуз" in result["rejected"][0]
    assert get_today_summary(test_user)["meals_count"] == before + 1


def test_log_food_batch_too_many(test_user):
    """Больше 10 позиций — отказ целиком."""
    items = [
        {"product_name": f"Блюдо {i}", "weight_g": 100, "calories": 100,
         "protein_g": 5, "fat_g": 5, "carbs_g": 10, "meal_type": "snack"}
        for i in range(11)
    ]
    result = execute_tool(test_user, "log_food_batch", {"items": items})
    assert "error" in result

    assert "error" in execute_tool(test_user, "log_food_batch", {"items": []})
    assert "error" in execute_tool(test_user, "log_food_batch", {})


def test_log_food_batch_all_invalid(test_user):
    """Все позиции невалидны — ошибка, ничего не записано."""
    result = execute_tool(test_user, "log_food_batch", {
        "items": [
            {"product_name": "", "weight_g": 100, "calories": 100,
             "protein_g": 5, "fat_g": 5, "carbs_g": 10, "meal_type": "snack"},
        ],
    })
    assert "error" in result


def test_log_workout_done_valid(test_user, db_conn):
    """Выполненная тренировка создаёт запись в workout_sessions."""
    result = execute_tool(test_user, "log_workout_done", {
        "duration_min": 45,
        "description": "Приседания и отжимания",
        "exercises": ["приседания 3x12", "отжимания 3x15"],
    })
    assert result["ok"] is True
    assert result["session_id"] > 0
    assert "45 мин" in result["summary"]
    assert "Приседания и отжимания" in result["summary"]

    row = db_conn.execute(
        "SELECT * FROM workout_sessions WHERE id = ?", (result["session_id"],)
    ).fetchone()
    assert row is not None
    assert row["user_id"] == test_user
    assert row["duration_min"] == 45
    assert row["type"] == "strength"
    assert "приседания" in row["notes"]


def test_log_workout_done_cardio_synonym(test_user):
    result = execute_tool(test_user, "log_workout_done", {
        "duration_min": 30, "description": "Пробежка 5 км", "workout_type": "бег",
    })
    assert result["ok"] is True
    assert result["workout_type"] == "cardio"


def test_log_workout_done_validation(test_user):
    """duration_min строго 1..600, description обязателен."""
    assert "error" in execute_tool(test_user, "log_workout_done", {
        "duration_min": 0, "description": "Тренировка"})
    assert "error" in execute_tool(test_user, "log_workout_done", {
        "duration_min": 601, "description": "Тренировка"})
    assert "error" in execute_tool(test_user, "log_workout_done", {
        "duration_min": "abc", "description": "Тренировка"})
    assert "error" in execute_tool(test_user, "log_workout_done", {
        "duration_min": 45, "description": ""})
    assert "error" in execute_tool(test_user, "log_workout_done", {
        "duration_min": 45, "description": "Тренировка", "workout_type": "custom"})


def test_voice_day_flow_mock(test_user, monkeypatch):
    """Голос «за день»: транскрипт → chat_with_tools → log_food_batch (мок API).

    Имитирует ответ Gemini: раунд 1 — functionCall log_food_batch со всеми
    блюдами из транскрипта, раунд 2 — текстовое подтверждение. Сеть не нужна.
    """
    import asyncio
    from core.ai.gemini_client import GeminiClient

    client = GeminiClient(api_key="test-key")

    batch_items = [
        {"product_name": "Омлет из двух яиц", "weight_g": 150, "calories": 210,
         "protein_g": 13, "fat_g": 15, "carbs_g": 2, "meal_type": "breakfast"},
        {"product_name": "Гречка с курицей", "weight_g": 300, "calories": 480,
         "protein_g": 35, "fat_g": 12, "carbs_g": 55, "meal_type": "lunch"},
        {"product_name": "Творог", "weight_g": 200, "calories": 240,
         "protein_g": 34, "fat_g": 10, "carbs_g": 6, "meal_type": "dinner"},
    ]
    responses = iter([
        {"candidates": [{"content": {"parts": [
            {"functionCall": {"name": "log_food_batch", "args": {"items": batch_items}}},
        ]}}]},
        {"candidates": [{"content": {"parts": [
            {"text": "Всё записал за день — отличная работа!"},
        ]}}]},
    ])

    async def fake_generate(contents, tool_declarations, system_instruction=None):
        return next(responses)

    monkeypatch.setattr(client, "_generate_with_tools", fake_generate)

    question = ("[Голосовое сообщение, расшифровка]: на завтрак омлет из двух яиц, "
                "на обед гречка с курицей 300 грамм, вечером творог")
    result = asyncio.run(client.chat_with_tools(user_id=test_user, question=question))

    assert result is not None
    assert "Всё записал" in result["text"]
    assert any(u["tool"] == "log_food_batch" for u in result["tools_used"])
    batch_summary = next(u["summary"] for u in result["tools_used"]
                         if u["tool"] == "log_food_batch")
    assert "3 приёмов пищи" in batch_summary
    assert "930" in batch_summary

    summary = get_today_summary(test_user)
    assert summary["total_calories"] >= 930


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
