"""Обработчики тренировок: сессии, планы, упражнения (с поддержкой user_id)."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import html
import json
import logging

from core.database import get_user
from core.training_service import (
    get_exercises_by_muscle, add_exercise as db_add_exercise,
    create_session, add_exercise_to_session, add_set,
    get_session_history,
    get_exercise_history, suggest_progression,
    save_workout_feedback
)
from core.api_clients import search_exercises_by_name_wger, get_exercise_detail_wger
from core.gamification import notify_progress
from bot.handlers.admin import is_admin

logger = logging.getLogger(__name__)

router = Router()

# Словарь групп мышц для кнопок
MUSCLE_GROUPS = {
    "chest": "Грудь",
    "back": "Спина",
    "legs": "Ноги",
    "shoulders": "Плечи",
    "core": "Пресс",
    "cardio": "Кардио",
    "full_body": "Всё тело",
}


# ── Состояния FSM ────────────────────────────────────────────────────────

class WorkoutSession(StatesGroup):
    choosing_type = State()
    entering_duration = State()
    entering_intensity = State()
    managing_exercises = State()
    adding_exercise_name = State()
    entering_sets = State()
    entering_rest = State()


class AddExercise(StatesGroup):
    waiting_for_name = State()
    waiting_for_muscle = State()
    waiting_for_type = State()


class WorkoutFeedback(StatesGroup):
    difficulty = State()
    soreness = State()
    energy = State()


# ── Вспомогательная функция ──────────────────────────────────────────────

def _get_user_id(message: Message, user_id: int = None) -> int:
    return user_id if user_id else message.from_user.id


# ── /start_workout ────────────────────────────────────────────────────────

@router.message(Command("start_workout"))
async def cmd_start_workout(message: Message, state: FSMContext, user_id: int = None):
    uid = _get_user_id(message, user_id)
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏋️ Силовая", callback_data="type_strength")],
        [InlineKeyboardButton(text="🏃 Кардио", callback_data="type_cardio")],
        [InlineKeyboardButton(text="🧘 Растяжка", callback_data="type_stretching")],
    ])
    await message.answer("Выбери тип тренировки:", reply_markup=kb)
    await state.set_state(WorkoutSession.choosing_type)


@router.callback_query(WorkoutSession.choosing_type, F.data.startswith("type_"))
async def process_type(callback: CallbackQuery, state: FSMContext):
    type_map = {
        "type_strength": "strength",
        "type_cardio": "cardio",
        "type_stretching": "stretching",
    }
    session_type = type_map.get(callback.data)
    if not session_type:
        await callback.answer()
        return
    await state.update_data(session_type=session_type)
    await callback.message.edit_text("Введи общую длительность в минутах (или пришли 0, если не важно):")
    await state.set_state(WorkoutSession.entering_duration)
    await callback.answer()


@router.message(WorkoutSession.entering_duration)
async def process_duration(message: Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
        if duration < 0 or duration > 600:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введи целое число минут от 0 до 600.")
        return
    await state.update_data(duration=duration)
    await message.answer("Оцени интенсивность от 1 до 10:")
    await state.set_state(WorkoutSession.entering_intensity)


@router.message(WorkoutSession.entering_intensity)
async def process_intensity(message: Message, state: FSMContext):
    try:
        intensity = int(message.text.strip())
        if not 1 <= intensity <= 10:
            raise ValueError
    except ValueError:
        await message.answer("Введи число от 1 до 10.")
        return
    await state.update_data(intensity=intensity)

    data = await state.get_data()
    user_id = data.get("_user_id") or message.from_user.id
    session_id = create_session(
        user_id=user_id,
        session_type=data["session_type"],
        duration_min=data["duration"],
        intensity=data["intensity"],
    )
    await state.update_data(session_id=session_id, exercises=[])

    await message.answer("Сессия создана! Теперь добавляй упражнения.")
    await show_session_menu(message, state)


async def show_session_menu(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить упражнение", callback_data="add_exercise_to_session")],
        [InlineKeyboardButton(text="✅ Завершить тренировку", callback_data="finish_session")],
    ])
    data = await state.get_data()
    ex_list = data.get("exercises", [])
    if ex_list:
        text = "Текущие упражнения:\n" + "\n".join(f"• {html.escape(str(e['name']))}" for e in ex_list)
    else:
        text = "Пока нет упражнений."
    await message.answer(text, reply_markup=kb)
    await state.set_state(WorkoutSession.managing_exercises)


@router.callback_query(WorkoutSession.managing_exercises, F.data == "add_exercise_to_session")
async def add_exercise_to_session_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введи название упражнения или выбери из базы:")
    await state.set_state(WorkoutSession.adding_exercise_name)
    await callback.answer()


@router.message(WorkoutSession.adding_exercise_name)
async def process_exercise_name(message: Message, state: FSMContext):
    name = message.text.strip()
    exercises = get_exercises_by_muscle("")
    matches = [e for e in exercises if name.lower() in e["name"].lower()][:5]
    if matches:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=e["name"], callback_data=f"use_exercise_{e['id']}")] for e in matches
        ] + [[InlineKeyboardButton(text="✍️ Ввести своё", callback_data="use_custom_exercise")]])
        await state.update_data(custom_name=name)
        await message.answer("Найдены упражнения:", reply_markup=kb)
    else:
        await state.update_data(custom_name=name)
        await message.answer("Упражнение не найдено в базе. Введи подходы вручную (вес x повторения через запятую, например 20x12, 25x10):")
        await state.set_state(WorkoutSession.entering_sets)


@router.callback_query(WorkoutSession.adding_exercise_name, F.data.startswith("use_exercise_"))
async def use_existing_exercise(callback: CallbackQuery, state: FSMContext):
    try:
        ex_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("❌ Ошибка выбора упражнения")
        return
    await state.update_data(selected_exercise_id=ex_id, custom_name=None)
    await callback.message.edit_text("Введи подходы (вес x повторения через запятую, например 20x12, 25x10):")
    await state.set_state(WorkoutSession.entering_sets)
    await callback.answer()


@router.callback_query(WorkoutSession.adding_exercise_name, F.data == "use_custom_exercise")
async def use_custom_exercise(callback: CallbackQuery, state: FSMContext):
    await state.update_data(selected_exercise_id=None)
    await callback.message.edit_text("Введи подходы (вес x повторения через запятую, например 20x12, 25x10):")
    await state.set_state(WorkoutSession.entering_sets)
    await callback.answer()


@router.message(WorkoutSession.entering_sets)
async def process_sets(message: Message, state: FSMContext):
    raw = message.text.strip()
    sets = []
    for part in raw.split(","):
        part = part.strip()
        if "x" in part:
            try:
                w, r = part.split("x")
                sets.append((float(w.strip()), int(r.strip())))
            except ValueError:
                await message.answer("Неверный формат. Попробуй ещё раз (например, 20x12, 25x10).")
                return
        else:
            await message.answer("Используй формат весxповторения, например 20x12.")
            return
    if not sets:
        await message.answer("Введи хотя бы один подход.")
        return

    data = await state.get_data()
    session_id = data["session_id"]
    ex_name = data.get("custom_name", "Упражнение")
    ex_id = data.get("selected_exercise_id")

    we_id = add_exercise_to_session(
        session_id=session_id,
        exercise_id=ex_id,
        custom_name=ex_name if not ex_id else None,
        sort_order=len(data.get("exercises", [])) + 1,
    )
    for i, (weight, reps) in enumerate(sets, 1):
        add_set(we_id, set_number=i, reps=reps, weight_kg=weight)

    ex_list = data.get("exercises", [])
    ex_list.append({"name": ex_name if not ex_id else f"Упражнение #{ex_id}"})
    await state.update_data(exercises=ex_list)

    await message.answer("Упражнение добавлено! Что дальше?")
    await show_session_menu(message, state)


@router.callback_query(WorkoutSession.managing_exercises, F.data == "finish_session")
async def finish_session(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    session_id = data.get("session_id")
    user_id = callback.from_user.id
    await state.clear()
    await callback.message.edit_text(f"Тренировка завершена! ID сессии: {session_id}\nИспользуй /stats для анализа.")
    await callback.answer()
    await notify_progress(callback.message, user_id)

    # Опрос самочувствия: ответы адаптируют следующий план
    await state.update_data(fb_session_id=session_id, fb_user_id=user_id)
    await callback.message.answer(
        "Короткий опрос, чтобы скорректировать следующую тренировку 💬\n\n"
        "1/3. Насколько тяжело далась тренировка? (1 — очень легко, 5 — очень тяжело)",
        reply_markup=_feedback_scale_keyboard("difficulty")
    )
    await state.set_state(WorkoutFeedback.difficulty)


# ── Опрос самочувствия после тренировки (fb_*) ────────────────────────────

def _feedback_scale_keyboard(metric: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=str(i), callback_data=f"fb_{metric}_{i}") for i in range(1, 6)
    ]])


@router.callback_query(WorkoutFeedback.difficulty, F.data.startswith("fb_difficulty_"))
async def fb_difficulty(callback: CallbackQuery, state: FSMContext):
    await state.update_data(fb_difficulty=int(callback.data.rsplit("_", 1)[1]))
    await state.set_state(WorkoutFeedback.soreness)
    await callback.message.edit_text(
        "2/3. Ощущаешь болезненность в мышцах? (1 — нет, 5 — очень сильная)",
        reply_markup=_feedback_scale_keyboard("soreness")
    )
    await callback.answer()


@router.callback_query(WorkoutFeedback.soreness, F.data.startswith("fb_soreness_"))
async def fb_soreness(callback: CallbackQuery, state: FSMContext):
    await state.update_data(fb_soreness=int(callback.data.rsplit("_", 1)[1]))
    await state.set_state(WorkoutFeedback.energy)
    await callback.message.edit_text(
        "3/3. Какой у тебя уровень энергии? (1 — разбит, 5 — полон сил)",
        reply_markup=_feedback_scale_keyboard("energy")
    )
    await callback.answer()


@router.callback_query(WorkoutFeedback.energy, F.data.startswith("fb_energy_"))
async def fb_energy(callback: CallbackQuery, state: FSMContext):
    energy = int(callback.data.rsplit("_", 1)[1])
    data = await state.get_data()
    save_workout_feedback(
        user_id=data.get("fb_user_id") or callback.from_user.id,
        session_id=data.get("fb_session_id"),
        difficulty=data.get("fb_difficulty"),
        soreness=data.get("fb_soreness"),
        energy=energy,
    )
    await state.clear()
    await callback.message.edit_text("Спасибо! Учту это при составлении следующего плана 💪")
    await callback.answer()


# ── /add_exercise ─────────────────────────────────────────────────────────

@router.message(Command("add_exercise"))
async def cmd_add_exercise(message: Message, state: FSMContext, user_id: int = None):
    uid = _get_user_id(message, user_id)
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await state.set_state(AddExercise.waiting_for_name)
    await message.answer("Введи название нового упражнения:")


@router.message(AddExercise.waiting_for_name)
async def process_new_ex_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=MUSCLE_GROUPS[mg], callback_data=f"muscle_{mg}")] for mg in MUSCLE_GROUPS
    ])
    await message.answer("Выбери группу мышц:", reply_markup=kb)
    await state.set_state(AddExercise.waiting_for_muscle)


@router.callback_query(AddExercise.waiting_for_muscle, F.data.startswith("muscle_"))
async def process_new_ex_muscle(callback: CallbackQuery, state: FSMContext):
    mg = callback.data.split("_", 1)[1]
    await state.update_data(muscle_group=mg)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Силовое", callback_data="type_strength")],
        [InlineKeyboardButton(text="Кардио", callback_data="type_cardio")],
        [InlineKeyboardButton(text="Растяжка", callback_data="type_stretching")],
    ])
    await callback.message.edit_text("Выбери тип упражнения:", reply_markup=kb)
    await state.set_state(AddExercise.waiting_for_type)
    await callback.answer()


@router.callback_query(AddExercise.waiting_for_type, F.data.startswith("type_"))
async def process_new_ex_type(callback: CallbackQuery, state: FSMContext):
    ex_type = callback.data.split("_", 1)[1]
    data = await state.get_data()
    user_id = callback.from_user.id
    db_add_exercise(
        name=data["name"],
        muscle_group=data["muscle_group"],
        ex_type=ex_type,
        is_custom=True,
        added_by=user_id,
    )
    await state.clear()
    await callback.message.edit_text(f"Упражнение «{html.escape(str(data['name']))}» добавлено!")
    await callback.answer()


# ── /workout_history ──────────────────────────────────────────────────────

@router.message(Command("workout_history"))
async def cmd_workout_history(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    sessions = get_session_history(uid, days=7)
    if not sessions:
        await message.answer("За последние 7 дней тренировок не найдено.")
        return
    text = "📋 <b>История тренировок за неделю:</b>\n\n"
    for s in sessions[:5]:
        text += f"<b>{s['date']}</b> — {s['type']} ({s['duration_min']} мин)\n"
        for ex in s.get("exercises", []):
            sets_str = ", ".join(f"{st['weight_kg']}×{st['reps']}" for st in ex.get("sets", []))
            text += f"  • {ex.get('name') or ex.get('custom_exercise_name', '?')}: {sets_str}\n"
        text += "\n"
    await message.answer(text)

@router.message(Command("check_exercises"))
async def cmd_check_exercises(message: Message):
    if not is_admin(message.from_user.id, message.from_user.username or ""):
        await message.answer("⛔ Доступ запрещён.")
        return
    from core.database import get_db
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
    await message.answer(f"Упражнений в базе: {total}")

@router.message(Command("debug_plan"))
async def cmd_debug_plan(message: Message):
    if not is_admin(message.from_user.id, message.from_user.username or ""):
        await message.answer("⛔ Доступ запрещён.")
        return
    from core.training_service import get_exercises_by_muscle
    groups = ["chest", "back", "legs", "shoulders", "core"]
    text = ""
    for mg in groups:
        exercises = get_exercises_by_muscle(mg)
        text += f"{mg}: {len(exercises)} упр.\n"
        if exercises:
            text += f"  пример: {exercises[0]['name']}\n"
    await message.answer(text)

@router.message(Command("test_plan"))
async def cmd_test_plan(message: Message, state: FSMContext, user_id: int = None):
    if not is_admin(message.from_user.id, message.from_user.username or ""):
        await message.answer("⛔ Доступ запрещён.")
        return
    uid = _get_user_id(message, user_id)
    from core.training_service import generate_daily_workout_plan
    plan = generate_daily_workout_plan(uid)
    if plan is None:
        await message.answer("Генератор вернул None")
    elif "error" in plan:
        await message.answer(f"Ошибка: {plan['error']}")
    else:
        await message.answer(f"Результат генератора:\n\n{json.dumps(plan, ensure_ascii=False, indent=2, default=str)}")

class ExerciseProgress(StatesGroup):
    waiting_for_exercise = State()

@router.message(Command("progress"))
async def cmd_progress_start(message: Message, state: FSMContext):
    await state.set_state(ExerciseProgress.waiting_for_exercise)
    await message.answer("Введите название упражнения для просмотра прогресса (например, «Жим штанги лёжа»):")

@router.message(ExerciseProgress.waiting_for_exercise)
async def process_progress_name(message: Message, state: FSMContext):
    name = message.text.strip()
    uid = message.from_user.id
    sessions = get_exercise_history(uid, name)
    if not sessions:
        await state.clear()
        await message.answer(f"По упражнению «{html.escape(name)}» пока нет данных.")
        return
    text = f"📈 <b>Прогресс: {html.escape(name)}</b>\n\n"
    for sess in sessions[:5]:
        text += f"📅 {sess['date']}:\n"
        for s in sess["sets"]:
            text += f"  • {s['weight']} кг × {s['reps']}\n"
        text += "\n"
    suggestion = suggest_progression(uid, name)
    if suggestion:
        text += f"\n💡 {suggestion}"
    await state.clear()
    await message.answer(text)

# ═══════════════════════════════════════════════════════════════
# ПОИСК УПРАЖНЕНИЙ
# ═══════════════════════════════════════════════════════════════

@router.message(Command("search_exercise"))
async def cmd_search_exercise(message: Message, state: FSMContext, user_id: int = None):
    """Поиск упражнений."""
    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    await message.answer(
        "🏋️ <b>Поиск упражнений</b>\n\n"
        "Напиши название упражнения (на английском):\n"
        "<i>Например: bench press, squat, deadlift</i>"
    )

    await state.set_state(SearchExercise.waiting_for_query)


class SearchExercise(StatesGroup):
    waiting_for_query = State()
    waiting_for_selection = State()


@router.message(SearchExercise.waiting_for_query)
async def process_exercise_search(message: Message, state: FSMContext):
    """Поиск упражнений по названию."""
    query = message.text.strip()

    if not query:
        await message.answer("Введи название упражнения.")
        return

    # ═══════════════════════════════════════════════════════════════
    # ИМПОРТ ПЕРЕВОДА
    # ═══════════════════════════════════════════════════════════════

    from core.api_clients import translate_query_ru_to_en, translate_exercise_name

    # Перевод запроса RU → EN
    en_query = translate_query_ru_to_en(query)
    logger.info("Поиск: %s → %s", query, en_query)

    # Ищем в wger
    exercises = await search_exercises_by_name_wger(en_query, limit=5)

    if not exercises:
        await message.answer(
            f"❌ Ничего не найдено по запросу \"{html.escape(query)}\"\n\n"
            f"<i>Попробуй: жим лежа, приседания, становая тяга</i>"
        )
        await state.clear()
        return

    # ═══════════════════════════════════════════════════════════════
    # ПЕРЕВОД ДЛЯ ОТОБРАЖЕНИЯ
    # ═══════════════════════════════════════════════════════════════

    keyboard = []
    for ex in exercises[:5]:
        ru_name = translate_exercise_name(ex['name'])  # ← ПЕРЕВОД!
        kb_text = f"{ru_name} ({ex['category']})"
        keyboard.append([InlineKeyboardButton(text=kb_text, callback_data=f"ex_{ex['id']}")])

    keyboard.append([InlineKeyboardButton(text="❌ Искать снова", callback_data="ex_search_again")])

    await state.update_data(search_results=exercises)

    text = f"🏋️ Найдено по запросу \"{html.escape(query)}\":\n\n"
    for i, ex in enumerate(exercises[:5], 1):
        ru_name = translate_exercise_name(ex['name'])  # ← ПЕРЕВОД!
        text += f"{i}. <b>{html.escape(str(ru_name))}</b> — {html.escape(str(ex['category']))}\n"

    text += "\nВыбери упражнение:"

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await state.set_state(SearchExercise.waiting_for_selection)


@router.callback_query(F.data == "ex_search_again")
async def process_exercise_search_again(callback: F, state: FSMContext):
    await state.set_state(SearchExercise.waiting_for_query)
    await callback.message.edit_text("Напиши название упражнения:")
    await callback.answer()


@router.callback_query(F.data.startswith("ex_"))
async def process_exercise_select(callback: F, state: FSMContext):
    """Выбор упражнения (поиск — справочный)."""
    parts = callback.data.split("_")

    try:
        exercise_id = int(parts[1])
    except ValueError:
        await callback.answer("❌ Ошибка выбора упражнения")
        return

    # Сначала пробуем получить из state (если есть в результатах поиска)
    data = await state.get_data()
    search_results = data.get("search_results", [])

    # Ищем в результатах поиска
    exercise = None
    for ex in search_results:
        if ex.get("id") == exercise_id:
            exercise = ex
            break

    # Если не нашли в state, пробуем API
    if not exercise:
        exercise = await get_exercise_detail_wger(exercise_id)

    # Если всё ещё не нашли — используем fallback
    if not exercise:
        exercise = {
            "id": exercise_id,
            "name": f"Exercise #{exercise_id}",
            "category": "Strength",
            "muscles": [],
            "difficulty": "intermediate",
            "description": "Упражнение найдено в базе.",
            "video_url": "",
        }

    text = (
        f"🏋️ <b>{html.escape(str(exercise['name']))}</b>\n\n"
        f"📊 Категория: {html.escape(str(exercise['category']))}\n"
        f"💪 Сложность: {html.escape(str(exercise['difficulty']))}\n"
        f"🎯 Мышцы: {html.escape(', '.join(str(m) for m in exercise['muscles'])) if exercise['muscles'] else 'Не указано'}\n\n"
        f"📝 <b>Описание:</b>\n"
        f"{html.escape(str(exercise['description']))[:500]}...\n\n"
    )

    if exercise.get('video_url'):
        text += f"🎬 Видео: {exercise['video_url']}\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к поиску", callback_data="ex_search_again")],
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()
