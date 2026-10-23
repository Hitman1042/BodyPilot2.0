"""Обработчики выбора вида спорта."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from core.sports.catalog import (
    get_all_sports,
    get_sport,
    get_sport_icon,
    get_sport_description,
    set_user_sport,
    get_user_sport,
)
from core.database import get_user

router = Router()


class SportSelection(StatesGroup):
    choosing_sport = State()
    choosing_level = State()


@router.message(Command("set_sport"))
async def cmd_set_sport(message: Message, state: FSMContext, user_id: int = None):
    uid = user_id if user_id else message.from_user.id
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    current_sport = get_user_sport(uid)
    text = "🏃 <b>Выбор вида спорта</b>\n\nЭто поможет нам подбирать правильные тренировки!\n\n"

    if current_sport and current_sport.get('sport_id'):
        icon = get_sport_icon(current_sport.get('name_en', ''))
        text += f"📊 <b>Текущий:</b> {icon} {current_sport.get('name', 'Не выбран')}\n"
        text += f"📈 Уровень: {current_sport.get('sport_level', 'beginner')}\n\n"

    text += "Выбери вид спорта:"

    sports = get_all_sports()
    keyboard = [
        [InlineKeyboardButton(text=f"{get_sport_icon(s['name_en'])} {s['name']}", callback_data=f"sport_{s['id']}")] for
        s in sports]
    keyboard.append([InlineKeyboardButton(text="✏️ Пропустить (общий план)", callback_data="sport_skip")])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await state.set_state(SportSelection.choosing_sport)


@router.callback_query(SportSelection.choosing_sport)
async def process_sport_selection(callback: CallbackQuery, state: FSMContext):
    if callback.data == "sport_skip":
        await state.clear()
        await callback.message.edit_text("✅ Ок, будем составлять общие планы.")
        await callback.answer()
        return

    try:
        sport_id = int(callback.data.split("_")[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Выбери вид спорта кнопкой ниже")
        return
    await state.update_data(sport_id=sport_id)
    sport = get_sport(sport_id)

    if not sport:
        await callback.answer("❌ Ошибка: вид спорта не найден")
        return

    text = f"✅ <b>{sport['icon']} {sport['name']}</b>\n\n{get_sport_description(sport['name_en'])}\n\n"
    text += "📈 <b>Выбери уровень:</b>\n\n"
    text += "• <b>Beginner</b> — новичок (менее 6 месяцев)\n"
    text += "• <b>Intermediate</b> — средний (6 мес — 2 года)\n"
    text += "• <b>Advanced</b> — продвинутый (более 2 лет)"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔰 Beginner", callback_data="level_beginner")],
        [InlineKeyboardButton(text="📈 Intermediate", callback_data="level_intermediate")],
        [InlineKeyboardButton(text="🔥 Advanced", callback_data="level_advanced")],
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await state.set_state(SportSelection.choosing_level)
    await callback.answer()


@router.callback_query(SportSelection.choosing_level)
async def process_level_selection(callback: CallbackQuery, state: FSMContext):
    level_map = {"level_beginner": "beginner", "level_intermediate": "intermediate", "level_advanced": "advanced"}
    sport_level = level_map.get(callback.data, "beginner")
    data = await state.get_data()
    sport_id = data.get('sport_id')
    user_id = callback.from_user.id

    success = set_user_sport(user_id, sport_id, sport_level)

    if success:
        sport = get_sport(sport_id)
        icon = get_sport_icon(sport['name_en']) if sport else "🏃"
        text = f"✅ <b>Готово!</b>\n\nТвой вид спорта: {icon} {sport['name']}\nУровень: {sport_level}\n\n"
        text += "🎯 Теперь тренировки будут подбираться с учётом твоего вида спорта!\n\n"
        text += "Используй /workout_plan чтобы увидеть новый план."
        await callback.message.edit_text(text)
    else:
        await callback.message.edit_text("❌ Произошла ошибка при сохранении.")

    await state.clear()
    await callback.answer()


@router.message(Command("my_sport"))
async def cmd_my_sport(message: Message, user_id: int = None):
    uid = user_id if user_id else message.from_user.id
    user_sport = get_user_sport(uid)

    if not user_sport or not user_sport.get('sport_id'):
        await message.answer("🏃 <b>Вид спорта не выбран</b>\n\nИспользуй /set_sport чтобы выбрать.")
        return

    icon = get_sport_icon(user_sport.get('name_en', ''))
    text = f"📊 <b>Твой профиль</b>\n\n"
    text += f"🏃 <b>Вид спорта:</b> {icon} {user_sport.get('name', 'Не выбран')}\n"
    text += f"📈 <b>Уровень:</b> {user_sport.get('sport_level', 'beginner')}\n"
    text += f"📅 <b>Этап:</b> {user_sport.get('training_phase', 'general')}\n\n"
    text += f"💡 Используй /set_sport чтобы изменить."

    await message.answer(text)