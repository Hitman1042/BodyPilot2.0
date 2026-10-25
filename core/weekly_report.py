"""Еженедельный отчёт с PNG-графиками и одним AI-комментарием."""

import asyncio
import html
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile

from .charts import (
    chart_fitness,
    chart_sleep,
    chart_steps,
    generate_calories_chart,
    generate_weight_chart,
    generate_workouts_chart,
)
from .database import get_db, get_user
from .gamification import get_streak
from .health_data import get_weekly_health_stats
from .nutrition_calc import get_nutrition_plan

logger = logging.getLogger(__name__)

_WEEKDAYS_FULL = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def _offset_modifier(offset: int) -> str:
    return f"{offset:+d} minutes"


def _days_word(value: int) -> str:
    if 11 <= value % 100 <= 14:
        return "дней"
    if value % 10 == 1:
        return "день"
    if 2 <= value % 10 <= 4:
        return "дня"
    return "дней"


def _fmt_int(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _signed(value: float) -> str:
    if value > 0:
        return f"+{value:.1f}"
    if value < 0:
        return f"−{abs(value):.1f}"
    return "0.0"


def _collect_metrics(user_id: int) -> Optional[Dict[str, Any]]:
    user = get_user(user_id)
    if not user:
        return None

    offset = int(user.get("timezone_offset") or 0)
    today = (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()
    first_day = today - timedelta(days=6)
    cutoff = (first_day - timedelta(days=1)).isoformat()
    conn = get_db()

    nutrition_rows = conn.execute(
        """SELECT date(logged_at, ?) AS day,
                  SUM(calories) AS calories,
                  SUM(protein_g) AS protein_g,
                  COUNT(*) AS entries
           FROM food_log_new
           WHERE user_id = ? AND logged_at >= ?
           GROUP BY day""",
        (_offset_modifier(offset), user_id, cutoff),
    ).fetchall()
    nutrition = {}
    for row in nutrition_rows:
        try:
            day = date.fromisoformat(row["day"])
        except (TypeError, ValueError):
            continue
        if first_day <= day <= today:
            nutrition[day] = {
                "calories": float(row["calories"] or 0),
                "protein_g": float(row["protein_g"] or 0),
                "entries": int(row["entries"] or 0),
            }

    workout_count = conn.execute(
        "SELECT COUNT(*) FROM workout_sessions WHERE user_id = ? AND date >= ? AND date <= ?",
        (user_id, first_day.isoformat(), today.isoformat()),
    ).fetchone()[0]
    duration = conn.execute(
        """SELECT COALESCE(SUM(duration_min), 0)
           FROM workout_sessions
           WHERE user_id = ? AND date >= ? AND date <= ?""",
        (user_id, first_day.isoformat(), today.isoformat()),
    ).fetchone()[0]
    tonnage = conn.execute(
        """SELECT COALESCE(SUM(ws.weight_kg * ws.reps), 0)
           FROM workout_sets ws
           JOIN workout_exercises we ON we.id = ws.workout_exercise_id
           JOIN workout_sessions s ON s.id = we.session_id
           WHERE s.user_id = ? AND s.date >= ? AND s.date <= ?""",
        (user_id, first_day.isoformat(), today.isoformat()),
    ).fetchone()[0]

    weight_rows = conn.execute(
        """SELECT weight_kg, datetime(logged_at, ?) AS local_logged_at
           FROM weight_log
           WHERE user_id = ? AND logged_at >= ?
           ORDER BY logged_at""",
        (_offset_modifier(offset), user_id, cutoff),
    ).fetchall()
    weights = []
    for row in weight_rows:
        try:
            logged_at = datetime.fromisoformat(row["local_logged_at"])
            weight = float(row["weight_kg"])
        except (TypeError, ValueError):
            continue
        if first_day <= logged_at.date() <= today:
            weights.append((logged_at, weight))

    achievement_rows = conn.execute(
        """SELECT datetime(unlocked_at, ?) AS local_unlocked_at
           FROM achievements
           WHERE user_id = ? AND unlocked_at >= ?""",
        (_offset_modifier(offset), user_id, cutoff),
    ).fetchall()
    new_achievements = 0
    for row in achievement_rows:
        try:
            unlocked_at = datetime.fromisoformat(row["local_unlocked_at"])
        except (TypeError, ValueError):
            continue
        if first_day <= unlocked_at.date() <= today:
            new_achievements += 1

    plan = get_nutrition_plan(user_id)
    calorie_target = float(plan.get("target_calories") or 0)
    protein_target = float((plan.get("macros") or {}).get("protein_g") or 0)
    total_calories = sum(item["calories"] for item in nutrition.values())
    total_protein = sum(item["protein_g"] for item in nutrition.values())

    best_day = None
    food_days = [item for item in nutrition.items() if item[1]["entries"] > 0]
    if food_days and calorie_target > 0:
        best_day = min(
            food_days,
            key=lambda item: abs(item[1]["calories"] - calorie_target),
        )

    streak = get_streak(user_id)
    weight_change = weights[-1][1] - weights[0][1] if len(weights) >= 2 else None

    health = None
    try:
        stats = get_weekly_health_stats(user_id)
        if any(
            stats[key] is not None
            for key in ("avg_steps", "avg_sleep_hours", "avg_resting_heart_rate")
        ):
            health = stats
    except Exception as exc:
        logger.warning("Недельный отчёт: метрики здоровья недоступны (%s): %s", user_id, exc)

    freshness = None
    try:
        from .load import get_current_freshness

        freshness = get_current_freshness(user_id)
    except Exception as exc:
        logger.warning("Недельный отчёт: нагрузка недоступна (%s): %s", user_id, exc)

    return {
        "start_date": first_day.isoformat(),
        "end_date": today.isoformat(),
        "average_calories": total_calories / 7,
        "calorie_target": calorie_target,
        "average_protein_g": total_protein / 7,
        "protein_target": protein_target,
        "workouts_count": int(workout_count or 0),
        "total_duration_min": int(duration or 0),
        "total_tonnage_kg": float(tonnage or 0),
        "weight_start": weights[0][1] if weights else None,
        "weight_end": weights[-1][1] if weights else None,
        "weight_change_kg": weight_change,
        "streak_current": int(streak["current"]),
        "new_achievements": new_achievements,
        "best_day": (
            {
                "date": best_day[0].isoformat(),
                "weekday": _WEEKDAYS_FULL[best_day[0].weekday()],
                "calories": best_day[1]["calories"],
            }
            if best_day
            else None
        ),
        "is_active": bool(nutrition or workout_count),
        "health": health,
        "freshness": freshness,
    }


def _trend_text(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    if pct > 3:
        arrow = "↑"
    elif pct < -3:
        arrow = "↓"
    else:
        arrow = "→"
    return f" ({arrow} {pct:+.0f}% к прошлой неделе)"


def _format_health_block(health: Dict[str, Any]) -> list[str]:
    lines = ["", "⌚ <b>Активность и сон</b>"]
    if health["avg_steps"] is not None:
        steps_line = f"• Шаги: в среднем {_fmt_int(health['avg_steps'])} /день"
        if health["total_steps"] is not None:
            steps_line += f", всего {_fmt_int(health['total_steps'])}"
        steps_line += _trend_text(health["steps_trend_pct"])
        lines.append(steps_line)
    if health["avg_sleep_hours"] is not None:
        lines.append(
            f"• Сон: в среднем {health['avg_sleep_hours']:g} ч/ночь"
            + _trend_text(health["sleep_trend_pct"])
        )
    if health["avg_resting_heart_rate"] is not None:
        lines.append(f"• Пульс покоя: в среднем {int(round(health['avg_resting_heart_rate']))} уд/мин")
    best = health.get("best_sleep_day")
    if best:
        best_date = date.fromisoformat(best["date"])
        lines.append(
            f"🌙 Лучший сон: {best['weekday']}, {best_date.strftime('%d.%m')} — {best['hours']:g} ч"
        )
    return lines


def _format_report_text(metrics: Dict[str, Any]) -> str:
    start = date.fromisoformat(metrics["start_date"])
    end = date.fromisoformat(metrics["end_date"])
    lines = [
        "📅 <b>Отчёт за неделю</b>",
        f"<b>{start.strftime('%d.%m')} — {end.strftime('%d.%m.%Y')}</b>",
        "",
        "🍽 <b>Питание</b>",
        (
            f"• Средние калории: {_fmt_int(metrics['average_calories'])} / "
            f"{_fmt_int(metrics['calorie_target'])} ккал"
        ),
        (
            f"• Средний белок: {metrics['average_protein_g']:.1f} / "
            f"{metrics['protein_target']:.1f} г"
        ),
    ]
    if metrics["best_day"]:
        best = metrics["best_day"]
        best_date = date.fromisoformat(best["date"])
        lines.append(
            f"🌟 Лучший день: {best['weekday']}, {best_date.strftime('%d.%m')} — "
            f"{_fmt_int(best['calories'])} ккал, ближе всего к норме"
        )
    else:
        lines.append("🌟 Лучший день не выбран — записей питания пока нет")

    lines.extend([
        "",
        "🏋️ <b>Тренировки</b>",
        f"• Сессий: {metrics['workouts_count']}",
        f"• Суммарный тоннаж: {_fmt_int(metrics['total_tonnage_kg'])} кг",
    ])

    if metrics["weight_change_kg"] is not None:
        lines.extend([
            "",
            (
                f"⚖️ <b>Вес:</b> {metrics['weight_start']:.1f} → "
                f"{metrics['weight_end']:.1f} кг "
                f"({_signed(metrics['weight_change_kg'])} кг за неделю)"
            ),
        ])
    elif metrics["weight_end"] is not None:
        lines.extend(["", f"⚖️ <b>Вес:</b> {metrics['weight_end']:.1f} кг (одна запись)"])

    if metrics.get("health"):
        lines.extend(_format_health_block(metrics["health"]))

    freshness = metrics.get("freshness")
    if freshness:
        lines.extend([
            "",
            "📈 <b>Форма и усталость</b>",
            f"• Fitness: {freshness['fitness']:g}; Fatigue: {freshness['fatigue']:g}",
            f"• Freshness: {freshness['freshness']:g} — {freshness['interpretation']}",
        ])

    lines.extend([
        "",
        f"🔥 <b>Текущая серия:</b> {metrics['streak_current']} "
        f"{_days_word(metrics['streak_current'])}",
        f"🏆 <b>Новых достижений:</b> {metrics['new_achievements']}",
    ])
    return "\n".join(lines)


def _build_charts(user_id: int) -> list[Dict[str, Any]]:
    specs = (
        ("weight", "weight_30d.png", "Вес за 30 дней", generate_weight_chart),
        ("calories", "calories_7d.png", "Калории за 7 дней", generate_calories_chart),
        ("workouts", "workouts_7d.png", "Тренировки за 7 дней", generate_workouts_chart),
        ("steps", "steps_14d.png", "Шаги за 14 дней", chart_steps),
        ("sleep", "sleep_14d.png", "Сон за 14 дней", chart_sleep),
        ("fitness", "fitness_8w.png", "Форма и усталость за 8 недель", chart_fitness),
    )
    charts = []
    for name, filename, caption, generator in specs:
        try:
            data = generator(user_id)
        except Exception as exc:
            logger.warning("Не удалось построить график %s для %s: %s", name, user_id, exc)
            continue
        if data:
            charts.append({
                "name": name,
                "filename": filename,
                "caption": caption,
                "data": data,
            })
    return charts


def _build_report_data(user_id: int) -> Dict[str, Any]:
    metrics = _collect_metrics(user_id)
    if metrics is None:
        return {"text": "Пользователь не найден.", "charts": [], "metrics": None}
    return {
        "text": _format_report_text(metrics),
        "charts": _build_charts(user_id),
        "metrics": metrics,
    }


def _fallback_comment(metrics: Dict[str, Any]) -> str:
    if not metrics["is_active"]:
        return (
            "Данных за эту неделю пока мало. На следующей неделе начни с записей "
            "питания и одной тренировки — так прогресс будет нагляднее."
        )

    if metrics["workouts_count"] >= 2:
        positive = f"Хорошая неделя: тренировок — {metrics['workouts_count']}."
    elif metrics["streak_current"] >= 3:
        positive = f"Серия {metrics['streak_current']} дней показывает хорошую регулярность."
    else:
        positive = "Хорошо, что ты продолжаешь записывать прогресс."

    target = metrics["calorie_target"]
    average = metrics["average_calories"]
    if metrics["workouts_count"] == 0:
        recommendation = "На следующей неделе добавь хотя бы две короткие тренировки."
    elif target > 0 and abs(average - target) / target > 0.15:
        recommendation = "На следующей неделе старайся держать калории ближе к дневной норме."
    elif metrics["protein_target"] > 0 and metrics["average_protein_g"] < 0.9 * metrics["protein_target"]:
        recommendation = "На следующей неделе добавляй источник белка в каждый основной приём пищи."
    else:
        recommendation = "На следующей неделе сохрани этот ритм и продолжай отмечать каждый день."
    return f"{positive} {recommendation}"


async def _generate_comment(user: Dict[str, Any], metrics: Dict[str, Any]) -> str:
    fallback = _fallback_comment(metrics)
    try:
        from .ai.gemini_client import COACH_PERSONA, get_gemini_client

        client = get_gemini_client()
        if not client:
            return fallback
        summary = (
            f"Средние калории: {metrics['average_calories']:.0f} из {metrics['calorie_target']:.0f}; "
            f"белок: {metrics['average_protein_g']:.1f} из {metrics['protein_target']:.1f} г; "
            f"тренировок: {metrics['workouts_count']}; тоннаж: {metrics['total_tonnage_kg']:.0f} кг; "
            f"изменение веса: {metrics['weight_change_kg']}; "
            f"текущая серия: {metrics['streak_current']} дней; "
            f"новых достижений: {metrics['new_achievements']}."
        )
        result = await client.chat_answer(
            user_profile={
                "goal": user.get("goal", "maintain"),
                "sport": user.get("sport_level", "fitness"),
                "sport_level": user.get("sport_level", "beginner"),
                "allergies": user.get("allergies", "нет"),
            },
            question=(
                f"{COACH_PERSONA}\n\n"
                "Дай комментарий к этому недельному отчёту ровно в 2-3 предложениях: "
                "сначала отметь, что получилось хорошо, затем дай одну конкретную "
                "рекомендацию на следующую неделю. Без списков и markdown."
            ),
            context=summary,
        )
        if result and "error" not in result:
            answer = (result.get("answer") or "").strip()
            if answer:
                return answer
    except Exception as exc:
        logger.warning("AI-комментарий недельного отчёта недоступен: %s", exc)
    return fallback


async def build_weekly_report(user_id: int) -> Dict[str, Any]:
    """Собрать текст, метрики и PNG-графики; выполнить не более одного вызова Gemini."""
    loop = asyncio.get_running_loop()
    report = await loop.run_in_executor(None, _build_report_data, user_id)
    if report["metrics"] is None:
        return report

    user = await loop.run_in_executor(None, get_user, user_id)
    comment = await _generate_comment(user, report["metrics"])
    report["text"] += f"\n\n💡 <b>Комментарий:</b>\n{html.escape(comment)}"
    report["comment"] = comment
    return report


async def send_weekly_report(bot: Bot, chat_id: int, user_id: int) -> Dict[str, Any]:
    """Отправить текст и все доступные графики; сбой одного PNG не прерывает рассылку."""
    report = await build_weekly_report(user_id)
    await bot.send_message(chat_id=chat_id, text=report["text"])
    for chart in report["charts"]:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(chart["data"], filename=chart["filename"]),
                caption=chart["caption"],
            )
        except Exception as exc:
            logger.warning(
                "Не удалось отправить график %s пользователю %s: %s",
                chart["name"],
                user_id,
                exc,
            )
    return report
