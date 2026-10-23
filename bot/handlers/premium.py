"""Обработчики Premium и реферальной программы (с поддержкой user_id)."""

import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from datetime import datetime, timedelta, timezone

from core.database import (
    get_user, get_subscription, create_subscription, update_subscription,
    get_bonus_balance, get_referral_list,
)
from core.referrals import (
    get_subscription_info, check_subscription_active,
    generate_referral_code, process_referral,
)

router = Router()


def _get_user_id(message: Message, user_id: int = None) -> int:
    return user_id if user_id else message.from_user.id


# ── /premium ────────────────────────────────────────────────────────────

@router.message(Command("premium"))
async def cmd_premium(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    info = get_subscription_info(uid)
    if info["is_active"]:
        await message.answer(
            f"⭐ <b>У тебя активна Premium подписка!</b>\n\n"
            f"Осталось дней: <b>{info['days_left']}</b>\n"
            f"Дата окончания: {info['expires_at'][:10] if info['expires_at'] else 'неизвестно'}\n\n"
            f"Пригласи друга по реферальной ссылке и получи дополнительные дни!\n"
            f"Используй /ref чтобы узнать ссылку."
        )
    else:
        trial_text = ""
        if not info["trial_used"]:
            trial_text = "🎁 <b>У тебя есть 3 дня Premium бесплатно!</b> Они активируются при первой регистрации.\n\n"
        await message.answer(
            f"💎 <b>Premium подписка</b>\n\n"
            f"{trial_text}"
            f"<b>Что даёт Premium:</b>\n"
            f"• Расширенная статистика за 30 дней\n"
            f"• Персональные планы питания\n"
            f"• Персональные планы тренировок\n"
            f"• Экспорт данных\n"
            f"• Приоритетная поддержка\n\n"
            f"💰 Стоимость: <b>299 ₽/мес</b>\n\n"
            f"Для оформления используй /subscribe"
        )


# ── /ref ────────────────────────────────────────────────────────────────

@router.message(Command("ref"))
async def cmd_ref(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    code = user.get("referral_code") or generate_referral_code(uid)
    link = f"https://t.me/{(message.bot._me.username)}?start=ref_{code}" if message.bot._me.username else ""

    info = get_subscription_info(uid)
    bonus_text = ""
    if info["is_active"]:
        bonus_text = "\n\n🎁 <b>Бонус:</b> каждый приведённый друг даёт +5 дней Premium, а если он оплатит подписку — ещё +10 дней!"

    await message.answer(
        f"🔗 <b>Твоя реферальная ссылка:</b>\n"
        f"{link}\n\n"
        f"Отправь её другу! Когда он зарегистрируется, ты получишь <b>5 дней Premium</b> бесплатно."
        f"{bonus_text}"
    )


# ── /bonus ──────────────────────────────────────────────────────────────

@router.message(Command("bonus"))
async def cmd_bonus(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    balance = get_bonus_balance(uid)
    if balance > 0:
        await message.answer(
            f"🎁 <b>Твой бонусный баланс:</b> {balance} дн.\n\n"
            f"Эти дни будут автоматически активированы, как только у тебя появится активная Premium-подписка.\n"
            f"Если в течение 30 дней подписка не будет оформлена, бонусы сгорят."
        )
    else:
        await message.answer(
            "🎁 <b>У тебя пока нет бонусных дней.</b>\n"
            "Пригласи друга по реферальной ссылке и получи +5 дней Premium!"
        )


# ── /referrals ──────────────────────────────────────────────────────────

@router.message(Command("referrals"))
async def cmd_referrals(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    refs = get_referral_list(uid)
    if not refs:
        await message.answer("У тебя пока нет приглашённых пользователей. Отправь свою реферальную ссылку друзьям!")
        return

    text = "👥 <b>Приглашённые тобой:</b>\n\n"
    for r in refs:
        status = "✅ оплатил" if r["invited_paid"] else "⏳ ожидает"
        text += f"• {html.escape(str(r['username'] or 'id: ' + str(r['invited_id'])))} — {status} ({r['created_at'][:10]})\n"
    await message.answer(text)


# ── /subscribe ──────────────────────────────────────────────────────────

@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    from core.config import settings

    await message.answer(
        "💳 <b>Оформление подписки</b>\n\n"
        "На данный момент оплата не настроена.\n"
        f"Для получения Premium в тестовом режиме напиши администратору: @{settings.TELEGRAM_ADMIN_USERNAME}"
    )


# ── /admin grant_premium ────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    from core.config import settings

    if (message.from_user.username or "").lower() != settings.TELEGRAM_ADMIN_USERNAME.lower():
        await message.answer("⛔ Доступ запрещён.")
        return

    args = message.text.strip().split()
    if len(args) < 2:
        await message.answer("Использование: /admin grant_premium &lt;user_id&gt; &lt;дни&gt;")
        return

    if args[1] == "grant_premium":
        if len(args) < 4:
            await message.answer("Укажи user_id и количество дней: /admin grant_premium 123456 30")
            return
        try:
            target_id = int(args[2])
            days = int(args[3])
        except ValueError:
            await message.answer("user_id и дни должны быть числами.")
            return

        sub = get_subscription(target_id)
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)

        if sub:
            update_subscription(target_id, plan="premium", expires_at=expires_at.isoformat())
        else:
            create_subscription(target_id, plan="premium", expires_at=expires_at.isoformat())

        await message.answer(f"✅ Пользователю {target_id} выдано {days} дней Premium.")
    else:
        await message.answer("Неизвестная команда. Доступно: grant_premium")