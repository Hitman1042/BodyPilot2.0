"""Контекст пользователя для AI-коуча (system_instruction в chat_with_tools).

build_user_context(user_id) собирает блок «ПРОФИЛЬ И СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЯ»
из локальной БД: профиль, нормы КБЖУ, съедено сегодня, тренировка, стрик,
Premium. Каждый источник обёрнут в try/except — частичный сбой не роняет
сборку, недостающие строки просто пропускаются. None — пользователь не
зарегистрирован (коуч должен предложить /register).
"""

from typing import Optional

GOAL_NAMES = {
    "lose": "похудение",
    "maintain": "поддержание веса",
    "gain": "набор массы",
}
ACTIVITY_NAMES = {
    "sedentary": "низкая (сидячий образ жизни)",
    "moderate": "средняя",
    "high": "высокая",
}
GENDER_NAMES = {"male": "мужской", "female": "женский"}
SPORT_LEVEL_NAMES = {
    "beginner": "новичок",
    "intermediate": "средний",
    "advanced": "продвинутый",
}


def build_user_context(user_id: int) -> Optional[str]:
    """Текстовый блок с актуальными данными пользователя или None."""
    from core.database import get_user

    try:
        user = get_user(user_id)
    except Exception:
        user = None
    if not user:
        return None

    lines = [
        "ПРОФИЛЬ И СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЯ "
        "(актуальные данные из бота — уже известны, НЕ переспрашивай):"
    ]

    # ── Профиль ────────────────────────────────────────────────
    try:
        gender = GENDER_NAMES.get(user.get("gender"), "не указан")
        parts = [
            f"имя: {user.get('username') or 'не указано'}",
            f"пол: {gender}",
            f"возраст: {user.get('age') or '?'} лет",
        ]
        height = user.get("height_cm")
        weight = user.get("weight_kg")
        if height:
            parts.append(f"рост: {height:g} см")
        if weight:
            parts.append(f"вес: {weight:g} кг")
        if height and weight:
            try:
                from core.nutrition_calc import bmi

                bmi_val = bmi(float(weight), float(height))
                if bmi_val:
                    parts.append(f"BMI: {bmi_val}")
            except Exception:
                pass
        if user.get("city"):
            parts.append(f"город: {user['city']}")
        lines.append("- Профиль: " + ", ".join(parts))
    except Exception:
        pass

    # ── Цель и активность ──────────────────────────────────────
    try:
        goal = GOAL_NAMES.get(user.get("goal"), user.get("goal") or "не указана")
        activity = ACTIVITY_NAMES.get(
            user.get("activity"), user.get("activity") or "не указана"
        )
        lines.append(f"- Цель: {goal}; активность: {activity}")
    except Exception:
        pass

    # ── Вид спорта и уровень ───────────────────────────────────
    try:
        from core.sports.catalog import get_user_sport

        sport = get_user_sport(user_id)
        if sport and sport.get("name"):
            level = SPORT_LEVEL_NAMES.get(
                sport.get("sport_level"), sport.get("sport_level") or "не указан"
            )
            lines.append(f"- Спорт: {sport['name']}, уровень: {level}")
    except Exception:
        pass

    # ── Аллергии / ограничения ─────────────────────────────────
    try:
        allergies = (user.get("allergies") or "").strip()
        lines.append(f"- Аллергии/ограничения: {allergies if allergies else 'нет'}")
    except Exception:
        pass

    # ── Здоровье и ограничения тренировок ──────────────────────
    try:
        from core.safety import get_safety_rules

        safety_rules = get_safety_rules(user_id)
        condition_names = safety_rules.get("condition_names") or []
        if condition_names:
            details = list(condition_names)
            if user.get("age"):
                details.append(f"возраст: {user['age']} лет")
            lines.append("- Здоровье/ограничения: " + "; ".join(details))
    except Exception:
        pass

    # ── Предпочтения тренировок и питания ──────────────────────
    try:
        from core.preferences import get_preferences, describe_preferences

        prefs = get_preferences(user_id)
        prefs_text = describe_preferences(prefs)
        if prefs_text:
            lines.append(f"- Предпочтения: {prefs_text}")
        exclusions = (prefs.get("food_exclusions") or "").strip()
        food_notes = (prefs.get("food_notes") or "").strip()
        if exclusions or food_notes:
            details = []
            if exclusions:
                details.append(f"исключённые продукты: {exclusions}")
            if food_notes:
                details.append(f"особенности питания: {food_notes}")
            lines.append("- Исключения из еды: " + "; ".join(details))
    except Exception:
        pass

    # ── Нормы на сегодня (КБЖУ + вода) ─────────────────────────
    try:
        from core.nutrition_calc import get_nutrition_plan

        plan = get_nutrition_plan(user_id) or {}
        macros = plan.get("macros") or {}
        if plan.get("target_calories"):
            water_text = ""
            try:
                from core.gamification import get_water_target

                water_text = f", вода {get_water_target(user_id)} мл"
            except Exception:
                pass
            lines.append(
                f"- Нормы на сегодня: {plan['target_calories']:g} ккал, "
                f"Б {macros.get('protein_g', '?')} г, Ж {macros.get('fat_g', '?')} г, "
                f"У {macros.get('carbs_g', '?')} г{water_text}"
            )
    except Exception:
        pass

    # ── Съедено сегодня ────────────────────────────────────────
    try:
        from core.nutrition_tracker import get_today_summary

        summary = get_today_summary(user_id) or {}
        lines.append(
            f"- Съедено сегодня: {summary.get('total_calories', 0):g} ккал, "
            f"белка {summary.get('total_protein_g', 0):g} г "
            f"(приёмов пищи: {summary.get('meals_count', 0)})"
        )
    except Exception:
        pass

    # ── Тренировка сегодня ─────────────────────────────────────
    try:
        from core.database import get_db
        from core.training_service import get_daily_plan

        plan = get_daily_plan(user_id)
        if plan:
            plan_text = f"есть план ({len(plan.get('exercises') or [])} упражнений)"
        else:
            plan_text = "плана нет"

        session_text = ""
        try:
            row = get_db().execute(
                "SELECT COUNT(*) AS cnt FROM workout_sessions "
                "WHERE user_id = ? AND date = date('now')",
                (user_id,),
            ).fetchone()
            if row and row["cnt"]:
                session_text = "; тренировка сегодня уже БЫЛА выполнена"
        except Exception:
            pass
        lines.append(f"- Тренировка сегодня: {plan_text}{session_text}")
    except Exception:
        pass

    # ── Сон и шаги (носимые устройства) ────────────────────────
    try:
        from core.health_data import get_metrics_summary, get_today_metrics

        today_metrics = get_today_metrics(user_id) or {}
        summary = get_metrics_summary(user_id, days=7) or {}
        if today_metrics.get("sleep_hours") is not None:
            lines.append(f"- Сон прошлой ночью: {today_metrics['sleep_hours']:g} ч")
        if summary.get("avg_sleep_hours") is not None:
            lines.append(f"- Средний сон за неделю: {summary['avg_sleep_hours']:g} ч")
        if summary.get("steps_yesterday") is not None:
            steps = f"{int(round(summary['steps_yesterday'])):,}".replace(",", " ")
            lines.append(f"- Шаги вчера: {steps}")
    except Exception:
        pass

    # ── Форма и усталость (только контекст, не правила плана) ───
    try:
        from core.load import get_current_freshness

        load = get_current_freshness(user_id)
        if load["history_days"]:
            lines.append(
                f"- Форма и усталость: Fitness {load['fitness']:g}, "
                f"Fatigue {load['fatigue']:g}, Freshness {load['freshness']:g} "
                f"({load['interpretation']})"
            )
    except Exception:
        pass

    # ── Стрик ──────────────────────────────────────────────────
    try:
        from core.gamification import get_streak

        streak = get_streak(user_id)
        lines.append(
            f"- Стрик дневника питания: {streak.get('current', 0)} дн. "
            f"(рекорд {streak.get('best', 0)})"
        )
    except Exception:
        pass

    # ── Premium ────────────────────────────────────────────────
    try:
        from core.referrals import check_subscription_active

        premium = "активен" if check_subscription_active(user_id) else "нет (Free)"
        lines.append(f"- Premium: {premium}")
    except Exception:
        pass

    return "\n".join(lines)
