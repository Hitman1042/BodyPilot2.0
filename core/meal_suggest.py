"""«Что мне съесть?» — подбор блюд под остаток КБЖУ на сегодня.

Два источника вариантов:
1. Правила по локальной БД food_products — быстро и бесплатно, без сети.
2. Один вызов Gemini с контекстом (остаток КБЖУ, аллергии, цель) —
   3 конкретных блюда с КБЖУ. При недоступности AI — фолбэк на правила.
"""

import logging
from typing import Dict, List, Optional

from core.database import get_db, get_user
from core.nutrition_calc import get_nutrition_plan
from core.nutrition_tracker import get_today_summary

logger = logging.getLogger(__name__)

# Порция по умолчанию, если у продукта не задан serving_size_g
DEFAULT_PORTION_G = 250
# Меньше этого остатка калорий предлагать еду бессмысленно
MIN_REMAINING_KCAL = 100
# Порции меньше этого веса не предлагаем
MIN_PORTION_G = 50

GOAL_NAMES = {
    "lose": "похудение",
    "maintain": "поддержание веса",
    "gain": "набор массы",
}


def get_remaining_today(user_id: int) -> Dict:
    """Остаток КБЖУ на сегодня: норма минус съеденное (не ниже нуля)."""
    plan = get_nutrition_plan(user_id) or {}
    macros = plan.get("macros") or {}
    summary = get_today_summary(user_id) or {}

    target_calories = float(plan.get("target_calories") or 2000)
    target_protein = float(macros.get("protein_g") or 150)
    target_fat = float(macros.get("fat_g") or 70)
    target_carbs = float(macros.get("carbs_g") or 250)

    eaten_calories = float(summary.get("total_calories") or 0)
    eaten_protein = float(summary.get("total_protein_g") or 0)
    eaten_fat = float(summary.get("total_fat_g") or 0)
    eaten_carbs = float(summary.get("total_carbs_g") or 0)

    return {
        "calories": round(max(target_calories - eaten_calories, 0)),
        "protein_g": round(max(target_protein - eaten_protein, 0), 1),
        "fat_g": round(max(target_fat - eaten_fat, 0), 1),
        "carbs_g": round(max(target_carbs - eaten_carbs, 0), 1),
        "target_calories": round(target_calories),
        "eaten_calories": round(eaten_calories),
        "eaten_protein_g": round(eaten_protein, 1),
    }


def rule_based_suggestions(
        remaining: Dict,
        exclude: Optional[List[str]] = None,
        limit: int = 3,
) -> List[Dict]:
    """Подбор блюд из локальной БД food_products под остаток калорий/белка.

    Порция ужимается под остаток калорий; при дефиците белка приоритет —
    продуктам с большей белковой плотностью.
    """
    remaining_kcal = float(remaining.get("calories") or 0)
    if remaining_kcal < MIN_REMAINING_KCAL:
        return []

    excluded = {n.strip().lower() for n in (exclude or []) if n}

    rows = get_db().execute(
        """SELECT name, calories_100g, protein_100g, fat_100g, carbs_100g, serving_size_g
           FROM food_products
           WHERE calories_100g > 0
           ORDER BY is_verified DESC, times_used DESC, name
           LIMIT 300"""
    ).fetchall()

    protein_deficit = float(remaining.get("protein_g") or 0) > 0
    candidates = []

    for row in rows:
        name = (row["name"] or "").strip()
        if not name or name.lower() in excluded:
            continue

        cal_100g = float(row["calories_100g"] or 0)
        serving = float(row["serving_size_g"] or 0)
        if not (MIN_PORTION_G <= serving <= 800):
            serving = DEFAULT_PORTION_G

        # Ужимаем порцию под остаток калорий (округление до 10 г)
        max_portion = remaining_kcal * 100.0 / cal_100g
        portion = min(serving, max_portion)
        portion = round(portion / 10) * 10
        if portion < MIN_PORTION_G:
            continue

        factor = portion / 100.0
        protein_g = round(float(row["protein_100g"] or 0) * factor, 1)
        protein_density = (row["protein_100g"] or 0) / cal_100g if cal_100g else 0

        candidates.append({
            "name": name,
            "weight_g": portion,
            "calories": round(cal_100g * factor),
            "protein_g": protein_g,
            "fat_g": round(float(row["fat_100g"] or 0) * factor, 1),
            "carbs_g": round(float(row["carbs_100g"] or 0) * factor, 1),
            "_score": protein_density if protein_deficit else cal_100g / 1000.0,
        })

    candidates.sort(key=lambda c: c["_score"], reverse=True)
    for c in candidates:
        c.pop("_score", None)
    return candidates[:limit]


def _normalize_ai_meal(raw: Dict) -> Optional[Dict]:
    """Привести одно блюдо из ответа Gemini к виду карточки или отбросить."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    try:
        meal = {
            "name": name,
            "weight_g": round(float(raw.get("weight_g") or 0)),
            "calories": round(float(raw.get("calories") or 0)),
            "protein_g": round(float(raw.get("protein_g") or 0), 1),
            "fat_g": round(float(raw.get("fat_g") or 0), 1),
            "carbs_g": round(float(raw.get("carbs_g") or 0), 1),
        }
    except (TypeError, ValueError):
        return None
    if meal["calories"] <= 0 or meal["weight_g"] <= 0:
        return None
    return meal


async def ai_suggestions(
        user_id: int,
        remaining: Dict,
        user: Dict,
        exclude: Optional[List[str]] = None,
) -> Optional[List[Dict]]:
    """Один вызов Gemini: 3 конкретных блюда под остаток КБЖУ. None при недоступности."""
    from core.ai.gemini_client import get_gemini_client

    client = get_gemini_client()
    if not client:
        return None

    allergies = (user.get("allergies") or "").strip() or "нет"
    goal = GOAL_NAMES.get(user.get("goal"), user.get("goal") or "не указана")
    exclude_text = ""
    if exclude:
        exclude_text = f"\nНЕ предлагай эти блюда (уже показывал): {', '.join(exclude[:10])}."

    prompt = f"""
Ты — AI-нутрициолог BodyPilot. Пользователь спрашивает: «Что мне съесть?»

ОСТАТОК НА СЕГОДНЯ (норма минус съеденное):
- Калории: {remaining.get('calories', 0)} ккал
- Белок: {remaining.get('protein_g', 0)} г
- Жиры: {remaining.get('fat_g', 0)} г
- Углеводы: {remaining.get('carbs_g', 0)} г

ЦЕЛЬ ПОЛЬЗОВАТЕЛЯ: {goal}
АЛЛЕРГИИ/ОГРАНИЧЕНИЯ: {allergies}
{exclude_text}

ЗАДАЧА: предложи 3 конкретных реальных блюда (не продукты по одному, а блюда/сочетания),
каждое из которых вписывается в остаток калорий одного приёма пищи.
Учитывай аллергии и цель. КБЖУ укажи на ВСЮ предложенную порцию.

ВЕРНИ ТОЛЬКО JSON:
{{
    "meals": [
        {{
            "name": "название блюда на русском",
            "weight_g": число (вес порции в граммах),
            "calories": число (ккал на всю порцию),
            "protein_g": число,
            "fat_g": число,
            "carbs_g": число
        }},
        ...
    ]
}}
"""

    try:
        result = await client._request(prompt, json_mode=True)
    except Exception as e:
        logger.warning("meal_suggest AI error: %s", e)
        return None

    if not result or "error" in result:
        return None

    raw_meals = result.get("meals")
    if not isinstance(raw_meals, list):
        return None

    meals = []
    for raw in raw_meals:
        meal = _normalize_ai_meal(raw)
        if meal:
            meals.append(meal)
        if len(meals) >= 3:
            break

    return meals or None


async def suggest_meals(
        user_id: int,
        exclude: Optional[List[str]] = None,
        use_ai: bool = True,
) -> Optional[Dict]:
    """Подобрать 3 варианта блюд под остаток дня.

    Сначала пробует AI (один вызов), при недоступности — правила по локальной БД.
    None — пользователь не зарегистрирован.
    """
    user = get_user(user_id)
    if not user:
        return None

    remaining = get_remaining_today(user_id)

    if use_ai:
        meals = await ai_suggestions(user_id, remaining, user, exclude=exclude)
        if meals:
            return {"remaining": remaining, "suggestions": meals, "source": "ai"}

    meals = rule_based_suggestions(remaining, exclude=exclude)
    return {"remaining": remaining, "suggestions": meals, "source": "rules"}
