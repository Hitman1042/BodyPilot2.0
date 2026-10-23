"""Middleware для проверки премиум-доступа и AI-лимитов."""

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Any, Awaitable, Callable, Dict
from functools import wraps

from core.referrals import check_subscription_active, get_ai_limit, use_ai_feature
from core.config import settings


class PremiumMiddleware(BaseMiddleware):
    """Добавляет is_premium в контекст handler'а."""

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id
            data["is_premium"] = check_subscription_active(user_id)
            data["user_id"] = user_id

        return await handler(event, data)


def check_premium_access(feature_name: str = "эта функция"):
    """Декоратор для проверки Premium доступа."""
    def decorator(func):
        @wraps(func)
        async def wrapper(event: Message | CallbackQuery, *args, **kwargs):
            user_id = event.from_user.id

            if not check_subscription_active(user_id):
                text = (
                    f"⭐ <b>{feature_name} доступен только Premium</b>\n\n"
                    "Преимущества Premium:\n"
                    "• Безлимитный AI-анализ\n"
                    "• Персональные планы питания\n"
                    "• AI-адаптация тренировок\n"
                    "• Приоритетная поддержка\n\n"
                    "Используй /premium для подключения."
                )
                if isinstance(event, CallbackQuery):
                    await event.message.answer(text)
                    await event.answer()
                else:
                    await event.answer(text)
                return

            return await func(event, *args, **kwargs)

        return wrapper
    return decorator


def check_ai_limit(feature: str):
    """Декоратор для проверки AI-лимитов."""
    def decorator(func):
        @wraps(func)
        async def wrapper(event: Message | CallbackQuery, *args, **kwargs):
            user_id = event.from_user.id

            limit_info = get_ai_limit(user_id, feature)

            if not limit_info["can_use"] and not limit_info["is_premium"]:
                reset_at = limit_info.get("reset_at")
                reset_text = ""
                if reset_at:
                    try:
                        from datetime import datetime
                        reset_dt = datetime.fromisoformat(reset_at)
                        reset_text = f"\n\nСброс: {reset_dt.strftime('%d.%m в %H:%M')}"
                    except:
                        pass

                text = (
                    f"⚠️ <b>Лимит AI исчерпан</b>\n\n"
                    f"Вы использовали {limit_info['used']} из {limit_info['limit']} попыток.\n"
                    f"Осталось: {limit_info['remaining']}{reset_text}\n\n"
                    f"⭐ Premium снимает все ограничения!\n"
                    f"В бета-тесте Premium выдаётся бесплатно — напишите администратору: @{settings.TELEGRAM_ADMIN_USERNAME}"
                )
                if isinstance(event, CallbackQuery):
                    await event.message.answer(text)
                    await event.answer()
                else:
                    await event.answer(text)
                return

            result = await func(event, *args, **kwargs)

            # Списываем лимит только после успешного выполнения хендлера
            use_ai_feature(user_id, feature)

            return result

        return wrapper
    return decorator