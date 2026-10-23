"""Обработчики статистики с визуализацией."""

import html
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.database import (
    get_user, get_weekly_stats,
    get_weight_log, get_weight_history,
    get_tonnage_history,
)
from core.nutrition_tracker import get_food_log, get_calories_history
from core.nutrition_calc import compute_profile, bmi
from core.referrals import check_subscription_active
from core.visuals import progress_bar, trend_emoji, mini_graph, status_icon, bmi_status

router = Router()


def _get_user_id(message: Message, user_id: int = None) -> int:
    return user_id if user_id else message.from_user.id


@router.message(Command("stats"))
async def cmd_stats(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    stats = get_weekly_stats(uid)
    food_log = get_food_log(uid, days=7)
    weight_log = get_weight_log(uid, days=7)
    metrics = compute_profile(
        weight_kg=float(user["weight_kg"]),
        height_cm=float(user["height_cm"]),
        age=int(user["age"]),
        gender=user["gender"],
        activity=user["activity"],
        goal=user["goal"],
    )

    cal_history = get_calories_history(uid, days=14)
    tonnage_history = get_tonnage_history(uid, days=7)
    weight_history = get_weight_history(uid, days=7)

    target_cal = metrics["daily_calorie_goal"]
    avg_cal = stats["avg_daily_calories"]
    cal_bar = progress_bar(avg_cal, target_cal)

    # Среднее за предыдущую неделю (дни 8–14 назад) для тренда
    week_cutoff = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
    prev_week_cals = [d["calories"] for d in cal_history if d["day"] < week_cutoff]
    prev_avg_cal = sum(prev_week_cals) / len(prev_week_cals) if prev_week_cals else 0
    cal_trend = trend_emoji(avg_cal, prev_avg_cal)
    cal_history = [d for d in cal_history if d["day"] >= week_cutoff]

    tonnage = stats.get("weekly_tonnage", 0)
    tonnage_history_14 = get_tonnage_history(uid, days=14)
    prev_week_tonnage = sum(t["tonnage"] for t in tonnage_history_14 if t["day"] < week_cutoff)
    tonnage_trend = trend_emoji(tonnage, prev_week_tonnage)

    bmi_val = bmi(float(user["weight_kg"]), float(user["height_cm"]))
    bmi_str = bmi_status(bmi_val)
    weight_current = stats.get("current_weight_kg")
    weight_change = stats.get("weight_change_kg")

    # ✅ ИСПРАВЛЕНИЕ: обработка None
    if weight_current is not None and weight_change is not None:
        weight_trend = trend_emoji(weight_current, weight_current - weight_change)
    else:
        weight_trend = "⚪"

    lines = [
        f"📊 <b>Статистика за 7 дней</b>",
        f"👤 {html.escape(str(user['username']))} | Цель: {user['goal']}",
        "",
        f"🥗 <b>Питание</b>",
        f"{cal_bar} от цели ({avg_cal:.0f} ккал/день) {cal_trend}",
        f"Белка: {stats['total_protein_g']:.0f} г {status_icon(stats['total_protein_g'], 7 * metrics['protein_g_target'])}",
        f"Приёмов пищи: {len(food_log)}",
        "",
        f"🏋️ <b>Тренировки</b>",
        f"Дней: {stats['workout_days']} из 7",
        f"Тоннаж: {tonnage:.0f} кг {tonnage_trend}",
    ]
    if tonnage_history:
        lines.append(f"Нагрузка: {mini_graph([t['tonnage'] for t in tonnage_history])}")
    lines.append("")
    lines.append(f"⚖️ <b>Вес</b>")
    if weight_current:
        lines.append(f"Текущий: {weight_current} кг {weight_trend}")
    if bmi_val:
        lines.append(f"ИМТ: {bmi_val} — {bmi_str}")

    if weight_history:
        w_vals = [w["weight"] for w in weight_history]
        lines.append(f"Динамика: {mini_graph(w_vals)}")

    await message.answer("\n".join(lines))


@router.message(Command("premium_stats"))
async def cmd_premium_stats(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    if not check_subscription_active(uid):
        await message.answer(
            "Эта функция доступна только с Premium подпиской.\n"
            "Используй /premium чтобы узнать подробности."
        )
        return

    metrics = compute_profile(
        weight_kg=float(user["weight_kg"]),
        height_cm=float(user["height_cm"]),
        age=int(user["age"]),
        gender=user["gender"],
        activity=user["activity"],
        goal=user["goal"],
    )

    cal_history = get_calories_history(uid, days=30)
    weight_history = get_weight_history(uid, days=30)
    tonnage_history = get_tonnage_history(uid, days=30)

    avg_cal_30 = sum(d["calories"] for d in cal_history) / max(len(cal_history), 1)
    total_tonnage_30 = sum(d["tonnage"] for d in tonnage_history)
    workout_days_30 = len([t for t in tonnage_history if t["tonnage"] > 0])

    lines = [
        f"⭐ <b>Premium статистика за 30 дней</b>",
        f"👤 {html.escape(str(user['username']))}",
        "",
        f"🥗 <b>Питание</b>",
        f"Среднее: {avg_cal_30:.0f} ккал/день (цель {metrics['daily_calorie_goal']} ккал)",
        f"График калорий: {mini_graph([d['calories'] for d in cal_history])}",
        "",
        f"⚖️ <b>Вес</b>",
    ]
    if weight_history:
        w_vals = [w["weight"] for w in weight_history]
        lines.append(f"Динамика: {mini_graph(w_vals)}")
        first_w = weight_history[0]["weight"]
        last_w = weight_history[-1]["weight"]
        lines.append(f"Изменение: {last_w - first_w:+.1f} кг за 30 дней")
    else:
        lines.append("Нет данных")

    lines.append("")
    lines.append(f"🏋️ <b>Тренировки</b>")
    lines.append(f"Тренировочных дней: {workout_days_30} из 30")
    lines.append(f"Тоннаж всего: {total_tonnage_30:.0f} кг")
    if tonnage_history:
        lines.append(f"Нагрузка: {mini_graph([t['tonnage'] for t in tonnage_history])}")

    await message.answer("\n".join(lines))