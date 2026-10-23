"""Расчёты КБЖУ: BMR/BMI/TDEE, целевые калории, макросы."""

import pytest

from core.nutrition_calc import (
    bmi,
    bmi_category,
    bmr,
    calculate_macros,
    calculate_target_calories,
    calculate_tdee,
    suggest_water_intake,
)

MALE_80KG = {"weight_kg": 80, "height_cm": 180, "age": 30, "gender": "male"}


def test_bmr_mifflin_male():
    # 10*80 + 6.25*180 - 5*30 + 5 = 1780
    assert bmr(80, 180, 30, "male") == 1780


def test_bmr_mifflin_female():
    # 10*60 + 6.25*165 - 5*25 - 161 = 1345.25
    assert bmr(60, 165, 25, "female") == pytest.approx(1345.25)


def test_bmi():
    assert bmi(80, 180) == pytest.approx(24.7)
    assert bmi(0, 180) is None
    assert bmi_category(24.7) == "normal"
    assert bmi_category(None) == "unknown"


def test_tdee_moderate():
    tdee = calculate_tdee({**MALE_80KG, "activity": "moderate"})
    assert tdee == pytest.approx(1780 * 1.55)


def test_tdee_activity_levels():
    sedentary = calculate_tdee({**MALE_80KG, "activity": "sedentary"})
    active = calculate_tdee({**MALE_80KG, "activity": "very_active"})
    assert sedentary < active


def test_target_calories_by_goal():
    tdee = 2759.0
    assert calculate_target_calories(tdee, "lose") == pytest.approx(tdee * 0.85, abs=1)
    assert calculate_target_calories(tdee, "maintain") == tdee
    assert calculate_target_calories(tdee, "gain") == pytest.approx(tdee * 1.10, abs=1)


def test_calculate_macros_consistent(test_user):
    macros = calculate_macros(test_user, 80, "gain")
    assert macros["protein_g"] > 0
    assert macros["fat_g"] > 0
    assert macros["carbs_g"] > 0
    # 4/9/4 ккал на грамм — суммарная энергия должна быть положительной
    kcal = macros["protein_g"] * 4 + macros["fat_g"] * 9 + macros["carbs_g"] * 4
    assert kcal > 1000


def test_water_intake():
    low = suggest_water_intake(80, "sedentary")
    high = suggest_water_intake(80, "high")
    assert low > 0
    assert high >= low
