"""Inline-клавиатуры для подменю BodyPilot."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ── Еда ────────────────────────────────────────────────────────────────────

def get_food_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🍳 Что съесть?", callback_data="food_suggest"),
        ],
        [
            InlineKeyboardButton(text="📋 Отчёт за сегодня", callback_data="food_today"),
        ],
        [
            InlineKeyboardButton(text="🔍 Найти продукт", callback_data="food_search"),
        ],
        [
            InlineKeyboardButton(text="📷 По штрих-коду", callback_data="food_barcode"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Свой продукт", callback_data="food_add"),
        ],
        [
            InlineKeyboardButton(text="✍️ Ручной ввод КБЖУ", callback_data="food_log"),
        ],
        [
            InlineKeyboardButton(text="💧 Вода", callback_data="water_menu"),
        ],
        [
            InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"),
        ],
    ])


def get_water_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+250 мл", callback_data="water_add_250"),
            InlineKeyboardButton(text="+500 мл", callback_data="water_add_500"),
            InlineKeyboardButton(text="+1000 мл", callback_data="water_add_1000"),
        ],
        [
            InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"),
        ],
    ])

# ── Тренировки ────────────────────────────────────────────────────────────

def get_workout_menu() -> InlineKeyboardMarkup:
    """Меню раздела тренировок."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 План на сегодня", callback_data="workout_plan")],
        [InlineKeyboardButton(text="🔄 Перегенерировать план", callback_data="workout_refresh")],
        [InlineKeyboardButton(text="▶️ Начать тренировку", callback_data="workout_session")],
        [InlineKeyboardButton(text="📊 История тренировок", callback_data="workout_history")],
        [InlineKeyboardButton(text="➕ Добавить упражнение", callback_data="workout_add_exercise")],
        [InlineKeyboardButton(text="📈 Прогресс упражнения", callback_data="workout_progress")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
    ])
    return keyboard

# ── Прогресс (вес + статистика) ─────────────────────────────────────────────

def get_progress_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚖️ Записать вес", callback_data="weight_log"),
        ],
        [
            InlineKeyboardButton(text="📈 Динамика веса (неделя)", callback_data="weight_history"),
        ],
        [
            InlineKeyboardButton(text="📸 Фото прогресса", callback_data="progress_photo_menu"),
        ],
        [
            InlineKeyboardButton(text="⌚ Активность (шаги, сон)", callback_data="activity_log"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика 7 дней", callback_data="stats_week"),
        ],
        [
            InlineKeyboardButton(text="📅 Отчёт за неделю", callback_data="week_report"),
        ],
        [
            InlineKeyboardButton(text="🎯 Челленджи", callback_data="challenges"),
        ],
        [
            InlineKeyboardButton(text="📤 Поделиться", callback_data="share_card"),
        ],
        [
            InlineKeyboardButton(text="⭐ Расширенная 30 дней", callback_data="stats_month"),
        ],
        [
            InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"),
        ],
    ])

# ── Настройки (профиль + дайджест + premium + рефералы + помощь) ────────────

def get_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile_view"),
        ],
        [
            InlineKeyboardButton(text="✏️ Изменить данные", callback_data="profile_edit"),
        ],
        [
            InlineKeyboardButton(text="🌅 Дайджест сейчас", callback_data="digest_now"),
        ],
        [
            InlineKeyboardButton(text="⏰ Время дайджеста", callback_data="digest_set_time"),
        ],
        [
            InlineKeyboardButton(text="⭐ Premium", callback_data="premium_subscribe"),
        ],
        [
            InlineKeyboardButton(text="🔗 Рефералы", callback_data="ref_menu"),
        ],
        [
            InlineKeyboardButton(text="❓ Помощь", callback_data="help_guide"),
        ],
        [
            InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"),
        ],
    ])

# ── Premium ────────────────────────────────────────────────────────────────

def get_premium_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🥗 План питания", callback_data="premium_meal_plan"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить план питания", callback_data="premium_refresh_meal"),
        ],
        [
            InlineKeyboardButton(text="🏋️ План тренировок", callback_data="premium_workout_plan"),
        ],
        [
            InlineKeyboardButton(text="📊 Premium статистика", callback_data="premium_stats"),
        ],
        [
            InlineKeyboardButton(text="⭐ Подписаться", callback_data="premium_subscribe"),
        ],
        [
            InlineKeyboardButton(text="🎁 Пригласить друга", callback_data="premium_referral"),
        ],
        [
            InlineKeyboardButton(text="💎 Мои бонусы", callback_data="premium_bonuses"),
        ],
        [
            InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"),
        ],
    ])

# ── Рефералы ──────────────────────────────────────────────────────────────

def get_referral_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔗 Моя ссылка", callback_data="ref_link"),
        ],
        [
            InlineKeyboardButton(text="👥 Приглашённые", callback_data="ref_list"),
        ],
        [
            InlineKeyboardButton(text="🏆 Рейтинг друзей", callback_data="ref_rating"),
        ],
        [
            InlineKeyboardButton(text="🎁 Бонусный баланс", callback_data="ref_balance"),
        ],
        [
            InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"),
        ],
    ])

# ── AI-коуч ────────────────────────────────────────────────────────────────

def get_ai_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Чат с AI-коучем", callback_data="ai_chat_start"),
        ],
        [
            InlineKeyboardButton(text="🍽 AI-план питания на день", callback_data="ai_plan_start"),
        ],
        [
            InlineKeyboardButton(text="📊 AI-анализ питания", callback_data="ai_analyze_start"),
        ],
        [
            InlineKeyboardButton(text="💪 AI-анализ тренировки", callback_data="ai_workout_start"),
        ],
        [
            InlineKeyboardButton(text="📸 Распознать еду по фото", callback_data="ai_photo_hint"),
        ],
        [
            InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"),
        ],
    ])


# ── Помощь ────────────────────────────────────────────────────────────────

def get_help_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📖 Инструкция", callback_data="help_guide"),
        ],
        [
            InlineKeyboardButton(text="💬 Поддержка", callback_data="help_support"),
        ],
        [
            InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"),
        ],
    ])