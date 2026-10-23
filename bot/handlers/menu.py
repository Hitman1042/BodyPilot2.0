"""Обработчики главного меню и inline-кнопок (с админ-панелью)."""

import html
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile, WebAppInfo,
)

from bot.keyboards.main_menu import get_main_menu
from bot.keyboards.inline_menus import (
    get_food_menu, get_workout_menu, get_progress_menu,
    get_settings_menu, get_ai_menu, get_water_menu, get_referral_menu,
)

from bot.handlers.food_tracker import cmd_log_meal, cmd_search_food, cmd_add_product, cmd_food_today, cmd_barcode
from bot.handlers.workout import cmd_start_workout, cmd_add_exercise, cmd_workout_history, ExerciseProgress
from bot.handlers.weight import cmd_log_weight
from bot.handlers.stats import cmd_stats, cmd_premium_stats
from bot.handlers.digest_handlers import (
    cmd_digest_now, cmd_set_digest_time, cmd_weather, cmd_set_city,
)
from bot.handlers.profile import cmd_profile, cmd_register
from bot.handlers.premium import cmd_premium, cmd_ref, cmd_bonus, cmd_referrals
from bot.handlers.plans import cmd_meal_plan, cmd_workout_plan as cmd_weekly_workout_plan
from bot.handlers.admin import AdminSession, show_admin_panel

from core.database import get_workout_log, get_weight_log, get_user
from core.challenges import (
    CHALLENGES, get_active_challenges, get_challenge_progress, join_challenge,
)
from core.charts import build_share_card
from core.gamification import add_water, get_today_water, get_water_target, notify_progress
from core.referrals import get_friend_rating, get_subscription_info
from core.visuals import progress_bar
from core.weekly_report import send_weekly_report

logger = logging.getLogger(__name__)
router = Router()

MAIN_MENU_ITEMS = {
    "🍽 Еда": get_food_menu,
    "🏋️ Тренировки": get_workout_menu,
    "📊 Прогресс": get_progress_menu,
    "🤖 AI-коуч": get_ai_menu,
    "⚙️ Профиль": get_settings_menu,
}

async def _answer_with_menu(message: Message, text: str, state: FSMContext = None, **kwargs):
    """Отправляет сообщение и прикрепляет главное меню (с учётом админ-прав)."""
    is_admin = False
    if state:
        current_state = await state.get_state()
        is_admin = (current_state == AdminSession.active.state)
    await message.answer(text, reply_markup=get_main_menu(is_admin=is_admin), **kwargs)

@router.message(F.text.in_(MAIN_MENU_ITEMS.keys()))
async def show_submenu(message: Message):
    keyboard_func = MAIN_MENU_ITEMS[message.text]
    titles = {
        "🍽 Еда": (
            "🥗 <b>Питание</b>\n\n"
            "Просто напиши, что съел — например, «200 г гречки с курицей», "
            "или пришли фото блюда 📸\n\n"
            "Или выбери действие:"
        ),
        "🏋️ Тренировки": "🏋️ <b>Тренировки</b> — выбери действие:",
        "📊 Прогресс": "📊 <b>Прогресс</b> — вес и статистика:",
        "🤖 AI-коуч": "🤖 <b>AI-коуч</b> — персональные планы и анализ на базе ИИ:",
        "⚙️ Профиль": "⚙️ <b>Профиль и настройки</b> — выбери действие:",
    }
    title = titles.get(message.text, "Выбери действие:")
    logger.info("📱 Пользователь %d открыл меню: %s", message.from_user.id, message.text)
    await message.answer(title, reply_markup=keyboard_func())

# Обработка кнопки «🔧 Администрирование»
@router.message(F.text == "🔧 Администрирование")
async def admin_panel_entry(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != AdminSession.active.state:
        await message.answer("Сначала войдите как администратор: /admin_login")
        return
    await show_admin_panel(message)

@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    """Сброс состояния и показ главного меню (на эту команду ссылаются подсказки)."""
    await state.clear()
    await _answer_with_menu(message, "Выбери раздел меню:", state=state)


@router.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    is_admin = (await state.get_state() == AdminSession.active.state)
    await callback.message.edit_text(
        "Выбери нужный раздел на клавиатуре снизу 👇",
        reply_markup=None
    )
    await callback.answer()

# ── Mini App ──────────────────────────────────────────────────────────────

def _app_markup() -> InlineKeyboardMarkup | None:
    """Inline-кнопка открытия Mini App или None, если фича не настроена."""
    from core.config import settings
    if not settings.MINIAPP_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📱 Открыть приложение",
            web_app=WebAppInfo(url=settings.MINIAPP_URL),
        )
    ]])


@router.message(Command("app"))
async def cmd_app(message: Message):
    markup = _app_markup()
    if markup is None:
        await message.answer("📱 Приложение скоро появится!")
        return
    await message.answer(
        "📱 <b>BodyPilot Mini App</b> — питание, тренировки и прогресс в удобном веб-интерфейсе:",
        reply_markup=markup,
    )


@router.message(F.text == "📱 Приложение")
async def menu_app_button(message: Message):
    await cmd_app(message)


@router.callback_query(F.data == "open_app")
async def open_app(callback: CallbackQuery):
    markup = _app_markup()
    if markup is None:
        await callback.answer("📱 Приложение скоро появится!", show_alert=True)
        return
    await callback.message.edit_text(
        "📱 <b>BodyPilot Mini App</b> — питание, тренировки и прогресс в удобном веб-интерфейсе:",
        reply_markup=markup,
    )
    await callback.answer()

# ── AI-коуч ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ai_chat_start")
async def start_ai_chat(callback: CallbackQuery, state: FSMContext):
    from bot.handlers.ai_chat import cmd_ai_chat
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_ai_chat(callback.message, state, user_id=callback.from_user.id)

@router.callback_query(F.data == "ai_plan_start")
async def start_ai_plan(callback: CallbackQuery):
    from bot.handlers.ai_nutrition import cmd_ai_plan
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_ai_plan(callback.message, user_id=callback.from_user.id)

@router.callback_query(F.data == "ai_analyze_start")
async def start_ai_analyze(callback: CallbackQuery):
    from bot.handlers.ai_analyze import cmd_ai_analyze
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_ai_analyze(callback.message, user_id=callback.from_user.id)

@router.callback_query(F.data == "ai_workout_start")
async def start_ai_workout(callback: CallbackQuery):
    from bot.handlers.ai_analyze import cmd_ai_workout
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_ai_workout(callback.message, user_id=callback.from_user.id)

@router.callback_query(F.data == "ai_photo_hint")
async def ai_photo_hint(callback: CallbackQuery):
    await callback.message.edit_text(
        "📸 <b>Распознавание еды по фото</b>\n\n"
        "Просто отправь фото блюда в чат — AI распознает его, "
        "посчитает КБЖУ и предложит записать в дневник.\n\n"
        "Можно добавить подпись, например: «обед» или «перекус».",
        reply_markup=get_ai_menu()
    )
    await callback.answer()

# ── Еда ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "food_log")
async def start_food_log(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 food_log от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_log_meal(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "food_search")
async def start_food_search(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 food_search от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_search_food(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "food_add")
async def start_add_product(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 food_add от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.update_data(_user_id=callback.from_user.id)
    await cmd_add_product(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "food_today")
async def show_food_today(callback: CallbackQuery):
    logger.info("🔔 food_today от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_food_today(callback.message, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "food_barcode")
async def start_food_barcode(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 food_barcode от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_barcode(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()


def _water_text(user_id: int) -> str:
    current = get_today_water(user_id)
    target = get_water_target(user_id)
    lines = [
        "💧 <b>Вода</b>",
        "",
        f"Сегодня: <b>{current} мл</b> из {target} мл",
        progress_bar(current, target),
    ]
    if current >= target:
        lines.extend(["", "✅ Норма воды выполнена!"])
    return "\n".join(lines)


@router.message(Command("water"))
async def cmd_water(message: Message, user_id: int = None):
    uid = user_id or message.from_user.id
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await message.answer(_water_text(uid), reply_markup=get_water_menu())


@router.callback_query(F.data == "water_menu")
async def show_water_menu(callback: CallbackQuery):
    uid = callback.from_user.id
    if not get_user(uid):
        await callback.answer("Сначала зарегистрируйся с помощью /register", show_alert=True)
        return
    await callback.message.edit_text(_water_text(uid), reply_markup=get_water_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("water_add_"))
async def add_water_from_menu(callback: CallbackQuery):
    uid = callback.from_user.id
    if not get_user(uid):
        await callback.answer("Сначала зарегистрируйся с помощью /register", show_alert=True)
        return
    try:
        amount = int(callback.data.rsplit("_", 1)[1])
    except ValueError:
        await callback.answer("Неизвестный объём", show_alert=True)
        return
    if amount not in (250, 500, 1000):
        await callback.answer("Неизвестный объём", show_alert=True)
        return

    before = get_today_water(uid)
    add_water(uid, amount)
    target = get_water_target(uid)
    current = get_today_water(uid)
    await callback.message.edit_text(_water_text(uid), reply_markup=get_water_menu())
    if before < target <= current:
        await callback.answer("✅ Норма воды выполнена!")
    else:
        await callback.answer(f"+{amount} мл")
    await notify_progress(callback.message, uid, show_streak=False)

# ── Тренировки ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "workout_plan")
async def show_workout_plan(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 workout_plan от пользователя %d", callback.from_user.id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    uid = callback.from_user.id
    logger.info("Генерация плана для пользователя %d", uid)

    if not get_user(uid):
        await callback.message.answer("Сначала зарегистрируйся с помощью /register")
        return

    from core.training_service import generate_daily_workout_plan

    plan = generate_daily_workout_plan(uid)

    logger.info("План получен: %s", "OK" if plan else "None")

    if not plan:
        logger.error("План пустой (None)")
        await callback.message.answer("❌ Не удалось сгенерировать план (None).")
        return

    if not plan.get("exercises"):
        logger.error("В плане нет упражнений")
        await callback.message.answer("❌ В плане нет упражнений.")
        return

    logger.info("В плане %d упражнений", len(plan.get("exercises", [])))

    # Группируем упражнения по модулям (категориям)
    modules = {}
    for ex in plan.get("exercises", []):
        cat = ex.get("category", "accessory")
        if cat not in modules:
            modules[cat] = []
        modules[cat].append(ex)

    logger.info("Модули: %s", {k: len(v) for k, v in modules.items()})

    module_names = {
        "warmup": "🔥 Модуль 1: Разминка (кардио)",
        "mobility": "🔄 Модуль 2: Мобилизация",
        "special": "🎯 Модуль 3: Специальная разминка",
        "strength": "💪 Модуль 4: Основная сила",
        "accessory": "🏋️ Модуль 5: ОФП",
        "cool_down": "🧘 Модуль 6: Заминка",
    }

    module_desc = {
        "warmup": "Поднимает пульс, разогревает тело",
        "mobility": "Увеличивает амплитуду в суставах",
        "special": "Подводящие движения",
        "strength": "Базовые многосуставные упражнения",
        "accessory": "Вспомогательные упражнения",
        "cool_down": "Растяжка, восстановление",
    }

    text = "🏋️ <b>Твой план тренировки на сегодня</b>\n\n"
    from core.preferences import get_preferences, is_bodyweight_only
    prefs = get_preferences(uid)
    if is_bodyweight_only(prefs):
        text += "🏠 Домашний план (без инвентаря)\n"
    elif (prefs.get("training_place") or "") == "outdoor":
        text += "🌳 План для улицы\n"
    adaptation = plan.get("adaptation") or {}
    if adaptation.get("note"):
        text += f"⚖️ <b>План скорректирован:</b> {adaptation['note']}\n\n"
    text += "Построено по спортивной науке: 6 модулей 📚\n\n"

    module_order = ["warmup", "mobility", "special", "strength", "accessory", "cool_down"]

    for module_key in module_order:
        exercises = modules.get(module_key, [])
        if not exercises:
            continue

        text += f"<b>{module_names.get(module_key, module_key)}</b>\n"
        text += f"<i>{module_desc.get(module_key, '')}</i>\n\n"

        for i, ex in enumerate(exercises, 1):
            if ex.get("category") in ["warmup", "cool_down"]:
                duration = ex.get("duration_min", 1)
                reps = ex.get("reps_min", 30)
                if duration and duration > 1:
                    text += f"  {i}. {ex['name']} — {duration} мин\n"
                else:
                    text += f"  {i}. {ex['name']} — удерживать {reps} сек\n"
            else:
                sets = ex.get("sets", 3)
                reps_min = ex.get("reps_min", 8)
                reps_max = ex.get("reps_max", 12)
                rest = ex.get("rest_sec", 60)

                if reps_min == reps_max:
                    text += f"  {i}. {ex['name']} — {sets}×{reps_min} (отдых {rest} сек)\n"
                else:
                    text += f"  {i}. {ex['name']} — {sets}×{reps_min}-{reps_max} (отдых {rest} сек)\n"

        text += "\n"

    text += "💡 <b>Совет:</b> Начинай каждый модуль только после завершения предыдущего.\n"
    text += "Не пропускай разминку и заминку — это снижает риск травм!\n\n"
    text += "Используй /start_workout, чтобы начать тренировку."

    await callback.message.answer(text)

@router.callback_query(F.data == "workout_session")
async def start_workout_btn(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 workout_session от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_start_workout(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "workout_add_exercise")
async def add_exercise_btn(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 workout_add_exercise от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_add_exercise(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "workout_history")
async def show_workout_history(callback: CallbackQuery):
    logger.info("🔔 workout_history от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_workout_history(callback.message, user_id=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "workout_refresh")
async def refresh_workout_plan(callback: CallbackQuery):
    """Перегенерировать план тренировки на сегодня."""
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    uid = callback.from_user.id

    if not get_user(uid):
        await callback.message.answer("Сначала зарегистрируйся с помощью /register")
        return

    from core.training_service import generate_daily_workout_plan
    from core.database import get_db
    from datetime import date

    # Очищаем старый план на сегодня
    conn = get_db()
    conn.execute("DELETE FROM daily_workout_plans WHERE user_id = ? AND date = ?", (uid, date.today().isoformat()))
    conn.commit()

    # Генерируем новый план
    plan = generate_daily_workout_plan(uid, force_refresh=True)

    if not plan or not plan.get("exercises"):
        await callback.message.answer("❌ Не удалось сгенерировать план.")
        return

    # Названия модулей
    module_names = {
        "warmup": "🔥 Модуль 1: Разминка (кардио)",
        "mobility": "🔄 Модуль 2: Мобилизация",
        "special": "🎯 Модуль 3: Специальная разминка",
        "strength": "💪 Модуль 4: Основная сила",
        "accessory": "🏋️ Модуль 5: ОФП",
        "cool_down": "🧘 Модуль 6: Заминка",
    }

    modules = plan.get("modules", {})

    text = "🔄 <b>План перегенерирован!</b>\n\n"
    from core.preferences import get_preferences, is_bodyweight_only
    prefs = get_preferences(uid)
    if is_bodyweight_only(prefs):
        text += "🏠 Домашний план (без инвентаря)\n"
    adaptation = plan.get("adaptation") or {}
    if adaptation.get("note"):
        text += f"⚖️ <b>План скорректирован:</b> {adaptation['note']}\n\n"
    text += "🏋️ <b>Твой новый план на сегодня:</b>\n\n"

    module_order = ["warmup", "mobility", "special", "strength", "accessory", "cool_down"]

    for module_key in module_order:
        exercises = modules.get(module_key, [])
        if not exercises:
            continue

        text += f"<b>{module_names.get(module_key, module_key)}</b>\n"

        for i, ex in enumerate(exercises, 1):
            if ex.get("category") in ["warmup", "cool_down"]:
                duration = ex.get("duration_min", 1)
                text += f"  {i}. {ex['name']} — {duration} мин\n" if duration > 1 else f"  {i}. {ex['name']}\n"
            else:
                sets = ex.get("sets", 3)
                reps = f"{ex.get('reps_min', 8)}-{ex.get('reps_max', 12)}"
                rest = ex.get("rest_sec", 60)
                text += f"  {i}. {ex['name']} — {sets}×{reps} (отдых {rest} сек)\n"

        text += "\n"

    text += "💡 Этот план уникален и отличается от предыдущего!"

    await callback.message.answer(text)

@router.callback_query(F.data == "workout_progress")
async def start_progress(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 workout_progress от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Введите название упражнения для просмотра прогресса:")
    await state.set_state(ExerciseProgress.waiting_for_exercise)
    await callback.answer()

# ── Вес ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "weight_log")
async def start_weight_log(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 weight_log от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_log_weight(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "weight_history")
async def show_weight_history(callback: CallbackQuery):
    logger.info("🔔 weight_history от пользователя %d", callback.from_user.id)
    user_id = callback.from_user.id
    weights = get_weight_log(user_id, days=7)
    if not weights:
        await _answer_with_menu(callback.message, "За последние 7 дней записей веса нет.")
    else:
        text = "⚖️ <b>Динамика веса за неделю:</b>\n\n"
        for w in weights[:10]:
            text += f"• {w['weight_kg']} кг ({w['logged_at'][:10]})\n"
        await _answer_with_menu(callback.message, text)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()

# ── Статистика ──────────────────────────────────────────────────────────

async def _week_report(message: Message, user_id: int):
    if not get_user(user_id):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    status = await message.answer("⏳ Готовлю отчёт за неделю...")
    try:
        await send_weekly_report(message.bot, message.chat.id, user_id)
    except Exception as exc:
        logger.warning("Ошибка недельного отчёта для %s: %s", user_id, exc)
        await message.answer("❌ Не удалось подготовить отчёт. Попробуй ещё раз позже.")
    finally:
        try:
            await status.delete()
        except Exception:
            pass


@router.message(Command("week_report"))
async def cmd_week_report(message: Message, user_id: int = None):
    await _week_report(message, user_id or message.from_user.id)


@router.callback_query(F.data == "week_report")
async def show_week_report(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await _week_report(callback.message, callback.from_user.id)


def _challenges_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    active = get_active_challenges(user_id)
    active_codes = {item["code"] for item in active}
    lines = ["🎯 <b>Челленджи</b>"]
    if active:
        lines.append("\n<b>Активные:</b>")
        for item in active:
            lines.append(
                f"• {item['name']} — {item['current']}/{item['target']} "
                f"{item['unit']} {progress_bar(item['current'], item['target'], 8)}"
            )
    else:
        lines.append("\nАктивных челленджей пока нет.")

    available = [item for code, item in CHALLENGES.items() if code not in active_codes]
    if available:
        lines.append("\n<b>Доступные:</b>")
        lines.extend(f"• {item['name']} — {item['description']}" for item in available)

    buttons = [
        [InlineKeyboardButton(text=f"📊 {item['name']}", callback_data=f"ch_progress_{item['code']}")]
        for item in active
    ]
    buttons.extend(
        [InlineKeyboardButton(text=f"✅ Участвовать: {item['name']}", callback_data=f"ch_join_{item['code']}")]
        for item in available
    )
    buttons.append([InlineKeyboardButton(text="🔙 К прогрессу", callback_data="progress_menu")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("challenges"))
async def cmd_challenges(message: Message, user_id: int = None):
    uid = user_id or message.from_user.id
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    text, keyboard = _challenges_view(uid)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.in_({"challenges", "ch_list"}))
async def show_challenges(callback: CallbackQuery):
    uid = callback.from_user.id
    if not get_user(uid):
        await callback.answer("Сначала зарегистрируйся с помощью /register", show_alert=True)
        return
    text, keyboard = _challenges_view(uid)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("ch_join_"))
async def join_challenge_from_menu(callback: CallbackQuery):
    code = callback.data.removeprefix("ch_join_")
    try:
        progress = join_challenge(callback.from_user.id, code)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    text, keyboard = _challenges_view(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer(f"Ты участвуешь: {progress['name']}")


@router.callback_query(F.data.startswith("ch_progress_"))
async def show_challenge_progress(callback: CallbackQuery):
    code = callback.data.removeprefix("ch_progress_")
    try:
        progress = get_challenge_progress(callback.from_user.id, code)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    status_text = {"active": "Активен", "completed": "Выполнен", "failed": "Завершён"}.get(
        progress["status"], progress["status"]
    )
    text = (
        f"🎯 <b>{progress['name']}</b>\n\n"
        f"{progress['description']}\n"
        f"Условие: {progress['condition']}\n\n"
        f"Прогресс: <b>{progress['current']}/{progress['target']} {progress['unit']}</b>\n"
        f"{progress_bar(progress['current'], progress['target'])}\n"
        f"Статус: {status_text}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 К челленджам", callback_data="ch_list")
    ]])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "progress_menu")
async def show_progress_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📊 <b>Прогресс</b> — вес, статистика и челленджи:",
        reply_markup=get_progress_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "share_card")
async def send_share_card(callback: CallbackQuery):
    uid = callback.from_user.id
    if not get_user(uid):
        await callback.answer("Сначала зарегистрируйся с помощью /register", show_alert=True)
        return
    await callback.answer()
    status = await callback.message.answer("⏳ Готовлю карточку недели...")
    try:
        image = build_share_card(uid)
        if image:
            await callback.message.bot.send_photo(
                chat_id=callback.message.chat.id,
                photo=BufferedInputFile(image, filename="bodypilot_week.png"),
                caption="Поделись результатом с друзьями! 👉 @BodyPilot2_bot",
            )
        else:
            await callback.message.answer("Не удалось построить карточку. Попробуй позже.")
    except Exception as exc:
        logger.warning("Ошибка share-карточки для %s: %s", uid, exc)
        await callback.message.answer("❌ Не удалось подготовить карточку. Попробуй позже.")
    finally:
        try:
            await status.delete()
        except Exception:
            pass


@router.callback_query(F.data == "stats_week")
async def show_stats_week(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 stats_week от пользователя %d", callback.from_user.id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_stats(callback.message, user_id=callback.from_user.id)
    await _answer_with_menu(callback.message, "Главное меню:", state=state)


@router.callback_query(F.data == "stats_month")
async def show_stats_month(callback: CallbackQuery):
    logger.info("🔔 stats_month от пользователя %d", callback.from_user.id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    # ✅ ПРОВЕРКА ПОДПИСКИ
    from core.database import get_subscription
    from datetime import datetime, timezone

    subscription = get_subscription(callback.from_user.id)

    if not subscription:
        await _answer_with_menu(
            callback.message,
            "📆 Статистика за 30 дней доступна только с <b>Premium</b> подпиской.\n"
            "Используй /premium чтобы узнать подробности."
        )
        return

    # ✅ ПРОВЕРКА ДАТЫ ИСТЕЧЕНИЯ
    if subscription.get("expires_at"):
        try:
            expire_dt = datetime.fromisoformat(subscription["expires_at"])
            if expire_dt <= datetime.now(timezone.utc):
                await _answer_with_menu(
                    callback.message,
                    "⚠️ Ваша Premium подписка истекла.\n"
                    "Используй /premium чтобы продлить."
                )
                return
        except Exception:
            pass

    # ✅ ПОДПИСКА АКТИВНА — вызываем cmd_premium_stats
    from bot.handlers.stats import cmd_premium_stats
    await cmd_premium_stats(callback.message, user_id=callback.from_user.id)

# ── Дайджест ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "digest_now")
async def start_digest_now(callback: CallbackQuery):
    logger.info("🔔 digest_now от пользователя %d", callback.from_user.id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_digest_now(callback.message, user_id=callback.from_user.id)

@router.callback_query(F.data == "digest_set_time")
async def start_set_digest_time(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 digest_set_time от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_set_digest_time(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "weather")
async def show_weather(callback: CallbackQuery):
    logger.info("🔔 weather от пользователя %d", callback.from_user.id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_weather(callback.message, user_id=callback.from_user.id)

@router.callback_query(F.data == "city_set")
async def start_set_city(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 city_set от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_set_city(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()

# ── Профиль ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "profile_view")
async def show_profile(callback: CallbackQuery):
    logger.info("🔔 profile_view от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_profile(callback.message, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "profile_edit")
async def start_profile_edit(callback: CallbackQuery, state: FSMContext):
    logger.info("🔔 profile_edit от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_register(callback.message, state, user_id=callback.from_user.id)
    await callback.answer()

# ── Premium ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "premium_subscribe")
async def show_premium_info(callback: CallbackQuery):
    logger.info("🔔 premium_subscribe от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_premium(callback.message, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "premium_meal_plan")
async def show_meal_plan(callback: CallbackQuery):
    """Показать план питания (Premium)."""
    logger.info("🔔 premium_meal_plan от пользователя %d", callback.from_user.id)
    from bot.handlers.plans import cmd_meal_plan
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_meal_plan(callback.message, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "premium_refresh_meal")
async def refresh_meal_plan(callback: CallbackQuery):
    logger.info("🔔 premium_refresh_meal от пользователя %d", callback.from_user.id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    user = get_user(callback.from_user.id)
    if not user:
        await callback.message.answer("Сначала зарегистрируйся с помощью /register")
        return

    from core.referrals import check_subscription_active
    if not check_subscription_active(callback.from_user.id):
        await _answer_with_menu(
            callback.message,
            "Эта функция доступна только с <b>Premium</b> подпиской.\n"
            "Используй /premium чтобы узнать подробности."
        )
        return

    # Импортируем generate_meal_plan, чтобы передать refresh=True
    from core.plans import generate_meal_plan
    user["user_id"] = callback.from_user.id
    plan = generate_meal_plan(user, refresh=True)

    text = (
        f"🍽 <b>Твой обновлённый план питания</b>\n\n"
        f"🎯 Цель: {plan['calorie_target']} ккал\n"
        f"📊 Макросы: Б: {plan['macros_target']['protein_g']}г, Ж: {plan['macros_target']['fat_g']}г, У: {plan['macros_target']['carbs_g']}г\n\n"
        f"<b>Завтрак:</b> {plan['meals']['breakfast']['name']} — {plan['meals']['breakfast']['cal']} ккал\n"
        f"<b>Обед:</b> {plan['meals']['lunch']['name']} — {plan['meals']['lunch']['cal']} ккал\n"
        f"<b>Ужин:</b> {plan['meals']['dinner']['name']} — {plan['meals']['dinner']['cal']} ккал\n"
        f"<b>Перекус:</b> {plan['meals']['snack']['name']} — {plan['meals']['snack']['cal']} ккал\n\n"
        f"<b>Итого за день:</b> {plan['total']['calories']} ккал\n"
        f"Б: {plan['total']['protein_g']}г, Ж: {plan['total']['fat_g']}г, У: {plan['total']['carbs_g']}г"
    )
    await callback.message.answer(text)

@router.callback_query(F.data == "premium_workout_plan")
async def show_premium_workout_plan(callback: CallbackQuery):
    logger.info("🔔 premium_workout_plan от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_weekly_workout_plan(callback.message, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "premium_stats")
async def show_premium_stats(callback: CallbackQuery):
    logger.info("🔔 premium_stats от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_premium_stats(callback.message, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "premium_referral")
async def show_referral_info(callback: CallbackQuery):
    logger.info("🔔 premium_referral от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_ref(callback.message, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "premium_bonuses")
async def show_bonus_info(callback: CallbackQuery):
    logger.info("🔔 premium_bonuses от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_bonus(callback.message, user_id=callback.from_user.id)
    await callback.answer()

# ── Рефералы ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "ref_menu")
async def show_referral_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔗 <b>Рефералы</b> — приглашай друзей и соревнуйтесь вместе:",
        reply_markup=get_referral_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "ref_rating")
async def show_friend_rating(callback: CallbackQuery):
    rating = get_friend_rating(callback.from_user.id)
    if len(rating) <= 1:
        text = "Пригласи друзей по своей ссылке — соревнуйтесь вместе!"
    else:
        medals = ("🥇", "🥈", "🥉")
        lines = ["🏆 <b>Рейтинг друзей за неделю</b>", ""]
        for place, item in enumerate(rating, start=1):
            medal = medals[place - 1] if place <= 3 else f"{place}."
            name = "Вы" if item["is_self"] else html.escape(item["username"])
            lines.append(
                f"{medal} <b>{name}</b> — {item['points']} очков\n"
                f"   🏋️ {item['workouts']} • 🍽 {item['food_days']} дн. • 🔥 {item['streak']}"
            )
        lines.append("\nОчки: тренировка ×10, день питания ×5, день серии ×3.")
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=get_referral_menu())
    await callback.answer()


@router.callback_query(F.data == "ref_link")
async def show_ref_link(callback: CallbackQuery):
    logger.info("🔔 ref_link от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_ref(callback.message, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "ref_list")
async def show_ref_list(callback: CallbackQuery):
    logger.info("🔔 ref_list от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_referrals(callback.message, user_id=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "ref_balance")
async def show_ref_balance(callback: CallbackQuery):
    logger.info("🔔 ref_balance от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await cmd_bonus(callback.message, user_id=callback.from_user.id)
    await callback.answer()

# ── Помощь ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "help_guide")
async def show_guide(callback: CallbackQuery):
    logger.info("🔔 help_guide от пользователя %d", callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _answer_with_menu(
        callback.message,
        "📖 <b>Краткая инструкция:</b>\n\n"
        "1. Зарегистрируйся через /register или кнопку «⚙️ Профиль».\n"
        "2. Записывай питание в разделе «🍽 Еда» — или просто напиши, что съел.\n"
        "3. Записывай тренировки в разделе «🏋️ Тренировки».\n"
        "4. Следи за весом и статистикой в разделе «📊 Прогресс».\n"
        "5. Настрой утренний дайджест в «⚙️ Профиль».\n\n"
        "Все данные сохраняются и помогают тебе достигать целей!"
    )
    await callback.answer()

@router.callback_query(F.data == "help_support")
async def show_support(callback: CallbackQuery):
    logger.info("🔔 help_support от пользователя %d", callback.from_user.id)
    from core.config import settings
    await callback.message.edit_reply_markup(reply_markup=None)
    await _answer_with_menu(
        callback.message,
        f"💬 По всем вопросам и предложениям пиши: @{settings.TELEGRAM_ADMIN_USERNAME}"
    )
    await callback.answer()