"""AI-обработчик фото еды для BodyPilot.

Фото классифицируется одним vision-вызовом (photo_type):
- dish    → сразу запись в дневник (как раньше)
- label   → этикетка с КБЖУ на 100 г: ввод веса → карточка smart_input,
            опционально сохранение продукта в food_products (source="label")
- receipt → список позиций чека → «Записать всё» (КБЖУ оценивает модель)
- other   → вежливый отказ
"""

import html
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command  # ← ДОБАВИТЬ ЭТУ СТРОКУ
from bot.middleware.premium_check import check_ai_limit
from core.ai.food_recognition import (
    analyze_food_photo,
    add_recognized_dish,
    scale_label_to_weight,
    get_food_suggestions,
)
from core.ai.chat_history import append_event
from core.ai.tools import execute_tool
from core.database import get_user, get_db
from core.nutrition_calc import get_nutrition_plan
from core.nutrition_tracker import get_today_summary, add_food_product
from core.gamification import notify_progress
from bot.handlers.smart_input import (
    _food_card_text,
    _food_card_keyboard,
    _meal_type_by_time,
    MEAL_NAMES_RU,
)

logger = logging.getLogger(__name__)

router = Router()


class PhotoLabelInput(StatesGroup):
    """Ввод веса порции после распознавания этикетки."""
    waiting_for_weight = State()


MANUAL_INPUT_HINT = (
    "💡 <b>Попробуй вручную:</b>\n\n"
    "Напиши название продукта:\n"
    "<i>Например: гречка 200г, куриная грудка</i>\n\n"
    "Используй /add_food"
)


# ═══════════════════════════════════════════════════════════════
# КЛАССИФИКАЦИЯ ФОТО + СЦЕНАРИИ ПО ТИПАМ
# ═══════════════════════════════════════════════════════════════

async def _process_food_photo(
        message: Message,
        state: FSMContext,
        uid: int,
        image_bytes: bytes,
        meal_type: str = None,
) -> dict | None:
    """Классифицировать фото и обработать неблюдо-сценарии.

    Возвращает результат add_recognized_dish для photo_type="dish"
    (рендерит вызывающий хендлер) или None, если ответ уже отправлен здесь.
    """
    status_message = await message.answer("🤖 <b>AI анализирует фото...</b>\n\nЭто займёт 5-10 секунд.")

    try:
        parsed = await analyze_food_photo(image_bytes)
    except Exception as e:
        logger.exception("AI food error: %s", e)
        await message.bot.delete_message(uid, status_message.message_id)
        await message.answer(
            "❌ <b>Ошибка при распознавании</b>\n\n"
            "Попробуй ещё раз или используй /add_food"
        )
        return None

    await message.bot.delete_message(uid, status_message.message_id)
    photo_type = parsed.get("photo_type")

    if photo_type == "error":
        reason = html.escape(str(parsed.get("reason", "ошибка AI")))
        await message.answer(f"❌ Не удалось распознать: {reason}")
        await message.answer(MANUAL_INPUT_HINT)
        return None

    if photo_type == "other":
        await message.answer(
            "🤷 <b>Не смог распознать еду на фото.</b>\n\n"
            "Пришли фото блюда, этикетки с КБЖУ или чек из магазина/кафе 📸"
        )
        return None

    if photo_type == "label":
        label = parsed["label"]
        await state.update_data(photo_label=label)
        await state.set_state(PhotoLabelInput.waiting_for_weight)

        builder = InlineKeyboardBuilder()
        builder.button(text="💾 Сохранить продукт", callback_data="label_save_product")
        builder.button(text="❌ Отмена", callback_data="label_cancel")
        builder.adjust(1)

        brand_line = f"🏷 Бренд: {html.escape(label['brand'])}\n" if label.get("brand") else ""
        await message.answer(
            f"📦 <b>Это упаковка:</b> {html.escape(label['product_name'])}\n"
            f"{brand_line}\n"
            f"📊 <b>КБЖУ на 100 г:</b>\n"
            f"🔥 {label['calories_100g']:g} ккал | "
            f"Б {label['protein_100g']:g}г | "
            f"Ж {label['fat_100g']:g}г | "
            f"У {label['carbs_100g']:g}г\n\n"
            "⚖️ Сколько грамм съел? Введи число (например: 250)",
            reply_markup=builder.as_markup(),
        )
        return None

    if photo_type == "receipt":
        items = parsed["items"]
        await state.update_data(receipt_items=items)

        total_cal = sum(i["calories"] for i in items)
        lines = []
        for i, item in enumerate(items[:15], 1):
            weight = f", {item['weight_g']:g}г" if item.get("weight_g") else ""
            lines.append(f"{i}. {html.escape(item['name'])}{weight} — {item['calories']:g} ккал")

        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Записать всё", callback_data="receipt_confirm_all")
        builder.button(text="❌ Отмена", callback_data="receipt_cancel")
        builder.adjust(1)

        await message.answer(
            f"🧾 <b>Похоже на чек.</b> Нашёл {len(items)} позиций "
            f"(~{total_cal:g} ккал суммарно):\n\n"
            + "\n".join(lines)
            + "\n\nЗаписать всё в дневник?",
            reply_markup=builder.as_markup(),
        )
        return None

    # dish — запись в дневник, рендерит вызывающий хендлер
    return add_recognized_dish(uid, parsed, meal_type=meal_type)


def _progress_text(uid: int) -> str:
    """Прогресс-бары за сегодня (для ответа по блюду без подписи)."""
    summary = get_today_summary(uid)
    plan = get_nutrition_plan(uid)

    def progress_bar(current, target, length=10):
        if target <= 0:
            return "─" * length
        percent = min(current / target, 1.0)
        filled = int(length * percent)
        return "█" * filled + "─" * (length - filled)

    cal_progress = progress_bar(summary.get("total_calories", 0), plan.get("target_calories", 2000))

    return (
        f"\n📊 <b>Прогресс за сегодня:</b>\n"
        f"🔥 Калории: {summary.get('total_calories', 0)} / {plan.get('target_calories', 2000)} ккал\n"
        f"`[{cal_progress}]`\n\n"
        f"Используй /food_today для полного отчёта."
    )


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТКА ФОТО ЕДЫ
# ═══════════════════════════════════════════════════════════════

@router.message(F.photo, ~F.caption)
@check_ai_limit("ai_photo")
async def handle_food_photo(message: Message, state: FSMContext, user_id: int = None):
    """
    Обработка фото еды.
    Пользователь отправляет фото → AI распознаёт → добавляет в дневник.
    """
    uid = user_id if user_id else message.from_user.id

    # Проверяем регистрацию
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    # Скачиваем фото (берём лучшее качество)
    photo = message.photo[-1]

    # Отправляем фото на файл для обработки
    file = await message.bot.get_file(photo.file_id)
    image_data = await message.bot.download_file(file.file_path)
    image_bytes = image_data.read()

    result = await _process_food_photo(message, state, uid, image_bytes)
    if result is None:
        return

    # Блюдо распознано и записано
    result["message"] += (
        _progress_text(uid)
        + "\n\nНапиши, что ещё съел, или пришли фото 📸"
    )

    await message.answer(result["message"])
    await notify_progress(message, uid)

    # Если уверенность низкая — предлагаем удалить запись
    entry_id = result.get("entry_id")
    if result.get("confidence", 1.0) < 0.7 and entry_id:
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Удалить запись", callback_data=f"ai_delete_entry_{entry_id}")
        await message.answer(
            "⚠️ AI не уверен в распознавании. Проверь данные:",
            reply_markup=builder.as_markup()
        )


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТКА ТЕКСТА С ФОТО
# ═══════════════════════════════════════════════════════════════

@router.message(F.photo & F.caption)
@check_ai_limit("ai_photo")
async def handle_food_photo_with_caption(message: Message, state: FSMContext, user_id: int = None):
    """
    Обработка фото с подписью.
    Пример: фото + "это был обед".
    """
    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    caption = message.caption

    # Определяем meal_type из подписи
    meal_type = "snack"
    caption_lower = caption.lower()

    if any(word in caption_lower for word in ["завтрак", "утро", "morning"]):
        meal_type = "breakfast"
    elif any(word in caption_lower for word in ["обед", "день", "lunch", "dinner"]):
        meal_type = "lunch"
    elif any(word in caption_lower for word in ["ужин", "вечер", "evening", "night"]):
        meal_type = "dinner"

    # Скачиваем фото
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_data = await message.bot.download_file(file.file_path)
    image_bytes = image_data.read()

    result = await _process_food_photo(message, state, uid, image_bytes, meal_type=meal_type)
    if result is None:
        return

    await message.answer(result["message"] + "\n\nНапиши, что ещё съел, или пришли фото 📸")
    await notify_progress(message, uid)


# ═══════════════════════════════════════════════════════════════
# ЭТИКЕТКА: ВВОД ВЕСА, СОХРАНЕНИЕ ПРОДУКТА, ОТМЕНА
# ═══════════════════════════════════════════════════════════════

@router.message(PhotoLabelInput.waiting_for_weight, F.text)
async def label_weight_input(message: Message, state: FSMContext):
    """Вес порции по этикетке → пересчёт КБЖУ на вес → карточка smart_input."""
    data = await state.get_data()
    label = data.get("photo_label")

    if not label:
        await state.clear()
        await message.answer("⚠️ Данные устарели — пришли фото этикетки ещё раз.")
        return

    try:
        weight = float(message.text.strip().replace(",", ".").replace("г", "").replace(" ", ""))
        if not (1 <= weight <= 5000):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число граммов от 1 до 5000 (например: 250)")
        return

    food = scale_label_to_weight(label, weight)

    # Карточка подтверждения переиспользуется из smart_input:
    # запись пойдёт через smart_food_confirm → execute_tool("log_food")
    await state.set_state(None)
    await state.update_data(smart_food=food)
    await message.answer(_food_card_text(food), reply_markup=_food_card_keyboard())


@router.callback_query(F.data == "label_save_product")
async def label_save_product(callback: CallbackQuery, state: FSMContext):
    """Сохранить продукт с этикетки в food_products (source="label")."""
    uid = callback.from_user.id
    data = await state.get_data()
    label = data.get("photo_label")

    if not label:
        await callback.answer("⚠️ Данные устарели — пришли фото этикетки ещё раз.", show_alert=True)
        return

    product_id = add_food_product(
        name=label["product_name"],
        calories=label["calories_100g"],
        protein=label["protein_100g"],
        fat=label["fat_100g"],
        carbs=label["carbs_100g"],
        brand=label.get("brand", ""),
        source="label",
        added_by=uid,
    )

    if product_id:
        append_event(
            uid,
            f"[событие: сохранён продукт с этикетки «{label['product_name']}», "
            f"{label['calories_100g']:g} ккал/100г]",
        )
        await callback.answer("💾 Продукт сохранён в базу", show_alert=True)
    else:
        await callback.answer("Такой продукт уже есть в базе", show_alert=True)


@router.callback_query(F.data == "label_cancel")
async def label_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена сценария этикетки."""
    await state.clear()
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# ЧЕК: ЗАПИСАТЬ ВСЁ / ОТМЕНА
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "receipt_confirm_all")
async def receipt_confirm_all(callback: CallbackQuery, state: FSMContext):
    """Записать все позиции чека в дневник (КБЖУ уже оценены моделью)."""
    uid = callback.from_user.id
    data = await state.get_data()
    items = data.get("receipt_items")

    if not items:
        await callback.answer("⚠️ Данные устарели — пришли фото чека ещё раз.", show_alert=True)
        return

    meal_type = _meal_type_by_time()
    logged, failed = [], []

    for item in items:
        result = execute_tool(uid, "log_food", {
            "product_name": item["name"],
            "weight_g": item.get("weight_g") or 100,
            "calories": item["calories"],
            "protein_g": item["protein_g"],
            "fat_g": item["fat_g"],
            "carbs_g": item["carbs_g"],
            "meal_type": meal_type,
        })
        if "error" in result:
            failed.append(item["name"])
        else:
            logged.append(item)

    await state.update_data(receipt_items=None)

    if not logged:
        await callback.message.edit_text("❌ Не удалось записать позиции чека. Попробуй /add_food")
        await callback.answer()
        return

    total_cal = sum(i["calories"] for i in logged)
    summary = get_today_summary(uid)
    plan = get_nutrition_plan(uid) or {}
    target = plan.get("target_calories", 2000)

    # Событие для AI-коуча (записи по позициям уже добавил log_food)
    append_event(
        uid,
        f"[событие: записан чек, {len(logged)} позиций, "
        f"{total_cal:g} ккал, {MEAL_NAMES_RU[meal_type]}]",
    )

    failed_line = ""
    if failed:
        failed_line = f"\n⚠️ Не записано: {html.escape(', '.join(failed))}\n"

    await callback.message.edit_text(
        f"✅ <b>Записал {len(logged)} позиций из чека</b> ({MEAL_NAMES_RU[meal_type]})\n\n"
        f"🔥 Суммарно: {total_cal:g} ккал\n"
        f"{failed_line}\n"
        f"📊 Сегодня: <b>{summary.get('total_calories', 0)}</b> из {target} ккал\n\n"
        "Напиши, что ещё съел, или пришли фото 📸"
    )
    await callback.answer("✅ Записано")
    await notify_progress(callback.message, uid)


@router.callback_query(F.data == "receipt_cancel")
async def receipt_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена сценария чека."""
    await state.update_data(receipt_items=None)
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()


# ═══════════════════════════════════════════════════════════════
# AI-СОВЕТЫ ПО ПИТАНИЮ
# ═══════════════════════════════════════════════════════════════

@router.message(Command("ai_advice"))
async def cmd_ai_advice(message: Message, user_id: int = None):
    """
    Получить AI-рекомендации по питанию на текущий момент.
    """
    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    status_message = await message.answer("🤖 <b>AI анализирует твоё питание...</b>")

    try:
        summary = get_today_summary(uid)
        plan = get_nutrition_plan(uid)

        current = {
            "calories": summary.get("total_calories", 0),
            "protein": summary.get("total_protein_g", 0),
            "carbs": summary.get("total_carbs_g", 0),
            "fat": summary.get("total_fat_g", 0),
        }

        targets = {
            "calories": plan.get("target_calories", 2000),
            "protein": plan.get("macros", {}).get("protein_g", 150),
            "carbs": plan.get("macros", {}).get("carbs_g", 250),
            "fat": plan.get("macros", {}).get("fat_g", 70),
        }

        advice = await get_food_suggestions(uid, current, targets)

        await message.bot.delete_message(uid, status_message.message_id)

        if advice:
            await message.answer(advice)
        else:
            await message.answer(
                "💡 <b>Всё отлично!</b>\n\n"
                "Ты набираешь норму по всем нутриентам. Продолжай в том же духе! 💪"
            )

    except Exception as e:
        logger.exception("AI advice error: %s", e)
        await message.bot.delete_message(uid, status_message.message_id)
        await message.answer("❌ Не удалось получить рекомендации. Попробуй позже.")

# ═══════════════════════════════════════════════════════════════
# УДАЛЕНИЕ ЗАПИСИ (НИЗКАЯ УВЕРЕННОСТЬ AI)
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ai_delete_entry_"))
async def handle_ai_delete_entry(callback: CallbackQuery):
    """Удалить запись еды, добавленную AI, если распознавание было неточным."""
    uid = callback.from_user.id

    try:
        entry_id = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("❌ Ошибка: запись не найдена")
        return

    conn = get_db()
    cur = conn.execute(
        "DELETE FROM food_log_new WHERE id = ? AND user_id = ?",
        (entry_id, uid),
    )
    conn.commit()

    if cur.rowcount:
        await callback.message.edit_text("✅ Запись удалена из дневника.")
        await callback.answer("✅ Запись удалена")
    else:
        await callback.answer("❌ Запись не найдена")
