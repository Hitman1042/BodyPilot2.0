"""Генераторы планов питания и тренировок для Premium (исправленный расчёт порций)."""

import random
import re
from datetime import date
from .nutrition_tracker import get_products_by_category, increment_product_usage
from .nutrition_calc import compute_profile


def _get_food_exclusions(profile: dict) -> list:
    """Термины-исключения: нелюбимые продукты из user_preferences + аллергии из профиля."""
    raw_parts = [profile.get("allergies") or ""]
    user_id = profile.get("user_id")
    if user_id:
        try:
            from .preferences import get_preferences

            prefs = get_preferences(user_id)
            raw_parts.append(prefs.get("food_exclusions") or "")
        except Exception:
            pass
    terms = []
    for part in raw_parts:
        for term in re.split(r"[,;]", part):
            term = term.strip().lower()
            if term:
                terms.append(term)
    return terms


def _filter_excluded(meals: list, exclusions: list) -> list:
    """Убрать блюда, в названии/бренде которых встречается исключённый термин.

    Если после фильтра ничего не осталось — вернуть исходный список
    (лучше план с исключением, чем пустой).
    """
    if not exclusions or not meals:
        return meals
    filtered = [
        m for m in meals
        if not any(
            term in (m.get("name") or "").lower()
            or term in (m.get("brand") or "").lower()
            for term in exclusions
        )
    ]
    return filtered or meals


def generate_meal_plan(profile: dict, refresh: bool = False) -> dict:
    """Создаёт дневной план питания с подбором реалистичных порций.
    
    Использует случайный seed на основе дня и ID пользователя для ротации блюд.
    Если refresh=True, seed сбрасывается и план всегда новый.
    Также увеличивает счётчик использования выбранных продуктов (крауд-верификация).
    Исключает блюда из food_exclusions (user_preferences) и allergies (профиль).
    В конце адаптирует макросы под последние тренировки.
    """
    metrics = compute_profile(
        weight_kg=float(profile["weight_kg"]),
        height_cm=float(profile["height_cm"]),
        age=int(profile["age"]),
        gender=profile["gender"],
        activity=profile["activity"],
        goal=profile["goal"],
    )
    cal_goal = metrics["daily_calorie_goal"]
    protein_target = metrics["protein_g_target"]
    fat_target = metrics["fat_g_target"]
    carbs_target = metrics["carbs_g_target"]
    goal = profile.get("goal", "maintain")

    # Ротация
    if refresh:
        random.seed()
    else:
        seed_value = profile.get("user_id", 0) + date.today().toordinal()
        random.seed(seed_value)

    target_ratios = {
        "breakfast": 0.25,
        "lunch": 0.35,
        "dinner": 0.25,
        "snack": 0.15,
    }
    min_cal_per_category = {
        "breakfast": 200,
        "lunch": 300,
        "dinner": 250,
        "snack": 80,
    }

    def select_best_meal(meals, target_cal, min_cal):
        if not meals:
            return None, 0, target_cal

        candidates = [m for m in meals if m["calories_100g"] >= 30]
        if not candidates:
            candidates = meals

        random.shuffle(candidates)

        best = None
        best_weight = 100
        best_diff = float("inf")

        for m in candidates:
            if m["calories_100g"] > 0:
                ideal_weight = (target_cal / m["calories_100g"]) * 100
                ideal_weight = max(50, min(500, ideal_weight))
                actual_cal = (ideal_weight / 100) * m["calories_100g"]
                diff = abs(actual_cal - target_cal)
                if diff < best_diff:
                    best_diff = diff
                    best = m
                    best_weight = ideal_weight
            else:
                continue

        if not best:
            return {
                "name": "Сбалансированное блюдо",
                "calories_100g": target_cal,
                "protein_100g": 10,
                "fat_100g": 5,
                "carbs_100g": 20,
            }, 100, target_cal

        return best, best_weight, (best_weight / 100) * best["calories_100g"]

    selected_meals = {}
    total_cal = 0
    total_p = 0
    total_f = 0
    total_c = 0

    exclusions = _get_food_exclusions(profile)

    for cat_name in ["breakfast", "lunch", "dinner", "snack"]:
        meals = get_products_by_category(cat_name, verified_only=False)
        meals = _filter_excluded(meals, exclusions)
        target_cal = cal_goal * target_ratios[cat_name]
        min_cal = min_cal_per_category.get(cat_name, 100)

        best, weight, actual_cal = select_best_meal(meals, target_cal, min_cal)

        if best:
            if best.get("id") is not None:
                increment_product_usage(best["id"])

            factor = weight / 100
            protein = best["protein_100g"] * factor
            fat = best["fat_100g"] * factor
            carbs = best["carbs_100g"] * factor

            selected_meals[cat_name] = {
                "name": f"{best['name']} ({int(weight)} г)",
                "cal": int(actual_cal),
                "p": round(protein, 1),
                "f": round(fat, 1),
                "c": round(carbs, 1),
            }
            total_cal += actual_cal
            total_p += protein
            total_f += fat
            total_c += carbs
        else:
            selected_meals[cat_name] = {
                "name": "Неизвестное блюдо",
                "cal": int(target_cal),
                "p": 10,
                "f": 5,
                "c": 20,
            }
            total_cal += target_cal

    # Собираем план
    plan = {
        "calorie_target": cal_goal,
        "macros_target": {
            "protein_g": protein_target,
            "fat_g": fat_target,
            "carbs_g": carbs_target,
        },
        "meals": selected_meals,
        "total": {
            "calories": int(total_cal),
            "protein_g": round(total_p, 1),
            "fat_g": round(total_f, 1),
            "carbs_g": round(total_c, 1),
        },
    }

    # Адаптация под тренировки
    from .recommendations import adjust_meal_plan
    return adjust_meal_plan(profile.get("user_id", 0), plan)

def generate_workout_plan(profile: dict) -> dict:
    goal = profile.get("goal", "maintain")

    if goal == "lose":
        days = [
            {"day": "Пн", "focus": "Кардио + Пресс", "exercises": [
                {"name": "Бег или ходьба", "sets": 1, "reps": "30 мин"},
                {"name": "Скручивания", "sets": 3, "reps": "20"},
                {"name": "Планка", "sets": 3, "reps": "45 сек"},
            ]},
            {"day": "Вт", "focus": "Ноги + Кардио", "exercises": [
                {"name": "Приседания", "sets": 3, "reps": "15"},
                {"name": "Выпады", "sets": 3, "reps": "12 на ногу"},
                {"name": "Велотренажёр", "sets": 1, "reps": "20 мин"},
            ]},
            {"day": "Ср", "focus": "Отдых", "exercises": []},
            {"day": "Чт", "focus": "Руки + Кардио", "exercises": [
                {"name": "Отжимания", "sets": 3, "reps": "12"},
                {"name": "Обратные отжимания", "sets": 3, "reps": "10"},
                {"name": "Скакалка", "sets": 1, "reps": "15 мин"},
            ]},
            {"day": "Пт", "focus": "Спина + Пресс", "exercises": [
                {"name": "Тяга гантели в наклоне", "sets": 3, "reps": "12"},
                {"name": "Гиперэкстензия", "sets": 3, "reps": "15"},
                {"name": "Боковая планка", "sets": 2, "reps": "30 сек"},
            ]},
            {"day": "Сб", "focus": "Активный отдых", "exercises": [
                {"name": "Прогулка", "sets": 1, "reps": "60 мин"},
            ]},
            {"day": "Вс", "focus": "Кардио", "exercises": [
                {"name": "Бег", "sets": 1, "reps": "40 мин"},
            ]},
        ]
    elif goal == "gain":
        days = [
            {"day": "Пн", "focus": "Грудь + Трицепс", "exercises": [
                {"name": "Жим штанги лёжа", "sets": 4, "reps": "8-10"},
                {"name": "Жим гантелей на наклонной", "sets": 3, "reps": "10"},
                {"name": "Французский жим", "sets": 3, "reps": "10"},
            ]},
            {"day": "Вт", "focus": "Спина + Бицепс", "exercises": [
                {"name": "Подтягивания", "sets": 4, "reps": "8-10"},
                {"name": "Тяга штанги в наклоне", "sets": 3, "reps": "10"},
                {"name": "Подъём штанги на бицепс", "sets": 3, "reps": "10"},
            ]},
            {"day": "Ср", "focus": "Отдых", "exercises": []},
            {"day": "Чт", "focus": "Ноги + Плечи", "exercises": [
                {"name": "Приседания со штангой", "sets": 4, "reps": "8-10"},
                {"name": "Жим ногами", "sets": 3, "reps": "10"},
                {"name": "Армейский жим", "sets": 3, "reps": "10"},
            ]},
            {"day": "Пт", "focus": "Грудь + Спина", "exercises": [
                {"name": "Жим гантелей лёжа", "sets": 3, "reps": "10-12"},
                {"name": "Тяга верхнего блока", "sets": 3, "reps": "10"},
                {"name": "Разведение гантелей", "sets": 3, "reps": "12"},
            ]},
            {"day": "Сб", "focus": "Руки + Пресс", "exercises": [
                {"name": "Подъём гантелей на бицепс", "sets": 3, "reps": "12"},
                {"name": "Отжимания на брусьях", "sets": 3, "reps": "10"},
                {"name": "Скручивания", "sets": 4, "reps": "15"},
            ]},
            {"day": "Вс", "focus": "Отдых", "exercises": []},
        ]
    else:  # maintain
        days = [
            {"day": "Пн", "focus": "Фулбоди", "exercises": [
                {"name": "Приседания", "sets": 3, "reps": "12"},
                {"name": "Жим гантелей лёжа", "sets": 3, "reps": "10"},
                {"name": "Тяга гантели в наклоне", "sets": 3, "reps": "12"},
            ]},
            {"day": "Вт", "focus": "Кардио + Пресс", "exercises": [
                {"name": "Бег", "sets": 1, "reps": "30 мин"},
                {"name": "Планка", "sets": 3, "reps": "45 сек"},
                {"name": "Скручивания", "sets": 3, "reps": "20"},
            ]},
            {"day": "Ср", "focus": "Отдых", "exercises": []},
            {"day": "Чт", "focus": "Фулбоди", "exercises": [
                {"name": "Становая тяга", "sets": 3, "reps": "10"},
                {"name": "Отжимания", "sets": 3, "reps": "15"},
                {"name": "Выпады", "sets": 3, "reps": "12 на ногу"},
            ]},
            {"day": "Пт", "focus": "Кардио + Растяжка", "exercises": [
                {"name": "Велотренажёр", "sets": 1, "reps": "30 мин"},
                {"name": "Растяжка", "sets": 1, "reps": "15 мин"},
            ]},
            {"day": "Сб", "focus": "Активный отдых", "exercises": [
                {"name": "Прогулка", "sets": 1, "reps": "60 мин"},
            ]},
            {"day": "Вс", "focus": "Отдых", "exercises": []},
        ]

    return {"goal": goal, "days": days}
