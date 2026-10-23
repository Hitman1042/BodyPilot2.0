"""Обработчики регистрации и просмотра профиля (с поддержкой callback)."""

import html

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.keyboards.main_menu import get_main_menu, MAIN_MENU_BUTTONS
from core.database import get_or_create_user, update_user, get_user
from core.nutrition_calc import compute_profile
from core.referrals import start_trial

router = Router()

GENDER_MAP = {"мужской": "male", "женский": "female"}
GOAL_MAP = {"похудеть": "lose", "сохранить": "maintain", "набрать": "gain"}
ACTIVITY_MAP = {"низкая": "sedentary", "средняя": "moderate", "высокая": "high"}

# Часовые пояса: (смещение в минутах, подпись)
TIMEZONES = [
    (0, "UTC+0 — Лондон"),
    (60, "UTC+1 — Берлин"),
    (120, "UTC+2 — Киев"),
    (180, "UTC+3 — Москва"),
    (240, "UTC+4 — Самара"),
    (300, "UTC+5 — Екатеринбург"),
    (360, "UTC+6 — Омск"),
    (420, "UTC+7 — Новосибирск"),
    (480, "UTC+8 — Иркутск"),
    (540, "UTC+9 — Якутск"),
    (600, "UTC+10 — Владивосток"),
    (660, "UTC+11 — Магадан"),
    (720, "UTC+12 — Камчатка"),
]

_CANCEL_BUTTON = [InlineKeyboardButton(text="❌ Отмена", callback_data="reg_cancel")]
_SKIP_BUTTON = InlineKeyboardButton(text="⏭ Пропустить", callback_data="reg_skip")
_SKIP_ALL_BUTTON = InlineKeyboardButton(text="Пропустить всё остальное ⏭", callback_data="reg_skip_all")

# Дефолты для опциональных шагов при «Пропустить всё остальное»
REG_DEFAULTS = {
    "allergies": "",
    "city": "Moscow",
    "timezone_offset": 180,
    "preferred_time": "07:00",
}


class Registration(StatesGroup):
    waiting_for_name = State()
    waiting_for_gender = State()
    waiting_for_age = State()
    waiting_for_height = State()
    waiting_for_weight = State()
    waiting_for_goal = State()
    waiting_for_activity = State()
    waiting_for_allergies = State()
    waiting_for_city = State()
    waiting_for_timezone = State()
    waiting_for_timezone_manual = State()
    waiting_for_digest_time = State()


def _default_name(message: Message) -> str:
    return message.from_user.username or message.from_user.full_name or ""


def _get_user_id(message: Message, user_id: int = None) -> int:
    return user_id if user_id else message.from_user.id


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    """Клавиатура шага регистрации с кнопкой отмены внизу."""
    return InlineKeyboardMarkup(inline_keyboard=[*rows, _CANCEL_BUTTON])


# ── Шаги регистрации (общие приглашения для текста и кнопок) ─────────────

async def _ask_gender(message: Message, state: FSMContext):
    kb = _kb([
        InlineKeyboardButton(text="👨 Мужской", callback_data="reg_gender_male"),
        InlineKeyboardButton(text="👩 Женский", callback_data="reg_gender_female"),
    ])
    await message.answer("Укажи пол:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_gender)


async def _ask_age(message: Message, state: FSMContext):
    await message.answer("Сколько тебе полных лет? (просто число)", reply_markup=_kb())
    await state.set_state(Registration.waiting_for_age)


async def _ask_height(message: Message, state: FSMContext):
    await message.answer("Какой у тебя рост? (в сантиметрах, например 175)", reply_markup=_kb())
    await state.set_state(Registration.waiting_for_height)


async def _ask_weight(message: Message, state: FSMContext):
    await message.answer("Какой у тебя вес? (в килограммах, например 70)", reply_markup=_kb())
    await state.set_state(Registration.waiting_for_weight)


async def _ask_goal(message: Message, state: FSMContext):
    kb = _kb(
        [InlineKeyboardButton(text="🔥 Похудеть", callback_data="reg_goal_lose")],
        [InlineKeyboardButton(text="⚖️ Сохранить форму", callback_data="reg_goal_maintain")],
        [InlineKeyboardButton(text="💪 Набрать массу", callback_data="reg_goal_gain")],
    )
    await message.answer("Какая у тебя цель?", reply_markup=kb)
    await state.set_state(Registration.waiting_for_goal)


async def _ask_activity(message: Message, state: FSMContext):
    kb = _kb(
        [InlineKeyboardButton(text="🪑 Низкая (сидячая работа)", callback_data="reg_act_sedentary")],
        [InlineKeyboardButton(text="🚶 Средняя (3-5 тренировок в неделю)", callback_data="reg_act_moderate")],
        [InlineKeyboardButton(text="🏃 Высокая (интенсив или физ. труд)", callback_data="reg_act_high")],
    )
    await message.answer("Какой у тебя уровень физической активности?", reply_markup=kb)
    await state.set_state(Registration.waiting_for_activity)


async def _ask_allergies(message: Message, state: FSMContext):
    kb = _kb([_SKIP_BUTTON], [_SKIP_ALL_BUTTON])
    await message.answer(
        "Есть ли у тебя пищевые аллергии?\n"
        "Перечисли через запятую (например: <b>арахис, лактоза</b>) или пропусти шаг.",
        reply_markup=kb
    )
    await state.set_state(Registration.waiting_for_allergies)


async def _ask_city(message: Message, state: FSMContext):
    kb = _kb([_SKIP_BUTTON], [_SKIP_ALL_BUTTON])
    await message.answer(
        "В каком городе ты находишься?\n"
        "Это нужно для прогноза погоды в утреннем дайджесте.\n"
        "Напиши название (например, <b>Москва</b>) или пропусти шаг.",
        reply_markup=kb
    )
    await state.set_state(Registration.waiting_for_city)


async def _ask_timezone(message: Message, state: FSMContext):
    rows = []
    for i in range(0, len(TIMEZONES), 2):
        row = [
            InlineKeyboardButton(text=label, callback_data=f"reg_tz_{minutes}")
            for minutes, label in TIMEZONES[i:i + 2]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✍️ Другая (ввести вручную)", callback_data="reg_tz_other")])
    rows.append([_SKIP_ALL_BUTTON])
    rows.append(_CANCEL_BUTTON)
    await message.answer(
        "Выбери свой часовой пояс:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await state.set_state(Registration.waiting_for_timezone)


async def _ask_digest_time(message: Message, state: FSMContext):
    await message.answer(
        "В какое время присылать утренний дайджест?\n"
        "Введи время в формате <b>ЧЧ:ММ</b> (например, <b>07:00</b> или <b>8:30</b>)",
        reply_markup=_kb([_SKIP_ALL_BUTTON])
    )
    await state.set_state(Registration.waiting_for_digest_time)


# ── Отмена и пропуск ─────────────────────────────────────────────────────

@router.callback_query(StateFilter(Registration), F.data == "reg_cancel")
async def cancel_registration(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Регистрация отменена.")
    await callback.message.answer("Выбери раздел меню:", reply_markup=get_main_menu())
    await callback.answer()


@router.message(StateFilter(Registration), Command("cancel"))
async def cancel_registration_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Регистрация отменена.", reply_markup=get_main_menu())


@router.callback_query(StateFilter(Registration), F.data == "reg_skip")
async def skip_registration_step(callback: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    if current == Registration.waiting_for_name.state:
        default = callback.from_user.username or callback.from_user.full_name or "Пользователь"
        await state.update_data(username=default)
        await callback.message.edit_text(f"Имя: <b>{html.escape(default)}</b>")
        await _ask_gender(callback.message, state)
    elif current == Registration.waiting_for_allergies.state:
        await state.update_data(allergies="")
        await callback.message.edit_text("Аллергии: нет")
        await _ask_city(callback.message, state)
    elif current == Registration.waiting_for_city.state:
        await state.update_data(city="Moscow")
        await callback.message.edit_text("Город: Москва")
        await _ask_timezone(callback.message, state)
    else:
        await callback.answer("Этот шаг нельзя пропустить")
        return
    await callback.answer()


@router.callback_query(StateFilter(Registration), F.data == "reg_skip_all")
async def skip_all_registration(callback: CallbackQuery, state: FSMContext):
    """Пропустить все оставшиеся опциональные шаги и завершить регистрацию."""
    data = await state.get_data()
    required = ["gender", "age", "height_cm", "weight_kg", "goal", "activity"]
    missing = [f for f in required if f not in data]
    if missing:
        await callback.answer(
            "Сначала заверши обязательные шаги: пол, возраст, рост, вес, цель, активность",
            show_alert=True,
        )
        return
    for key, value in REG_DEFAULTS.items():
        if key not in data:
            data[key] = value
    await callback.message.edit_text(
        "⏭ Остальные шаги пропущены — использую значения по умолчанию."
    )
    await _finish_registration(callback.message, state, callback.from_user.id, data)
    await callback.answer()


# ── /register ─────────────────────────────────────────────────────────────

@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext, user_id: int = None):
    await state.clear()
    uid = _get_user_id(message, user_id)
    default = _default_name(message) if not user_id else ""
    kb = _kb([_SKIP_BUTTON])
    if default:
        await message.answer(
            f"Давай познакомимся!\n\n"
            f"Как к тебе обращаться? Напиши имя или нажми «Пропустить», "
            f"чтобы использовать <b>{html.escape(default)}</b>.",
            reply_markup=kb
        )
    else:
        await message.answer("Привет! Как к тебе обращаться? Напиши своё имя.", reply_markup=kb)
    await state.update_data(_user_id=uid)
    await state.set_state(Registration.waiting_for_name)


@router.message(StateFilter(Registration), F.text.in_(MAIN_MENU_BUTTONS))
async def registration_menu_escape(message: Message, state: FSMContext):
    """Кнопка главного меню во время регистрации — отменить и открыть раздел."""
    await state.clear()
    if message.text == "📱 Приложение":
        from bot.handlers.menu import cmd_app
        await cmd_app(message)
        return
    from bot.handlers.menu import show_submenu
    await show_submenu(message)


@router.message(StateFilter(Registration), F.text.startswith("/"))
async def registration_command_escape(message: Message, state: FSMContext):
    """Команда во время регистрации — отменить регистрацию и отпустить команду."""
    await state.clear()
    await message.answer(
        "Регистрация отменена. Повтори команду — или начни заново: /register",
        reply_markup=get_main_menu(),
    )


@router.message(Registration.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    default = _default_name(message)
    if not name:
        name = default or "Пользователь"
    await state.update_data(username=name)
    await message.answer(f"Приятно познакомиться, {html.escape(name)}!")
    await _ask_gender(message, state)


@router.callback_query(Registration.waiting_for_gender, F.data.startswith("reg_gender_"))
async def process_gender_btn(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.removeprefix("reg_gender_")
    if gender not in ("male", "female"):
        await callback.answer()
        return
    await state.update_data(gender=gender)
    await callback.message.edit_text(f"Пол: <b>{'мужской' if gender == 'male' else 'женский'}</b>")
    await _ask_age(callback.message, state)
    await callback.answer()


@router.message(Registration.waiting_for_gender)
async def process_gender(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    if answer not in GENDER_MAP:
        await message.answer("Пожалуйста, выбери пол кнопкой выше или напиши <b>мужской</b> / <b>женский</b>")
        return
    await state.update_data(gender=GENDER_MAP[answer])
    await _ask_age(message, state)


@router.message(Registration.waiting_for_age)
async def process_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age < 10 or age > 120:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введи возраст от 10 до 120 лет")
        return
    await state.update_data(age=age)
    await _ask_height(message, state)


@router.message(Registration.waiting_for_height)
async def process_height(message: Message, state: FSMContext):
    try:
        height = float(message.text.strip().replace(",", "."))
        if height < 100 or height > 250:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введи рост в см (от 100 до 250)")
        return
    await state.update_data(height_cm=height)
    await _ask_weight(message, state)


@router.message(Registration.waiting_for_weight)
async def process_weight(message: Message, state: FSMContext):
    try:
        weight = float(message.text.strip().replace(",", "."))
        if weight < 30 or weight > 300:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введи вес в кг (от 30 до 300)")
        return
    await state.update_data(weight_kg=weight)
    await _ask_goal(message, state)


@router.callback_query(Registration.waiting_for_goal, F.data.startswith("reg_goal_"))
async def process_goal_btn(callback: CallbackQuery, state: FSMContext):
    goal = callback.data.removeprefix("reg_goal_")
    if goal not in ("lose", "maintain", "gain"):
        await callback.answer()
        return
    await state.update_data(goal=goal)
    label = {"lose": "похудеть", "maintain": "сохранить форму", "gain": "набрать массу"}[goal]
    await callback.message.edit_text(f"Цель: <b>{label}</b>")
    await _ask_activity(callback.message, state)
    await callback.answer()


@router.message(Registration.waiting_for_goal)
async def process_goal(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    if answer not in GOAL_MAP:
        await message.answer("Пожалуйста, выбери цель кнопкой выше или напиши <b>похудеть</b>, <b>сохранить</b> или <b>набрать</b>")
        return
    await state.update_data(goal=GOAL_MAP[answer])
    await _ask_activity(message, state)


@router.callback_query(Registration.waiting_for_activity, F.data.startswith("reg_act_"))
async def process_activity_btn(callback: CallbackQuery, state: FSMContext):
    activity = callback.data.removeprefix("reg_act_")
    if activity not in ("sedentary", "moderate", "high"):
        await callback.answer()
        return
    await state.update_data(activity=activity)
    label = {"sedentary": "низкая", "moderate": "средняя", "high": "высокая"}[activity]
    await callback.message.edit_text(f"Активность: <b>{label}</b>")
    await _ask_allergies(callback.message, state)
    await callback.answer()


@router.message(Registration.waiting_for_activity)
async def process_activity(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    if answer not in ACTIVITY_MAP:
        await message.answer("Пожалуйста, выбери активность кнопкой выше или напиши <b>низкая</b>, <b>средняя</b> или <b>высокая</b>")
        return
    await state.update_data(activity=ACTIVITY_MAP[answer])
    await _ask_allergies(message, state)


@router.message(Registration.waiting_for_allergies)
async def process_allergies(message: Message, state: FSMContext):
    allergies = message.text.strip()
    if allergies.lower() in ("нет", "no", "none", "отсутствуют"):
        allergies = ""
    await state.update_data(allergies=allergies)
    await _ask_city(message, state)


@router.message(Registration.waiting_for_city)
async def process_city(message: Message, state: FSMContext):
    city = message.text.strip()
    if not city:
        city = "Moscow"
    await state.update_data(city=city)
    await _ask_timezone(message, state)


@router.callback_query(Registration.waiting_for_timezone, F.data == "reg_tz_other")
async def process_timezone_other(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введи смещение от UTC в минутах.\n\n"
        "Например:\n"
        "• Москва — <b>180</b>\n"
        "• Екатеринбург — <b>300</b>\n"
        "• Владивосток — <b>600</b>",
        reply_markup=_kb()
    )
    await state.set_state(Registration.waiting_for_timezone_manual)
    await callback.answer()


@router.callback_query(Registration.waiting_for_timezone, F.data.regexp(r"^reg_tz_\d+$"))
async def process_timezone_btn(callback: CallbackQuery, state: FSMContext):
    tz = int(callback.data.removeprefix("reg_tz_"))
    await state.update_data(timezone_offset=tz)
    await callback.message.edit_text(f"Часовой пояс: <b>UTC{tz // 60:+d}</b>")
    await _ask_digest_time(callback.message, state)
    await callback.answer()


@router.message(Registration.waiting_for_timezone_manual)
async def process_timezone_manual(message: Message, state: FSMContext):
    try:
        tz = int(message.text.strip())
        if tz < -720 or tz > 840:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введи целое число от -720 до 840")
        return
    await state.update_data(timezone_offset=tz)
    await _ask_digest_time(message, state)


@router.message(Registration.waiting_for_timezone)
async def process_timezone(message: Message, state: FSMContext):
    # Текстовый ввод для тех, кто проигнорировал кнопки
    try:
        tz = int(message.text.strip())
        if tz < -720 or tz > 840:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, выбери часовой пояс кнопкой выше или введи число от -720 до 840")
        return
    await state.update_data(timezone_offset=tz)
    await _ask_digest_time(message, state)


@router.message(Registration.waiting_for_digest_time)
async def process_digest_time(message: Message, state: FSMContext):
    from datetime import time as dt_time
    raw = message.text.strip()
    if ":" not in raw:
        await message.answer("Пожалуйста, введи время в формате ЧЧ:ММ (например, 07:00)")
        return
    parts = raw.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        t = dt_time(hour, minute)
        formatted = f"{hour:02d}:{minute:02d}"
    except (ValueError, IndexError):
        await message.answer("Пожалуйста, введи время в формате ЧЧ:ММ (например, 07:00)")
        return

    data = await state.get_data()
    data["preferred_time"] = formatted
    user_id = data.get("_user_id") or message.from_user.id
    await _finish_registration(message, state, user_id, data)


async def _finish_registration(message: Message, state: FSMContext, user_id: int, data: dict):
    """Создать пользователя, посчитать нормы и отправить финальное сообщение."""
    required = ["gender", "age", "height_cm", "weight_kg", "goal", "activity",
                "timezone_offset", "preferred_time"]
    missing = [f for f in required if f not in data]
    if missing:
        await state.clear()
        await message.answer("⚠️ Данные профиля потеряны. Начни заново с /register.")
        return

    username = data.get("username") or "Пользователь"

    get_or_create_user(user_id, username)
    update_user(
        user_id,
        username=username,
        gender=data["gender"],
        age=data["age"],
        height_cm=data["height_cm"],
        weight_kg=data["weight_kg"],
        goal=data["goal"],
        activity=data["activity"],
        allergies=data.get("allergies", ""),
        city=data.get("city", "Moscow"),
        timezone_offset=data["timezone_offset"],
        preferred_time=data["preferred_time"],
    )

    # Активируем пробный период
    start_trial(user_id)

    await state.clear()

    user = get_user(user_id)
    metrics = compute_profile(
        weight_kg=float(user["weight_kg"]),
        height_cm=float(user["height_cm"]),
        age=int(user["age"]),
        gender=user["gender"],
        activity=user["activity"],
        goal=user["goal"],
    )

    GENDER_LABEL = {"male": "мужской", "female": "женский"}
    GOAL_LABEL = {"lose": "похудеть", "maintain": "сохранить", "gain": "набрать"}
    ACTIVITY_LABEL = {"sedentary": "низкая", "moderate": "средняя", "high": "высокая"}
    BMI_LABEL = {
        "underweight": "недостаточный вес",
        "normal": "норма",
        "overweight": "избыточный вес",
        "obese": "ожирение",
        "unknown": "неизвестно",
    }

    await message.answer(
        f"✅ <b>Профиль сохранён!</b>\n\n"
        f"👤 Имя: {html.escape(str(user['username']))}\n"
        f"• Пол: {GENDER_LABEL.get(user['gender'], user['gender'])}\n"
        f"• Возраст: {user['age']}\n"
        f"• Рост: {user['height_cm']} см\n"
        f"• Вес: {user['weight_kg']} кг\n"
        f"• Цель: {GOAL_LABEL.get(user['goal'], user['goal'])}\n"
        f"• Активность: {ACTIVITY_LABEL.get(user['activity'], user['activity'])}\n"
        f"• Аллергии: {html.escape(str(user['allergies'] or 'нет'))}\n"
        f"• Город: {html.escape(str(user.get('city', 'Moscow')))}\n"
        f"• Часовой пояс: UTC{user['timezone_offset']:+d} мин\n"
        f"• Дайджест в: {user['preferred_time']}\n\n"
        f"<b>Показатели:</b>\n"
        f"• ИМТ (BMI): {metrics['bmi']} ({BMI_LABEL.get(metrics['bmi_category'], metrics['bmi_category'])})\n"
        f"• Базовый обмен (BMR): {metrics['bmr']} ккал\n"
        f"• Поддержание веса (TDEE): {metrics['tdee']} ккал\n"
        f"• Цель калорий: {metrics['daily_calorie_goal']} ккал\n"
        f"• Белки: {metrics['protein_g_target']} г\n"
        f"• Жиры: {metrics['fat_g_target']} г\n"
        f"• Углеводы: {metrics['carbs_g_target']} г\n\n"
        f"<b>Что дальше?</b>\n"
        f"✍️ Напиши, что съел — я запишу (например: «200 г гречки с курицей»)\n"
        f"📸 Пришли фото еды — распознаю и посчитаю КБЖУ\n"
        f"🤖 Спроси что угодно — я AI-коуч, отвечу и помогу",
        reply_markup=get_main_menu()
    )


# ── /profile ──────────────────────────────────────────────────────────────

@router.message(Command("profile"))
async def cmd_profile(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer(
            "Ты ещё не зарегистрирован.\n"
            "Используй команду /register для создания профиля."
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

    GENDER_LABEL = {"male": "мужской", "female": "женский"}
    GOAL_LABEL = {"lose": "похудеть", "maintain": "сохранить", "gain": "набрать"}
    ACTIVITY_LABEL = {"sedentary": "низкая", "moderate": "средняя", "high": "высокая"}
    BMI_LABEL = {
        "underweight": "недостаточный вес",
        "normal": "норма",
        "overweight": "избыточный вес",
        "obese": "ожирение",
        "unknown": "неизвестно",
    }

    # Собираем полный текст профиля
    text = f"👤 <b>Твой профиль</b>\n\n"
    text += f"👤 Имя: {html.escape(str(user['username']))}\n"
    text += f"• Пол: {GENDER_LABEL.get(user['gender'], user['gender'])}\n"
    text += f"• Возраст: {user['age']}\n"
    text += f"• Рост: {user['height_cm']} см\n"
    text += f"• Вес: {user['weight_kg']} кг\n"
    text += f"• Цель: {GOAL_LABEL.get(user['goal'], user['goal'])}\n"
    text += f"• Активность: {ACTIVITY_LABEL.get(user['activity'], user['activity'])}\n"
    text += f"• Аллергии: {html.escape(str(user['allergies'] or 'нет'))}\n"
    text += f"• Город: {html.escape(str(user.get('city', 'Moscow')))}\n"
    text += f"• Часовой пояс: UTC{user['timezone_offset']:+d} мин\n"
    text += f"• Дайджест в: {user['preferred_time']}\n\n"

    # Добавляем вид спорта
    from core.sports.catalog import get_user_sport, get_sport_icon
    user_sport = get_user_sport(uid)

    if user_sport and user_sport.get('sport_id'):
        icon = get_sport_icon(user_sport.get('name_en', ''))
        text += f"🏃 <b>Вид спорта:</b> {icon} {user_sport.get('name', 'Не выбран')}\n"
        text += f"📈 <b>Уровень:</b> {user_sport.get('sport_level', 'beginner')}\n\n"
    else:
        text += f"🏃 <b>Вид спорта:</b> Не выбран (используй /set_sport)\n\n"

    text += f"<b>Показатели:</b>\n"
    text += f"• ИМТ (BMI): {metrics['bmi']} ({BMI_LABEL.get(metrics['bmi_category'], metrics['bmi_category'])})\n"
    text += f"• Базовый обмен (BMR): {metrics['bmr']} ккал\n"
    text += f"• Поддержание веса (TDEE): {metrics['tdee']} ккал\n"
    text += f"• Цель калорий: {metrics['daily_calorie_goal']} ккал\n"
    text += f"• Белки: {metrics['protein_g_target']} г\n"
    text += f"• Жиры: {metrics['fat_g_target']} г\n"
    text += f"• Углеводы: {metrics['carbs_g_target']} г\n\n"
    text += f"Для изменения данных используй /register повторно."

    await message.answer(text)
