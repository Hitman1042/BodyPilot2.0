"""Обработчики настройки дайджеста и города (с поддержкой user_id)."""

import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from core.database import get_user, update_user
from core.digest import generate_digest_text, _fetch_weather

router = Router()


class DigestSettings(StatesGroup):
    waiting_for_time = State()


class CitySettings(StatesGroup):
    waiting_for_city = State()


def _get_user_id(message: Message, user_id: int = None) -> int:
    return user_id if user_id else message.from_user.id


# ── /set_digest_time ────────────────────────────────────────────────────

@router.message(Command("set_digest_time"))
async def cmd_set_digest_time(message: Message, state: FSMContext, user_id: int = None):
    await state.set_state(DigestSettings.waiting_for_time)
    await message.answer(
        "Введи новое время для утреннего дайджеста в формате <b>ЧЧ:ММ</b> (например, 07:00 или 8:30)."
    )
    await state.update_data(_user_id=_get_user_id(message, user_id))


@router.message(DigestSettings.waiting_for_time)
async def process_digest_time(message: Message, state: FSMContext):
    raw = message.text.strip()
    if ":" not in raw:
        await message.answer("Пожалуйста, введи время в формате ЧЧ:ММ (например, 07:00).")
        return
    parts = raw.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        formatted = f"{hour:02d}:{minute:02d}"
    except (ValueError, IndexError):
        await message.answer("Некорректное время. Введи в формате ЧЧ:ММ (например, 07:00).")
        return

    data = await state.get_data()
    user_id = data.get("_user_id") or message.from_user.id
    user = get_user(user_id)
    if not user:
        await state.clear()
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    update_user(user_id, preferred_time=formatted)
    await state.clear()
    await message.answer(f"✅ Время дайджеста установлено на <b>{formatted}</b>.")


# ── /set_city ───────────────────────────────────────────────────────────

@router.message(Command("set_city"))
async def cmd_set_city(message: Message, state: FSMContext, user_id: int = None):
    await state.set_state(CitySettings.waiting_for_city)
    await message.answer("Введи название города (например, <b>Москва</b>, <b>London</b>):")
    await state.update_data(_user_id=_get_user_id(message, user_id))


@router.message(CitySettings.waiting_for_city)
async def process_city(message: Message, state: FSMContext):
    city = message.text.strip()
    if not city:
        await message.answer("Пожалуйста, введи название города.")
        return

    data = await state.get_data()
    user_id = data.get("_user_id") or message.from_user.id
    user = get_user(user_id)
    if not user:
        await state.clear()
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    update_user(user_id, city=city)
    await state.clear()
    await message.answer(f"✅ Город изменён на <b>{html.escape(city)}</b>. Погода в дайджесте обновится.")


# ── /weather ────────────────────────────────────────────────────────────

@router.message(Command("weather"))
async def cmd_weather(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    city = user.get("city") or "Moscow"
    await message.answer(f"Узнаю погоду в городе <b>{html.escape(city)}</b>...")
    weather = await _fetch_weather(city)
    if weather:
        await message.answer(f"🌤️ Погода в <b>{html.escape(city)}</b>: {weather}")
    else:
        await message.answer("Не удалось получить погоду. Попробуй позже.")


# ── /digest_now ─────────────────────────────────────────────────────────

@router.message(Command("digest_now"))
async def cmd_digest_now(message: Message, user_id: int = None):
    uid = _get_user_id(message, user_id)
    user = get_user(uid)
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    await message.answer("Готовлю твой утренний дайджест...")
    text = await generate_digest_text(uid)
    await message.answer(text)