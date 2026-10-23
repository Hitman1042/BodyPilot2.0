"""AI-анализ питания и тренировок для BodyPilot."""
import html
import logging
logger = logging.getLogger(__name__)
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from core.ai.gemini_client import get_gemini_client
from core.database import get_user
from core.nutrition_calc import get_nutrition_plan
from core.nutrition_tracker import get_today_summary, get_food_log_today
from core.training_service import get_daily_plan
from bot.middleware.premium_check import check_ai_limit
router = Router()


# ═══════════════════════════════════════════════════════════════
# AI-АНАЛИЗ ДНЯ ПИТАНИЯ
# ═══════════════════════════════════════════════════════════════

@router.message(Command("ai_analyze"))
@check_ai_limit("ai_analyze_food")
async def cmd_ai_analyze(message: Message, user_id: int = None):
    """AI-анализ питания за сегодня с рекомендациями."""
    import logging
    logger = logging.getLogger(__name__)

    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    status_message = await message.answer("🤖 <b>AI анализирует твой день...</b>\n\nЭто займёт 10-15 секунд.")

    try:
        logger.info(f"AI analyze: начинаем для пользователя {uid}")

        client = get_gemini_client()
        logger.info(f"AI analyze: клиент Gemini = {client}")

        if not client:
            await message.bot.delete_message(uid, status_message.message_id)
            await message.answer("❌ AI-сервис временно недоступен (клиент не инициализирован)")
            return

        # Собираем данные
        plan = get_nutrition_plan(uid)
        logger.info(f"AI analyze: план питания = {plan}")

        summary = get_today_summary(uid)
        logger.info(f"AI analyze: сводка = {summary}")

        food_log = get_food_log_today(uid)
        logger.info(f"AI analyze: лог еды = {food_log}")

        from core.sports.catalog import get_user_sport
        user_sport = get_user_sport(uid) or {}

        user_profile = {
            "goal": user.get("goal", "maintain"),
            "calorie_target": plan.get("target_calories", 2000),
            "protein_target": plan.get("macros", {}).get("protein_g", 150),
            "sport": user_sport.get("name_en") or "fitness",
            "sport_level": user_sport.get("sport_level") or "beginner",
        }

        logger.info(f"AI analyze: профиль = {user_profile}")
        logger.info(f"AI analyze: вызываем client.analyze_day_nutrition...")

        # Запускаем AI-анализ
        result = await client.analyze_day_nutrition(
            user_profile=user_profile,
            food_log=food_log,
        )

        logger.info(f"AI analyze: результат = {result}")

        await message.bot.delete_message(uid, status_message.message_id)

        if not result:
            logger.error("AI analyze: результат пустой (None)")
            await message.answer("❌ Не удалось проанализировать. Попробуй позже.")
            return

        if "error" in result:
            logger.error(f"AI analyze: ошибка в результате = {result.get('error')}")
            error_msg = result.get("message", "неизвестная ошибка")
            await message.answer(f"❌ Ошибка AI: {error_msg}")
            return

        # Формируем отчёт
        score = result.get("day_score", 0)

        if score >= 80:
            score_emoji = "🟢"
        elif score >= 60:
            score_emoji = "🟡"
        else:
            score_emoji = "🔴"

        text = f"{score_emoji} <b>AI-анализ питания</b>\n"
        text += f"<i>Оценка дня: {score}/100</i>\n\n"

        strengths = result.get("strengths", [])
        if strengths:
            text += f"✅ <b>Что хорошо:</b>\n"
            for s in strengths[:3]:
                text += f"• {s}\n"
            text += "\n"

        problems = result.get("problems", [])
        if problems:
            text += f"⚠️ <b>Что улучшить:</b>\n"
            for p in problems[:3]:
                text += f"• {p}\n"
            text += "\n"

        recommendations = result.get("recommendations", [])
        if recommendations:
            text += f"💡 <b>Рекомендации AI:</b>\n"
            for r in recommendations[:3]:
                priority = r.get("priority", "medium")
                emoji = "🔴" if priority == "high" else "🟡" if priority == "medium" else "🟢"
                text += f"{emoji} {r.get('text', '')}\n"
            text += "\n"

        tomorrow = result.get("tomorrow_plan", "")
        if tomorrow:
            text += f"📅 <b>План на завтра:</b>\n{tomorrow}\n\n"

        motivation = result.get("motivation", "")
        if motivation:
            text += f"💪 <i>{motivation}</i>"

        await message.answer(text)
        logger.info("AI analyze: успешно отправлено пользователю")

    except Exception as e:
        logger.exception(f"AI analyze: критическая ошибка — {type(e).__name__}: {e}")
        await message.bot.delete_message(uid, status_message.message_id)
        await message.answer(f"❌ Произошла ошибка при анализе.\n\n<code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>")


@router.message(Command("ai_workout"))
@check_ai_limit("ai_analyze_workout")
async def cmd_ai_workout(message: Message, user_id: int = None):
    """AI-анализ последней тренировки."""
    import logging
    logger = logging.getLogger(__name__)

    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    status_message = await message.answer("🤖 <b>AI анализирует тренировку...</b>\n\nЭто займёт 10-15 секунд.")

    try:
        client = get_gemini_client()
        if not client:
            await message.bot.delete_message(uid, status_message.message_id)
            await message.answer("❌ AI-сервис временно недоступен")
            return

        # ═══════════════════════════════════════════════════════════════
        # ПОЛУЧАЕМ ДАННЫЕ ПОСЛЕДНЕЙ ТРЕНИРОВКИ ИЗ БД
        # ═══════════════════════════════════════════════════════════════

        from core.database import get_db
        from datetime import datetime, timedelta

        conn = get_db()

        # Последняя тренировка
        last_workout = conn.execute("""
            SELECT * FROM workout_sessions 
            WHERE user_id = ? 
            ORDER BY date DESC 
            LIMIT 1
        """, (uid,)).fetchone()

        if not last_workout:
            await message.bot.delete_message(uid, status_message.message_id)
            await message.answer(
                "❌ <b>Тренировок не найдено</b>\n\n"
                "Сначала выполни тренировку с /workout_plan"
            )
            return

        # Конвертируем в dict
        last_workout = dict(last_workout)

        # Упражнения последней тренировки
        exercises = conn.execute("""
            SELECT we.*, e.name as exercise_name
            FROM workout_exercises we
            JOIN exercises e ON we.exercise_id = e.id
            WHERE we.session_id = ?
        """, (last_workout["id"],)).fetchall()

        exercises = [dict(ex) for ex in exercises]

        # Сеты (подходы)
        sets_data = conn.execute("""
            SELECT ws.*, we.exercise_id, e.name as exercise_name
            FROM workout_sets ws
            JOIN workout_exercises we ON ws.workout_exercise_id = we.id
            JOIN exercises e ON we.exercise_id = e.id
            WHERE we.session_id = ?
            ORDER BY we.exercise_id, ws.set_number
        """, (last_workout["id"],)).fetchall()

        sets_data = [dict(s) for s in sets_data]

        # Группируем сеты по упражнениям
        exercises_with_sets = {}
        for ex in exercises:
            ex_id = ex["id"]
            ex_name = ex.get("exercise_name", ex.get("custom_exercise_name", "?"))
            exercises_with_sets[ex_id] = {
                "name": ex_name,
                "sets": [],
                "target_sets": 0,
                "target_reps": 0,
            }

        for s in sets_data:
            ex_id = s["exercise_id"]
            if ex_id not in exercises_with_sets:
                exercises_with_sets[ex_id] = {
                    "name": s.get("exercise_name", "?"),
                    "sets": [],
                    "target_sets": 0,
                    "target_reps": 0,
                }
            exercises_with_sets[ex_id]["sets"].append({
                "set_number": s.get("set_number", 0),
                "reps": s.get("reps", 0),
                "weight": s.get("weight_kg", 0),
            })

        # Считаем тоннаж
        total_tonnage = sum(
            s["weight"] * s["reps"]
            for ex in exercises_with_sets.values()
            for s in ex["sets"]
        )

        # Формируем данные для AI
        workout_data = {
            "type": last_workout.get("type", "сила"),
            "duration": last_workout.get("duration_min", 60),
            "exercises_count": len(exercises),
            "tonnage": total_tonnage,
            "intensity": last_workout.get("intensity", 7),
            "exercises": [
                {
                    "name": ex["name"],
                    "sets": len(ex["sets"]),
                    "reps": ex["sets"][0]["reps"] if ex["sets"] else 0,
                    "weight": ex["sets"][0]["weight"] if ex["sets"] else 0,
                }
                for ex in exercises_with_sets.values()
            ],
        }

        # История последних 5 тренировок
        history_workouts = conn.execute("""
            SELECT id, date, type
            FROM workout_sessions
            WHERE user_id = ? AND id != ?
            ORDER BY date DESC
            LIMIT 5
        """, (uid, last_workout["id"])).fetchall()

        history_workouts = [dict(w) for w in history_workouts]

        history = []
        for w in history_workouts:
            # Считаем тоннаж для каждой тренировки
            tonnage_result = conn.execute("""
                SELECT SUM(ws.weight_kg * ws.reps) as tonnage
                FROM workout_sets ws
                JOIN workout_exercises we ON ws.workout_exercise_id = we.id
                WHERE we.session_id = ?
            """, (w["id"],)).fetchone()
            tonnage = tonnage_result["tonnage"] if tonnage_result and tonnage_result["tonnage"] else 0

            history.append({
                "date": str(w["date"]),
                "type": w.get("type", "?"),
                "tonnage": tonnage,
            })

        # Восстановление: белок — фактическое потребление сегодня,
        # дни отдыха — по тренировкам за последние 7 дней (дефолты, если данных нет)
        summary = get_today_summary(uid)
        workout_days_7 = conn.execute(
            "SELECT COUNT(DISTINCT DATE(date)) FROM workout_sessions "
            "WHERE user_id = ? AND date >= DATE('now', '-7 days')",
            (uid,),
        ).fetchone()[0]

        recovery = {
            "sleep_hours": 7,
            "protein_g": summary.get("total_protein_g") or 100,
            "rest_days": max(0, 7 - workout_days_7) if workout_days_7 else 2,
        }

        logger.info(f"AI workout: данные = {workout_data}")
        logger.info(f"AI workout: история = {history}")

        # ═══════════════════════════════════════════════════════════════
        # ЗАПУСКАЕМ AI-АНАЛИЗ
        # ═══════════════════════════════════════════════════════════════

        result = await client.analyze_workout(
            workout_data=workout_data,
            history=history,
            recovery=recovery,
        )

        await message.bot.delete_message(uid, status_message.message_id)

        if not result or "error" in result:
            await message.answer("❌ Не удалось проанализировать тренировку.")
            return

        # ═══════════════════════════════════════════════════════════════
        # ФОРМИРУЕМ ОТВЕТ
        # ═══════════════════════════════════════════════════════════════

        score = result.get("workout_score", 0)
        score_emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"

        text = f"{score_emoji} <b>AI-анализ тренировки</b>\n"
        text += f"<i>Оценка: {score}/100</i>\n\n"

        # Прогресс
        progress = result.get("progress_detected")
        progress_pct = result.get("progress_percentage", 0)

        if progress is True:
            if progress_pct > 10:
                text += f"✅ <b>Прогресс обнаружен!</b> (+{progress_pct}% к прошлой тренировке)\n\n"
            else:
                text += f"✅ <b>Прогресс обнаружен!</b>\n\n"
        elif progress is False:
            text += f"⚠️ <b>Прогресса нет</b> ({progress_pct}%)\n\n"

        # Сильные стороны
        strengths = result.get("strengths", [])
        if strengths:
            text += f"✅ <b>Что хорошо:</b>\n"
            for s in strengths:
                text += f"• {s}\n"
            text += "\n"

        # Проблемы
        problems = result.get("problems", [])
        if problems:
            text += f"⚠️ <b>Что улучшить:</b>\n"
            for p in problems:
                text += f"• {p}\n"
            text += "\n"

        # Советы на следующую тренировку
        advice = result.get("next_workout_advice", [])
        if advice:
            text += f"💡 <b>Советы на следующую тренировку:</b>\n"
            for a in advice[:5]:
                ex_name = a.get("exercise", "?")
                change = a.get("change", "?")
                text += f"• {ex_name}: {change}\n"
            text += "\n"

        # Восстановление
        recovery_status = result.get("recovery_status", "unknown")
        recovery_emoji = "✅" if recovery_status == "good" else "⚠️" if recovery_status == "needs_attention" else "❌"
        text += f"{recovery_emoji} <b>Восстановление:</b> {recovery_status}\n"

        if result.get("recovery_advice"):
            text += f"<i>{result['recovery_advice']}</i>\n\n"

        # Мотивация
        if result.get("motivation"):
            text += f"💪 <i>{result['motivation']}</i>"

        await message.answer(text)

    except Exception as e:
        logger.exception(f"AI workout: критическая ошибка — {type(e).__name__}: {e}")
        await message.bot.delete_message(uid, status_message.message_id)
        await message.answer(f"❌ Ошибка при анализе тренировки.\n\n<code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>")