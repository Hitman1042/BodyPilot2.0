"""Административная панель BodyPilot (с импортом продуктов и статистикой)."""

import html

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta, timezone

from core.config import settings
from core.database import (
    get_user, get_subscription, create_subscription, update_subscription,
    get_db,
)
from core.nutrition_tracker import add_food_product
from core.referrals import get_subscription_info
from core.api_clients import search_food_off_detailed

router = Router()


class AdminSession(StatesGroup):
    waiting_for_password = State()
    active = State()


class GrantPremium(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()


class SearchUser(StatesGroup):
    waiting_for_user_id = State()


class AdminImport(StatesGroup):
    waiting_for_query = State()
    waiting_for_selection = State()
    waiting_for_category = State()


class ManualProduct(StatesGroup):
    waiting_for_name = State()
    waiting_for_category = State()
    waiting_for_calories = State()
    waiting_for_protein = State()
    waiting_for_fat = State()
    waiting_for_carbs = State()


def is_admin(user_id: int, username: str = "") -> bool:
    if username.lower() == settings.TELEGRAM_ADMIN_USERNAME.lower():
        return True

    raw_ids = settings.TELEGRAM_ADMIN_USER_IDS
    admin_ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]

    return user_id in admin_ids


# ── /admin_login ────────────────────────────────────────────────────────

@router.message(Command("admin_login"))
async def cmd_admin_login(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id, message.from_user.username or ""):
        await message.answer("⛔ Доступ запрещён.")
        return
    await state.set_state(AdminSession.waiting_for_password)
    await message.answer("Введите пароль администратора:")


@router.message(AdminSession.waiting_for_password)
async def process_admin_password(message: Message, state: FSMContext):
    try:
        await message.delete()
    except Exception:
        pass
    if message.text.strip() == settings.ADMIN_PASSWORD:
        await state.set_state(AdminSession.active)
        from bot.keyboards.main_menu import get_main_menu
        await message.answer(
            "✅ Вы вошли как администратор.",
            reply_markup=get_main_menu(is_admin=True)
        )
    else:
        await message.answer("❌ Неверный пароль.")
        await state.clear()


@router.message(Command("admin_logout"))
async def cmd_admin_logout(message: Message, state: FSMContext):
    await state.clear()
    from bot.keyboards.main_menu import get_main_menu
    await message.answer("Вы вышли из админ-панели.", reply_markup=get_main_menu(is_admin=False))


# ── Админ-панель ───────────────────────────────────────────────────────

async def show_admin_panel(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_search_user")],
        [InlineKeyboardButton(text="⭐ Выдать Premium", callback_data="admin_grant_premium")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📥 Импорт продуктов", callback_data="admin_import")],
        [InlineKeyboardButton(text="➕ Добавить продукт вручную", callback_data="admin_add_manual")],
        [InlineKeyboardButton(text="📊 Статистика продуктов", callback_data="admin_food_stats")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")],
    ])
    await message.answer("🔧 <b>Администрирование</b>", reply_markup=keyboard)


@router.callback_query(F.data == "admin_panel")
async def open_admin_panel(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state != AdminSession.active.state:
        await callback.answer("Сначала войдите как администратор: /admin_login", show_alert=True)
        return
    await callback.message.edit_text("Выберите действие:")
    await show_admin_panel(callback.message)
    await callback.answer()


# ── Пользователи ────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_users")
async def show_users_list(callback: CallbackQuery):
    conn = get_db()
    rows = conn.execute(
        "SELECT user_id, username, created_at FROM users ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    if not rows:
        await callback.message.edit_text("Нет зарегистрированных пользователей.")
        await callback.answer()
        return
    text = "👥 <b>Последние 20 пользователей:</b>\n\n"
    for r in rows:
        text += f"• ID: <code>{r['user_id']}</code> — {html.escape(str(r['username']))} ({r['created_at'][:10]})\n"
    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data == "admin_search_user")
async def start_search_user(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SearchUser.waiting_for_user_id)
    await callback.message.edit_text("Введите ID пользователя для детального просмотра:")
    await callback.answer()


@router.message(SearchUser.waiting_for_user_id)
async def process_search_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    user = get_user(user_id)
    if not user:
        await message.answer(f"Пользователь с ID {user_id} не найден.")
        await state.clear()
        return
    await state.clear()
    info = get_subscription_info(user_id)
    conn = get_db()
    food_count = conn.execute("SELECT COUNT(*) FROM food_log_new WHERE user_id = ?", (user_id,)).fetchone()[0]
    workout_count = conn.execute("SELECT COUNT(*) FROM workout_log WHERE user_id = ?", (user_id,)).fetchone()[0]
    last_food = conn.execute(
        "SELECT logged_at FROM food_log_new WHERE user_id = ? ORDER BY logged_at DESC LIMIT 1", (user_id,)
    ).fetchone()
    last_activity = last_food["logged_at"][:10] if last_food else "нет"
    GENDER_LABEL = {"male": "мужской", "female": "женский"}
    GOAL_LABEL = {"lose": "похудеть", "maintain": "сохранить", "gain": "набрать"}
    text = (
        f"🔍 <b>Пользователь #{user_id}</b>\n\n"
        f"👤 Имя: {html.escape(str(user['username']))}\n"
        f"⚧ Пол: {GENDER_LABEL.get(user['gender'], user['gender'])}\n"
        f"🎂 Возраст: {user['age']}\n"
        f"📏 Рост: {user['height_cm']} см\n"
        f"⚖️ Вес: {user['weight_kg']} кг\n"
        f"🎯 Цель: {GOAL_LABEL.get(user['goal'], user['goal'])}\n"
        f"🏙 Город: {user.get('city', 'не указан')}\n"
        f"📅 Зарегистрирован: {user['created_at'][:10]}\n"
        f"🕐 Последняя активность: {last_activity}\n\n"
        f"💎 <b>Подписка:</b> {info['plan']}\n"
        f"📆 Активна: {'Да' if info['is_active'] else 'Нет'}\n"
        f"⏳ Дней осталось: {info['days_left']}\n"
        f"🎁 Пробный период использован: {'Да' if info['trial_used'] else 'Нет'}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Приёмов пищи: {food_count}\n"
        f"• Тренировок: {workout_count}\n"
    )
    await message.answer(text)


# ── Выдача Premium ─────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_grant_premium")
async def start_grant_premium(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GrantPremium.waiting_for_user_id)
    await callback.message.edit_text("Введите ID пользователя для выдачи Premium:")
    await callback.answer()


@router.message(GrantPremium.waiting_for_user_id)
async def process_grant_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    target_user = get_user(user_id)
    if not target_user:
        await message.answer(f"Пользователь с ID {user_id} не найден.")
        await state.clear()
        return
    await state.update_data(grant_user_id=user_id)
    await state.set_state(GrantPremium.waiting_for_days)
    await message.answer(f"Пользователь: {html.escape(str(target_user['username']))} (ID: {user_id}).\nВведите количество дней Premium:")


@router.message(GrantPremium.waiting_for_days)
async def process_grant_days(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Количество дней должно быть положительным числом.")
        return
    data = await state.get_data()
    user_id = data.get("grant_user_id")
    sub = get_subscription(user_id)
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    if sub:
        update_subscription(user_id, plan="premium", expires_at=expires_at.isoformat())
    else:
        create_subscription(user_id, plan="premium", expires_at=expires_at.isoformat())
    target_user = get_user(user_id)
    await state.clear()
    await message.answer(f"✅ Пользователю {html.escape(str(target_user['username']))} (ID: {user_id}) выдано {days} дней Premium.")


# ── Статистика ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_stats")
async def show_stats(callback: CallbackQuery):
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    active_users = conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM food_log_new WHERE logged_at >= ?", (week_ago,)
    ).fetchone()[0]
    premium_users = conn.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE plan = 'premium' AND expires_at > ?",
        (datetime.now(timezone.utc).isoformat(),)
    ).fetchone()[0]
    text = (
        f"📊 <b>Статистика BodyPilot</b>\n\n"
        f"• Всего пользователей: <b>{total_users}</b>\n"
        f"• Активных за 7 дней: <b>{active_users}</b>\n"
        f"• Premium-пользователей: <b>{premium_users}</b>\n"
    )
    await callback.message.edit_text(text)
    await callback.answer()


# ── Импорт продуктов ───────────────────────────────────────────────────

@router.callback_query(F.data == "admin_import")
async def start_import(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Open Food Facts", callback_data="import_off")],
        [InlineKeyboardButton(text="🔒 FatSecret (после деплоя)", callback_data="import_fatsecret")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")],
    ])
    await callback.message.edit_text("Выберите источник для импорта продуктов:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "import_off")
async def import_off_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminImport.waiting_for_query)
    await state.update_data(import_source="off")
    await callback.message.edit_text(
        "Введите ключевое слово для поиска продуктов в Open Food Facts (например, «гречка», «творог»):"
    )
    await callback.answer()


@router.callback_query(F.data == "import_fatsecret")
async def import_fatsecret_stub(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSession.active)
    await callback.message.edit_text(
        "🔒 Импорт из FatSecret будет доступен после деплоя на сервер.\n"
        "Сейчас можно использовать Open Food Facts."
    )
    await callback.answer()


@router.message(AdminImport.waiting_for_query)
async def process_import_query(message: Message, state: FSMContext):
    query = message.text.strip()
    if not query:
        await message.answer("Введите ключевое слово.")
        return
    results = await search_food_off_detailed(query, page_size=10)
    if not results:
        await message.answer("Ничего не найдено. Попробуйте другой запрос.")
        await state.set_state(AdminSession.active)
        return
    await state.update_data(import_results=results, import_selected=[])
    await state.set_state(AdminImport.waiting_for_selection)
    
    text = f"🔍 <b>Результаты для «{html.escape(query)}»:</b>\n\n"
    keyboard = []
    for i, item in enumerate(results):
        text += (
            f"{i+1}. <b>{html.escape(str(item['name']))}</b> ({html.escape(str(item['brand']))})\n"
            f"   Ккал: {item['calories']} | Б: {item['protein']}г | Ж: {item['fat']}г | У: {item['carbs']}г\n\n"
        )
        keyboard.append([InlineKeyboardButton(
            text=f"➕ {item['name'][:30]}",
            callback_data=f"import_select_{i}"
        )])
    keyboard.append([InlineKeyboardButton(text="✅ Завершить импорт", callback_data="import_finish")])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data.startswith("import_select_"))
async def import_select_product(callback: CallbackQuery, state: FSMContext):
    try:
        idx = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Продукт не найден.")
        return
    data = await state.get_data()
    results = data.get("import_results", [])
    if idx < 0 or idx >= len(results):
        await callback.answer("Продукт не найден.")
        return
    product = results[idx]
    await state.update_data(pending_import=product)
    await state.set_state(AdminImport.waiting_for_category)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Завтрак", callback_data="import_cat_breakfast")],
        [InlineKeyboardButton(text="☀️ Обед", callback_data="import_cat_lunch")],
        [InlineKeyboardButton(text="🌙 Ужин", callback_data="import_cat_dinner")],
        [InlineKeyboardButton(text="🍏 Перекус", callback_data="import_cat_snack")],
    ])
    await callback.message.edit_text(
        f"Выберите категорию для <b>{html.escape(str(product['name']))}</b>:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("import_cat_"))
async def import_set_category(callback: CallbackQuery, state: FSMContext):
    cat_map = {
        "import_cat_breakfast": "breakfast",
        "import_cat_lunch": "lunch",
        "import_cat_dinner": "dinner",
        "import_cat_snack": "snack",
    }
    cat_name = cat_map.get(callback.data, "snack")
    data = await state.get_data()
    product = data.get("pending_import")
    if not product:
        await callback.answer("Ошибка: продукт не выбран.")
        return
    
    added = add_food_product(
        name=product["name"],
        category=cat_name,
        calories=product["calories"],
        protein=product["protein"],
        fat=product["fat"],
        carbs=product["carbs"],
        brand=product.get("brand", ""),
        source="off",
        source_id=product.get("source_id"),
        is_verified=1,
    )
    if added:
        await callback.answer(f"✅ {product['name']} добавлен в категорию {cat_name}")
    else:
        await callback.answer(f"⚠️ {product['name']} уже существует в базе")
    
    await state.set_state(AdminImport.waiting_for_selection)
    results = data.get("import_results", [])
    text = f"🔍 <b>Результаты поиска:</b>\n\n"
    keyboard = []
    for i, item in enumerate(results):
        text += (
            f"{i+1}. <b>{html.escape(str(item['name']))}</b> ({html.escape(str(item['brand']))})\n"
            f"   Ккал: {item['calories']} | Б: {item['protein']}г | Ж: {item['fat']}г | У: {item['carbs']}г\n\n"
        )
        keyboard.append([InlineKeyboardButton(
            text=f"➕ {item['name'][:30]}",
            callback_data=f"import_select_{i}"
        )])
    keyboard.append([InlineKeyboardButton(text="✅ Завершить импорт", callback_data="import_finish")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data == "import_finish")
async def import_finish(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSession.active)
    await callback.message.edit_text("📥 Импорт завершён. Продукты добавлены в базу.")
    await callback.answer()


# ── Ручное добавление продукта ─────────────────────────────────────────

@router.callback_query(F.data == "admin_add_manual")
async def start_manual_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ManualProduct.waiting_for_name)
    await callback.message.edit_text("Введите название продукта:")
    await callback.answer()


@router.message(ManualProduct.waiting_for_name)
async def process_manual_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Завтрак", callback_data="man_cat_breakfast")],
        [InlineKeyboardButton(text="☀️ Обед", callback_data="man_cat_lunch")],
        [InlineKeyboardButton(text="🌙 Ужин", callback_data="man_cat_dinner")],
        [InlineKeyboardButton(text="🍏 Перекус", callback_data="man_cat_snack")],
    ])
    await message.answer("Выберите категорию:", reply_markup=keyboard)
    await state.set_state(ManualProduct.waiting_for_category)


@router.callback_query(ManualProduct.waiting_for_category)
async def process_manual_category(callback: CallbackQuery, state: FSMContext):
    cat_map = {
        "man_cat_breakfast": "breakfast",
        "man_cat_lunch": "lunch",
        "man_cat_dinner": "dinner",
        "man_cat_snack": "snack",
    }
    cat = cat_map.get(callback.data, "snack")
    await state.update_data(category=cat)
    await callback.message.edit_text(
        f"Категория: {cat}\nТеперь введите калорийность (ккал на 100г):"
    )
    await state.set_state(ManualProduct.waiting_for_calories)
    await callback.answer()


@router.message(ManualProduct.waiting_for_calories)
async def process_manual_calories(message: Message, state: FSMContext):
    try:
        cal = float(message.text.strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(calories=cal)
    await message.answer("Введите количество белка (г на 100г):")
    await state.set_state(ManualProduct.waiting_for_protein)


@router.message(ManualProduct.waiting_for_protein)
async def process_manual_protein(message: Message, state: FSMContext):
    try:
        prot = float(message.text.strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(protein=prot)
    await message.answer("Введите количество жиров (г на 100г):")
    await state.set_state(ManualProduct.waiting_for_fat)


@router.message(ManualProduct.waiting_for_fat)
async def process_manual_fat(message: Message, state: FSMContext):
    try:
        fat = float(message.text.strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(fat=fat)
    await message.answer("Введите количество углеводов (г на 100г):")
    await state.set_state(ManualProduct.waiting_for_carbs)


@router.message(ManualProduct.waiting_for_carbs)
async def process_manual_carbs(message: Message, state: FSMContext):
    try:
        carbs = float(message.text.strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    data = await state.get_data()
    add_food_product(
        name=data["name"],
        category=data["category"],
        calories=data["calories"],
        protein=data["protein"],
        fat=data["fat"],
        carbs=carbs,
        brand="",
        source="custom",
        is_verified=1,
    )
    await state.clear()
    await state.set_state(AdminSession.active)
    await message.answer(f"✅ Продукт '{html.escape(str(data['name']))}' добавлен в категорию {data['category']}.")


# ── Статистика продуктов ───────────────────────────────────────────────

@router.callback_query(F.data == "admin_food_stats")
async def show_food_stats(callback: CallbackQuery):
    """Показывает статистику по продуктам в базе."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM food_products").fetchone()[0]
    by_cat = conn.execute(
        "SELECT COALESCE(NULLIF(category, ''), 'без категории') AS cat, COUNT(*) "
        "FROM food_products GROUP BY cat ORDER BY cat"
    ).fetchall()
    text = f"📊 <b>Продукты в базе</b>\n\nВсего: <b>{total}</b>\n\n"
    for cat_name, cnt in by_cat:
        text += f"• {cat_name}: {cnt}\n"
    await callback.message.edit_text(text)
    await callback.answer()