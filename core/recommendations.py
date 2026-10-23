"""Адаптивные рекомендации на основе профиля, питания и тренировок."""

from datetime import date, timedelta
from .database import get_db
from .nutrition_tracker import get_today_calories, get_food_log
from .training_service import get_weekly_tonnage, get_session_history

def adjust_meal_plan(user_id: int, plan: dict) -> dict:
    """Корректирует план питания на основе последних тренировок."""
    conn = get_db()
    # Проверяем, была ли вчера тренировка
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    session = conn.execute(
        "SELECT id FROM workout_sessions WHERE user_id = ? AND date = ?",
        (user_id, yesterday)
    ).fetchone()

    if session:
        # Увеличиваем белок на 10% после тренировки
        plan["macros_target"]["protein_g"] = round(plan["macros_target"]["protein_g"] * 1.1, 1)
        # Углеводы немного уменьшаем, если цель — похудеть
        user = conn.execute("SELECT goal FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user and user["goal"] == "lose":
            plan["macros_target"]["carbs_g"] = round(plan["macros_target"]["carbs_g"] * 0.9, 1)

    # Если сегодня уже много съедено, уменьшаем калории в плане
    today_cals = get_today_calories(user_id)
    if today_cals > 0:
        remaining = plan["calorie_target"] - today_cals
        if remaining < 0:
            remaining = 0
        # Корректируем целевые калории
        plan["calorie_target"] = max(500, remaining)  # не опускаем ниже 500 ккал

    return plan


def adjust_workout_plan(user_id: int, plan: dict) -> dict:
    """Корректирует план тренировок на основе питания и веса."""
    conn = get_db()
    user = conn.execute("SELECT goal, weight_kg FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        return plan

    goal = user["goal"]
    # Проверяем, записывал ли пользователь еду сегодня
    food_today = get_food_log(user_id, days=1)
    if not food_today and goal == "lose":
        # Если цель похудеть и нет еды — меняем силовую на кардио
        if "days" in plan:  # недельный план
            for day in plan["days"]:
                if day["exercises"]:
                    day["exercises"] = [{"name": "Бег на беговой дорожке", "sets": 1, "reps": "30 мин"}]
        elif "exercises" in plan:  # дневной план
            plan["exercises"] = [{"name": "Бег на беговой дорожке", "sets": 1, "reps": "30 мин",
                                  "muscle_group": "cardio", "reps_min": 1, "reps_max": 1, "weight_kg": None, "rest_sec": 0}]

    # Если вчера был высокий тоннаж, добавляем восстановительное упражнение
    tonnage = get_weekly_tonnage(user_id)
    if tonnage > 10000:  # условный порог
        if "exercises" in plan:
            plan["exercises"].append({"name": "Растяжка спины", "sets": 1, "reps": "10 мин",
                                      "muscle_group": "stretching", "reps_min": 1, "reps_max": 1, "weight_kg": None, "rest_sec": 0})

    return plan


def get_daily_insight(user_id: int) -> str:
    """Генерирует персональный совет дня на основе текущей ситуации."""
    conn = get_db()
    user = conn.execute("SELECT goal, weight_kg FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        return ""

    insights = []
    goal = user["goal"]

    # Анализ питания
    food_log = get_food_log(user_id, days=1)
    if not food_log:
        insights.append("Сегодня ещё нет записей о еде. Не забудьте записать приёмы пищи!")

    # Анализ тренировок
    sessions = get_session_history(user_id, days=1)
    if not sessions:
        if goal == "lose":
            insights.append("Вы ещё не тренировались сегодня. Даже короткая прогулка поможет сжигать калории.")
        elif goal == "gain":
            insights.append("Сегодня без тренировки? Мышцы растут во время отдыха — дайте им восстановиться!")

    # Анализ веса (по тренду)
    weight_log = conn.execute(
        "SELECT weight_kg FROM weight_log WHERE user_id = ? ORDER BY logged_at DESC LIMIT 2", (user_id,)
    ).fetchall()
    if len(weight_log) >= 2:
        delta = weight_log[0]["weight_kg"] - weight_log[1]["weight_kg"]
        if goal == "lose" and delta > 0:
            insights.append("Вес немного подрос. Проверьте питание — возможно, стоит уменьшить калории.")
        elif goal == "gain" and delta < 0:
            insights.append("Вес снизился. Добавьте больше белка и углеводов в рацион.")

    return " ".join(insights) if insights else ""