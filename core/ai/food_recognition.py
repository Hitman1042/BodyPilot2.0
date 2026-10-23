"""AI-распознавание еды для BodyPilot."""

import html
from typing import Optional, Dict, List
from .gemini_client import get_gemini_client
from ..nutrition_tracker import search_food, add_food_entry, add_custom_food_entry


def _to_float(value, default: float = 0.0) -> float:
    """Безопасное приведение к float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_photo_result(result: Optional[Dict]) -> Dict:
    """Нормализовать ответ Gemini vision (classify + извлечение за один вызов).

    Всегда возвращает dict с ключом photo_type:
    "dish" | "label" | "receipt" | "other" | "error".
    Старые ответы без photo_type трактуются как "dish" (обратная совместимость).
    """
    if not result:
        return {"photo_type": "error", "reason": "ошибка AI"}

    if "error" in result:
        return {
            "photo_type": "error",
            "reason": result.get("reason") or result.get("message") or str(result.get("error")),
            "rate_limit": result.get("error") == "rate_limit",
        }

    photo_type = str(result.get("photo_type") or "dish").strip().lower()
    confidence = _to_float(result.get("confidence"), 0.5)

    if photo_type == "label":
        raw = result.get("label") or {}
        label = {
            "product_name": str(raw.get("product_name") or result.get("food_name") or "").strip(),
            "brand": str(raw.get("brand") or "").strip(),
            "calories_100g": _to_float(raw.get("calories_100g")),
            "protein_100g": _to_float(raw.get("protein_100g")),
            "fat_100g": _to_float(raw.get("fat_100g")),
            "carbs_100g": _to_float(raw.get("carbs_100g")),
        }
        if label["product_name"] and label["calories_100g"] > 0:
            return {"photo_type": "label", "label": label, "confidence": confidence}
        return {"photo_type": "other", "reason": "не удалось прочитать КБЖУ на этикетке"}

    if photo_type == "receipt":
        receipt = result.get("receipt")
        raw_items = receipt.get("items") if isinstance(receipt, dict) else result.get("items")
        items = []
        for raw in raw_items or []:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            weight_g = _to_float(raw.get("weight_g"), 100.0)
            items.append({
                "name": name,
                "weight_g": weight_g if weight_g > 0 else 100.0,
                "calories": _to_float(raw.get("calories")),
                "protein_g": _to_float(raw.get("protein_g")),
                "fat_g": _to_float(raw.get("fat_g")),
                "carbs_g": _to_float(raw.get("carbs_g")),
            })
        if items:
            return {"photo_type": "receipt", "items": items, "confidence": confidence}
        return {"photo_type": "other", "reason": "не удалось прочитать позиции чека"}

    if photo_type == "other":
        return {
            "photo_type": "other",
            "reason": str(result.get("reason") or "на фото не еда").strip(),
        }

    # dish (включая старые ответы без photo_type)
    weight_g = _to_float(result.get("weight_g"), 100.0)
    return {
        "photo_type": "dish",
        "food_name": result.get("food_name", ""),
        "weight_g": weight_g if weight_g > 0 else 100.0,
        "calories": _to_float(result.get("calories")),
        "protein_g": _to_float(result.get("protein_g")),
        "fat_g": _to_float(result.get("fat_g")),
        "carbs_g": _to_float(result.get("carbs_g")),
        "meal_type": result.get("meal_type") or "snack",
        "confidence": confidence,
        "health_score": result.get("health_score"),
        "suggestions": result.get("suggestions") or [],
    }


def scale_label_to_weight(label: Dict, weight_g: float) -> Dict:
    """Пересчитать КБЖУ этикетки (на 100 г) на фактический вес порции.

    Возвращает dict в формате карточки подтверждения smart_input (smart_food).
    """
    k = weight_g / 100.0
    return {
        "food_name": label["product_name"],
        "weight_g": weight_g,
        "calories": round(label.get("calories_100g", 0) * k, 1),
        "protein_g": round(label.get("protein_100g", 0) * k, 1),
        "fat_g": round(label.get("fat_100g", 0) * k, 1),
        "carbs_g": round(label.get("carbs_100g", 0) * k, 1),
    }


async def analyze_food_photo(image_data: bytes) -> Dict:
    """Один vision-вызов: классификация фото + извлечение данных."""
    client = get_gemini_client()
    if not client:
        return {"photo_type": "error", "reason": "AI-сервис временно недоступен"}
    result = await client.recognize_food_from_photo(image_data)
    return parse_photo_result(result)


def add_recognized_dish(
        user_id: int,
        dish: Dict,
        meal_type: str = None,
        source: str = "photo",
) -> Dict:
    """Записать распознанное блюдо (photo_type="dish") в дневник.

    dish — результат parse_photo_result. Ищет продукт в базе, при отсутствии
    добавляет кастомную запись, пишет событие в историю чата.
    """
    food_name = dish.get("food_name", "")
    weight_g = dish.get("weight_g", 100)
    calories = dish.get("calories", 0)
    protein_g = dish.get("protein_g", 0)
    fat_g = dish.get("fat_g", 0)
    carbs_g = dish.get("carbs_g", 0)
    confidence = dish.get("confidence", 0.5)

    # Если meal_type не указан — берём из AI
    if not meal_type:
        meal_type = dish.get("meal_type", "snack")

    # Пытаемся найти продукт в базе
    products = search_food(food_name, limit=1)

    if products and products[0]:
        # Нашли в базе — используем данные из базы
        product = products[0]
        entry_id = add_food_entry(
            user_id=user_id,
            product_id=product["id"],
            product_name=product["name"],
            weight_g=weight_g,
            calories_100g=product["calories_100g"],
            protein_100g=product["protein_100g"],
            fat_100g=product["fat_100g"],
            carbs_100g=product["carbs_100g"],
            meal_type=meal_type,
        )

        calories = round(product["calories_100g"] * weight_g / 100, 1)
        protein_g = round(product["protein_100g"] * weight_g / 100, 1)
        fat_g = round(product["fat_100g"] * weight_g / 100, 1)
        carbs_g = round(product["carbs_100g"] * weight_g / 100, 1)
    else:
        # Не нашли в базе — добавляем как кастомный
        entry_id = add_custom_food_entry(
            user_id=user_id,
            product_name=food_name,
            weight_g=weight_g,
            calories=calories,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
            meal_type=meal_type,
        )

    # Формируем ответ
    meal_names = {
        "breakfast": "завтрак",
        "lunch": "обед",
        "dinner": "ужин",
        "snack": "перекус"
    }

    # Запоминаем событие в истории чата — чтобы следующее сообщение
    # вида «таких 2 штуки съел» попало в контекст AI-коуча
    from .chat_history import append_event
    append_event(
        user_id,
        f"[событие: записано «{food_name}», {weight_g}г, {calories} ккал, "
        f"{meal_names.get(meal_type, meal_type)}]",
    )

    message = (
        f"✅ <b>Добавлено!</b>\n\n"
        f"📷 Распознано: <b>{html.escape(str(food_name))}</b>\n"
        f"⚖️ Вес: {weight_g}г\n"
        f"🕒 Тип: {meal_names.get(meal_type, meal_type)}\n\n"
        f"📊 <b>КБЖУ:</b>\n"
        f"🔥 {calories} ккал\n"
        f"🥩 {protein_g}г белков\n"
        f"🥑 {fat_g}г жиров\n"
        f"🍞 {carbs_g}г углеводов\n"
    )

    if confidence < 0.7:
        message += f"\n⚠️ AI не уверен в распознавании ({confidence:.0%}). Проверь данные."

    if dish.get("suggestions"):
        message += f"\n\n💡 <b>Совет AI:</b> {', '.join(html.escape(str(s)) for s in dish['suggestions'][:2])}"

    return {
        "success": True,
        "food_name": food_name,
        "weight_g": weight_g,
        "calories": calories,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g,
        "entry_id": entry_id,
        "message": message,
        "confidence": confidence,
        "source": source,
    }


async def recognize_and_add_food(
        user_id: int,
        image_data: bytes = None,
        text_input: str = None,
        meal_type: str = None,
) -> Dict:
    """
    Распознать еду (фото или текст) и добавить в дневник.

    Для фото с типом label/receipt/other запись НЕ создаётся — возвращается
    {"success": False, "photo_type": ..., "parsed": ...}; интерактивные сценарии
    для этих типов реализованы в bot/handlers/ai_food.py.

    Returns:
        {
            "success": true/false,
            "food_name": "...",
            "weight_g": ...,
            "calories": ...,
            "entry_id": ... или None,
            "message": "сообщение пользователю"
        }
    """
    client = get_gemini_client()

    if not client:
        return {
            "success": False,
            "message": "❌ AI-сервис временно недоступен"
        }

    # Распознавание
    if image_data:
        parsed = await analyze_food_photo(image_data)
        source = "photo"
        if parsed["photo_type"] == "error":
            return {
                "success": False,
                "photo_type": "error",
                "message": f"❌ Не удалось распознать: {html.escape(str(parsed.get('reason', 'ошибка AI')))}",
            }
        if parsed["photo_type"] != "dish":
            return {
                "success": False,
                "photo_type": parsed["photo_type"],
                "parsed": parsed,
                "message": "❌ На фото не блюдо — используй интерактивный сценарий",
            }
        return add_recognized_dish(user_id, parsed, meal_type=meal_type, source=source)
    elif text_input:
        result = await client.recognize_food_from_text(text_input)
        source = "text"
    else:
        return {
            "success": False,
            "message": "❌ фото или текст"
        }

    if not result or "error" in result:
        reason = result.get("reason", "не распознано") if result else "ошибка AI"
        return {
            "success": False,
            "message": f"❌ Не удалось распознать: {html.escape(str(reason))}"
        }

    return add_recognized_dish(user_id, result, meal_type=meal_type, source=source)


async def get_food_suggestions(
        user_id: int,
        current_nutrition: Dict,
        targets: Dict,
) -> Optional[str]:
    """
    Получить AI-рекомендации по продуктам.
    """
    client = get_gemini_client()

    if not client:
        return None

    from datetime import datetime
    hour = datetime.now().hour

    if 6 <= hour < 11:
        time_of_day = "утро (завтрак)"
    elif 11 <= hour < 15:
        time_of_day = "день (обед)"
    elif 15 <= hour < 18:
        time_of_day = "полдник"
    else:
        time_of_day = "вечер (ужин)"

    # Определяем статус тренировки
    workout_status = "нет"  # TODO: получить из БД

    result = await client.recommend_products(
        current_nutrition=current_nutrition,
        targets=targets,
        time_of_day=time_of_day,
        workout_status=workout_status,
    )

    if not result or "error" in result:
        return None

    # Форматируем ответ
    deficiency = result.get("deficiency", "ничего")
    products = result.get("products", [])

    if not products:
        return None

    text = f"💡 <b>AI-рекомендации</b>\n\n"
    text += f"🎯 Нужно добрать: <b>{html.escape(str(deficiency))}</b>\n\n"
    text += f"<b>Что съесть:</b>\n"

    for p in products[:3]:
        text += f"• {html.escape(str(p.get('name', '?')))} — {p.get('grams', 100)}г ({p.get('calories', 0)} ккал)\n"
        text += f"  <i>{html.escape(str(p.get('reason', '')))}</i>\n"

    if result.get("timing_advice"):
        text += f"\n⏰ <b>Когда:</b> {html.escape(str(result['timing_advice']))}\n"

    if result.get("warning"):
        text += f"\n⚠️ <b>Внимание:</b> {html.escape(str(result['warning']))}\n"

    return text