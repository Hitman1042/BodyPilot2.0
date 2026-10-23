"""Обработчики команд /start и /help."""

import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.main_menu import get_main_menu
from core.config import settings
from core.database import get_user

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Приветственное сообщение при первом запуске."""
    user = get_user(message.from_user.id)

    if not user:
        # Новый пользователь
        await message.answer(
            "👋 Добро пожаловать в <b>BodyPilot</b>!\n\n"
            "Я помогу тебе следить за питанием, тренировками и весом.\n\n"
            "Используй кнопки ниже для быстрой навигации.",
            reply_markup=get_main_menu()
        )
    else:
        # Уже зарегистрирован
        await message.answer(
            f"👋 Привет, <b>{html.escape(str(user['username']))}</b>!\n\n"
            "✍️ Напиши, что съел — запишу в дневник\n"
            "📸 Пришли фото еды — посчитаю КБЖУ\n"
            "🤖 Спроси что угодно — я AI-коуч\n\n"
            "Или выбери раздел меню:",
            reply_markup=get_main_menu()
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Справка по командам."""
    await message.answer(
        "🤖 <b>BodyPilot — Справка</b>\n\n"
        "Я отслеживаю твоё питание, тренировки и вес. "
        "Просто пиши мне, что ты ел или делал.\n\n"
        "<b>Питание:</b>\n"
        "/add_food — добавить еду в дневник\n"
        "/food_today — сводка питания за сегодня\n"
        "/log_meal — записать приём пищи вручную (КБЖУ)\n"
        "/search_food — найти и записать продукт\n"
        "/barcode — добавить продукт по штрих-коду\n\n"
        "<b>Тренировки:</b>\n"
        "/start_workout — начать тренировку\n"
        "/workout_plan — план тренировки\n"
        "/workout_history — история тренировок\n"
        "/search_exercise — найти упражнение\n"
        "/progress — прогресс по упражнению\n\n"
        "<b>AI-функции:</b>\n"
        "/ai — чат с AI-коучем\n"
        "/ai_plan — AI-план питания на день\n"
        "/ai_analyze — AI-анализ питания за день\n"
        "/ai_workout — AI-анализ тренировки\n"
        "/ai_advice — AI-совет по питанию\n"
        "📷 Отправь фото еды — AI распознает и запишет её\n\n"
        "<b>Профиль и статистика:</b>\n"
        "/profile — посмотреть или изменить профиль\n"
        "/log_weight — записать вес\n"
        "/stats — статистика за 7 дней\n\n"
        "<b>Прочее:</b>\n"
        "/set_digest_time — время утреннего дайджеста\n"
        "/set_city — изменить город для погоды\n"
        "/weather — погода сейчас\n"
        "/digest_now — получить дайджест\n"
        "/premium — информация о премиум-функциях\n\n"
        f"По вопросам: @{settings.TELEGRAM_ADMIN_USERNAME}",
        reply_markup=get_main_menu()
    )


@router.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")