"""Обработчики трекера питания."""

from aiogram import Router, F
import html
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from core.ai.food_search import ai_search_products, search_products
from core.nutrition_tracker import (
    search_food, get_food_by_id, add_food_entry, add_custom_food_entry,
    add_food_product, get_today_summary, get_food_log_today,
)
from core.database import get_user
from core.nutrition_calc import get_nutrition_plan
from core.gamification import notify_progress
from core.api_clients import get_product_by_barcode_off

router = Router()

MEAL_TYPE_MAP = {
    "завтрак": "breakfast",
    "обед": "lunch",
    "ужин": "dinner",
    "перекус": "snack",
}


class AddFood(StatesGroup):
    waiting_for_meal_type = State()
    waiting_for_food = State()
    waiting_for_weight = State()


class LogMeal(StatesGroup):
    waiting_for_product = State()
    waiting_for_weight = State()
    waiting_for_calories = State()
    waiting_for_protein = State()
    waiting_for_fat = State()
    waiting_for_carbs = State()
    waiting_for_meal_type = State()


class AddProduct(StatesGroup):
    waiting_for_name = State()
    waiting_for_category = State()
    waiting_for_calories = State()
    waiting_for_protein = State()
    waiting_for_fat = State()
    waiting_for_carbs = State()


class BarcodeSearch(StatesGroup):
    waiting_for_barcode = State()
    waiting_for_weight = State()


# ═══════════════════════════════════════════════════════════════
# КОМАНДЫ
# ═══════════════════════════════════════════════════════════════

@router.message(Command("add_food"))
async def cmd_add_food(message: Message, state: FSMContext, user_id: int = None):
    """Добавить еду в дневник."""
    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    # Авто-выбор по времени
    from datetime import datetime
    hour = datetime.now().hour
    if 6 <= hour < 11:
        default_meal = "breakfast"
        default_text = "🌅 Завтрак"
    elif 11 <= hour < 15:
        default_meal = "lunch"
        default_text = "☀️ Обед"
    elif 15 <= hour < 18:
        default_meal = "snack"
        default_text = "🍎 Перекус"
    else:
        default_meal = "dinner"
        default_text = "🌙 Ужин"

    await state.update_data(meal_type=default_meal)

    await message.answer(
        f"🍽 <b>Добавление еды</b>\n\n"
        f"🕒 Сейчас: {default_text} (можно изменить)\n\n"
        "Напиши название продукта:\n"
        "<i>Например: гречка, куриная грудка, борщ</i>"
    )

    await state.set_state(AddFood.waiting_for_food)


@router.message(Command("food_today"))
async def cmd_food_today(message: Message, user_id: int = None):
    """Показать сводку за сегодня."""
    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    summary = get_today_summary(uid)
    plan = get_nutrition_plan(uid)
    log = get_food_log_today(uid)

    def progress_bar(current, target, length=10):
        if target <= 0:
            return "─" * length
        percent = min(current / target, 1.0)
        filled = int(length * percent)
        return "█" * filled + "─" * (length - filled)

    cal_progress = progress_bar(summary.get("total_calories", 0), plan.get("target_calories", 2000))
    prot_progress = progress_bar(summary.get("total_protein_g", 0), plan.get("macros", {}).get("protein_g", 150))

    text = f"📅 <b>Питание за сегодня</b>\n"
    text += f"<i>{summary.get('date', '')}</i>\n\n"

    text += f"🔥 <b>Калории:</b> {summary.get('total_calories', 0)} / {plan.get('target_calories', 2000)} ккал\n"
    text += f"`[{cal_progress}]`\n\n"

    text += f"🥩 <b>Белок:</b> {summary.get('total_protein_g', 0)} / {plan.get('macros', {}).get('protein_g', 150)}г\n"
    text += f"`[{prot_progress}]`\n\n"

    text += f"📊 <b>БЖУ за день:</b>\n"
    text += f"• Белки: {summary.get('total_protein_g', 0)}г\n"
    text += f"• Жиры: {summary.get('total_fat_g', 0)}г\n"
    text += f"• Углеводы: {summary.get('total_carbs_g', 0)}г\n\n"

    meal_names = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин", "snack": "Перекус"}
    text += f"🍽 <b>Приёмы пищи:</b>\n"
    text += f"• {meal_names.get('breakfast')}: {summary.get('breakfast_calories', 0)} ккал\n"
    text += f"• {meal_names.get('lunch')}: {summary.get('lunch_calories', 0)} ккал\n"
    text += f"• {meal_names.get('dinner')}: {summary.get('dinner_calories', 0)} ккал\n"
    text += f"• {meal_names.get('snack')}: {summary.get('snack_calories', 0)} ккал\n\n"

    if log:
        text += f"📋 <b>Последние записи:</b>\n"
        for entry in log[:5]:
            meal = meal_names.get(entry.get('meal_type', 'snack'), 'Перекус')
            text += f"• {html.escape(str(entry['product_name']))} ({entry['weight_g']}г) — {entry['calories']} ккал ({meal})\n"

    text += f"\n💡 Используй /add_food чтобы добавить еду."

    await message.answer(text)


# ═══════════════════════════════════════════════════════════════
# ПОИСК ПРОДУКТА (текст)
# ═══════════════════════════════════════════════════════════════

@router.message(AddFood.waiting_for_food)
async def process_food_search(message: Message, state: FSMContext):
    query = message.text.strip()

    import re
    weight_match = re.search(r'(\d+)\s*г', query)
    weight = int(weight_match.group(1)) if weight_match else None

    food_name = re.sub(r'\s*\d+\s*г', '', query).strip() if weight_match else query

    # ═══════════════════════════════════════════════════════════════
    # AI-ПОИСК С СИНОНИМАМИ
    # ═══════════════════════════════════════════════════════════════

    # Получаем цель пользователя для AI-советов
    data = await state.get_data()
    uid = data.get("_user_id") or message.from_user.id
    user = get_user(uid)
    user_goal = user.get("goal", "maintain") if user else "maintain"

    # AI-поиск
    search_result = ai_search_products(food_name, user_goal)
    products = search_result.get("products", [])
    ai_tip = search_result.get("ai_tip", "")

    # Конвертируем в формат который ожидает код ниже
    results = []
    for p in products[:5]:
        results.append({
            "id": p["id"],
            "name": p["name"],
            "calories_100g": p.get("calories", 0),
            "protein_100g": p.get("protein", 0),
            "fat_100g": p.get("fat", 0),
            "carbs_100g": p.get("carbs", 0),
        })

    if not results:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🕒 Изменить тип приёма", callback_data="change_meal_type")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="food_cancel")],
        ])

        await message.answer(
            f"❌ Ничего не найдено по запросу \"{html.escape(food_name)}\"\n\n"
            f"{html.escape(ai_tip)}\n\n"  # ← AI-СОВЕТ
            "Попробуй другое название.",
            reply_markup=keyboard
        )
        return

    keyboard = []
    for r in results[:5]:
        kb_text = f"{r['name']} ({r['calories_100g']} ккал/100г)"
        keyboard.append([InlineKeyboardButton(text=kb_text, callback_data=f"food_{r['id']}")])

    keyboard.append([InlineKeyboardButton(text="❌ Не то, искать снова", callback_data="food_search_again")])
    keyboard.append([InlineKeyboardButton(text="🕒 Изменить тип приёма", callback_data="change_meal_type")])

    await state.update_data(food_name=food_name, search_weight=weight)

    data = await state.get_data()
    meal_type = data.get("meal_type", "snack")
    meal_names = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин", "snack": "Перекус"}

    await message.answer(
        f"🔍 Найдено по запросу \"{html.escape(food_name)}\":\n"
        f"🕒 Тип: <b>{meal_names.get(meal_type, meal_type)}</b>\n\n"
        "Выбери продукт:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data == "food_search_again")
async def process_search_again(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddFood.waiting_for_food)
    await callback.message.edit_text("Напиши название продукта для поиска:")
    await callback.answer()


@router.callback_query(F.data == "change_meal_type")
async def process_change_meal(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Завтрак", callback_data="meal_breakfast")],
        [InlineKeyboardButton(text="☀️ Обед", callback_data="meal_lunch")],
        [InlineKeyboardButton(text="🌙 Ужин", callback_data="meal_dinner")],
        [InlineKeyboardButton(text="🍎 Перекус", callback_data="meal_snack")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="meal_back")],
    ])

    await callback.message.edit_text("🕒 Выбери тип приёма пищи:")
    await state.set_state(AddFood.waiting_for_meal_type)
    await callback.answer()


@router.callback_query(F.data.startswith("meal_"))
async def process_meal_type_select(callback: CallbackQuery, state: FSMContext):
    meal_type = callback.data.split("_")[1]

    if meal_type == "back":
        await state.set_state(AddFood.waiting_for_food)
        await callback.message.edit_text("Напиши название продукта для поиска:")
        await callback.answer()
        return

    await state.update_data(meal_type=meal_type)

    meal_names = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин", "snack": "Перекус"}
    await callback.message.edit_text(f"✅ Выбрано: <b>{meal_names.get(meal_type, meal_type)}</b>\n\nТеперь напиши название продукта:")
    await state.set_state(AddFood.waiting_for_food)
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# ВВОД ВЕСА (текст)
# ═══════════════════════════════════════════════════════════════

@router.message(AddFood.waiting_for_weight)
async def process_weight_input(message: Message, state: FSMContext):
    """Обработка ввода веса пользователем."""
    try:
        weight = int(message.text.strip().replace('г', '').replace(' ', ''))
    except ValueError:
        await message.answer("❌ Введи число (например: 200)")
        return

    data = await state.get_data()
    food_id = data.get("selected_food_id")

    if not food_id:
        await message.answer("❌ Ошибка: продукт не выбран. Начни сначала с /add_food")
        await state.clear()
        return

    food = get_food_by_id(food_id)
    if not food:
        await message.answer("❌ Продукт не найден")
        await state.clear()
        return

    meal_type = data.get("meal_type", "snack")

    multiplier = weight / 100.0
    calories = round(food["calories_100g"] * multiplier, 1)
    protein = round(food["protein_100g"] * multiplier, 1)
    fat = round(food["fat_100g"] * multiplier, 1)
    carbs = round(food["carbs_100g"] * multiplier, 1)

    await state.update_data(selected_weight=weight)

    text = (
        f"✅ <b>{html.escape(str(food['name']))}</b>\n\n"
        f"📊 <b>На 100г:</b> {food['calories_100g']} ккал | Б {food['protein_100g']}г | Ж {food['fat_100g']}г | У {food['carbs_100g']}г\n\n"
        f"⚖️ <b>Вес:</b> {weight}г\n"
        f"📊 <b>Итого:</b> {calories} ккал | Б {protein}г | Ж {fat}г | У {carbs}г\n\n"
        f"Подтвердить?"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, добавить", callback_data="food_confirm")],
        [InlineKeyboardButton(text="✏️ Изменить вес", callback_data="food_change_weight")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="food_cancel")],
    ])

    await message.answer(text, reply_markup=keyboard)


# ═══════════════════════════════════════════════════════════════
# ВЫБОР ПРОДУКТА (food_{id})
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.regexp(r"^food_\d+$"))
async def process_food_select(callback: CallbackQuery, state: FSMContext):
    food_id = int(callback.data.split("_")[1])
    food = get_food_by_id(food_id)

    if not food:
        await callback.answer("❌ Продукт не найден")
        return

    data = await state.get_data()
    weight = data.get("search_weight") or food.get("serving_size_g", 100)
    meal_type = data.get("meal_type", "snack")

    multiplier = weight / 100.0
    calories = round(food["calories_100g"] * multiplier, 1)
    protein = round(food["protein_100g"] * multiplier, 1)
    fat = round(food["fat_100g"] * multiplier, 1)
    carbs = round(food["carbs_100g"] * multiplier, 1)

    await state.update_data(selected_food_id=food_id, selected_weight=weight)

    meal_names = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин", "snack": "Перекус"}

    text = (
        f"✅ <b>{html.escape(str(food['name']))}</b>\n\n"
        f"🕒 <b>Тип:</b> {meal_names.get(meal_type, meal_type)}\n\n"
        f"📊 <b>На 100г:</b> {food['calories_100g']} ккал | Б {food['protein_100g']}г | Ж {food['fat_100g']}г | У {food['carbs_100g']}г\n\n"
        f"⚖️ <b>Вес:</b> {weight}г\n"
        f"📊 <b>Итого:</b> {calories} ккал | Б {protein}г | Ж {fat}г | У {carbs}г\n\n"
        f"Подтвердить?"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, добавить", callback_data="food_confirm")],
        [InlineKeyboardButton(text="✏️ Изменить вес", callback_data="food_change_weight")],
        [InlineKeyboardButton(text="🕒 Изменить тип", callback_data="change_meal_type")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="food_cancel")],
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# ИЗМЕНИТЬ ВЕС
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "food_change_weight")
async def process_change_weight(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✏️ Введи новый вес (в граммах):")
    await state.set_state(AddFood.waiting_for_weight)
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# ПОДТВЕРДИТЬ
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "food_confirm")
async def process_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    uid = callback.from_user.id

    food_id = data.get("selected_food_id")
    weight = data.get("selected_weight", 100)
    meal_type = data.get("meal_type", "snack")

    food = get_food_by_id(food_id)
    if not food:
        await callback.message.edit_text("❌ Ошибка: продукт не найден")
        await state.clear()
        return

    entry_id = add_food_entry(
        user_id=uid,
        product_id=food_id,
        product_name=food["name"],
        weight_g=weight,
        calories_100g=food["calories_100g"],
        protein_100g=food["protein_100g"],
        fat_100g=food["fat_100g"],
        carbs_100g=food["carbs_100g"],
        meal_type=meal_type,
    )

    summary = get_today_summary(uid)
    plan = get_nutrition_plan(uid)

    meal_names = {"breakfast": "завтрак", "lunch": "обед", "dinner": "ужин", "snack": "перекус"}

    text = (
        f"✅ <b>Добавлено!</b>\n\n"
        f"{html.escape(str(food['name']))} — {weight}г ({meal_names.get(meal_type, 'перекус')})\n\n"
        f"📊 <b>Прогресс за сегодня:</b>\n"
        f"🔥 Калории: {summary.get('total_calories', 0)} / {plan.get('target_calories', 2000)} ккал\n"
        f"🥩 Белок: {summary.get('total_protein_g', 0)} / {plan.get('macros', {}).get('protein_g', 150)}г\n\n"
        f"Используй /food_today чтобы увидеть полный отчёт.\n\n"
        f"Напиши, что ещё съел, или пришли фото 📸"
    )

    await callback.message.edit_text(text)
    await state.clear()
    await callback.answer()
    await notify_progress(callback.message, uid)


# ═══════════════════════════════════════════════════════════════
# ОТМЕНА
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "food_cancel")
async def process_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()

# ═══════════════════════════════════════════════════════════════
# АЛИАСЫ КОМАНД (единый трекер питания)
# ═══════════════════════════════════════════════════════════════

@router.message(Command("today"))
async def cmd_today(message: Message, user_id: int = None):
    """Алиас /food_today."""
    await cmd_food_today(message, user_id=user_id)


@router.message(Command("search_food"))
async def cmd_search_food(message: Message, state: FSMContext, user_id: int = None):
    """Алиас /add_food (поиск продукта и запись в дневник)."""
    await cmd_add_food(message, state, user_id=user_id)


# ═══════════════════════════════════════════════════════════════
# РУЧНОЙ ВВОД КБЖУ (/log_meal)
# ═══════════════════════════════════════════════════════════════

@router.message(Command("log_meal"))
async def cmd_log_meal(message: Message, state: FSMContext, user_id: int = None):
    """Записать приём пищи вручную (название + КБЖУ)."""
    uid = user_id if user_id else message.from_user.id
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await state.clear()
    await state.update_data(_user_id=user_id if user_id else message.from_user.id)
    await message.answer("Что ты съел? Напиши название продукта или блюда.")
    await state.set_state(LogMeal.waiting_for_product)


@router.message(LogMeal.waiting_for_product)
async def process_log_product(message: Message, state: FSMContext):
    product = message.text.strip()
    if not product:
        await message.answer("Пожалуйста, введи название продукта.")
        return
    await state.update_data(product=product)
    await message.answer("Сколько граммов? (например, 200)")
    await state.set_state(LogMeal.waiting_for_weight)


@router.message(LogMeal.waiting_for_weight)
async def process_log_weight(message: Message, state: FSMContext):
    try:
        weight = float(message.text.strip().replace(",", "."))
        if weight <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введи положительное число граммов.")
        return
    await state.update_data(weight=weight)
    await message.answer("Сколько килокалорий?")
    await state.set_state(LogMeal.waiting_for_calories)


@router.message(LogMeal.waiting_for_calories)
async def process_log_calories(message: Message, state: FSMContext):
    try:
        cal = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Пожалуйста, введи число.")
        return
    await state.update_data(calories=cal)
    await message.answer("Сколько граммов белка?")
    await state.set_state(LogMeal.waiting_for_protein)


@router.message(LogMeal.waiting_for_protein)
async def process_log_protein(message: Message, state: FSMContext):
    try:
        prot = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Пожалуйста, введи число.")
        return
    await state.update_data(protein=prot)
    await message.answer("Сколько граммов жиров?")
    await state.set_state(LogMeal.waiting_for_fat)


@router.message(LogMeal.waiting_for_fat)
async def process_log_fat(message: Message, state: FSMContext):
    try:
        fat = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Пожалуйста, введи число.")
        return
    await state.update_data(fat=fat)
    await message.answer("Сколько граммов углеводов?")
    await state.set_state(LogMeal.waiting_for_carbs)


@router.message(LogMeal.waiting_for_carbs)
async def process_log_carbs(message: Message, state: FSMContext):
    try:
        carbs = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Пожалуйста, введи число.")
        return
    await state.update_data(carbs=carbs)
    await message.answer(
        "Какой это приём пищи?\n"
        "<b>завтрак</b> / <b>обед</b> / <b>ужин</b> / <b>перекус</b>"
    )
    await state.set_state(LogMeal.waiting_for_meal_type)


@router.message(LogMeal.waiting_for_meal_type)
async def process_log_meal_type(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    if answer not in MEAL_TYPE_MAP:
        await message.answer("Выбери из вариантов: завтрак, обед, ужин, перекус")
        return

    data = await state.get_data()
    required = ["product", "calories", "protein", "fat", "carbs", "weight"]
    missing = [f for f in required if f not in data]
    if missing:
        await state.clear()
        await message.answer("⚠️ Данные приёма пищи потеряны. Начни заново с /log_meal.")
        return

    uid = data.get("_user_id") or message.from_user.id
    add_custom_food_entry(
        user_id=uid,
        product_name=data["product"],
        weight_g=data["weight"],
        calories=data["calories"],
        protein_g=data["protein"],
        fat_g=data["fat"],
        carbs_g=data["carbs"],
        meal_type=MEAL_TYPE_MAP[answer],
    )
    summary = get_today_summary(uid)

    await state.clear()
    await message.answer(
        f"✅ <b>Приём пищи записан!</b>\n\n"
        f"• {html.escape(str(data['product']))} — {data['calories']} ккал\n"
        f"• Всего за сегодня: <b>{summary.get('total_calories', 0):.0f} ккал</b>\n\n"
        f"Напиши, что ещё съел, или пришли фото 📸"
    )
    await notify_progress(message, uid)


# ═══════════════════════════════════════════════════════════════
# ДОБАВЛЕНИЕ СВОЕГО ПРОДУКТА (/add_product)
# ═══════════════════════════════════════════════════════════════

@router.message(Command("add_product"))
async def cmd_add_product(message: Message, state: FSMContext, user_id: int = None):
    """Добавить свой продукт в общую базу."""
    uid = user_id if user_id else message.from_user.id
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await state.clear()
    await state.update_data(_user_id=uid)
    await state.set_state(AddProduct.waiting_for_name)
    await message.answer("Введите название продукта:")


@router.message(AddProduct.waiting_for_name)
async def process_add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Название не может быть пустым. Введите ещё раз.")
        return
    await state.update_data(name=name)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Завтрак", callback_data="add_cat_breakfast")],
        [InlineKeyboardButton(text="☀️ Обед", callback_data="add_cat_lunch")],
        [InlineKeyboardButton(text="🌙 Ужин", callback_data="add_cat_dinner")],
        [InlineKeyboardButton(text="🍏 Перекус", callback_data="add_cat_snack")],
    ])
    await message.answer("Выберите категорию продукта:", reply_markup=keyboard)
    await state.set_state(AddProduct.waiting_for_category)


@router.callback_query(AddProduct.waiting_for_category)
async def process_add_category(callback: CallbackQuery, state: FSMContext):
    cat_map = {
        "add_cat_breakfast": "breakfast",
        "add_cat_lunch": "lunch",
        "add_cat_dinner": "dinner",
        "add_cat_snack": "snack",
    }
    cat = cat_map.get(callback.data, "snack")
    await state.update_data(category=cat)
    await callback.message.edit_text(
        f"Категория: {cat}\nТеперь введите калорийность на 100 г (ккал):"
    )
    await state.set_state(AddProduct.waiting_for_calories)
    await callback.answer()


@router.message(AddProduct.waiting_for_calories)
async def process_add_calories(message: Message, state: FSMContext):
    try:
        cal = float(message.text.strip().replace(",", "."))
        if cal <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите положительное число.")
        return
    await state.update_data(calories=cal)
    await message.answer("Введите количество белка (г на 100 г):")
    await state.set_state(AddProduct.waiting_for_protein)


@router.message(AddProduct.waiting_for_protein)
async def process_add_protein(message: Message, state: FSMContext):
    try:
        prot = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(protein=prot)
    await message.answer("Введите количество жиров (г на 100 г):")
    await state.set_state(AddProduct.waiting_for_fat)


@router.message(AddProduct.waiting_for_fat)
async def process_add_fat(message: Message, state: FSMContext):
    try:
        fat = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(fat=fat)
    await message.answer("Введите количество углеводов (г на 100 г):")
    await state.set_state(AddProduct.waiting_for_carbs)


@router.message(AddProduct.waiting_for_carbs)
async def process_add_carbs(message: Message, state: FSMContext):
    try:
        carbs = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Введите число.")
        return
    data = await state.get_data()
    uid = data.get("_user_id") or message.from_user.id
    result = add_food_product(
        name=data["name"],
        category=data["category"],
        calories=data["calories"],
        protein=data["protein"],
        fat=data["fat"],
        carbs=carbs,
        brand="",
        source="custom",
        added_by=uid,
        is_verified=0,
    )
    await state.clear()
    if result:
        await message.answer(f"✅ Продукт «{html.escape(str(data['name']))}» добавлен! Другие пользователи смогут его использовать.")
    else:
        await message.answer(f"⚠️ Продукт «{html.escape(str(data['name']))}» уже существует в базе.")


# ═══════════════════════════════════════════════════════════════
# ПОИСК ПО ШТРИХ-КОДУ (/barcode)
# ═══════════════════════════════════════════════════════════════

@router.message(Command("barcode"))
async def cmd_barcode(message: Message, state: FSMContext, user_id: int = None):
    """Найти продукт по штрих-коду и записать в дневник."""
    await state.clear()

    uid = user_id if user_id else message.from_user.id
    user = get_user(uid)

    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    await state.update_data(_user_id=uid)
    await message.answer(
        "📱 <b>Поиск по штрих-коду</b>\n\n"
        "Напиши штрих-код продукта (цифры):\n"
        "<i>Например: 4600000000000</i>"
    )
    await state.set_state(BarcodeSearch.waiting_for_barcode)


@router.message(BarcodeSearch.waiting_for_barcode)
async def process_barcode(message: Message, state: FSMContext):
    text = message.text.strip()

    if not (text.isdigit() and len(text) >= 8):
        await message.answer(
            "Штрих-код — это 8 и более цифр. Попробуй ещё раз или выйди через /menu."
        )
        return

    product = await get_product_by_barcode_off(text)

    if not product:
        await message.answer(
            f"❌ Продукт со штрих-кодом {text} не найден.\n\n"
            "Попробуй написать название продукта через /add_food."
        )
        await state.clear()
        return

    await state.update_data(selected_product=product, barcode=text)
    await message.answer(
        f"🔍 <b>Найден продукт!</b>\n\n"
        f"📦 <b>{html.escape(str(product['name']))}</b>\n"
        f"🏷️ Бренд: {html.escape(str(product['brand']))}\n"
        f"📊 Штрих-код: {text}\n\n"
        f"<b>КБЖУ на 100г:</b>\n"
        f"🔥 Калории: {product['calories_100g']} ккал\n"
        f"🥩 Белки: {product['protein_100g']}г\n"
        f"🥑 Жиры: {product['fat_100g']}г\n"
        f"🍞 Углеводы: {product['carbs_100g']}г\n\n"
        "Сколько граммов ты съел?"
    )
    await state.set_state(BarcodeSearch.waiting_for_weight)


@router.message(BarcodeSearch.waiting_for_weight)
async def process_barcode_weight(message: Message, state: FSMContext):
    try:
        weight = float(message.text.strip().replace(",", "."))
        if weight <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введи положительное число граммов.")
        return

    data = await state.get_data()
    product = data.get("selected_product")
    barcode = data.get("barcode")
    if not product:
        await state.clear()
        await message.answer("⚠️ Данные продукта потеряны. Начни заново с /barcode.")
        return

    uid = data.get("_user_id") or message.from_user.id

    product_id = add_food_product(
        name=product["name"],
        brand=product.get("brand", ""),
        calories=product["calories_100g"],
        protein=product["protein_100g"],
        fat=product["fat_100g"],
        carbs=product["carbs_100g"],
        source="off",
        source_id=barcode,
        is_verified=0,
    )
    if product_id is None:
        existing = search_food(product["name"], limit=1)
        product_id = existing[0]["id"] if existing else None

    from datetime import datetime
    hour = datetime.now().hour
    if 6 <= hour < 11:
        meal_type = "breakfast"
    elif 11 <= hour < 15:
        meal_type = "lunch"
    elif 15 <= hour < 18:
        meal_type = "snack"
    else:
        meal_type = "dinner"

    if product_id:
        add_food_entry(
            user_id=uid,
            product_id=product_id,
            product_name=product["name"],
            weight_g=weight,
            calories_100g=product["calories_100g"],
            protein_100g=product["protein_100g"],
            fat_100g=product["fat_100g"],
            carbs_100g=product["carbs_100g"],
            meal_type=meal_type,
        )
        calories = round(product["calories_100g"] * weight / 100, 1)
    else:
        factor = weight / 100.0
        calories = round(product["calories_100g"] * factor, 1)
        add_custom_food_entry(
            user_id=uid,
            product_name=product["name"],
            weight_g=weight,
            calories=calories,
            protein_g=round(product["protein_100g"] * factor, 1),
            fat_g=round(product["fat_100g"] * factor, 1),
            carbs_g=round(product["carbs_100g"] * factor, 1),
            meal_type=meal_type,
        )

    summary = get_today_summary(uid)
    await state.clear()
    await message.answer(
        f"✅ <b>Записано:</b> {html.escape(str(product['name']))} ({weight:.0f}г) — ~{calories:.0f} ккал\n"
        f"Всего за сегодня: <b>{summary.get('total_calories', 0):.0f} ккал</b>"
    )
    await notify_progress(message, uid)

