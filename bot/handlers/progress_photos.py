"""Фото прогресса: серия фотографий формы с датами и весом.

Вход только явный (кнопка «📸 Фото прогресса» → FSM «жду фото»), чтобы не
перехватывать обычные фото еды — те обрабатывает ai_food.py. Роутер
подключается в bot/main.py ДО ai_food: state-хендлер этого роутера тогда
имеет приоритет над F.photo-хендлерами распознавания еды.
"""

import logging

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core.database import (
    add_progress_photo, count_progress_photos, get_progress_photos, get_user,
)

logger = logging.getLogger(__name__)

router = Router()


class ProgressPhotos(StatesGroup):
    waiting_for_photo = State()
    waiting_for_weight = State()


def _photo_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    count = count_progress_photos(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Добавить фото", callback_data="pp_add")],
        [InlineKeyboardButton(text=f"🖼 Мои фото ({count})", callback_data="pp_list")],
        [InlineKeyboardButton(text="🔙 К прогрессу", callback_data="progress_menu")],
    ])


_PHOTO_MENU_TEXT = (
    "📸 <b>Фото прогресса</b>\n\n"
    "Присылай фото формы раз в 2-4 недели — так прогресс видно лучше, "
    "чем по весам.\n\n"
    "🔒 Фото видишь только ты."
)

_CANCEL_ROW = [InlineKeyboardButton(text="❌ Отмена", callback_data="pp_cancel")]


def _fmt_day(taken_at: str) -> str:
    """'2026-10-21 09:30:00' → '21.10'."""
    day = (taken_at or "")[:10]
    return f"{day[8:10]}.{day[5:7]}" if len(day) == 10 else day


def build_weight_dynamics(photos: list[dict]) -> str:
    """Динамика веса между первым и последним фото (где вес указан)."""
    with_weight = sorted(
        (p for p in photos if p.get("weight_kg")),
        key=lambda p: (p.get("taken_at") or "", p.get("id") or 0),
    )
    if len(with_weight) < 2:
        return ""
    first, last = with_weight[0], with_weight[-1]
    diff = round(last["weight_kg"] - first["weight_kg"], 1)
    since = _fmt_day(first["taken_at"])
    if diff < 0:
        return f"📉 {diff} кг с {since}"
    if diff > 0:
        return f"📈 +{diff} кг с {since}"
    return f"➖ Вес без изменений с {since}"


async def _show_photo_menu(target, user_id: int, edit: bool):
    keyboard = _photo_menu_keyboard(user_id)
    if edit:
        await target.edit_text(_PHOTO_MENU_TEXT, reply_markup=keyboard)
    else:
        await target.answer(_PHOTO_MENU_TEXT, reply_markup=keyboard)


@router.message(Command("progress_photo"))
async def cmd_progress_photo(message: Message, state: FSMContext, user_id: int = None):
    uid = user_id if user_id else message.from_user.id
    if not get_user(uid):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await state.clear()
    await _show_photo_menu(message, uid, edit=False)


@router.callback_query(F.data == "progress_photo_menu")
async def show_photo_menu(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not get_user(uid):
        await callback.answer("Сначала зарегистрируйся с помощью /register", show_alert=True)
        return
    await state.clear()
    await _show_photo_menu(callback.message, uid, edit=True)
    await callback.answer()


@router.callback_query(F.data == "pp_add")
async def start_add_photo(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not get_user(uid):
        await callback.answer("Сначала зарегистрируйся с помощью /register", show_alert=True)
        return
    await state.set_state(ProgressPhotos.waiting_for_photo)
    await state.update_data(_user_id=uid)
    await callback.message.edit_text(
        "📸 Пришли фото прогресса одним сообщением.\n\n"
        "Можно добавить подпись — она сохранится как заметка "
        "(например, «после месяца силовых»).\n\n"
        "🔒 Фото видишь только ты.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_CANCEL_ROW]),
    )
    await callback.answer()


@router.callback_query(F.data == "pp_cancel")
async def cancel_photo(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()


@router.message(ProgressPhotos.waiting_for_photo, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("_user_id") or message.from_user.id
    user = get_user(uid)
    if not user:
        await state.clear()
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return

    await state.update_data(
        pp_file_id=message.photo[-1].file_id,
        pp_note=(message.caption or "").strip(),
    )
    await state.set_state(ProgressPhotos.waiting_for_weight)

    current_weight = user.get("weight_kg")
    buttons = []
    if current_weight:
        buttons.append([InlineKeyboardButton(
            text=f"⚖️ Текущий вес из профиля ({current_weight} кг)",
            callback_data="pp_weight_profile",
        )])
    buttons.append([InlineKeyboardButton(text="⏭️ Пропустить", callback_data="pp_weight_skip")])
    buttons.append(_CANCEL_ROW)
    await message.answer(
        "Фото получено! Указать к нему вес?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.message(ProgressPhotos.waiting_for_photo, ~F.text.startswith("/"))
async def receive_not_photo(message: Message):
    await message.answer(
        "Это не фото 🙂 Пришли снимок одним сообщением или нажми «❌ Отмена».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_CANCEL_ROW]),
    )


async def _save_photo(callback: CallbackQuery, state: FSMContext, weight: float | None):
    data = await state.get_data()
    file_id = data.get("pp_file_id")
    uid = data.get("_user_id") or callback.from_user.id
    if not file_id:
        await state.clear()
        await callback.answer("Кнопка устарела — начни заново: «📸 Добавить фото».", show_alert=True)
        return
    add_progress_photo(uid, file_id, weight_kg=weight, note=data.get("pp_note") or "")
    await state.clear()
    count = count_progress_photos(uid)
    weight_part = f" Вес: {weight} кг." if weight else ""
    await callback.message.edit_text(
        f"📸 <b>Фото сохранено!</b>{weight_part}\n\n"
        f"Всего фото: <b>{count}</b>.\n"
        f"Сравнивай себя через 2-4 недели — разница будет заметна 💪",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🖼 Мои фото", callback_data="pp_list")],
            [InlineKeyboardButton(text="🔙 К прогрессу", callback_data="progress_menu")],
        ]),
    )
    await callback.answer("Сохранено!")
    logger.info("Фото прогресса сохранено: user=%s, всего=%s", uid, count)


@router.callback_query(StateFilter(ProgressPhotos.waiting_for_weight), F.data == "pp_weight_profile")
async def weight_from_profile(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    uid = data.get("_user_id") or callback.from_user.id
    user = get_user(uid)
    weight = float(user["weight_kg"]) if user and user.get("weight_kg") else None
    await _save_photo(callback, state, weight)


@router.callback_query(StateFilter(ProgressPhotos.waiting_for_weight), F.data == "pp_weight_skip")
async def weight_skipped(callback: CallbackQuery, state: FSMContext):
    await _save_photo(callback, state, None)


@router.callback_query(F.data == "pp_list")
async def list_photos(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not get_user(uid):
        await callback.answer("Сначала зарегистрируйся с помощью /register", show_alert=True)
        return
    await state.clear()
    photos = get_progress_photos(uid)
    if not photos:
        await callback.message.edit_text(
            "🖼 Пока нет ни одного фото прогресса.\n\n"
            "Нажми «📸 Добавить фото» — первое фото станет точкой отсчёта.",
            reply_markup=_photo_menu_keyboard(uid),
        )
        await callback.answer()
        return

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    for photo in photos[:3]:
        caption_parts = [f"📅 {_fmt_day(photo['taken_at'])}"]
        if photo.get("weight_kg"):
            caption_parts.append(f"⚖️ {photo['weight_kg']} кг")
        if photo.get("note"):
            caption_parts.append(photo["note"])
        try:
            await callback.message.bot.send_photo(
                chat_id=callback.message.chat.id,
                photo=photo["file_id"],
                caption=" • ".join(caption_parts),
            )
        except Exception as exc:
            logger.warning("Не удалось отправить фото прогресса %s: %s", photo.get("id"), exc)
            await callback.message.answer(f"📅 {_fmt_day(photo['taken_at'])} — фото недоступно (Telegram удалил файл).")

    lines = []
    if len(photos) > 3:
        lines.append(f"Показаны последние 3 из {len(photos)} фото.")
    dynamics = build_weight_dynamics(photos)
    if dynamics:
        lines.append(dynamics)
    if not lines:
        lines.append("Добавляй фото с весом — через пару недель здесь появится динамика.")
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=_photo_menu_keyboard(uid),
    )
