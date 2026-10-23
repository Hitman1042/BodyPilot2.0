"""Обработчик логирования веса (только команда, с поддержкой user_id)."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from core.database import log_weight, get_user, update_user
from core.nutrition_calc import bmi, bmi_category
from core.gamification import notify_progress

router = Router()


class WeightLog(StatesGroup):
    waiting_for_weight = State()


def _get_user_id(message: Message, user_id: int = None) -> int:
    return user_id if user_id else message.from_user.id


@router.message(Command("log_weight"))
async def cmd_log_weight(message: Message, state: FSMContext, user_id: int = None):
    uid = _get_user_id(message, user_id)
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await state.clear()
    await state.set_state(WeightLog.waiting_for_weight)
    await state.update_data(_user_id=uid)
    await message.answer("Введи свой текущий вес в килограммах (например, 75.5):")


@router.message(WeightLog.waiting_for_weight)
async def process_weight(message: Message, state: FSMContext):
    raw = message.text.strip().replace(",", ".")
    try:
        weight = float(raw)
        if weight <= 0 or weight > 300:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введи число от 1 до 300 (кг).")
        return

    data = await state.get_data()
    user_id = data.get("_user_id") or message.from_user.id
    user = get_user(user_id)
    if not user:
        await state.clear()
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    log_weight(user_id, weight)
    update_user(user_id, weight_kg=weight)

    bmi_val = bmi(weight, float(user.get("height_cm", 170)))
    bmi_cat = bmi_category(bmi_val)

    BMI_LABEL = {
        "underweight": "недостаточный вес",
        "normal": "норма",
        "overweight": "избыточный вес",
        "obese": "ожирение",
        "unknown": "неизвестно",
    }

    await state.clear()
    await message.answer(
        f"⚖️ <b>Вес обновлён:</b> {weight} кг\n"
        f"• ИМТ (BMI): {bmi_val} ({BMI_LABEL.get(bmi_cat, bmi_cat)})\n\n"
        f"Профиль обновлён. Используй /profile для просмотра."
    )
    await notify_progress(message, user_id)
