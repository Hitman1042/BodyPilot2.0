"""Свободный текст: распознавание еды и AI-коуч без команд.

Роутер подключается ПОСЛЕДНИМ в bot/main.py — команды, FSM-состояния
и кнопки главного меню обрабатываются раньше. Сюда долетает только то,
что никто не забрал: текст без "/" и без активного FSM-состояния,
а также голосовые/аудио сообщения (их никто другой не ловит).

Логика текста: сначала пробуем распознать еду (recognize_food_from_text),
при успехе показываем карточку с КБЖУ и кнопками подтверждения. Если это не
еда — передаём текст AI-коучу (кэш/шаблоны → chat_with_tools).

Логика голоса: transcribe_voice → транскрипт целиком уходит AI-коучу
(chat_with_tools), который сам записывает еду (log_food_batch / log_food) или
тренировку (log_workout_done) и отвечает подтверждением.
"""

import html
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from core.ai.chat_history import get_history, append_history
from core.ai.text_markers import has_food_intent
from core.ai.tools import execute_tool
from core.database import get_user
from core.nutrition_tracker import get_today_summary
from core.nutrition_calc import get_nutrition_plan
from core.gamification import notify_progress

logger = logging.getLogger(__name__)

router = Router()

# Порог уверенности распознавания еды из текста (поле confidence от Gemini, 0.0-1.0)
FOOD_CONFIDENCE_THRESHOLD = 0.5

NEXT_STEP_HINT = "Напиши, что ещё съел, или пришли фото 📸"

MEAL_NAMES_RU = {
    "breakfast": "завтрак",
    "lunch": "обед",
    "dinner": "ужин",
    "snack": "перекус",
}


class SmartFoodEdit(StatesGroup):
    waiting_for_weight = State()


# ═══════════════════════════════════════════════════════════════
# ХЕЛПЕРЫ
# ═══════════════════════════════════════════════════════════════

def _meal_type_by_time() -> str:
    """Тип приёма пищи по локальному времени."""
    hour = datetime.now().hour
    if 5 <= hour < 11:
        return "breakfast"
    if 11 <= hour < 16:
        return "lunch"
    if 16 <= hour < 22:
        return "dinner"
    return "snack"


def _extract_food(result: dict | None) -> dict | None:
    """Проверить результат recognize_food_from_text и привести к виду карточки.

    Успех = есть название, калории > 0 и confidence >= FOOD_CONFIDENCE_THRESHOLD.
    """
    if not result or "error" in result:
        return None

    name = str(result.get("food_name") or "").strip()
    if not name:
        return None

    try:
        weight_g = float(result.get("weight_g") or 100)
        calories = float(result.get("calories") or 0)
        protein_g = float(result.get("protein_g") or 0)
        fat_g = float(result.get("fat_g") or 0)
        carbs_g = float(result.get("carbs_g") or 0)
        confidence = float(result.get("confidence") or 0.5)
    except (TypeError, ValueError):
        return None

    if calories <= 0 or confidence < FOOD_CONFIDENCE_THRESHOLD:
        return None

    return {
        "food_name": name,
        "weight_g": weight_g,
        "calories": calories,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g,
    }


def _food_card_text(food: dict) -> str:
    """Карточка распознанной еды."""
    meal_type = _meal_type_by_time()
    return (
        f"🍽 <b>Распознал:</b> {html.escape(str(food['food_name']))}\n\n"
        f"⚖️ Вес: {food['weight_g']:g} г\n"
        f"📊 {food['calories']:g} ккал | Б {food['protein_g']:g}г | "
        f"Ж {food['fat_g']:g}г | У {food['carbs_g']:g}г\n"
        f"🕒 Приём пищи: {MEAL_NAMES_RU[meal_type]}\n\n"
        "Записать в дневник?"
    )


def _food_card_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Записать", callback_data="smart_food_confirm")],
        [InlineKeyboardButton(text="✏️ Изменить вес", callback_data="smart_food_edit")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="smart_food_cancel")],
    ])


async def _ask_coach(uid: int, user: dict, text: str, direct: bool = False) -> str | None:
    """Ответ AI-коуча: сначала кэш/шаблоны (бесплатно), потом chat_with_tools.

    direct=True — пропустить кэш/шаблоны и сразу идти в chat_with_tools
    (для явных сообщений о еде: коуч запишет её через log_food).
    """
    from core.ai.ai_router import (
        hash_question, find_in_cache, find_template_match, _get_user_profile,
    )

    if not direct:
        # 1. Кэш (безлимитно)
        context = {"goal": user.get("goal", "maintain")}
        cached = find_in_cache(hash_question(text, context))
        if cached:
            return f"⚡ <i>Мгновенный ответ (кэш)</i>\n\n🤖 <b>AI-коуч:</b>\n\n{cached['answer']}"

        # 2. Шаблоны (безлимитно)
        template = find_template_match(text, _get_user_profile(uid))
        if template:
            return f"📚 <i>Ответ из базы знаний</i>\n\n🤖 <b>AI-коуч:</b>\n\n{template['answer']}"

    # 3. Полный AI с function calling
    from core.ai.gemini_client import get_gemini_client

    result = await get_gemini_client().chat_with_tools(
        user_id=uid,
        question=text,
        history=get_history(uid),
    )

    if result is None:
        return None
    if result.get("error") == "rate_limit":
        return "⏳ AI временно перегружен, попробуй через минуту."

    answer = result.get("text", "")
    for used in result.get("tools_used") or []:
        if used.get("summary"):
            answer = f"✅ {used['summary']}\n\n{answer}"

    append_history(uid, text, answer)
    return f"🤖 <b>AI-коуч:</b>\n\n{answer}"


# ═══════════════════════════════════════════════════════════════
# МИНИ-FSM: ИЗМЕНЕНИЕ ВЕСА (регистрируем ДО общего текстового хендлера)
# ═══════════════════════════════════════════════════════════════

@router.message(SmartFoodEdit.waiting_for_weight, F.text)
async def smart_food_weight_input(message: Message, state: FSMContext):
    """Новый вес порции → пересчёт КБЖУ пропорционально → снова карточка."""
    data = await state.get_data()
    food = data.get("smart_food")

    if not food:
        await state.clear()
        await message.answer("⚠️ Данные устарели — напиши ещё раз, что съел.")
        return

    try:
        new_weight = float(message.text.strip().replace(",", ".").replace("г", "").replace(" ", ""))
        if not (1 <= new_weight <= 5000):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число граммов от 1 до 5000 (например: 250)")
        return

    old_weight = float(food.get("weight_g") or 0)
    if old_weight <= 0:
        await state.clear()
        await message.answer("⚠️ Данные устарели — напиши ещё раз, что съел.")
        return

    ratio = new_weight / old_weight
    food = {
        **food,
        "weight_g": new_weight,
        "calories": round(food["calories"] * ratio, 1),
        "protein_g": round(food["protein_g"] * ratio, 1),
        "fat_g": round(food["fat_g"] * ratio, 1),
        "carbs_g": round(food["carbs_g"] * ratio, 1),
    }

    await state.set_state(None)
    await state.update_data(smart_food=food)
    await message.answer(_food_card_text(food), reply_markup=_food_card_keyboard())


# ═══════════════════════════════════════════════════════════════
# СВОБОДНЫЙ ТЕКСТ
# ═══════════════════════════════════════════════════════════════

@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def handle_free_text(message: Message, state: FSMContext, user_id: int = None):
    """Свободный текст без команд и состояний: еда → карточка, иначе → AI-коуч."""
    uid = user_id if user_id else message.from_user.id

    # Страховка: не перехватываем ввод в активных FSM-сценариях
    if await state.get_state() is not None:
        return

    text = message.text.strip()
    if len(text) < 3:
        return

    # Страховка: не перехватываем кнопки главного меню
    # (ленивый импорт — menu.py тянет много хендлеров, избегаем циклических импортов)
    from bot.handlers.menu import MAIN_MENU_ITEMS
    if text in MAIN_MENU_ITEMS:
        return

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    from core.ai.gemini_client import get_gemini_client
    client = get_gemini_client()
    if not client:
        return  # AI не настроен — игнорируем, как раньше

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    status_message = await message.answer("🤖 <b>Думаю...</b>")

    try:
        # 0. Явные маркеры еды («съел яблоко», «выпил латте») — сразу коучу:
        #    chat_with_tools с усиленной инструкцией запишет еду через log_food
        #    одним вызовом, без карточки-подтверждения
        if has_food_intent(text):
            answer = await _ask_coach(uid, user, text, direct=True)
            await message.bot.delete_message(message.chat.id, status_message.message_id)
            if answer:
                await message.answer(answer)
            else:
                await message.answer("🤔 Не понял. Попробуй переформулировать или открой меню.")
            return

        # 0.5. Несколько строк = список блюд → сразу коучу (log_food_batch):
        #    одноэлементная карточка склеила бы всё в одну запись
        if len([line for line in text.splitlines() if line.strip()]) > 1:
            answer = await _ask_coach(uid, user, text, direct=True)
            await message.bot.delete_message(message.chat.id, status_message.message_id)
            if answer:
                await message.answer(answer)
            else:
                await message.answer("🤔 Не понял. Попробуй переформулировать или открой меню.")
            return

        # 1. Пробуем распознать еду
        food_result = await client.recognize_food_from_text(text)

        # Несколько блюд одним сообщением: распознаватель вернул список —
        # отдаём коучу, он запишет всё через log_food_batch
        if isinstance(food_result, dict) and isinstance(food_result.get("items"), list):
            food_result = food_result["items"]
        if isinstance(food_result, list):
            if len(food_result) > 1:
                answer = await _ask_coach(uid, user, text, direct=True)
                await message.bot.delete_message(message.chat.id, status_message.message_id)
                if answer:
                    await message.answer(answer)
                else:
                    await message.answer("🤔 Не понял. Попробуй переформулировать или открой меню.")
                return
            food_result = food_result[0] if food_result else None

        if food_result and food_result.get("error") == "rate_limit":
            await message.bot.delete_message(message.chat.id, status_message.message_id)
            await message.answer("⏳ AI временно перегружен, попробуй через минуту.")
            return

        food = _extract_food(food_result)
        if food:
            await state.update_data(smart_food=food)
            await message.bot.delete_message(message.chat.id, status_message.message_id)
            await message.answer(_food_card_text(food), reply_markup=_food_card_keyboard())
            return

        # 2. Не еда — отвечает AI-коуч
        answer = await _ask_coach(uid, user, text)

        await message.bot.delete_message(message.chat.id, status_message.message_id)
        if answer:
            await message.answer(answer)
        else:
            await message.answer("🤔 Не понял. Попробуй переформулировать или открой меню.")

    except Exception as e:
        logger.exception("smart_input error: %s", e)
        try:
            await message.bot.delete_message(message.chat.id, status_message.message_id)
        except Exception:
            pass
        await message.answer("🤔 Не понял. Попробуй переформулировать или открой меню.")


# ═══════════════════════════════════════════════════════════════
# ГОЛОСОВЫЕ / АУДИО
# ═══════════════════════════════════════════════════════════════

NOT_HEARD_TEXT = "🎤 Не расслышал — напиши текстом, что съел, или повтори голосовое."


@router.message(StateFilter(None), F.voice | F.audio)
async def handle_voice(message: Message, state: FSMContext, user_id: int = None):
    """Голосовое = прямой вход в AI-коуча: транскрипция → chat_with_tools.

    Коуч сам разбирает транскрипт (там может быть несколько блюд за день или
    отчёт о тренировке) и записывает через log_food_batch / log_food /
    log_workout_done. Карточка одного блюда для голоса не используется.
    """
    uid = user_id if user_id else message.from_user.id

    # Страховка: не перехватываем ввод в активных FSM-сценариях
    if await state.get_state() is not None:
        return

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    from core.ai.gemini_client import get_gemini_client
    client = get_gemini_client()
    if not client:
        await message.answer(NOT_HEARD_TEXT)
        return

    attachment = message.voice or message.audio
    # Голосовые Telegram — ogg/opus; у файлов-аудио берём заявленный mime
    mime_type = "audio/ogg"
    if message.audio and message.audio.mime_type:
        mime_type = message.audio.mime_type

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    status_message = await message.answer("🎤 <b>Слушаю...</b>")

    try:
        file = await message.bot.get_file(attachment.file_id)
        buf = await message.bot.download_file(file.file_path)
        audio_bytes = buf.read()

        result = await client.transcribe_voice(audio_bytes, mime_type=mime_type)

        if result and result.get("error") == "rate_limit":
            await message.bot.delete_message(message.chat.id, status_message.message_id)
            await message.answer("⏳ AI временно перегружен, попробуй через минуту.")
            return

        transcript = str((result or {}).get("transcript") or "").strip()

        await message.bot.delete_message(message.chat.id, status_message.message_id)

        # Gemini не принял голос или ничего не расслышал
        if len(transcript) < 3:
            await message.answer(NOT_HEARD_TEXT)
            return

        # Транскрипт есть — передаём коучу как есть: он запишет еду/тренировку
        # через инструменты и ответит подтверждением
        coach_text = f"[Голосовое сообщение, расшифровка]: {transcript}"
        answer = await _ask_coach(uid, user, coach_text, direct=True)
        prefix = f"🎤 Распознал: «{html.escape(transcript[:300])}»\n\n"
        if answer:
            await message.answer(prefix + answer)
        else:
            await message.answer("🤔 Не понял. Попробуй переформулировать или открой меню.")

    except Exception as e:
        logger.exception("voice_input error: %s", e)
        try:
            await message.bot.delete_message(message.chat.id, status_message.message_id)
        except Exception:
            pass
        await message.answer(NOT_HEARD_TEXT)


# ═══════════════════════════════════════════════════════════════
# КНОПКИ КАРТОЧКИ ЕДЫ
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "smart_food_confirm")
async def smart_food_confirm(callback: CallbackQuery, state: FSMContext):
    """Записать распознанную еду в дневник через execute_tool."""
    uid = callback.from_user.id
    data = await state.get_data()
    food = data.get("smart_food")

    if not food:
        await callback.answer("⚠️ Данные устарели — напиши ещё раз, что съел.", show_alert=True)
        return

    meal_type = _meal_type_by_time()
    result = execute_tool(uid, "log_food", {        "product_name": food["food_name"],
        "weight_g": food["weight_g"],
        "calories": food["calories"],
        "protein_g": food["protein_g"],
        "fat_g": food["fat_g"],
        "carbs_g": food["carbs_g"],
        "meal_type": meal_type,
    })

    if "error" in result:
        await callback.message.edit_text(f"❌ Не удалось записать: {result['error']}")
        await callback.answer()
        return

    summary = get_today_summary(uid)
    plan = get_nutrition_plan(uid) or {}
    target = plan.get("target_calories", 2000)

    await state.update_data(smart_food=None)
    await callback.message.edit_text(
        f"✅ <b>Записал:</b> {html.escape(str(food['food_name']))}, {food['weight_g']:g} г — "
        f"{food['calories']:g} ккал ({MEAL_NAMES_RU[meal_type]})\n\n"
        f"📊 Сегодня: <b>{summary.get('total_calories', 0)}</b> из {target} ккал\n\n"
        f"{NEXT_STEP_HINT}"
    )
    await callback.answer("✅ Записано")
    await notify_progress(callback.message, uid)


@router.callback_query(F.data == "smart_food_edit")
async def smart_food_edit(callback: CallbackQuery, state: FSMContext):
    """Перейти к вводу нового веса порции."""
    data = await state.get_data()
    if not data.get("smart_food"):
        await callback.answer("⚠️ Данные устарели — напиши ещё раз, что съел.", show_alert=True)
        return

    await state.set_state(SmartFoodEdit.waiting_for_weight)
    await callback.message.edit_text("✏️ Введи новый вес порции в граммах (например: 250):")
    await callback.answer()


@router.callback_query(F.data == "smart_food_cancel")
async def smart_food_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена записи — убираем клавиатуру."""
    await state.update_data(smart_food=None)
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()
