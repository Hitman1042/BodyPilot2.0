"""Планировщик дайджестов, чек-инов, отчётов, микросоветов и очистки базы."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings
from .database import (
    get_users_due_for_digest, get_user, mark_plan_sent,
    cleanup_expired_bonus_days,
)
from .nutrition_tracker import cleanup_unused_products
from .reminders import (
    REMINDER_NO_FOOD, REMINDER_WORKOUT, REMINDER_REACTIVATION,
    REMINDER_PROGRESS_PHOTO,
    get_users_due_for_food_reminder, get_users_due_for_workout_reminder,
    get_users_due_for_reactivation, get_users_due_for_progress_photo_reminder,
    mark_reminder_sent,
    build_food_reminder_text, build_workout_reminder_text, build_reactivation_text,
    build_progress_photo_text,
)

logger = logging.getLogger(__name__)


async def _send_digest(bot: Bot, user_id: int):
    try:
        text = await _generate_digest_text(user_id)
        await bot.send_message(chat_id=user_id, text=text)

        loop = asyncio.get_running_loop()
        user = await loop.run_in_executor(None, get_user, user_id)
        if user:
            tz_offset = user.get("timezone_offset", 0)
            user_now = datetime.now(timezone.utc) + timedelta(minutes=tz_offset)
            plan_date = user_now.date().isoformat()
            await loop.run_in_executor(None, mark_plan_sent, user_id, plan_date)

        logger.info(f"Дайджест отправлен пользователю {user_id}")
    except Exception as e:
        logger.warning(f"Ошибка отправки дайджеста пользователю {user_id}: {e}")


from .digest import generate_digest_text as _generate_digest_text


def _get_users_due_for_checkin() -> list:
    """Пользователи для вечернего чек-ина: 21:00 локальное, чек-ина ещё не было,
    и сегодня есть активность (еда или тренировка) — не спамим неактивным."""
    from .database import get_db
    from bot.handlers.checkin import CHECKIN_HOUR

    conn = get_db()
    now = datetime.now(timezone.utc)
    due: list[tuple[int, str]] = []
    rows = conn.execute("SELECT user_id, timezone_offset FROM users").fetchall()
    for r in rows:
        u = dict(r)
        try:
            user_now = now + timedelta(minutes=int(u.get("timezone_offset") or 0))
        except (ValueError, TypeError):
            continue
        if user_now.hour != CHECKIN_HOUR or user_now.minute > 2:
            continue
        today = user_now.date().isoformat()
        # Уже отправляли (pending) или пользователь уже ответил
        if conn.execute(
                "SELECT id FROM daily_checkins WHERE user_id = ? AND checkin_date = ?",
                (u["user_id"], today),
        ).fetchone():
            continue
        offset_min = int(u.get("timezone_offset") or 0)
        day_expr = f"DATE(logged_at, '{offset_min:+d} minutes')"
        has_food = conn.execute(
            f"SELECT id FROM food_log_new WHERE user_id = ? AND {day_expr} = ? LIMIT 1",
            (u["user_id"], today),
        ).fetchone()
        has_workout = conn.execute(
            "SELECT id FROM workout_sessions WHERE user_id = ? AND date = ? LIMIT 1",
            (u["user_id"], today),
        ).fetchone()
        if not (has_food or has_workout):
            continue
        due.append((u["user_id"], today))
    return due


def _mark_checkin_sent(user_id: int, day: str) -> None:
    """Маркер отправки чек-ина, чтобы не дублировать сообщение в окне 21:00-21:02."""
    from .database import get_db

    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO daily_checkins (user_id, checkin_date, status) "
        "VALUES (?, ?, 'pending')",
        (user_id, day),
    )
    conn.commit()


async def _send_checkin(bot: Bot, user_id: int, day: str):
    try:
        from bot.handlers.checkin import build_checkin_message

        loop = asyncio.get_running_loop()
        text, keyboard = await loop.run_in_executor(None, build_checkin_message, user_id)
        await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        await loop.run_in_executor(None, _mark_checkin_sent, user_id, day)
        logger.info(f"Вечерний чек-ин отправлен пользователю {user_id}")
    except Exception as e:
        logger.warning(f"Ошибка отправки чек-ина пользователю {user_id}: {e}")


def _get_users_due_for_weekly_report() -> list:
    """Активные пользователи для отчёта: воскресенье 20:00, не чаще раза в 7 дней."""
    from .database import get_db

    conn = get_db()
    now = datetime.now(timezone.utc)
    due: list[tuple[int, str]] = []
    rows = conn.execute("SELECT user_id, timezone_offset FROM users").fetchall()
    for row in rows:
        user = dict(row)
        try:
            offset = int(user.get("timezone_offset") or 0)
        except (TypeError, ValueError):
            continue
        user_now = now + timedelta(minutes=offset)
        if user_now.weekday() != 6 or user_now.hour != 20 or user_now.minute > 2:
            continue

        user_id = user["user_id"]
        report_date = user_now.date().isoformat()
        last_report = conn.execute(
            """SELECT report_date FROM report_log
               WHERE user_id = ? AND report_type = 'weekly'
               ORDER BY report_date DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        if last_report:
            try:
                last_date = datetime.fromisoformat(last_report["report_date"]).date()
                if (user_now.date() - last_date).days < 7:
                    continue
            except (TypeError, ValueError):
                pass

        first_day = (user_now.date() - timedelta(days=6)).isoformat()
        modifier = f"{offset:+d} minutes"
        has_food = conn.execute(
            """SELECT id FROM food_log_new
               WHERE user_id = ? AND date(logged_at, ?) BETWEEN ? AND ? LIMIT 1""",
            (user_id, modifier, first_day, report_date),
        ).fetchone()
        has_workout = conn.execute(
            """SELECT id FROM workout_sessions
               WHERE user_id = ? AND date BETWEEN ? AND ? LIMIT 1""",
            (user_id, first_day, report_date),
        ).fetchone()
        if has_food or has_workout:
            due.append((user_id, report_date))
    return due


def _mark_weekly_report_sent(user_id: int, report_date: str) -> None:
    from .database import get_db

    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO report_log (user_id, report_type, report_date)
           VALUES (?, 'weekly', ?)""",
        (user_id, report_date),
    )
    conn.commit()


async def _send_weekly_report(bot: Bot, user_id: int, report_date: str):
    try:
        from .weekly_report import send_weekly_report as deliver_weekly_report

        await deliver_weekly_report(bot, user_id, user_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _mark_weekly_report_sent, user_id, report_date)
        logger.info(f"Недельный отчёт отправлен пользователю {user_id}")
    except Exception as e:
        logger.warning(f"Ошибка отправки недельного отчёта пользователю {user_id}: {e}")


def _get_users_due_for_tip() -> list:
    """Активные пользователи для совета: вторник/пятница, 13:00 локального времени."""
    from .database import get_db

    conn = get_db()
    now = datetime.now(timezone.utc)
    due: list[tuple[int, str]] = []
    rows = conn.execute(
        "SELECT user_id, timezone_offset FROM users "
        "WHERE preferred_time IS NOT NULL AND preferred_time != ''"
    ).fetchall()
    for row in rows:
        user = dict(row)
        try:
            offset = int(user.get("timezone_offset") or 0)
        except (TypeError, ValueError):
            continue
        user_now = now + timedelta(minutes=offset)
        if user_now.weekday() not in (1, 4) or user_now.hour != 13 or user_now.minute > 2:
            continue

        user_id = user["user_id"]
        tip_date = user_now.date().isoformat()
        if conn.execute(
            "SELECT id FROM tip_log WHERE user_id = ? AND tip_date = ?",
            (user_id, tip_date),
        ).fetchone():
            continue

        first_day = (user_now.date() - timedelta(days=6)).isoformat()
        modifier = f"{offset:+d} minutes"
        has_food = conn.execute(
            """SELECT id FROM food_log_new
               WHERE user_id = ? AND date(logged_at, ?) BETWEEN ? AND ? LIMIT 1""",
            (user_id, modifier, first_day, tip_date),
        ).fetchone()
        has_workout = conn.execute(
            """SELECT id FROM workout_sessions
               WHERE user_id = ? AND date BETWEEN ? AND ? LIMIT 1""",
            (user_id, first_day, tip_date),
        ).fetchone()
        if has_food or has_workout:
            due.append((user_id, tip_date))
    return due


def _mark_tip_sent(user_id: int, tip_date: str) -> None:
    from .database import get_db

    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO tip_log (user_id, tip_date) VALUES (?, ?)",
        (user_id, tip_date),
    )
    conn.commit()


async def _send_tip(bot: Bot, user_id: int, tip_date: str):
    try:
        from .tips import build_daily_tip

        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, build_daily_tip, user_id)
        await bot.send_message(chat_id=user_id, text=text)
        await loop.run_in_executor(None, _mark_tip_sent, user_id, tip_date)
        logger.info(f"Совет дня отправлен пользователю {user_id}")
    except Exception as e:
        logger.warning(f"Ошибка отправки совета пользователю {user_id}: {e}")


async def _send_reminder(bot: Bot, user_id: int, reminder_type: str, day: str, text: str):
    """Единый хелпер отправки напоминаний: ошибки логируются, планировщик не падает."""
    try:
        await bot.send_message(chat_id=user_id, text=text)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mark_reminder_sent, user_id, reminder_type, day)
        logger.info(f"Напоминание {reminder_type} отправлено пользователю {user_id}")
    except Exception as e:
        logger.warning(f"Ошибка отправки напоминания {reminder_type} пользователю {user_id}: {e}")


async def _send_workout_reminder(bot: Bot, user_id: int, day: str):
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, build_workout_reminder_text, user_id, day)
    await _send_reminder(bot, user_id, REMINDER_WORKOUT, day, text)


async def _send_reactivation(bot: Bot, user_id: int, day: str):
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, build_reactivation_text, user_id)
    await _send_reminder(bot, user_id, REMINDER_REACTIVATION, day, text)


async def _check_and_send(bot: Bot):
    loop = asyncio.get_running_loop()
    try:
        # Очистка просроченных бонусных дней
        await loop.run_in_executor(None, cleanup_expired_bonus_days)

        # Очистка невостребованных продуктов
        deleted = await loop.run_in_executor(None, cleanup_unused_products)
        if deleted:
            logger.info(f"Удалено {deleted} невостребованных продуктов.")

        due_users = await loop.run_in_executor(None, get_users_due_for_digest)
        for user in due_users:
            await _send_digest(bot, user["user_id"])

        # Вечерний чек-ин (21:00 по локальному времени пользователя)
        checkin_users = await loop.run_in_executor(None, _get_users_due_for_checkin)
        for user_id, day in checkin_users:
            await _send_checkin(bot, user_id, day)

        weekly_users = await loop.run_in_executor(None, _get_users_due_for_weekly_report)
        for user_id, report_date in weekly_users:
            await _send_weekly_report(bot, user_id, report_date)

        tip_users = await loop.run_in_executor(None, _get_users_due_for_tip)
        for user_id, tip_date in tip_users:
            await _send_tip(bot, user_id, tip_date)

        # Умные напоминания (по локальному времени пользователя)
        food_reminder_users = await loop.run_in_executor(None, get_users_due_for_food_reminder)
        for user_id, day in food_reminder_users:
            await _send_reminder(bot, user_id, REMINDER_NO_FOOD, day, build_food_reminder_text())

        workout_reminder_users = await loop.run_in_executor(None, get_users_due_for_workout_reminder)
        for user_id, day in workout_reminder_users:
            await _send_workout_reminder(bot, user_id, day)

        reactivation_users = await loop.run_in_executor(None, get_users_due_for_reactivation)
        for user_id, day in reactivation_users:
            await _send_reactivation(bot, user_id, day)

        progress_photo_users = await loop.run_in_executor(None, get_users_due_for_progress_photo_reminder)
        for user_id, day in progress_photo_users:
            await _send_reminder(bot, user_id, REMINDER_PROGRESS_PHOTO, day, build_progress_photo_text())
    except Exception as e:
        logger.error(f"Ошибка в планировщике дайджестов: {e}")


def start_scheduler(bot: Bot):
    scheduler = AsyncIOScheduler(timezone=str(datetime.now(timezone.utc).tzinfo))
    minutes = settings.DIGEST_CHECK_INTERVAL_MINUTES
    scheduler.add_job(
        _check_and_send,
        "interval",
        minutes=minutes,
        args=[bot],
        id="digest_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Планировщик дайджестов запущен (проверка каждые {minutes} мин.)")
    return scheduler