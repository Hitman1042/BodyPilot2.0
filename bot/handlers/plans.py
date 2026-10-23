"""Обработчики премиум-планов питания и тренировок."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.database import get_user
from core.referrals import check_subscription_active
from core.plans import generate_meal_plan
from core.training_service import generate_weekly_workout_plan

router = Router()


def _get_user_id(message: Message, user_id: int = None) -> int:
    return user_id if user_id else message.from_user.id


@router.message(Command("meal_plan"))
async def cmd_meal_plan(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    if not check_subscription_active(uid):
        await message.answer("Эта функция доступна только с Premium подпиской.\nИспользуй /premium чтобы узнать подробности.")
        return

    user["user_id"] = uid
    plan = generate_meal_plan(user)

    text = (
        f"🍽 <b>Твой план питания на сегодня</b>\n\n"
        f"🎯 Цель: {plan['calorie_target']} ккал\n"
        f"📊 Макросы: Б: {plan['macros_target']['protein_g']}г, Ж: {plan['macros_target']['fat_g']}г, У: {plan['macros_target']['carbs_g']}г\n\n"
        f"<b>Завтрак:</b> {plan['meals']['breakfast']['name']} — {plan['meals']['breakfast']['cal']} ккал\n"
        f"<b>Обед:</b> {plan['meals']['lunch']['name']} — {plan['meals']['lunch']['cal']} ккал\n"
        f"<b>Ужин:</b> {plan['meals']['dinner']['name']} — {plan['meals']['dinner']['cal']} ккал\n"
        f"<b>Перекус:</b> {plan['meals']['snack']['name']} — {plan['meals']['snack']['cal']} ккал\n\n"
        f"<b>Итого за день:</b> {plan['total']['calories']} ккал\n"
        f"Б: {plan['total']['protein_g']}г, Ж: {plan['total']['fat_g']}г, У: {plan['total']['carbs_g']}г\n\n"
        f"🔄 Используй «Обновить план» в меню Premium, чтобы получить новый вариант."
    )
    await message.answer(text)


@router.message(Command("workout_plan"))
async def cmd_workout_plan(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    if not check_subscription_active(uid):
        await message.answer("Эта функция доступна только с Premium подпиской.\nИспользуй /premium чтобы узнать подробности.")
        return

    plan = generate_weekly_workout_plan(uid)
    text = f"🏋️ <b>Твой недельный план тренировок</b> ({plan['goal']})\n\n"
    for day in plan["days"]:
        if day["exercises"]:
            text += f"<b>{day['day']} — {day['focus']}:</b>\n"
            for ex in day["exercises"]:
                text += f"• {ex['name']} — {ex['sets']}×{ex['reps']}\n"
            text += "\n"
        else:
            text += f"<b>{day['day']} — Отдых</b>\n\n"
    await message.answer(text)