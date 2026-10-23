"""Главное меню бота (Reply-клавиатура)."""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Тексты кнопок главного меню — используются также для защиты FSM-сценариев
# (кнопка меню во время регистрации/ввода не должна попадать в поле ввода)
MAIN_MENU_BUTTONS = [
    "🍽 Еда",
    "🏋️ Тренировки",
    "📊 Прогресс",
    "🤖 AI-коуч",
    "📱 Приложение",
    "⚙️ Профиль",
]


def get_main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Возвращает главное меню с основными разделами.

    Если is_admin=True, добавляется кнопка «🔧 Администрирование».
    """
    keyboard = [
        [
            KeyboardButton(text="🍽 Еда"),
            KeyboardButton(text="🏋️ Тренировки"),
        ],
        [
            KeyboardButton(text="📊 Прогресс"),
            KeyboardButton(text="🤖 AI-коуч"),
        ],
        [
            KeyboardButton(text="📱 Приложение"),
            KeyboardButton(text="⚙️ Профиль"),
        ],
    ]

    if is_admin:
        keyboard.append([KeyboardButton(text="🔧 Администрирование")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        persistent=True,
        one_time_keyboard=False,
    )
