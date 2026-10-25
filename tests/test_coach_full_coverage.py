"""Вода, челленджи и расширенный профиль через AI-инструменты."""

from core.ai.tools import execute_tool
from core.gamification import get_today_water


def test_log_water(test_user):
    result = execute_tool(test_user, "log_water", {"amount_ml": 500})
    assert result["ok"] is True
    assert "500" in result["summary"]
    assert get_today_water(test_user) >= 500


def test_log_water_validation(test_user):
    assert "error" in execute_tool(test_user, "log_water", {"amount_ml": 0})
    assert "error" in execute_tool(test_user, "log_water", {"amount_ml": 99999})


def test_join_challenge(test_user):
    result = execute_tool(test_user, "join_challenge", {"code": "food_30"})
    assert result["ok"] is True
    assert "30 дней дневника" in result["summary"]


def test_join_challenge_unknown(test_user):
    result = execute_tool(test_user, "join_challenge", {"code": "unknown"})
    assert "error" in result


def test_update_profile_allergies(test_user):
    result = execute_tool(test_user, "update_profile", {"field": "allergies", "value": "арахис, рыба"})
    assert result["ok"] is True


def test_update_profile_city(test_user):
    result = execute_tool(test_user, "update_profile", {"field": "city", "value": "Анапа"})
    assert result["ok"] is True


def test_update_profile_preferred_time(test_user):
    result = execute_tool(test_user, "update_profile", {"field": "preferred_time", "value": "07:30"})
    assert result["ok"] is True
    bad = execute_tool(test_user, "update_profile", {"field": "preferred_time", "value": "25:00"})
    assert "error" in bad


def test_update_profile_timezone(test_user):
    result = execute_tool(test_user, "update_profile", {"field": "timezone_offset", "value": 180})
    assert result["ok"] is True
