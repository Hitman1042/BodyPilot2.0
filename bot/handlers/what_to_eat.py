"""«Что мне съесть?» — подбор блюд под остаток КБЖУ на сегодня.

Команда /what_to_eat, кнопка «🍳 Что съесть?» в меню еды и кнопка
«🔄 Ещё варианты». Логика подбора — core.meal_suggest (AI → фолбэк на
правила по локальной БД). Уже показанные блюда копятся в FSM-данных
(wte_exclude), чтобы «Ещё варианты» не повторялось.
"""

import html
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from core.meal_suggest import suggest_meals, MIN_REMAINING_KCAL

logger = logging.getLogger(__name__)

router = Router()


def _format_suggestions(result: dict) -> str:
    """Карточка «остаток дня + варианты блюд»."""
    remaining = result["remaining"]
    suggestions = result["suggestions"]

    lines = [
        "🍳 <b>Что съесть?</b>",
        "",
        f"Осталось сегодня: <b>{remaining['calories']} ккал</b>, "
        f"белка <b>{remaining['protein_g']:g} г</b> "
        f"(Ж {remaining['fat_g']:g} г, У {remaining['carbs_g']:g} г)",
        "",
    ]

    if not suggestions:
        if remaining["calories"] < MIN_REMAINING_KCAL:
            lines.append("Норма на сегодня почти закрыта — отличная работа! 🎉")
        else:
            lines.append("Не удалось подобрать варианты. Попробуй спросить AI-коуча 🤖")
    else:
        for i, meal in enumerate(suggestions, 1):
            lines.append(
                f"{i}. <b>{html.escape(str(meal['name']))}</b> — {meal['weight_g']:g} г\n"
                f"   {meal['calories']:g} ккал | Б {meal['protein_g']:g}г | "
                f"Ж {meal['fat_g']:g}г | У {meal['carbs_g']:g}г"
            )
        lines.append("")
        if result.get("source") == "rules":
            lines.append("<i>Подобрал из базы продуктов (AI недоступен)</i>")
        lines.append("Съел что-то из этого? Просто напиши ✍️")

    return "\n".join(lines)


def _suggest_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Ещё варианты", callback_data="wte_more")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")],
    ])


async def _build_suggestions(uid: int, state: FSMContext, refresh: bool) -> dict | None:
    """Подобрать варианты и обновить список исключений в FSM."""
    exclude = (await state.get_data()).get("wte_exclude") if refresh else None
    result = await suggest_meals(uid, exclude=exclude)
    if result is None:
        return None

    shown = [str(m["name"]) for m in result["suggestions"]]
    await state.update_data(wte_exclude=(exclude or []) + shown)
    return result


async def _send_suggestions(message: Message, uid: int, state: FSMContext, refresh: bool = False):
    result = await _build_suggestions(uid, state, refresh)
    if result is None:
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await message.answer(_format_suggestions(result), reply_markup=_suggest_keyboard())


@router.message(Command("what_to_eat"))
async def cmd_what_to_eat(message: Message, state: FSMContext, user_id: int = None):
    """Команда /what_to_eat — подбор блюд под остаток дня."""
    uid = user_id if user_id else message.from_user.id
    status = await message.answer("🍳 Подбираю варианты...")
    try:
        await _send_suggestions(message, uid, state, refresh=False)
    finally:
        try:
            await message.bot.delete_message(message.chat.id, status.message_id)
        except Exception:
            pass


@router.callback_query(F.data == "food_suggest")
async def cb_what_to_eat(callback: CallbackQuery, state: FSMContext):
    """Кнопка «🍳 Что съесть?» в меню еды."""
    logger.info("🔔 food_suggest от пользователя %d", callback.from_user.id)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _send_suggestions(callback.message, callback.from_user.id, state, refresh=False)


@router.callback_query(F.data == "wte_more")
async def cb_what_to_eat_more(callback: CallbackQuery, state: FSMContext):
    """«🔄 Ещё варианты» — новые блюда без повторов, в том же сообщении."""
    uid = callback.from_user.id
    await callback.answer("Подбираю ещё...")
    result = await _build_suggestions(uid, state, refresh=True)
    if result is None:
        await callback.message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await callback.message.edit_text(
        _format_suggestions(result), reply_markup=_suggest_keyboard()
    )
