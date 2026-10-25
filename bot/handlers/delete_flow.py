"""Удаление/отмена записей еды свободным текстом — в любом FSM-состоянии.

Роутер подключается РАНЬШЕ остальных FSM-роутеров (food_tracker, smart_input
и др.), поэтому «удали курицу» не попадает в поле ввода граммов/веса, а
всегда идёт в реальное удаление через execute_tool("delete_food_entry").
"""

import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from core.ai.text_markers import is_delete_intent, extract_delete_target
from core.ai.tools import execute_tool

logger = logging.getLogger(__name__)
router = Router()


def _is_delete_message(message: Message) -> bool:
    return bool(
        message.text
        and not message.text.startswith("/")
        and is_delete_intent(message.text)
    )


@router.message(_is_delete_message)
async def handle_delete_intent(message: Message, state: FSMContext):
    """«удали X», «отмени», «не то записал» — удаление записи еды из любого состояния."""
    uid = message.from_user.id
    text = message.text.strip()

    # Сбрасываем активный FSM, чтобы следующее сообщение не залипло в сценарий
    await state.clear()

    target = extract_delete_target(text)
    lowered = text.lower()
    day = "yesterday" if "вчера" in lowered else None

    # Маршрутизация по типу удаляемого: тренировка / метрика / еда
    if "тренировк" in lowered:
        result = execute_tool(uid, "delete_workout_session", {"date": day} if day else {})
    elif "сон" in lowered or "спал" in lowered:
        result = execute_tool(uid, "delete_health_metric", {"metric_type": "sleep_hours", **({"date": day} if day else {})})
    elif "шаг" in lowered:
        result = execute_tool(uid, "delete_health_metric", {"metric_type": "steps", **({"date": day} if day else {})})
    elif "пульс" in lowered:
        result = execute_tool(uid, "delete_health_metric", {"metric_type": "resting_heart_rate", **({"date": day} if day else {})})
    else:
        result = execute_tool(uid, "delete_food_entry", {"product_name": target})

    if result.get("ok"):
        await message.answer(f"✅ {result['summary']}")
    else:
        await message.answer(f"🤔 {result.get('error', 'Не получилось удалить.')}")
    logger.info("Удаление еды через текст: user=%s text=%r -> %s", uid, text, result.get("ok", result))
