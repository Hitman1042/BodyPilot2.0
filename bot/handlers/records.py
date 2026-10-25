"""Экран личных рекордов пользователя."""

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from core.database import get_user
from core.records import get_personal_records

router = Router()


def _date(value: str | None) -> str:
    if not value:
        return ""
    parts = value[:10].split("-")
    return ".".join(reversed(parts))


def format_records(user_id: int) -> str:
    records = get_personal_records(user_id)
    weighted = [item for item in records["exercises"] if item["max_weight_kg"] is not None]
    weighted.sort(key=lambda item: item["max_weight_kg"], reverse=True)
    lines = ["🏆 <b>Личные рекорды</b>"]
    if weighted:
        lines.extend(["", "<b>Топ по весу:</b>"])
        for item in weighted[:5]:
            name = html.escape(item["name"])
            reps = f", до {item['max_reps']} повт." if item["max_reps"] else ""
            lines.append(
                f"• {name} — <b>{item['max_weight_kg']:g} кг</b>{reps} "
                f"({_date(item['max_weight_date'])})"
            )
    tonnage = records["session_tonnage"]
    duration = records["session_duration"]
    if tonnage or duration:
        lines.extend(["", "<b>Тренировки:</b>"])
        if tonnage:
            lines.append(f"• Тоннаж: <b>{tonnage['value_kg']:g} кг</b> ({_date(tonnage['date'])})")
        if duration:
            lines.append(f"• Длительность: <b>{duration['value_min']} мин</b> ({_date(duration['date'])})")
    steps = records["steps"]
    protein = records["protein"]
    if steps or protein:
        lines.extend(["", "<b>Дневная активность и питание:</b>"])
        if steps:
            lines.append(f"• Шаги: <b>{steps['value']:,}</b> ({_date(steps['date'])})".replace(",", " "))
        if protein:
            lines.append(
                f"• Белок: <b>{protein['value_g']:,.1f} г</b> ({_date(protein['date'])})".replace(",", " ")
            )
    if len(lines) == 1:
        return "🏆 Рекордов пока нет. Заверши тренировку с подходами или записывай шаги и питание."
    return "\n".join(lines)


async def _show_records(message: Message, user_id: int) -> None:
    if not get_user(user_id):
        await message.answer("Сначала зарегистрируйся с помощью /register")
        return
    await message.answer(format_records(user_id))


@router.message(Command("records"))
async def cmd_records(message: Message, user_id: int = None):
    await _show_records(message, user_id or message.from_user.id)


@router.callback_query(F.data == "records")
async def show_records(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _show_records(callback.message, callback.from_user.id)
