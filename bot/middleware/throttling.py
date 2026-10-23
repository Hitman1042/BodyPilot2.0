"""In-memory антифлуд: ограничение частоты сообщений и callback'ов."""

import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery


class ThrottlingMiddleware(BaseMiddleware):
    """Пропускает не чаще одного события за интервал на пользователя.

    Повторные события в пределах окна молча игнорируются.
    """

    def __init__(self, message_interval: float = 1.0, callback_interval: float = 0.5):
        self.message_interval = message_interval
        self.callback_interval = callback_interval
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            interval = self.message_interval
        elif isinstance(event, CallbackQuery):
            interval = self.callback_interval
        else:
            return await handler(event, data)

        user = event.from_user
        if user is None:
            return await handler(event, data)

        # Защита от разрастания словаря
        if len(self._last) > 10000:
            self._last.clear()

        now = time.monotonic()
        if now - self._last.get(user.id, 0.0) < interval:
            return None

        self._last[user.id] = now
        return await handler(event, data)
