"""AI-планы питания."""

import logging

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from datetime import datetime, timedelta

from core.database import get_user
from core.referrals import check_subscription_active, get_ai_limit, use_ai_feature
from core.ai.ai_router import ai_router

logger = logging.getLogger(__name__)

router = Router()


# ═══════════════════════════════════════════════════════════════
# AI-ПЛАН ПИТАНИЯ НА ДЕНЬ
# ═══════════════════════════════════════════════════════════════

@router.message(Command("ai_plan"))
async def cmd_ai_plan(message: Message, user_id: int = None):
    """Сгенерировать AI-план питания на день."""
    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    # ═══════════════════════════════════════════════════════════════
    # ПРОВЕРКА PREMIUM
    # ═══════════════════════════════════════════════════════════════

    is_premium = check_subscription_active(uid)

    if not is_premium:
        # Проверяем лимит
        limit_info = get_ai_limit(uid, "ai_chat")  # Используем общий лимит

        if not limit_info["can_use"]:
            reset_at = limit_info.get("reset_at")
            reset_text = ""
            if reset_at:
                try:
                    reset_dt = datetime.fromisoformat(reset_at)
                    reset_text = f"\n\nСброс: {reset_dt.strftime('%d.%m в %H:%M')}"
                except:
                    pass

            await message.answer(
                f"⚠️ <b>AI-планы доступны только Premium</b>\n\n"
                f"У вас осталось: {limit_info['remaining']} AI-запросов{reset_text}\n\n"
                "⭐ Premium снимает все ограничения!\n"
                "Используй /premium для подключения."
            )
            return

    # ═══════════════════════════════════════════════════════════════
    # ГЕНЕРИРУЕМ ПЛАН
    # ═══════════════════════════════════════════════════════════════

    status_message = await message.answer("🤖 <b>AI составляет план...</b>")

    try:
        # Формируем запрос к AI
        goal = user.get("goal", "maintain")
        weight = user.get("weight_kg", 70)
        height = user.get("height_cm", 175)
        age = user.get("age", 25)
        gender = user.get("gender", "male")

        question = f"""
Составь подробный план питания на день для:
- Цель: {goal}
- Вес: {weight}кг
- Рост: {height}см
- Возраст: {age} лет
- Пол: {gender}

Включи:
1. Завтрак (название, продукты, КБЖУ)
2. Перекус (название, продукты, КБЖУ)
3. Обед (название, продукты, КБЖУ)
4. Перекус (название, продукты, КБЖУ)
5. Ужин (название, продукты, КБЖУ)

Итого за день: калории, белки, жиры, углеводы.

Ответ в формате:
- Приём пищи: название
  Продукты: список
  КБЖУ: К ккал, Б г, Ж г, У г
"""

        result = await ai_router.get_answer(
            user_id=uid,
            question=question,
            context={"goal": goal, "type": "meal_plan"},
        )

        await message.bot.delete_message(uid, status_message.message_id)

        # ═══════════════════════════════════════════════════════════════
        # ФОРМИРУЕМ ОТВЕТ
        # ═══════════════════════════════════════════════════════════════

        answer = result["answer"]

        text = f"🍽️ <b>AI-план питания на день</b>\n\n"
        text += f"<i>Цель: {goal}, {weight}кг</i>\n\n"
        text += f"{answer}\n\n"

        # Кнопки
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Перегенерировать", callback_data="ai_plan_regenerate")],
        ])

        await message.answer(text, reply_markup=keyboard)

        # Логируем использование
        if not is_premium:
            use_ai_feature(uid, "ai_chat")

    except Exception as e:
        logger.exception("AI plan error: %s", e)
        await message.bot.delete_message(uid, status_message.message_id)
        await message.answer("❌ Ошибка при создании плана. Попробуй позже.")


# ═══════════════════════════════════════════════════════════════
# AI-ПЕРЕГЕНЕРАЦИЯ ПЛАНА
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "ai_plan_regenerate")
async def cb_ai_plan_regenerate(callback: F, user_id: int = None):
    """Перегенерировать план питания."""
    uid = user_id if user_id else callback.from_user.id

    is_premium = check_subscription_active(uid)

    if not is_premium:
        await callback.answer("⚠️ Перегенерация доступна только Premium", show_alert=True)
        return

    await callback.answer()
    await callback.message.delete()
    await cmd_ai_plan(callback.message, user_id=uid)
