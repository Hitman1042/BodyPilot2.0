"""Друзья: социальная лента, Kudos и групповые челленджи."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.inline_menus import get_settings_menu
from core.challenges import CHALLENGES, join_challenge
from core.social import get_feed, get_friends, get_group_challenge, give_kudos

logger = logging.getLogger(__name__)
router = Router()


def _social_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 Лента друзей", callback_data="social_feed")],
        [InlineKeyboardButton(text="🎯 Челленджи с друзьями", callback_data="social_challenges")],
        [InlineKeyboardButton(text="🔙 К профилю", callback_data="social_settings")],
    ])


def _feed_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        label = f"👏 Поддержано · {item['kudos_count']}" if item["kudosed"] else "👏 Поддержать"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"kudos_{item['type']}_{item['id']}",
        )])
    buttons.extend([
        [InlineKeyboardButton(text="🎯 Челленджи с друзьями", callback_data="social_challenges")],
        [InlineKeyboardButton(text="🔙 К друзьям", callback_data="social_menu")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "social_menu")
async def show_social_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "👥 <b>Друзья</b>\n\nСледите за прогрессом друг друга и поддерживайте 👏",
        reply_markup=_social_menu(),
    )


@router.callback_query(F.data == "social_settings")
async def back_to_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "⚙️ <b>Профиль и настройки</b> — выбери действие:",
        reply_markup=get_settings_menu(),
    )


@router.callback_query(F.data == "social_feed")
async def show_social_feed(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    if not get_friends(user_id):
        await callback.message.edit_text(
            "👥 <b>Друзья</b>\n\nПригласи друзей по своей ссылке — будет веселее!",
            reply_markup=_social_menu(),
        )
        return
    items = get_feed(user_id, limit=5)
    if not items:
        text = "📰 <b>Лента друзей</b>\n\nПока тихо. Свежие тренировки, рекорды и достижения появятся здесь."
    else:
        lines = ["📰 <b>Лента друзей</b>", ""]
        for item in items:
            name = html.escape(item["from_username"])
            text = html.escape(item["text"])
            count = f" · 👏 {item['kudos_count']}" if item["kudos_count"] else ""
            lines.append(f"• <b>{name}</b>: {text}{count}")
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=_feed_keyboard(items))


@router.callback_query(F.data.startswith("kudos_"))
async def send_kudos(callback: CallbackQuery) -> None:
    await callback.answer()
    payload = callback.data.removeprefix("kudos_")
    try:
        target_type, raw_target_id = payload.split("_", 1)
        target_id = int(raw_target_id)
    except ValueError:
        await callback.message.answer("Не удалось отправить поддержку. Обнови ленту.")
        return

    user_id = callback.from_user.id
    result = give_kudos(user_id, target_type, target_id)
    if not result["ok"]:
        messages = {
            "already_given": "Ты уже поддержал это событие 👏",
            "not_friends": "Поддерживать можно только друзей.",
        }
        await callback.message.answer(messages.get(result["error"], "Событие не найдено. Обнови ленту."))
        return

    item = next(
        (entry for entry in get_feed(user_id, limit=50)
         if entry["type"] == target_type and entry["id"] == target_id),
        None,
    )
    sender_name = html.escape(callback.from_user.full_name or callback.from_user.username or "Друг")
    event_text = html.escape(item["text"]) if item else "твоё достижение"
    try:
        await callback.bot.send_message(
            result["to_user_id"],
            f"👏 <b>{sender_name}</b> поддержал тебя: {event_text}",
        )
    except Exception as exc:
        logger.warning("Не удалось отправить Kudos пользователю %s: %s", result["to_user_id"], exc)
    await callback.message.answer("Отправлено 👏")


@router.callback_query(F.data == "social_challenges")
async def show_social_challenges(callback: CallbackQuery) -> None:
    await callback.answer()
    buttons = [
        [InlineKeyboardButton(text=item["name"], callback_data=f"social_challenge_{code}")]
        for code, item in CHALLENGES.items()
    ]
    buttons.append([InlineKeyboardButton(text="🔙 К друзьям", callback_data="social_menu")])
    await callback.message.edit_text(
        "🎯 <b>Челленджи с друзьями</b>\n\nВыбери челлендж, чтобы сравнить прогресс:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


def _group_challenge_view(user_id: int, code: str) -> tuple[str, InlineKeyboardMarkup]:
    group = get_group_challenge(user_id, code)
    status_labels = {
        "active": "в процессе",
        "completed": "🏆 выполнен",
        "failed": "завершён",
        "not_joined": "не участвует",
    }
    lines = [f"🎯 <b>{html.escape(group['name'])}</b>", ""]
    for participant in group["participants"]:
        name = html.escape(participant["username"])
        lines.append(
            f"• <b>{name}</b>: {participant['current']}/{participant['target']} "
            f"{group['unit']} · {status_labels.get(participant['status'], participant['status'])}"
        )
    buttons = []
    if not group["user_joined"]:
        buttons.append([InlineKeyboardButton(text="✅ Участвовать", callback_data=f"social_join_{code}")])
    buttons.extend([
        [InlineKeyboardButton(text="🔙 К челленджам", callback_data="social_challenges")],
        [InlineKeyboardButton(text="👥 К друзьям", callback_data="social_menu")],
    ])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.startswith("social_challenge_"))
async def show_group_challenge(callback: CallbackQuery) -> None:
    await callback.answer()
    code = callback.data.removeprefix("social_challenge_")
    try:
        text, keyboard = _group_challenge_view(callback.from_user.id, code)
    except ValueError as exc:
        await callback.message.answer(str(exc))
        return
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("social_join_"))
async def join_social_challenge(callback: CallbackQuery) -> None:
    await callback.answer()
    code = callback.data.removeprefix("social_join_")
    try:
        join_challenge(callback.from_user.id, code)
        text, keyboard = _group_challenge_view(callback.from_user.id, code)
    except ValueError as exc:
        await callback.message.answer(str(exc))
        return
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.message.answer("🎯 Ты в игре!")
