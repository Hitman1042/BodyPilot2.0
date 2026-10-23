"""Регрессионные тесты QA-аудита: утечка сессий, HTML-экранирование,
проверки регистрации в сценариях."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.smart_input import _extract_food, _food_card_text


# ── IPv4Session: сессия должна кэшироваться ─────────────────────────────

def test_ipv4_session_is_cached():
    """aiogram вызывает create_session() на каждый запрос — без кэша каждый
    вызов создаёт новую aiohttp-сессию (утечка «Unclosed client session»)."""
    from bot.main import IPv4Session

    async def run():
        session = IPv4Session()
        s1 = await session.create_session()
        s2 = await session.create_session()
        assert s1 is s2
        await s1.close()
        # После закрытия создаётся новая
        s3 = await session.create_session()
        assert s3 is not s1
        await s3.close()

    asyncio.run(run())


# ── smart_input: экранирование и устойчивость карточки еды ──────────────

def test_food_card_escapes_html_in_name():
    food = {
        "food_name": "Салат <b>Цезарь</b> & соус",
        "weight_g": 200.0,
        "calories": 350.0,
        "protein_g": 20.0,
        "fat_g": 25.0,
        "carbs_g": 10.0,
    }
    text = _food_card_text(food)
    assert "<b>Цезарь</b>" not in text.replace("<b>Распознал:</b>", "")
    assert "&lt;b&gt;Цезарь&lt;/b&gt;" in text
    assert "&amp; соус" in text


def test_extract_food_rejects_zero_calories_and_bad_types():
    assert _extract_food(None) is None
    assert _extract_food({"error": "не распознано"}) is None
    assert _extract_food({"food_name": ""}) is None
    assert _extract_food({"food_name": "Гречка", "calories": 0, "confidence": 0.9}) is None
    assert _extract_food({"food_name": "Гречка", "calories": "abc"}) is None
    assert _extract_food({"food_name": "Гречка", "calories": 200, "confidence": 0.3}) is None
    food = _extract_food({"food_name": "Гречка", "calories": 200, "confidence": 0.9})
    assert food and food["weight_g"] == 100.0


# ── Хелперы для хендлеров ────────────────────────────────────────────────

def _make_message(user_id: int = 999999999, username: str = None, text: str = ""):
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = user_id
    message.from_user.username = username
    message.from_user.full_name = "Test"
    message.text = text
    message.answer = AsyncMock()
    return message


def _make_state():
    state = MagicMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    return state


# ── Незарегистрированный пользователь → просьба /register ────────────────

def test_cmd_start_workout_requires_registration():
    from bot.handlers.workout import cmd_start_workout

    message = _make_message()
    state = _make_state()
    asyncio.run(cmd_start_workout(message, state))

    message.answer.assert_awaited_once()
    assert "/register" in message.answer.await_args.args[0]
    state.set_state.assert_not_awaited()


def test_cmd_log_meal_requires_registration():
    from bot.handlers.food_tracker import cmd_log_meal

    message = _make_message()
    state = _make_state()
    asyncio.run(cmd_log_meal(message, state))

    message.answer.assert_awaited_once()
    assert "/register" in message.answer.await_args.args[0]
    state.set_state.assert_not_awaited()


def test_cmd_add_product_requires_registration():
    from bot.handlers.food_tracker import cmd_add_product

    message = _make_message()
    state = _make_state()
    asyncio.run(cmd_add_product(message, state))

    message.answer.assert_awaited_once()
    assert "/register" in message.answer.await_args.args[0]


def test_cmd_log_weight_requires_registration():
    from bot.handlers.weight import cmd_log_weight

    message = _make_message()
    state = _make_state()
    asyncio.run(cmd_log_weight(message, state))

    message.answer.assert_awaited_once()
    assert "/register" in message.answer.await_args.args[0]
    state.set_state.assert_not_awaited()


# ── /admin без username у пользователя — не должен падать ────────────────

def test_cmd_admin_without_username():
    from bot.handlers.premium import cmd_admin

    message = _make_message(username=None, text="/admin")
    asyncio.run(cmd_admin(message))

    message.answer.assert_awaited_once()
    assert "Доступ запрещён" in message.answer.await_args.args[0]
