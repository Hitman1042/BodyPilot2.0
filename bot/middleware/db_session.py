"""Middleware для передачи соединения с БД в обработчики."""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

from core.database import get_db


class DBSessionMiddleware(BaseMiddleware):
    """Добавляет объект БД в data['db'] для каждого сообщения."""

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        data["db"] = get_db()
        return await handler(event, data)