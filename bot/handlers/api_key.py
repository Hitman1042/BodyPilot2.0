"""Команда /api_key: личный API-ключ для интеграций (часы, IFTTT, Shortcuts)."""

import html
import secrets

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from core.config import settings
from core.database import get_db, get_user

router = Router()

SELF_KEY_NAME = "user-self"


def get_or_create_self_api_key(user_id: int) -> tuple[str, bool]:
    """Вернуть (ключ, создан_ли_новый) личный ключ пользователя для интеграций."""
    conn = get_db()
    row = conn.execute(
        "SELECT api_key FROM api_keys WHERE user_id = ? AND name = ? AND is_active = 1",
        (user_id, SELF_KEY_NAME),
    ).fetchone()
    if row:
        return row["api_key"], False
    key = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
        (key, user_id, SELF_KEY_NAME),
    )
    conn.commit()
    return key, True


@router.message(Command("api_key"))
async def cmd_api_key(message: Message, user_id: int = None):
    uid = user_id if user_id else message.from_user.id
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    key, created = get_or_create_self_api_key(uid)
    intro = "Создал новый ключ" if created else "Твой активный ключ"
    await message.answer(
        "🔑 <b>Автоматическая синхронизация с часами</b> (для продвинутых)\n\n"
        "💡 Просто записать шаги и сон вручную — проще: /activity "
        "(или «📊 Прогресс» → «⌚ Активность»).\n\n"
        "Если хочешь, чтобы данные приходили сами, понадобится автоматизация "
        "на телефоне (Команды на iPhone / Tasker на Android), которая будет "
        "отправлять метрики в наш API с твоим личным ключом.\n\n"
        f"{intro}:\n<code>{html.escape(key)}</code>\n\n"
        "Пример запроса:\n"
        "<code>curl -X POST http://&lt;host&gt;:8000/api/v1/health/metrics \\\n"
        f'  -H "X-API-Key: {html.escape(key)}" \\\n'
        '  -H "Content-Type: application/json" \\\n'
        "  -d '{\"metrics\": [{\"ts\": \"2026-10-21T08:00:00\", "
        "\"metric_type\": \"steps\", \"value\": 8430, \"source\": \"watch\"}]}'</code>\n\n"
        "Ключ сам привязывает данные к твоему аккаунту — user_id указывать не нужно. "
        "Доступные metric_type: steps, heart_rate, resting_heart_rate, sleep_hours, "
        "weight, calories_burned, distance_km, active_minutes и др.\n\n"
        "⚠️ Не публикуй ключ: по нему можно отправлять данные от твоего имени.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Настроить автосинхронизацию", callback_data="watch_setup")],
        ]),
    )


@router.callback_query(F.data == "watch_setup")
async def cb_watch_setup(callback, state=None):
    await callback.answer()
    await callback.message.answer(
        "📱 <b>Автосинхронизация с часами</b>\n\nКакой у тебя телефон?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍎 iPhone", callback_data="watch_ios")],
            [InlineKeyboardButton(text="🤖 Android", callback_data="watch_android")],
        ]),
    )


@router.callback_query(F.data == "watch_ios")
async def cb_watch_ios(callback):
    await callback.answer()
    uid = callback.from_user.id
    if not get_user(uid):
        await callback.message.answer("Сначала зарегистрируйся с помощью /register")
        return
    key, _ = get_or_create_self_api_key(uid)
    link = settings.WATCH_SYNC_IOS_LINK
    if link:
        link_part = (
            f"1️⃣ Открой ссылку на своём iPhone и нажми «Добавить команду»:\n{link}\n\n"
        )
    else:
        link_part = "1️⃣ Ссылка на готовую команду скоро появится — напиши администратору.\n\n"
    await callback.message.answer(
        "🍎 <b>Настройка за 3 шага (iPhone)</b>\n\n"
        + link_part +
        "2️⃣ В приложении «Команды» нажми ⋯ на команде «BodyPilot Sync» "
        "и вставь свой ключ в первое поле:\n"
        f"<code>{html.escape(key)}</code>\n\n"
        "3️⃣ В «Командах» → вкладка «Автоматизация» → «+» → «Время дня» "
        "23:30 → выбери команду «BodyPilot Sync» → «Запускать немедленно».\n\n"
        "Готово! Каждый вечер iPhone сам будет отправлять шаги, сон и пульс "
        "из Apple Health (куда уже пишет Huawei Health) — утром увидишь их в дайджесте ⌚"
    )


@router.callback_query(F.data == "watch_android")
async def cb_watch_android(callback):
    await callback.answer()
    await callback.message.answer(
        "🤖 <b>Android</b>\n\n"
        "Честно: автосинхронизация Huawei Health на Android сейчас требует "
        "цепочки платных приложений и танцев с настройкой — мы не будем "
        "предлагать тебе кривой путь.\n\n"
        "Сейчас: /activity — ручной ввод шагов и сна за 10 секунд.\n"
        "Скоро: автоматическая синхронизация появится в нашем приложении "
        "(Health Connect) — без всяких настроек."
    )
