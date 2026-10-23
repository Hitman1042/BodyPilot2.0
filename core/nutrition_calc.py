"""Калькулятор питания BodyPilot — расчёт БЖУ под вид спорта и цель."""

from math import pow as mpow
from typing import Dict

from .database import get_user
from .sports.catalog import get_user_sport, get_sport_nutrition_norms


def bmi(weight_kg: float, height_cm: float) -> float | None:
    """Calculate Body Mass Index."""
    if height_cm <= 0 or weight_kg <= 0:
        return None
    return round(weight_kg / mpow(height_cm / 100, 2), 1)


def bmi_category(bmi_val: float | None) -> str:
    """Return BMI category string."""
    if bmi_val is None:
        return "unknown"
    if bmi_val < 18.5:
        return "underweight"
    if bmi_val < 25:
        return "normal"
    if bmi_val < 30:
        return "overweight"
    return "obese"


def bmr(weight_kg: float, height_cm: float, age: int, gender: str) -> float:
    """Mifflin-St Jeor BMR formula."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + 5 if gender == "male" else base - 161


def calculate_tdee(user: Dict) -> float:
    """Расчёт TDEE (Total Daily Energy Expenditure)."""
    weight = float(user.get('weight_kg', 70))
    height = float(user.get('height_cm', 170))
    age = int(user.get('age', 30))
    gender = user.get('gender', 'male')
    activity = user.get('activity', 'moderate')

    bmr_val = bmr(weight, height, age, gender)

    activity_multipliers = {
        'sedentary': 1.2, 'light': 1.375, 'moderate': 1.55,
        'active': 1.725, 'very_active': 1.9,
    }

    tdee = bmr_val * activity_multipliers.get(activity, 1.55)
    return round(tdee, 0)


def calculate_target_calories(tdee: float, goal: str) -> float:
    """Расчёт целевых калорий по цели."""
    goal_multipliers = {'lose': 0.85, 'maintain': 1.0, 'gain': 1.10}
    target = tdee * goal_multipliers.get(goal, 1.0)
    return round(target, 0)


def calculate_macros(user_id: int, weight_kg: float, goal: str) -> Dict[str, float]:
    """Расчёт БЖУ под вид спорта и цель."""
    user_sport = get_user_sport(user_id)

    if user_sport and user_sport.get('name_en'):
        sport_name = user_sport['name_en']
        norms = get_sport_nutrition_norms(sport_name, goal)
    else:
        norms = get_sport_nutrition_norms("fitness", goal)

    protein = round(norms['protein'] * weight_kg, 1)
    fat = round(norms['fat'] * weight_kg, 1)
    carbs = round(norms['carbs'] * weight_kg, 1)

    return {"protein_g": protein, "fat_g": fat, "carbs_g": carbs}


def macro_targets(calories: float, weight_kg: float, goal: str) -> dict:
    """Protein/Fat/Carbs in grams."""
    protein_g = round(weight_kg * 2.2 if goal == "gain" else weight_kg * 1.8, 1)
    fat_g = round(weight_kg * 1.0, 1)
    remaining_cal = calories - (protein_g * 4) - (fat_g * 9)
    carbs_g = round(max(remaining_cal / 4, 0), 1)
    return {"protein_g_target": protein_g, "fat_g_target": fat_g, "carbs_g_target": carbs_g}


def compute_profile(weight_kg: float, height_cm: float, age: int,
                   gender: str, activity: str, goal: str) -> dict:
    """Full health profile."""
    bmr_val = round(bmr(weight_kg, height_cm, age, gender))
    tdee_val = round(calculate_tdee({
        'weight_kg': weight_kg, 'height_cm': height_cm, 'age': age,
        'gender': gender, 'activity': activity
    }))
    cal_goal = round(calculate_target_calories(tdee_val, goal))
    macros = calculate_macros(0, weight_kg, goal)
    return {
        "bmi": bmi(weight_kg, height_cm),
        "bmi_category": bmi_category(bmi(weight_kg, height_cm)),
        "bmr": bmr_val,
        "tdee": tdee_val,
        "daily_calorie_goal": cal_goal,
        "protein_g_target": macros["protein_g"],
        "fat_g_target": macros["fat_g"],
        "carbs_g_target": macros["carbs_g"],
    }


def suggest_water_intake(weight_kg: float, activity: str) -> float:
    """Daily water intake in litres."""
    base = weight_kg * 0.033
    extra = {"sedentary": 0, "moderate": 0.5, "high": 1.0}
    return round(base + extra.get(activity, 0), 1)


def get_nutrition_plan(user_id: int) -> Dict:
    """Полный расчёт питания для пользователя."""
    user = get_user(user_id)
    if not user:
        return {}

    weight = float(user.get('weight_kg', 70))
    goal = user.get('goal', 'maintain')

    tdee = calculate_tdee(user)
    target_calories = calculate_target_calories(tdee, goal)
    macros = calculate_macros(user_id, weight, goal)

    calories_from_macros = (macros['protein_g'] * 4 + macros['carbs_g'] * 4 + macros['fat_g'] * 9)

    return {
        "tdee": tdee, "target_calories": target_calories, "macros": macros,
        "calories_from_macros": calories_from_macros, "goal": goal,
        "sport": get_user_sport(user_id),
    }
