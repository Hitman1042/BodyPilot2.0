"""Вечерний чек-ин: итоги дня и статус от пользователя."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core.database import get_db, get_user
from core.digest import _adaptation_rules, _fmt_num
from core.nutrition_calc import get_nutrition_plan
from core.nutrition_tracker import get_food_log_by_date
from core.training_service import get_session_history

logger = logging.getLogger(__name__)

router = Router()

CHECKIN_HOUR = 21  # локальное время отправки вечернего чек-ина


class CheckIn(StatesGroup):
    waiting_for_text = State()


# ── Дата/данные дня ─────────────────────────────────────────────

def local_today(user: Dict) -> str:
    """Сегодняшняя дата по локальному времени пользователя."""
    tz = int(user.get("timezone_offset") or 0)
    return (datetime.now(timezone.utc) + timedelta(minutes=tz)).date().isoformat()


def _collect_today_context(user_id: int, user: Dict) -> Dict[str, Any]:
    """Сводка сегодняшнего дня (локальная дата пользователя)."""
    today = local_today(user)
    ctx: Dict[str, Any] = {
        "today": today,
        "calories": 0.0,
        "protein_g": 0.0,
        "meals_count": 0,
        "had_food_log": False,
        "workout": None,
        "heavy_workout": False,
        "today_plan": None,
    }
    try:
        entries = get_food_log_by_date(user_id, today)
        ctx["meals_count"] = len(entries)
        ctx["had_food_log"] = bool(entries)
        for e in entries:
            ctx["calories"] += float(e.get("calories") or 0)
            ctx["protein_g"] += float(e.get("protein_g") or 0)
    except Exception as e:
        logger.warning(f"Чек-ин: не удалось получить питание за сегодня ({user_id}): {e}")
    try:
        sessions = get_session_history(user_id, days=1)
        t_sessions = [s for s in sessions if s.get("date") == today]
        if t_sessions:
            total_dur = sum(int(s.get("duration_min") or 0) for s in t_sessions)
            ctx["workout"] = {
                "types": sorted({str(s.get("type") or "тренировка") for s in t_sessions}),
                "duration_min": total_dur,
            }
            ctx["heavy_workout"] = total_dur >= 60 or max(
                (int(s.get("intensity") or 0) for s in t_sessions), default=0) >= 8
    except Exception as e:
        logger.warning(f"Чек-ин: не удалось получить тренировки ({user_id}): {e}")
    return ctx


# ── Работа с БД ─────────────────────────────────────────────────

def save_checkin(user_id: int, status: str, note: str = "") -> None:
    """Сохранить чек-ин на сегодня (локальная дата). Повторный ответ перезаписывает."""
    user = get_user(user_id)
    if not user:
        return
    today = local_today(user)
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO daily_checkins (user_id, checkin_date, status, note) "
        "VALUES (?, ?, ?, ?)",
        (user_id, today, status, note),
    )
    conn.commit()


def get_checkin(user_id: int, day: str) -> Optional[Dict]:
    """Получить чек-ин за дату (без маркеров 'pending')."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM daily_checkins WHERE user_id = ? AND checkin_date = ?",
        (user_id, day),
    ).fetchone()
    if not row or row["status"] == "pending":
        return None
    return dict(row)


# ── Сообщение чек-ина ───────────────────────────────────────────

def build_checkin_message(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Собрать текст и клавиатуру вечернего чек-ина."""
    user = get_user(user_id)
    name = (user or {}).get("username", "друг")

    summary_lines = []
    if user:
        ctx = _collect_today_context(user_id, user)
        try:
            plan = get_nutrition_plan(user_id)
        except Exception:
            plan = {}
        cal_goal = plan.get("target_calories", 0)
        prot_goal = (plan.get("macros") or {}).get("protein_g", 0)

        if ctx["had_food_log"]:
            summary_lines.append(
                f"🍽 Питание: {_fmt_num(ctx['calories'])}/{_fmt_num(cal_goal)} ккал, "
                f"Б {_fmt_num(ctx['protein_g'])}/{_fmt_num(prot_goal)} г"
            )
        else:
            summary_lines.append("🍽 Питание сегодня не записывалось")

        if ctx["workout"]:
            w = ctx["workout"]
            dur = f", {w['duration_min']} мин" if w["duration_min"] else ""
            summary_lines.append(f"🏋️ Тренировка: {', '.join(w['types'])}{dur}")
        else:
            summary_lines.append("🏋️ Тренировки сегодня не было")

    summary = "\n".join(summary_lines)
    text = (
        f"🌙 Как прошёл день, {name}?\n\n"
        f"{summary}\n\n"
        f"Отметь, как всё прошло — это поможет мне адаптировать завтрашний план:"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Всё по плану", callback_data="ci_ok")],
        [InlineKeyboardButton(text="🍽 Переел", callback_data="ci_overate")],
        [InlineKeyboardButton(text="😴 Пропустил тренировку", callback_data="ci_skipped")],
        [InlineKeyboardButton(text="✏️ Расскажу сам", callback_data="ci_custom")],
    ])
    return text, keyboard


# ── Совет на завтра ─────────────────────────────────────────────

def _tomorrow_focus_rules(user_id: int, user: Dict, ctx: Dict[str, Any]) -> str:
    """Правила (без AI): фокус на завтра по данным сегодняшнего дня."""
    try:
        plan = get_nutrition_plan(user_id)
        cal_goal = plan.get("target_calories", 2000)
        prot = (plan.get("macros") or {}).get("protein_g", 150)
    except Exception:
        cal_goal, prot = 2000, 150
    rules = _adaptation_rules(ctx, cal_goal, prot, user.get("goal", "maintain"))
    parts = [rules["nutrition_focus"], rules["workout_focus"]]
    if rules.get("micro_goal"):
        parts.append(f"Микро-цель: {rules['micro_goal']}")
    # Правила написаны для утреннего дайджеста («сегодня») — вечером читаем как «завтра»
    return "\n".join(
        p.replace("Сегодня", "Завтра").replace("сегодня", "завтра") for p in parts if p
    )


async def _tomorrow_focus_ai(user_id: int, user: Dict, ctx: Dict[str, Any], status: str) -> Optional[str]:
    """Короткий AI-совет на завтра. Только если Gemini доступен; при сбое — None."""
    try:
        from core.ai.gemini_client import get_gemini_client

        client = get_gemini_client()
        if not client:
            return None
        context = (
            f"Вечерний чек-ин. Съедено {round(ctx['calories'])} ккал, белка {round(ctx['protein_g'])} г. "
            f"Тренировка: {'была' if ctx['workout'] else 'не была'}. "
            f"Пользователь отметил: {status}."
        )
        result = await client.chat_answer(
            user_profile={
                "goal": user.get("goal", "maintain"),
                "sport_level": user.get("sport_level", "beginner"),
            },
            question="Дай один короткий совет на завтра (1-2 предложения)",
            context=context,
        )
        if result and isinstance(result, dict) and "error" not in result:
            return result.get("answer")
    except Exception as e:
        logger.warning(f"Чек-ин: AI-совет недоступен ({user_id}): {e}")
    return None


async def _reply_with_tomorrow_focus(callback: CallbackQuery, user: Dict,
                                     ctx: Dict[str, Any], status: str, ack_text: str) -> None:
    """Ответ на чек-ин: поддержка + фокус на завтра (AI при доступности, иначе правила)."""
    user_id = user["user_id"]
    ai_tip = await _tomorrow_focus_ai(user_id, user, ctx, status)
    if ai_tip:
        body = ai_tip
    else:
        focus = await asyncio.get_running_loop().run_in_executor(
            None, _tomorrow_focus_rules, user_id, user, ctx)
        body = f"<b>Фокус на завтра:</b>\n{focus}"
    await callback.message.edit_text(f"{callback.message.text}\n\n{ack_text}\n\n{body}")


async def _safe_answer(callback: CallbackQuery, text: Optional[str] = None) -> None:
    """Ack колбэка сразу, до долгих операций; повторные нажатия не роняют хендлер."""
    try:
        await callback.answer(text) if text else await callback.answer()
    except Exception as exc:
        logger.debug("callback.answer не удался (%s): %s", callback.data, exc)


def _get_ctx_and_user(callback: CallbackQuery) -> Tuple[Optional[Dict], Optional[Dict]]:
    user = get_user(callback.from_user.id)
    if not user:
        return None, None
    return user, _collect_today_context(user["user_id"], user)


# ── Команда /checkin ────────────────────────────────────────────

@router.message(Command("checkin"))
async def cmd_checkin(message: Message, user_id: int = None):
    uid = user_id or message.from_user.id
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    text, keyboard = build_checkin_message(uid)
    await message.answer(text, reply_markup=keyboard)


# ── Callback'и ──────────────────────────────────────────────────

@router.callback_query(F.data == "ci_ok")
async def ci_ok(callback: CallbackQuery):
    if not get_user(callback.from_user.id):
        await _safe_answer(callback, "Сначала зарегистрируйся с помощью /register")
        return
    await _safe_answer(callback)
    user, ctx = _get_ctx_and_user(callback)
    save_checkin(user["user_id"], "ok")
    await _reply_with_tomorrow_focus(
        callback, user, ctx, "всё по плану", "✅ Отлично! Так держать 💪")


@router.callback_query(F.data == "ci_overate")
async def ci_overate(callback: CallbackQuery):
    if not get_user(callback.from_user.id):
        await _safe_answer(callback, "Сначала зарегистрируйся с помощью /register")
        return
    await _safe_answer(callback)
    user, ctx = _get_ctx_and_user(callback)
    save_checkin(user["user_id"], "overate")
    await _reply_with_tomorrow_focus(
        callback, user, ctx, "переел",
        "🍽 Бывает, не ругай себя! Завтра: лёгкий завтрак, больше воды и возвращаемся к норме.")


@router.callback_query(F.data == "ci_skipped")
async def ci_skipped(callback: CallbackQuery):
    if not get_user(callback.from_user.id):
        await _safe_answer(callback, "Сначала зарегистрируйся с помощью /register")
        return
    await _safe_answer(callback)
    user, ctx = _get_ctx_and_user(callback)
    save_checkin(user["user_id"], "skipped_workout")
    await _reply_with_tomorrow_focus(
        callback, user, ctx, "пропустил тренировку",
        "😴 Ничего страшного — отдых тоже часть прогресса.")


@router.callback_query(F.data == "ci_custom")
async def ci_custom(callback: CallbackQuery, state: FSMContext):
    if not get_user(callback.from_user.id):
        await _safe_answer(callback, "Сначала зарегистрируйся с помощью /register")
        return
    await _safe_answer(callback)
    await state.set_state(CheckIn.waiting_for_text)
    await callback.message.edit_text(
        f"{callback.message.text}\n\n"
        "✏️ Расскажи текстом, как прошёл день — что получилось, что нет."
    )


@router.message(CheckIn.waiting_for_text, F.text)
async def ci_custom_text(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await state.clear()
    if not user:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    note = (message.text or "").strip()[:1000]
    save_checkin(user["user_id"], "custom", note=note)

    ctx = _collect_today_context(user["user_id"], user)
    ai_tip = await _tomorrow_focus_ai(user["user_id"], user, ctx, f"рассказал: {note[:200]}")
    if ai_tip:
        reply = ai_tip
    else:
        focus = _tomorrow_focus_rules(user["user_id"], user, ctx)
        reply = (
            "Спасибо, что поделился! Я учту это в завтрашнем плане. 🤝\n\n"
            f"<b>Фокус на завтра:</b>\n{focus}"
        )
    await message.answer(reply)
