"""AI-чат для вопросов по фитнесу и питанию (с гибридным AI)."""

import logging
import time

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from core.ai.ai_router import (
    ai_router, rate_response,
    hash_question, find_in_cache, find_template_match,
    ROUTE_CACHE, ROUTE_TEMPLATE, ROUTE_FULL_AI,
    _get_user_profile,
)
from core.ai.chat_history import get_history as _get_history, append_history as _append_history
from core.database import get_user
from core.config import settings
from core.referrals import check_subscription_active, get_ai_limit, use_ai_feature

logger = logging.getLogger(__name__)

router = Router()


# ═══════════════════════════════════════════════════════════════
# СОСТОЯНИЕ ЧАТА
# ═══════════════════════════════════════════════════════════════

class AIChat(StatesGroup):
    waiting_for_question = State()


# ═══════════════════════════════════════════════════════════════
# AI-ЧАТ — ВКЛЮЧЕНИЕ РЕЖИМА
# ═══════════════════════════════════════════════════════════════

@router.message(Command("ai"))
async def cmd_ai_chat(message: Message, state: FSMContext, user_id: int = None):
    """Задать вопрос AI-коучу (включает режим чата)."""
    uid = user_id if user_id else message.from_user.id

    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    is_premium = check_subscription_active(uid)
    premium_text = "⭐ Premium" if is_premium else "Free"

    # ═══════════════════════════════════════════════════════════════
    # ВКЛЮЧАЕМ РЕЖИМ ЧАТА
    # ═══════════════════════════════════════════════════════════════

    await state.set_state(AIChat.waiting_for_question)

    await message.answer(
        f"🤖 <b>AI-коуч BodyPilot</b> ({premium_text})\n\n"
        "<b>✅ Режим чата включён!</b>\n\n"
        "Задай вопрос по фитнесу или питанию!\n\n"
        "<i>Примеры:\n"
        "• Сколько белка мне нужно?\n"
        "• Что съесть после тренировки?\n"
        "• Запиши 200г гречки с курицей на обед\n"
        "• Сколько я сегодня съел?\n"
        "• Поставь мне цель похудение</i>\n\n"
        "💡 <b>Совет:</b> AI теперь умеет записывать еду и вес, менять цель и показывать статистику!\n\n"
        "🍽️ <b>Новое:</b> Используй /ai_plan для AI-плана питания на день!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>🔙 Чтобы выйти из чата: /menu или /stop</i>"
    )


# ═══════════════════════════════════════════════════════════════
# ВЫХОД ИЗ ЧАТА
# ═══════════════════════════════════════════════════════════════

@router.message(Command("stop"))
@router.message(Command("exit"))
async def cmd_exit_chat(message: Message, state: FSMContext):
    """Выйти из режима AI-чата."""
    await state.clear()
    await message.answer("🔙 <b>Вы вышли из AI-чата</b>\n\nИспользуй /ai чтобы вернуться.")


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТКА ВОПРОСОВ (ТОЛЬКО В РЕЖИМЕ ЧАТА)
# ═══════════════════════════════════════════════════════════════

@router.message(AIChat.waiting_for_question, F.text & ~F.text.startswith("/"))
async def handle_ai_question(message: Message, state: FSMContext, user_id: int = None):
    """Обработка вопроса пользователя к AI."""
    from datetime import datetime
    import asyncio

    uid = user_id if user_id else message.from_user.id

    # ═══════════════════════════════════════════════════════════════
    # ПРОВЕРКИ
    # ═══════════════════════════════════════════════════════════════

    # Пропускаем команды
    if message.text.startswith("/"):
        return

    # Пропускаем короткие сообщения
    if len(message.text.strip()) < 3:
        return

    user = get_user(uid)
    if not user:
        return

    question = message.text.strip()

    # ═══════════════════════════════════════════════════════════════
    # ПРОВЕРКА ДЛИНЫ ВОПРОСА
    # ═══════════════════════════════════════════════════════════════

    if len(question) > 500:
        await message.answer(
            "⚠️ <b>Слишком длинный вопрос</b>\n\n"
            f"Максимум 500 символов (у вас {len(question)}).\n\n"
            "Задайте вопрос короче или разбейте на несколько."
        )
        return

    # ═══════════════════════════════════════════════════════════════
    # ПРОВЕРКА ЛИМИТА ДО ВЫЗОВА AI (чтобы не оплачивать запрос впустую)
    # ═══════════════════════════════════════════════════════════════

    is_premium_user = check_subscription_active(uid)
    limit_info = get_ai_limit(uid, "ai_chat")

    if not limit_info["can_use"] and not is_premium_user:
        reset_at = limit_info.get("reset_at")
        reset_text = ""
        if reset_at:
            try:
                reset_dt = datetime.fromisoformat(reset_at)
                reset_text = f"\n\nСброс: {reset_dt.strftime('%d.%m в %H:%M')}"
            except:
                pass

        await message.answer(
            f"⚠️ <b>Лимит AI исчерпан</b>\n\n"
            f"Вы использовали {limit_info['used']} из {limit_info['limit']} попыток.\n"
            f"Осталось: {limit_info['remaining']}{reset_text}\n\n"
            f"⭐ Premium снимает все ограничения!\n"
            f"В бета-тесте Premium выдаётся бесплатно — напишите администратору: @{settings.TELEGRAM_ADMIN_USERNAME}"
        )
        return

    # ═══════════════════════════════════════════════════════════════
    # ОТПРАВЛЯЕМ СТАТУС "AI ДУМАЕТ" (с retry)
    # ═══════════════════════════════════════════════════════════════

    status_message = None
    for retry in range(3):
        try:
            status_message = await message.answer("🤖 <b>AI думает...</b>")
            break
        except Exception as e:
            if retry == 2:
                await message.answer("⚠️ Проблема с соединением. Попробуй ещё раз через 10 сек.")
                return
            await asyncio.sleep(1)

    try:
        # ═══════════════════════════════════════════════════════════════
        # МАРШРУТИЗАЦИЯ: КЭШ / ШАБЛОН (бесплатно) → FULL AI С ИНСТРУМЕНТАМИ
        # ═══════════════════════════════════════════════════════════════

        context = {"goal": user.get("goal", "maintain")}
        start_time = time.time()

        # 1. Кэш (безлимитно)
        question_hash = hash_question(question, context)
        cached = find_in_cache(question_hash)

        if cached:
            response_time_ms = int((time.time() - start_time) * 1000)
            log_id = ai_router._log_response(
                user_id=uid, question=question, answer=cached["answer"],
                route=ROUTE_CACHE, response_time_ms=response_time_ms, cost=0,
            )
            result = {
                "answer": cached["answer"],
                "route": ROUTE_CACHE,
                "response_time_ms": response_time_ms,
                "from_cache": True,
                "log_id": log_id,
            }
        else:
            # 2. Шаблоны (безлимитно)
            user_profile = _get_user_profile(uid)
            template = find_template_match(question, user_profile)

            if template:
                response_time_ms = int((time.time() - start_time) * 1000)
                log_id = ai_router._log_response(
                    user_id=uid, question=question, answer=template["answer"],
                    route=ROUTE_TEMPLATE, response_time_ms=response_time_ms, cost=0,
                )
                result = {
                    "answer": template["answer"],
                    "route": ROUTE_TEMPLATE,
                    "response_time_ms": response_time_ms,
                    "from_cache": False,
                    "log_id": log_id,
                }
            else:
                # 3. Полный AI с function calling — AI может реально
                #    записывать еду/вес, менять профиль, читать статистику
                from core.ai.gemini_client import get_gemini_client

                client = get_gemini_client()
                if not client:
                    result = {
                        "answer": "❌ AI-сервис временно недоступен",
                        "route": ROUTE_FULL_AI,
                        "response_time_ms": 0,
                        "from_cache": False,
                        "log_id": 0,
                    }
                else:
                    tool_result = await client.chat_with_tools(
                        user_id=uid,
                        question=question,
                        history=_get_history(uid),
                    )
                    response_time_ms = int((time.time() - start_time) * 1000)

                    if tool_result is None:
                        answer = "❌ Не удалось получить ответ от AI. Попробуй позже."
                    elif tool_result.get("error") == "rate_limit":
                        answer = "⚠️ " + tool_result.get("message", "Превышен лимит запросов. Попробуй позже.")
                    else:
                        answer = tool_result.get("text", "Не удалось получить ответ")
                        # Помечаем выполненные действия (summary есть у write-tools)
                        for used in tool_result.get("tools_used") or []:
                            if used.get("summary"):
                                answer = f"✅ {used['summary']}\n\n{answer}"

                    # Персональные ответы с данными пользователя НЕ сохраняем
                    # в базу знаний — только логируем
                    log_id = ai_router._log_response(
                        user_id=uid, question=question, answer=answer,
                        route=ROUTE_FULL_AI, response_time_ms=response_time_ms, cost=0.01,
                    )
                    _append_history(uid, question, answer)

                    result = {
                        "answer": answer,
                        "route": ROUTE_FULL_AI,
                        "response_time_ms": response_time_ms,
                        "from_cache": False,
                        "log_id": log_id,
                    }

        # ═══════════════════════════════════════════════════════════════
        # ПРОВЕРЯЕМ МАРШРУТ — НУЖЕН ЛИ ЛИМИТ?
        # ═══════════════════════════════════════════════════════════════

        route = result["route"]
        from_cache = result["from_cache"]
        log_id = result.get("log_id", 0)

        # Лимит уже проверен до вызова; списываем только за реальный вызов AI
        # (кэш и шаблоны — бесплатно)
        if route in ("hybrid", "full_ai"):
            use_ai_feature(uid, "ai_chat")

        # ═══════════════════════════════════════════════════════════════
        # ФОРМИРУЕМ ОТВЕТ
        # ═══════════════════════════════════════════════════════════════

        answer = result["answer"]
        response_time = result["response_time_ms"]

        # Индикатор источника ответа
        source_badge = ""
        if from_cache:
            source_badge = "⚡ <i>Мгновенный ответ (кэш)</i>\n\n"
        elif route == "template":
            source_badge = "📚 <i>Ответ из базы знаний</i>\n\n"
        elif route == "hybrid":
            source_badge = "🔀 <i>Гибридный ответ</i>\n\n"
        elif route == "full_ai":
            source_badge = "🤖 <i>Ответ от Gemini AI</i>\n\n"

        text = f"{source_badge}🤖 <b>AI-коуч:</b>\n\n{answer}\n\n"

        # ═══════════════════════════════════════════════════════════════
        # КНОПКИ ОЦЕНКИ (СОХРАНЯЕМ В БД!)
        # ═══════════════════════════════════════════════════════════════

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐️", callback_data=f"rate_{log_id}_1"),
                InlineKeyboardButton(text="⭐️⭐️", callback_data=f"rate_{log_id}_2"),
                InlineKeyboardButton(text="⭐️⭐️⭐️", callback_data=f"rate_{log_id}_3"),
            ],
            [
                InlineKeyboardButton(text="⭐️⭐️⭐️⭐️", callback_data=f"rate_{log_id}_4"),
                InlineKeyboardButton(text="⭐️⭐️⭐️⭐️⭐️", callback_data=f"rate_{log_id}_5"),
            ],
        ])

        # Статистика ответа
        stats_text = ""
        if response_time < 100:
            stats_text = f"⏱️ {response_time}мс"
        elif response_time < 1000:
            stats_text = f"⏱️ {response_time}мс"
        else:
            stats_text = f"⏱️ {response_time / 1000:.1f}сек"

        if from_cache:
            stats_text += " • из кэша"
        elif route == "template":
            stats_text += " • шаблон"
        elif route == "full_ai":
            stats_text += " • Gemini"

        text += f"<i>{stats_text}</i>"

        # ═══════════════════════════════════════════════════════════════
        # ОТПРАВЛЯЕМ ОТВЕТ (с retry)
        # ═══════════════════════════════════════════════════════════════

        if status_message:
            await message.bot.delete_message(uid, status_message.message_id)

        for retry in range(3):
            try:
                await message.answer(text, reply_markup=keyboard)
                break
            except Exception as e:
                if retry == 2:
                    await message.answer(f"⚠️ Ответ готов, но проблема с отправкой:\n\n{text[:500]}")
                    return
                await asyncio.sleep(1)

    except Exception as e:
        logger.exception("AI chat error: %s", e)
        if status_message:
            try:
                await message.bot.delete_message(uid, status_message.message_id)
            except:
                pass
        await message.answer("❌ Ошибка при обработке вопроса. Попробуй позже.")


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТКА ОЦЕНОК (СОХРАНЯЕМ В БД!)
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("rate_"))
async def handle_rating(callback: F, user_id: int = None):
    """Обработка оценки ответа — сохраняет в БД!"""
    uid = user_id if user_id else callback.from_user.id

    # Парсим callback: rate_{log_id}_{rating}
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка оценки")
        return

    try:
        log_id = int(parts[1])
        rating = int(parts[2])
    except ValueError:
        await callback.answer("❌ Ошибка оценки")
        return

    if not 1 <= rating <= 5:
        await callback.answer("❌ Ошибка оценки")
        return

    # ═══════════════════════════════════════════════════════════════
    # СОХРАНЯЕМ ОЦЕНКУ В БД (для всех ответов!)
    # ═══════════════════════════════════════════════════════════════

    if log_id > 0:
        # Для Gemini ответов — сохраняем в БД
        success = rate_response(log_id, rating)

        if success:
            emoji = "⭐️" * rating
            await callback.answer(f"✅ {emoji} Спасибо! Оценка сохранена в базе AI.")
        else:
            await callback.answer("❌ Не удалось сохранить оценку")
    else:
        # Для кэш/шаблон ответов — просто благодарим
        # (можно добавить сбор статистики для улучшения шаблонов)
        emoji = "⭐️" * rating
        await callback.answer(f"✅ {emoji} Спасибо! Это поможет улучшить AI.")