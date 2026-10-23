"""Обработчики питания."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.nutrition_calc import get_nutrition_plan
from core.database import get_user
from core.sports.catalog import get_sport_icon

router = Router()


@router.message(Command("nutrition_plan"))
async def cmd_nutrition_plan(message: Message, user_id: int = None):
    """Показывает план питания с учётом вида спорта и цели."""
    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    plan = get_nutrition_plan(uid)

    if not plan:
        await message.answer("❌ Не удалось рассчитать план питания.")
        return

    # Иконка вида спорта
    sport = plan.get('sport')
    if sport and sport.get('name_en'):
        icon = get_sport_icon(sport.get('name_en', ''))
        sport_name = sport.get('name', 'Фитнес')
    else:
        icon = "🧘"
        sport_name = "Фитнес"

    # Цель
    goal_labels = {
        "lose": "Похудение",
        "maintain": "Поддержание",
        "gain": "Набор массы",
    }
    goal_label = goal_labels.get(plan.get('goal', 'maintain'), 'Поддержание')

    text = f"🍽 <b>Твой план питания</b>\n\n"
    text += f"🏃 <b>Вид спорта:</b> {icon} {sport_name}\n"
    text += f"🎯 <b>Цель:</b> {goal_label}\n\n"

    text += f"📊 <b>Калории:</b>\n"
    text += f"• Поддержание (TDEE): {plan.get('tdee', 0)} ккал\n"
    text += f"• Цель: <b>{plan.get('target_calories', 0)} ккал</b>\n\n"

    macros = plan.get('macros', {})
    text += f"📈 <b>БЖУ (грамм в день):</b>\n"
    text += f"• <b>Белки:</b> {macros.get('protein_g', 0)} г ({macros.get('protein_g', 0) * 4} ккал)\n"
    text += f"• <b>Жиры:</b> {macros.get('fat_g', 0)} г ({macros.get('fat_g', 0) * 9} ккал)\n"
    text += f"• <b>Углеводы:</b> {macros.get('carbs_g', 0)} г ({macros.get('carbs_g', 0) * 4} ккал)\n\n"

    # Проверка сходимости калорий
    total_macro_cal = plan.get('calories_from_macros', 0)
    target_cal = plan.get('target_calories', 0)

    if abs(total_macro_cal - target_cal) > 200:
        text += f"⚠️ <b>Внимание:</b> Калории из БЖУ ({total_macro_cal}) не сходятся с целью ({target_cal}).\n"
        text += f"Это нормально — БЖУ рассчитаны под вид спорта, калории можно скорректировать.\n\n"

    text += f"💡 <b>Рекомендации:</b>\n"

    if plan.get('goal') == 'lose':
        text += "• Дефицит калорий для похудения\n"
        text += "• Больше белка для сохранения мышц\n"
        text += "• Углеводы вокруг тренировки\n"
    elif plan.get('goal') == 'gain':
        text += "• Профицит калорий для набора массы\n"
        text += "• Белок 2.0+ г/кг для роста мышц\n"
        text += "• Углеводы для энергии на тренировках\n"
    else:
        text += "• Сбалансированное питание\n"
        text += "• Белок 1.6-1.8 г/кг\n"
        text += "• Углеводы по активности\n"

    text += f"\n💡 Используй /full_plan чтобы увидеть полный план (еда + тренировки)."

    await message.answer(text)

@router.message(Command("full_plan"))
async def cmd_today(message: Message, user_id: int = None):
    """Единый план на сегодня: тренировки + питание + восстановление."""
    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    # Получаем план питания
    from core.nutrition_calc import get_nutrition_plan
    nutrition = get_nutrition_plan(uid)

    # Получаем план тренировки
    from core.training_service import generate_daily_workout_plan
    workout = generate_daily_workout_plan(uid)

    # Формируем единый текст
    text = f"📅 <b>Твой план на сегодня</b>\n"
    text += f"<i>{datetime.now().strftime('%d.%m.%Y')}</i>\n\n"

    # ═══════════════════════════════════════════════════════════════
    # ПИТАНИЕ
    # ═══════════════════════════════════════════════════════════════
    text += f"🍽 <b>ПИТАНИЕ</b>\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🎯 Калории: <b>{nutrition.get('target_calories', 0)} ккал</b>\n"
    text += f"📊 БЖУ: Б {nutrition['macros']['protein_g']}г | Ж {nutrition['macros']['fat_g']}г | У {nutrition['macros']['carbs_g']}г\n\n"

    # Рекомендации по приёмам пищи
    text += f"🍳 <b>Примерное меню:</b>\n"

    try:
        from core.plans import generate_meal_plan
        meal_plan = generate_meal_plan({**dict(user), "user_id": uid})
        meals = meal_plan.get("meals", {})
        meal_names = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин", "snack": "Перекусы"}
        if not meals:
            raise ValueError("пустой план")
        for cat in ["breakfast", "lunch", "dinner", "snack"]:
            m = meals.get(cat)
            if m:
                text += f"• <b>{meal_names[cat]}</b> (~{m['cal']} ккал): {m['name']}\n"
    except Exception:
        # Фолбэк: пропорции от нормы калорий пользователя
        target_cal = nutrition.get('target_calories', 1800)
        text += f"• <b>Завтрак</b> (~{int(target_cal * 0.25)} ккал): овсянка + яйца + фрукты\n"
        text += f"• <b>Обед</b> (~{int(target_cal * 0.35)} ккал): гречка + курица + овощи\n"
        text += f"• <b>Ужин</b> (~{int(target_cal * 0.25)} ккал): рыба + рис + салат\n"
        text += f"• <b>Перекусы</b> (~{int(target_cal * 0.15)} ккал): творог, орехи, фрукты\n"

    text += f"\n💧 <b>Вода:</b> 2-3 литра в день\n\n"

    # ═══════════════════════════════════════════════════════════════
    # ТРЕНИРОВКА
    # ═══════════════════════════════════════════════════════════════
    text += f"🏋️ <b>ТРЕНИРОВКА</b>\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    if workout and workout.get('exercises'):
        # Группируем по модулям
        modules = {}
        for ex in workout.get('exercises', []):
            cat = ex.get('category', 'accessory')
            if cat not in modules:
                modules[cat] = []
            modules[cat].append(ex)

        module_names = {
            "warmup": "🔥 Разминка",
            "mobility": "🔄 Мобилизация",
            "special": "🎯 Спец. разминка",
            "strength": "💪 Основная сила",
            "accessory": "🏋️ ОФП",
            "cool_down": "🧘 Заминка",
        }

        module_order = ["warmup", "mobility", "special", "strength", "accessory", "cool_down"]

        for module_key in module_order:
            exercises = modules.get(module_key, [])
            if not exercises:
                continue

            text += f"<b>{module_names.get(module_key, module_key)}</b>:\n"
            for i, ex in enumerate(exercises[:3], 1):  # Показываем до 3 упражнений
                if ex.get('category') in ['warmup', 'cool_down']:
                    text += f"  {i}. {ex['name']}\n"
                else:
                    sets = ex.get('sets', 3)
                    reps = f"{ex.get('reps_min', 8)}-{ex.get('reps_max', 12)}"
                    text += f"  {i}. {ex['name']} — {sets}×{reps}\n"
            text += "\n"
    else:
        text += "❌ План тренировки не сгенерирован. Используй /workout_plan\n\n"

    # ═══════════════════════════════════════════════════════════════
    # ВОССТАНОВЛЕНИЕ
    # ═══════════════════════════════════════════════════════════════
    text += f"🧘 <b>ВОССТАНОВЛЕНИЕ</b>\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"😴 <b>Сон:</b> 7-9 часов (22:30 - 06:30)\n"
    text += f"💧 <b>Вода:</b> 2-3 литра\n"
    text += f"🚶 <b>Активность:</b> прогулка 30 мин\n"

    if nutrition.get('goal') == 'gain':
        text += f"💡 <b>Совет:</b> После тренировки обязательно углеводы + белок!\n"
    elif nutrition.get('goal') == 'lose':
        text += f"💡 <b>Совет:</b> Дефицит калорий, но не голодай!\n"
    else:
        text += f"💡 <b>Совет:</b> Сбалансированное питание и режим!\n"

    text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"<i>Используй /workout_plan и /nutrition_plan для деталей.</i>"

    await message.answer(text)


# Для импорта datetime
from datetime import datetime