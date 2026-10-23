"""Генератор утреннего дайджеста (адаптивный: учитывает вчерашний день)."""

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from .database import get_db, get_user, get_weight_log, get_session_history
from .nutrition_calc import compute_profile, suggest_water_intake, get_nutrition_plan
from .nutrition_tracker import get_food_log_by_date
from .training_service import get_daily_plan
from .gamification import format_streak_text

logger = logging.getLogger(__name__)


async def _fetch_weather(city: str = "Moscow") -> str:
    """Получить текущую погоду через wttr.in (асинхронно)."""
    try:
        url = f"https://wttr.in/{quote(city)}?format=%C+%t&lang=en"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"User-Agent": "curl/8.0"})
            if resp.status_code < 400:
                raw = resp.text.strip()
                if raw:
                    return raw
    except Exception as e:
        logger.debug(f"Ошибка получения погоды для {city}: {e}")
    return ""


def _collect_yesterday_context(user_id: int, user: Dict) -> Dict[str, Any]:
    """Собрать фактические данные за вчерашний день (локальная дата пользователя)."""
    tz_offset = int(user.get("timezone_offset") or 0)
    user_now = datetime.now(timezone.utc) + timedelta(minutes=tz_offset)
    today_local = user_now.date()
    yesterday = (today_local - timedelta(days=1)).isoformat()

    ctx: Dict[str, Any] = {
        "yesterday_date": yesterday,
        "today_local": today_local,
        "calories": 0.0,
        "protein_g": 0.0,
        "fat_g": 0.0,
        "carbs_g": 0.0,
        "meals_count": 0,
        "had_food_log": False,
        "workout": None,
        "heavy_workout": False,
        "latest_weight": None,
        "weight_delta_week": None,
        "today_plan": None,
        "checkin_status": None,
        "checkin_note": "",
        "health_line": None,
    }

    # Питание за вчера
    try:
        entries = get_food_log_by_date(user_id, yesterday)
        ctx["meals_count"] = len(entries)
        ctx["had_food_log"] = bool(entries)
        for e in entries:
            ctx["calories"] += float(e.get("calories") or 0)
            ctx["protein_g"] += float(e.get("protein_g") or 0)
            ctx["fat_g"] += float(e.get("fat_g") or 0)
            ctx["carbs_g"] += float(e.get("carbs_g") or 0)
    except Exception as e:
        logger.warning(f"Дайджест: не удалось получить питание за вчера ({user_id}): {e}")

    # Тренировка за вчера
    try:
        sessions = get_session_history(user_id, days=2)
        y_sessions = [s for s in sessions if s.get("date") == yesterday]
        if y_sessions:
            total_dur = sum(int(s.get("duration_min") or 0) for s in y_sessions)
            max_intensity = max((int(s.get("intensity") or 0) for s in y_sessions), default=0)
            types = sorted({str(s.get("type") or "тренировка") for s in y_sessions})
            ctx["workout"] = {
                "sessions": len(y_sessions),
                "types": types,
                "duration_min": total_dur,
                "intensity": max_intensity,
            }
            ctx["heavy_workout"] = max_intensity >= 8 or total_dur >= 60
    except Exception as e:
        logger.warning(f"Дайджест: не удалось получить тренировки ({user_id}): {e}")

    # Вес (последний + динамика за неделю)
    try:
        weight_log = get_weight_log(user_id, days=30)
        if weight_log:
            latest = float(weight_log[0]["weight_kg"])
            ctx["latest_weight"] = latest
            week_cutoff = (user_now - timedelta(days=7)).isoformat()
            older = [w for w in weight_log if str(w.get("logged_at") or "") <= week_cutoff]
            if older:
                ctx["weight_delta_week"] = round(latest - float(older[0]["weight_kg"]), 1)
    except Exception as e:
        logger.warning(f"Дайджест: не удалось получить вес ({user_id}): {e}")

    # План тренировки на сегодня (только чтение, без генерации)
    try:
        plan = get_daily_plan(user_id, today_local)
        if plan and plan.get("exercises"):
            main = [e for e in plan["exercises"] if e.get("category") in ("strength", "special")]
            names = [e.get("name", "?") for e in (main or plan["exercises"])[:4]]
            ctx["today_plan"] = {
                "exercises_count": len(plan["exercises"]),
                "main_exercises": names,
            }
    except Exception as e:
        logger.warning(f"Дайджест: не удалось получить план на сегодня ({user_id}): {e}")

    # Вчерашний вечерний чек-ин (pending — только маркер отправки, не ответ)
    try:
        row = get_db().execute(
            "SELECT status, note FROM daily_checkins WHERE user_id = ? AND checkin_date = ?",
            (user_id, yesterday),
        ).fetchone()
        if row and row["status"] != "pending":
            ctx["checkin_status"] = row["status"]
            ctx["checkin_note"] = row["note"] or ""
    except Exception as e:
        logger.warning(f"Дайджест: не удалось получить чек-ин ({user_id}): {e}")

    # Метрики с носимых устройств за вчера/сегодня (сон, шаги, пульс покоя)
    try:
        from .health_data import get_metrics_summary

        summary = get_metrics_summary(user_id, days=2)
        parts = []
        if summary.get("avg_sleep_hours") is not None:
            parts.append(f"Сон: {summary['avg_sleep_hours']:.1f} ч")
        if summary.get("steps_yesterday") is not None:
            steps = f"{int(round(summary['steps_yesterday'])):,}".replace(",", " ")
            parts.append(f"шаги вчера: {steps}")
        if summary.get("avg_resting_heart_rate") is not None:
            parts.append(f"пульс покоя: {int(round(summary['avg_resting_heart_rate']))}")
        if summary.get("avg_sleep_hours") is not None and summary["avg_sleep_hours"] < 6:
            parts.append("⚠️ мало сна, тренировка сегодня легче")
        if parts:
            ctx["health_line"] = "⌚ " + ", ".join(parts)
    except Exception as e:
        logger.warning(f"Дайджест: не удалось получить метрики здоровья ({user_id}): {e}")

    return ctx


def _adaptation_rules(ctx: Dict[str, Any], cal_goal: float, prot: float, goal: str) -> Dict[str, Any]:
    """Правила адаптации дня на основе вчерашних данных (без AI, дёшево)."""
    rules: Dict[str, Any] = {
        "protein_deficit": False,
        "calorie_overshoot": False,
        "calorie_undershoot": False,
        "recovery_needed": False,
        "no_food_log": not ctx["had_food_log"],
        "nutrition_focus": "",
        "workout_focus": "",
        "recovery_tip": "",
        "micro_goal": "",
    }

    if ctx["had_food_log"]:
        if prot > 0 and ctx["protein_g"] < 0.9 * prot:
            rules["protein_deficit"] = True
            deficit = round(prot - ctx["protein_g"])
            rules["nutrition_focus"] = (
                f"Вчера белка не хватило ~{deficit} г. Сегодня добавь белковый продукт "
                f"в каждый приём пищи (яйца, творог, курица, рыба)."
            )
            rules["micro_goal"] = f"Набрать не меньше {round(prot)} г белка."
        elif cal_goal > 0 and ctx["calories"] > 1.15 * cal_goal and goal == "lose":
            rules["calorie_overshoot"] = True
            rules["nutrition_focus"] = (
                "Вчера был перебор по калориям. Сегодня держись цели, ужин — полегче."
            )
            rules["micro_goal"] = "Не превысить дневную норму калорий."
        elif cal_goal > 0 and ctx["calories"] < 0.8 * cal_goal and goal == "gain":
            rules["calorie_undershoot"] = True
            rules["nutrition_focus"] = (
                "Вчера калорий было мало для набора массы. Сегодня добавь плотный перекус."
            )
            rules["micro_goal"] = f"Съесть не меньше {round(cal_goal)} ккал."
        else:
            rules["nutrition_focus"] = "Питание вчера было близко к цели — держи тот же ритм."
    else:
        rules["nutrition_focus"] = "Вчера питание не записывалось. Сегодня отмечай каждый приём пищи — так проще держать цель."
        rules["micro_goal"] = "Записать все приёмы пищи."

    if ctx["heavy_workout"]:
        rules["recovery_needed"] = True
        rules["workout_focus"] = (
            "Вчера была тяжёлая тренировка — сегодня лучше лёгкая активность, "
            "растяжка или прогулка, не гнаться за весами."
        )
        rules["recovery_tip"] = "Приоритет — восстановление: сон 7-9 часов, вода и белок."
    elif ctx["workout"]:
        rules["workout_focus"] = "Вчера тренировка была умеренной — сегодня можно работать по плану."
        rules["recovery_tip"] = "Не пропускай разминку и следи за техникой."
    elif ctx["today_plan"]:
        rules["workout_focus"] = "Вчера тренировки не было — сегодня хороший день выполнить план."
        rules["recovery_tip"] = "Разомнись как следует перед основной частью."
    else:
        rules["workout_focus"] = "Вчера тренировки не было. Даже 20-30 минут активности сегодня — уже прогресс."
        rules["recovery_tip"] = "Ложись спать вовремя — восстановление не менее важно, чем нагрузка."

    # Учитываем вчерашний вечерний чек-ин пользователя
    checkin = ctx.get("checkin_status")
    if checkin == "overate":
        rules["calorie_overshoot"] = True
        rules["nutrition_focus"] = (
            "Ты отметил, что вчера переел. Сегодня — лёгкий день: "
            "держись нормы, ужин полегче, больше воды."
        )
        rules["micro_goal"] = "Вернуться в дневную норму калорий."
    elif checkin == "skipped_workout" and not ctx.get("heavy_workout"):
        rules["workout_focus"] = (
            "Вчера тренировка пропущена — без самобичевания. "
            "Сегодня мягко вернись к плану: даже короткая тренировка — победа."
        )
    elif checkin == "ok":
        rules["praise"] = "Вчера ты отметил: всё по плану — так держать! 👏"

    return rules


def _fmt_num(value: float) -> str:
    """Красиво отформатировать число (без .0 для целых)."""
    return str(int(round(value)))


async def generate_digest_text(user_id: int) -> str:
    """Создать текст утреннего дайджеста для пользователя."""
    loop = asyncio.get_running_loop()

    # Получаем профиль (синхронный вызов)
    user = await loop.run_in_executor(None, get_user, user_id)
    if not user:
        return "Пользователь не найден."

    # Вычисляем метрики
    metrics = compute_profile(
        weight_kg=float(user["weight_kg"]),
        height_cm=float(user["height_cm"]),
        age=int(user["age"]),
        gender=user["gender"],
        activity=user["activity"],
        goal=user["goal"],
    )
    cal_goal = metrics["daily_calorie_goal"]
    prot = metrics["protein_g_target"]
    fats = metrics["fat_g_target"]
    carbs = metrics["carbs_g_target"]
    water_l = suggest_water_intake(float(user["weight_kg"]), user["activity"])

    # Нормы из плана (учитывают вид спорта пользователя) — для сравнения со вчерашним днём
    try:
        plan = await loop.run_in_executor(None, get_nutrition_plan, user_id)
        if plan:
            cal_goal = plan.get("target_calories", cal_goal)
            macros = plan.get("macros") or {}
            prot = macros.get("protein_g", prot)
            fats = macros.get("fat_g", fats)
            carbs = macros.get("carbs_g", carbs)
    except Exception as e:
        logger.warning(f"Дайджест: get_nutrition_plan не сработал ({user_id}): {e}")

    # Контекст вчерашнего дня (синхронный вызов, вся БД разом)
    ctx = await loop.run_in_executor(None, _collect_yesterday_context, user_id, user)

    # Правила адаптации (fallback-формулировки, работают и без AI)
    rules = _adaptation_rules(ctx, cal_goal, prot, user.get("goal", "maintain"))

    # Цель текстом
    goal_text = {
        "lose": "🔥 Похудение",
        "maintain": "⚖️ Поддержание формы",
        "gain": "💪 Набор массы",
    }.get(user.get("goal", "maintain"), "⚖️ Поддержание формы")

    # Рекомендации по тренировке (запасной вариант, если плана на сегодня нет)
    exercise_suggestions = {
        "lose": "• Кардио: 30 мин ходьбы или бега\n• Бёрпи 3×15\n• Планка 3×30 сек",
        "maintain": "• Приседания 3×12\n• Отжимания 3×10\n• Планка 3×30 сек\n• Растяжка 10 мин",
        "gain": "• Приседания со штангой 4×8\n• Жим лёжа 4×8\n• Тяга штанги в наклоне 3×8\n• Подтягивания 3×8",
    }
    workout_text = exercise_suggestions.get(
        user.get("goal", "maintain"),
        exercise_suggestions["maintain"],
    )
    if ctx["today_plan"]:
        names = "\n".join(f"• {n}" for n in ctx["today_plan"]["main_exercises"])
        workout_text = f"По плану ({ctx['today_plan']['exercises_count']} упр.), ключевые:\n{names}"

    # Город из профиля
    city = user.get("city") or "Moscow"
    weather = await _fetch_weather(city)
    weather_line = f"🌤️ Погода в {html.escape(city)}: {weather}\n" if weather else ""

    # ── Блок «вчера» ─────────────────────────────────────────────
    yesterday_lines = []
    if ctx["had_food_log"]:
        yesterday_lines.append(
            f"🍽️ Питание: {_fmt_num(ctx['calories'])}/{_fmt_num(cal_goal)} ккал, "
            f"Б {_fmt_num(ctx['protein_g'])}/{_fmt_num(prot)} г, "
            f"Ж {_fmt_num(ctx['fat_g'])}/{_fmt_num(fats)} г, "
            f"У {_fmt_num(ctx['carbs_g'])}/{_fmt_num(carbs)} г"
        )
    else:
        yesterday_lines.append("🍽️ Питание не записывалось")

    if ctx["workout"]:
        w = ctx["workout"]
        dur = f", {w['duration_min']} мин" if w["duration_min"] else ""
        inten = f", интенсивность {w['intensity']}/10" if w["intensity"] else ""
        yesterday_lines.append(f"🏋️ Тренировка: {', '.join(w['types'])}{dur}{inten}")
    else:
        yesterday_lines.append("🏋️ Тренировки не было")

    if ctx["latest_weight"] is not None:
        delta = ctx["weight_delta_week"]
        delta_text = f" ({'+' if delta > 0 else ''}{delta} кг за неделю)" if delta is not None else ""
        yesterday_lines.append(f"⚖️ Вес: {ctx['latest_weight']} кг{delta_text}")

    if ctx.get("health_line"):
        yesterday_lines.append(ctx["health_line"])

    if ctx.get("checkin_status"):
        checkin_text = {
            "ok": "всё по плану ✅",
            "overate": "был перебор по еде 🍽",
            "skipped_workout": "тренировка пропущена 😴",
            "custom": f"«{ctx.get('checkin_note', '')[:80]}» ✏️",
        }.get(ctx["checkin_status"])
        if checkin_text:
            yesterday_lines.append(f"🌙 Чек-ин: {checkin_text}")

    yesterday_block = "<b>Итоги вчера:</b>\n" + "\n".join(yesterday_lines) + "\n\n"

    # ── AI-часть (один запрос; при недоступности — правила) ──────
    ai: Optional[Dict] = None
    try:
        from .ai.gemini_client import get_gemini_client

        client = get_gemini_client()
        if client:
            ai = await client.generate_daily_digest(
                user_profile={
                    "goal": user.get("goal", "maintain"),
                    "sport": user.get("sport_level", "fitness"),
                    "weight": float(user.get("weight_kg", 70)),
                    "calorie_target": cal_goal,
                    "protein_target": prot,
                    "fat_target": fats,
                    "carbs_target": carbs,
                },
                today_plan={
                    "workout": workout_text,
                    "has_plan": bool(ctx["today_plan"]),
                },
                yesterday_summary={
                    "date": ctx["yesterday_date"],
                    "calories": round(ctx["calories"]),
                    "protein_g": round(ctx["protein_g"], 1),
                    "fat_g": round(ctx["fat_g"], 1),
                    "carbs_g": round(ctx["carbs_g"], 1),
                    "meals_count": ctx["meals_count"],
                    "had_food_log": ctx["had_food_log"],
                    "workout": ctx["workout"],
                    "heavy_workout": ctx["heavy_workout"],
                    "latest_weight": ctx["latest_weight"],
                    "weight_delta_week": ctx["weight_delta_week"],
                    "checkin_status": ctx["checkin_status"],
                    "checkin_note": ctx["checkin_note"],
                    "adaptations": {
                        "protein_deficit": rules["protein_deficit"],
                        "calorie_overshoot": rules["calorie_overshoot"],
                        "calorie_undershoot": rules["calorie_undershoot"],
                        "recovery_needed": rules["recovery_needed"],
                        "no_food_log": rules["no_food_log"],
                    },
                },
            )
    except Exception as e:
        logger.warning(f"Дайджест: AI недоступен ({user_id}): {e}")
        ai = None

    if ai and ("error" in ai or not isinstance(ai, dict)):
        ai = None

    # ── Сборка сообщения ─────────────────────────────────────────
    greeting = f"🌅 Доброе утро, {html.escape(str(user.get('username', 'друг')))}!"
    if ai and ai.get("greeting"):
        greeting += f"\n{ai['greeting']}"

    focus_lines = []
    if ai:
        if ai.get("yesterday_review"):
            focus_lines.append(f"📌 {ai['yesterday_review']}")
        if ai.get("nutrition_focus"):
            focus_lines.append(f"🍗 {ai['nutrition_focus']}")
        if ai.get("workout_focus"):
            focus_lines.append(f"🏋️ {ai['workout_focus']}")
        if ai.get("recovery_tip"):
            focus_lines.append(f"😴 {ai['recovery_tip']}")
        if ai.get("micro_goal"):
            focus_lines.append(f"🎯 Микро-цель: {ai['micro_goal']}")
    else:
        # Шаблонные формулировки из правил — дайджест работает и без AI
        focus_lines.append(f"🍗 {rules['nutrition_focus']}")
        focus_lines.append(f"🏋️ {rules['workout_focus']}")
        focus_lines.append(f"😴 {rules['recovery_tip']}")
        if rules["micro_goal"]:
            focus_lines.append(f"🎯 Микро-цель: {rules['micro_goal']}")

    if rules.get("praise"):
        focus_lines.insert(0, f"📌 {rules['praise']}")

    focus_block = "<b>Фокус на сегодня:</b>\n" + "\n".join(focus_lines) + "\n\n"

    quote_line = ""
    if ai and ai.get("motivation_quote"):
        quote_line = f"\n💬 {ai['motivation_quote']}"

    streak_text = await loop.run_in_executor(None, format_streak_text, user_id)
    streak_line = f"{streak_text}\n" if streak_text else ""

    return (
        f"{greeting}\n{streak_line}\n"
        f"{yesterday_block}"
        f"<b>Цель дня:</b> {_fmt_num(cal_goal)} ккал ({goal_text})\n"
        f"<b>Макросы:</b> Б: {_fmt_num(prot)}г, Ж: {_fmt_num(fats)}г, У: {_fmt_num(carbs)}г\n"
        f"💧 Вода: {water_l} л\n"
        f"{weather_line}\n"
        f"{focus_block}"
        f"<b>Тренировка на сегодня:</b>\n{workout_text}{quote_line}\n\n"
        f"Не забывай записывать питание и тренировки! Хорошего дня! 💪"
    )
