"""Быстрый ручной ввод дневной активности (шаги, сон) — для пользователей
без автоматической интеграции часов. Автоматика — через /api_key."""

import logging
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.database import get_user
from core.health_data import (
    _local_today,
    _user_tz_offset,
    get_today_metrics,
    get_weekly_health_stats,
    local_noon_utc,
    replace_manual_metric,
)

logger = logging.getLogger(__name__)
router = Router()


class ActivityLog(StatesGroup):
    waiting_for_steps = State()
    waiting_for_sleep = State()


def _skip_kb(step: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"act_skip_{step}")],
    ])


def _date_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📅 Сегодня", callback_data="act_day_today"),
        InlineKeyboardButton(text="📆 Вчера", callback_data="act_day_yesterday"),
    ]])


def _day_word(data: dict) -> str:
    return "вчера" if data.get("day_offset") == 1 else "сегодня"


def _trend_text(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    if pct > 3:
        arrow = "↑"
    elif pct < -3:
        arrow = "↓"
    else:
        arrow = "→"
    return f" ({arrow} {pct:+.0f}% к прошлой неделе)"


def _fmt_weekly(stats: dict) -> str:
    lines = []
    if stats.get("avg_steps") is not None:
        lines.append(
            f"👟 Шаги: {int(stats['avg_steps']):,}".replace(",", " ")
            + f" в среднем за 7 дней{_trend_text(stats.get('steps_trend_pct'))}"
        )
    if stats.get("avg_sleep_hours") is not None:
        lines.append(
            f"😴 Сон: {stats['avg_sleep_hours']:g} ч в среднем за 7 дней"
            + _trend_text(stats.get("sleep_trend_pct"))
        )
    return "\n".join(lines)


def _fmt_metrics(m: dict) -> str:
    parts = []
    if m.get("steps"):
        parts.append(f"👟 Шаги: {int(m['steps']):,}".replace(",", " "))
    if m.get("sleep_hours"):
        parts.append(f"😴 Сон: {m['sleep_hours']:g} ч")
    if m.get("resting_heart_rate"):
        parts.append(f"❤️ Пульс покоя: {int(m['resting_heart_rate'])}")
    return "\n".join(parts)


async def _show_today(message: Message, user_id: int, intro: str = "") -> None:
    metrics = get_today_metrics(user_id)
    body = _fmt_metrics(metrics)
    text = intro
    if body:
        text += f"\n\nСегодня уже записано:\n{body}"
    else:
        text += "\n\nСегодня пока ничего не записано."
    try:
        weekly = _fmt_weekly(get_weekly_health_stats(user_id))
    except Exception as exc:
        logger.warning("Не удалось получить недельную сводку активности (%s): %s", user_id, exc)
        weekly = ""
    if weekly:
        text += f"\n\n<b>За 7 дней:</b>\n{weekly}"
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📈 Графики", callback_data="act_charts")],
        ]),
    )


@router.callback_query(F.data == "act_charts")
async def cb_act_charts(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    sent = False
    try:
        from core.charts import chart_sleep, chart_steps

        charts = (
            (chart_steps(user_id, days=14), "steps_14d.png", "👟 Шаги за 14 дней"),
            (chart_sleep(user_id, days=14), "sleep_14d.png", "😴 Сон за 14 дней"),
        )
    except Exception as exc:
        logger.warning("Не удалось построить графики активности (%s): %s", user_id, exc)
        charts = ()
    for png, filename, caption in charts:
        if not png:
            continue
        try:
            await callback.message.answer_photo(
                BufferedInputFile(png, filename=filename),
                caption=caption,
            )
            sent = True
        except Exception as exc:
            logger.warning("Не удалось отправить график %s (%s): %s", filename, user_id, exc)
    if not sent:
        await callback.message.answer(
            "Пока мало данных для графиков — записывай шаги и сон хотя бы "
            "пару дней через /activity или настрой автосинхронизацию с часами ⌚"
        )


@router.message(Command("activity"))
async def cmd_activity(message: Message, state: FSMContext, user_id: int = None):
    uid = user_id if user_id else message.from_user.id
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся: /register")
        return
    await state.clear()
    await _show_today(message, uid, "⌚ <b>Активность за день</b>")
    await message.answer("За какой день записать активность?", reply_markup=_date_kb())


@router.callback_query(F.data == "activity_log")
async def cb_activity(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await cmd_activity(callback.message, state, user_id=callback.from_user.id)


@router.callback_query(F.data.in_({"act_day_today", "act_day_yesterday"}))
async def cb_activity_day(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    day_offset = 1 if callback.data == "act_day_yesterday" else 0
    await state.clear()
    await state.update_data(day_offset=day_offset)
    await state.set_state(ActivityLog.waiting_for_steps)
    day = "вчера" if day_offset else "сегодня"
    await callback.message.answer(
        f"Сколько шагов прошёл {day}? (посмотри в приложении часов)\n"
        "Напиши число, например: 8500",
        reply_markup=_skip_kb("steps"),
    )


@router.callback_query(F.data == "sleep_log")
async def cb_sleep(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    if not get_user(uid):
        await callback.message.answer("Сначала зарегистрируйся: /register")
        return
    await state.clear()
    await state.update_data(day_offset=0)
    await state.set_state(ActivityLog.waiting_for_sleep)
    await callback.message.answer(
        "Сколько часов спал сегодня ночью? (например: 7.5)",
        reply_markup=_skip_kb("sleep"),
    )


async def _ask_sleep(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(ActivityLog.waiting_for_sleep)
    await message.answer(
        f"Сколько часов спал {_day_word(data)} ночью? (например: 7.5)",
        reply_markup=_skip_kb("sleep"),
    )


@router.callback_query(ActivityLog.waiting_for_steps, F.data == "act_skip_steps")
async def skip_steps(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _ask_sleep(callback.message, state)


@router.message(ActivityLog.waiting_for_steps, F.text)
async def process_steps(message: Message, state: FSMContext):
    try:
        steps = int(message.text.strip().replace(" ", ""))
        if not 0 < steps <= 100000:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Напиши число шагов, например: 8500 (или нажми «Пропустить»)")
        return
    await state.update_data(steps=steps)
    await message.answer(f"👟 Шаги: {steps:,}".replace(",", " "))
    await _ask_sleep(message, state)


@router.callback_query(ActivityLog.waiting_for_sleep, F.data == "act_skip_sleep")
async def skip_sleep(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _finish(callback.message, state, callback.from_user.id)


@router.message(ActivityLog.waiting_for_sleep, F.text)
async def process_sleep(message: Message, state: FSMContext):
    try:
        hours = float(message.text.strip().replace(",", "."))
        if not 0.5 <= hours <= 24:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Напиши часы сна, например: 7.5 (или нажми «Пропустить»)")
        return
    await state.update_data(sleep=hours)
    await _finish(message, state, message.from_user.id)


async def _finish(message: Message, state: FSMContext, user_id: int) -> None:
    from datetime import timedelta

    data = await state.get_data()
    await state.clear()
    day = _local_today(_user_tz_offset(user_id)) - timedelta(days=data.get("day_offset", 0))
    ts = local_noon_utc(user_id, day)
    saved = []
    if data.get("steps"):
        replace_manual_metric(user_id, "steps", data["steps"], source="manual", ts=ts)
        saved.append(f"👟 шаги: {int(data['steps']):,}".replace(",", " "))
    if data.get("sleep"):
        replace_manual_metric(user_id, "sleep_hours", data["sleep"], source="manual", ts=ts)
        saved.append(f"😴 сон: {data['sleep']:g} ч")
    if not saved:
        await message.answer("Ничего не записал. Передумаешь — /activity")
        return
    await message.answer(
        f"✅ Записал за {_day_word(data)}: " + ", ".join(saved) + "\n\n"
        "Эти данные учтутся в утреннем дайджесте.\n"
        "💡 Чтобы iPhone присылал данные сам — нажми кнопку ниже.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Настроить автосинхронизацию", callback_data="watch_setup")],
        ]),
    )
    logger.info("Пользователь %d записал активность вручную: %s", user_id, saved)
