"""AI-инструменты (Gemini function calling) для BodyPilot.

Декларации TOOL_DECLARATIONS отдаются модели в поле tools запроса
generateContent. Когда модель просит выполнить действие, GeminiClient
вызывает execute_tool(user_id, name, args) — диспетчер валидирует
аргументы и вызывает реальные core-функции. Любая ошибка возвращается
как {"error": ...} и уходит модели обратно в functionResponse, чтобы она
могла объяснить проблему пользователю.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# ДЕКЛАРАЦИИ ИНСТРУМЕНТОВ (формат Gemini functionDeclarations)
# ═══════════════════════════════════════════════════════════════

TOOL_DECLARATIONS = [
    {
        "name": "log_food",
        "description": (
            "Записать приём пищи в дневник питания пользователя. "
            "КБЖУ указывай на ВЕСЬ вес порции (weight_g), а не на 100 г. "
            "Вызывай всегда, когда пользователь сообщает, что что-то съел или выпил."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "Название продукта/блюда на русском",
                },
                "weight_g": {
                    "type": "number",
                    "description": "Вес порции в граммах (1-5000)",
                },
                "calories": {
                    "type": "number",
                    "description": "Калории на всю порцию, ккал",
                },
                "protein_g": {
                    "type": "number",
                    "description": "Белки на всю порцию, г",
                },
                "fat_g": {
                    "type": "number",
                    "description": "Жиры на всю порцию, г",
                },
                "carbs_g": {
                    "type": "number",
                    "description": "Углеводы на всю порцию, г",
                },
                "meal_type": {
                    "type": "string",
                    "enum": ["breakfast", "lunch", "dinner", "snack"],
                    "description": "Тип приёма пищи: breakfast/lunch/dinner/snack",
                },
            },
            "required": [
                "product_name", "weight_g", "calories",
                "protein_g", "fat_g", "carbs_g", "meal_type",
            ],
        },
    },
    {
        "name": "log_food_batch",
        "description": (
            "Записать НЕСКОЛЬКО блюд/приёмов пищи в дневник питания одним вызовом "
            "(например, пользователь перечислил всё, что съел за день). "
            "Максимум 10 позиций. КБЖУ каждой позиции указывай на ВЕСЬ вес порции. "
            "Вызывай, когда в сообщении больше одного блюда; для одного блюда — log_food."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "Позиции еды (1-10), каждая — как аргументы log_food",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_name": {
                                "type": "string",
                                "description": "Название продукта/блюда на русском",
                            },
                            "weight_g": {
                                "type": "number",
                                "description": "Вес порции в граммах (1-5000)",
                            },
                            "calories": {
                                "type": "number",
                                "description": "Калории на всю порцию, ккал",
                            },
                            "protein_g": {
                                "type": "number",
                                "description": "Белки на всю порцию, г",
                            },
                            "fat_g": {
                                "type": "number",
                                "description": "Жиры на всю порцию, г",
                            },
                            "carbs_g": {
                                "type": "number",
                                "description": "Углеводы на всю порцию, г",
                            },
                            "meal_type": {
                                "type": "string",
                                "enum": ["breakfast", "lunch", "dinner", "snack"],
                                "description": "Тип приёма пищи: breakfast/lunch/dinner/snack",
                            },
                        },
                        "required": [
                            "product_name", "weight_g", "calories",
                            "protein_g", "fat_g", "carbs_g", "meal_type",
                        ],
                    },
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "adjust_last_food_entry",
        "description": (
            "Скорректировать ПОСЛЕДНЮЮ запись еды пользователя за сегодня: "
            "умножить вес и КБЖУ на multiplier (например 2.0 для «съел 2 штуки») "
            "или задать новый вес new_weight_g с пропорциональным пересчётом. "
            "Вызывай, когда пользователь уточняет количество/вес недавно записанной еды."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "multiplier": {
                    "type": "number",
                    "description": "Множитель порции (0.1-10), напр. 2.0 для «2 штуки»",
                },
                "new_weight_g": {
                    "type": "number",
                    "description": "Новый вес порции в граммах (1-5000), КБЖУ пересчитаются пропорционально",
                },
            },
        },
    },
    {
        "name": "delete_food_entry",
        "description": (
            "Удалить запись еды из дневника пользователя. "
            "Вызывай при «удали», «отмени», «не то записал», «убери из дневника». "
            "Если product_name не указан — удаляет ПОСЛЕДНЮЮ запись за сегодня. "
            "НИКОГДА не говори «удалил/отменено» без вызова этого инструмента."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "Название продукта/блюда (или его часть) для поиска за сегодня; пусто = последняя запись",
                },
            },
        },
    },
    {
        "name": "delete_workout_session",
        "description": (
            "Удалить последнюю тренировку пользователя (или за указанную дату). "
            "Вызывай при «удали тренировку», «отмени тренировку», "
            "«тренировка записана неправильно»."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Дата сессии: 'yesterday' или 'YYYY-MM-DD'; пусто = последняя",
                },
            },
        },
    },
    {
        "name": "delete_health_metric",
        "description": (
            "Удалить ручную метрику здоровья за день (сон, шаги, пульс покоя, вес-метрику). "
            "Вызывай при «удали сон», «удали шаги за вчера», «обнули шаги»."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "metric_type": {
                    "type": "string",
                    "enum": ["steps", "sleep_hours", "resting_heart_rate", "weight"],
                    "description": "Тип метрики для удаления",
                },
                "date": {
                    "type": "string",
                    "description": "Дата: 'yesterday' или 'YYYY-MM-DD'; пусто = сегодня",
                },
            },
            "required": ["metric_type"],
        },
    },
    {
        "name": "log_water",
        "description": "Записать выпитую воду в миллилитрах (например «выпил 2 стакана воды» → 500).",
        "parameters": {
            "type": "object",
            "properties": {
                "amount_ml": {
                    "type": "integer",
                    "description": "Количество воды в мл (1-5000)",
                },
            },
            "required": ["amount_ml"],
        },
    },
    {
        "name": "join_challenge",
        "description": "Вступить в челлендж: food_30 (30 дней дневника), workout_12 (12 тренировок за 30 дней), calorie_week (7 дней в норме калорий).",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "enum": ["food_30", "workout_12", "calorie_week"],
                    "description": "Код челленджа",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_today_nutrition",
        "description": (
            "Получить сводку питания за сегодня (съедено калорий/БЖУ, "
            "количество приёмов пищи) и дневные нормы пользователя. "
            "Используй для вопросов вида «сколько я сегодня съел»."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_nutrition_history",
        "description": "Получить КБЖУ по дням за последние N дней (максимум 14).",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Количество дней истории (1-14)",
                },
            },
            "required": ["days"],
        },
    },
    {
        "name": "log_weight",
        "description": (
            "Записать текущий вес пользователя в дневник веса и обновить профиль. "
            "Вызывай только когда пользователь явно сообщает свой вес для записи."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "weight_kg": {
                    "type": "number",
                    "description": "Вес в килограммах (20-400)",
                },
            },
            "required": ["weight_kg"],
        },
    },
    {
        "name": "log_health_metric",
        "description": (
            "Записать или обновить метрику здоровья: шаги, сон, пульс покоя или вес-метрику. "
            "Для «вчера» передай date='yesterday', для другой даты — YYYY-MM-DD. "
            "Для текущего веса профиля используй log_weight."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "metric_type": {
                    "type": "string",
                    "enum": ["steps", "sleep_hours", "resting_heart_rate", "weight"],
                },
                "value": {"type": "number"},
                "date": {
                    "type": "string",
                    "description": "Необязательно: yesterday или YYYY-MM-DD",
                },
            },
            "required": ["metric_type", "value"],
        },
    },
    {
        "name": "update_profile",
        "description": (
            "Изменить одно поле профиля пользователя. Разрешённые поля: "
            "goal (цель: lose/maintain/gain), activity (активность: "
            "sedentary/moderate/high), weight_kg, height_cm, age. "
            "Вызывай только когда пользователь явно просит изменить данные."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "enum": ["goal", "activity", "weight_kg", "height_cm", "age"],
                    "description": "Поле профиля",
                },
                "value": {
                    "type": "string",
                    "description": (
                        "Новое значение: для goal — lose/maintain/gain, "
                        "для activity — sedentary/moderate/high, "
                        "для остальных — число строкой"
                    ),
                },
            },
            "required": ["field", "value"],
        },
    },
    {
        "name": "get_workout_plan_today",
        "description": "Получить план тренировки пользователя на сегодня (только чтение).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "log_workout_done",
        "description": (
            "Записать ВЫПОЛНЕННУЮ тренировку, о которой отчитался пользователь "
            "(«сделал тренировку: 3 подхода приседаний и отжимания», «пробежал 5 км»). "
            "Вызывай всегда, когда пользователь сообщает о факте тренировки. "
            "Запись учитывается в стриках, челленджах и статистике."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "duration_min": {
                    "type": "integer",
                    "description": "Длительность тренировки в минутах (1-600); если не указана — оцени сам",
                },
                "description": {
                    "type": "string",
                    "description": "Краткое описание тренировки на русском (например, «приседания и отжимания»)",
                },
                "exercises": {
                    "type": "array",
                    "description": "Упражнения свободным текстом (опционально)",
                    "items": {"type": "string"},
                },
                "workout_type": {
                    "type": "string",
                    "enum": ["strength", "cardio", "hiit", "yoga", "stretching"],
                    "description": "Тип тренировки; по умолчанию strength",
                },
            },
            "required": ["duration_min", "description"],
        },
    },
    {
        "name": "get_weekly_stats",
        "description": "Получить статистику пользователя за последние 7 дней (калории, белок, тренировки, вес, тоннаж).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "set_training_preferences",
        "description": (
            "Сохранить условия тренировок пользователя (место: дома/зал/улица, "
            "инвентарь, частота, длительность) и СРАЗУ перегенерировать план "
            "тренировки на сегодня с их учётом. Вызывай ВСЕГДА, когда пользователь "
            "просит изменить формат/условия тренировок («хочу дома без инвентаря», "
            "«у меня только гантели», «тренируюсь 3 раза в неделю по 40 минут»)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "training_place": {
                    "type": "string",
                    "enum": ["home", "gym", "outdoor"],
                    "description": "Где тренируется: home (дома) / gym (зал) / outdoor (улица)",
                },
                "equipment": {
                    "type": "string",
                    "description": "Инвентарь свободным текстом: «без инвентаря», «гантели 5 кг», «турник»",
                },
                "workouts_per_week": {
                    "type": "integer",
                    "description": "Сколько тренировок в неделю (1-7)",
                },
                "workout_duration_min": {
                    "type": "integer",
                    "description": "Желаемая длительность тренировки в минутах (10-180)",
                },
            },
        },
    },
    {
        "name": "regenerate_workout_plan",
        "description": (
            "Перегенерировать план тренировки на сегодня с текущими сохранёнными "
            "предпочтениями. Вызывай, когда пользователь просит просто обновить/"
            "пересобрать план тренировки без изменения условий."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "set_health_condition",
        "description": (
            "Сохранить или снять ограничение здоровья и СРАЗУ перегенерировать "
            "план тренировки с безопасными упражнениями. Вызывай при сообщениях "
            "о боли/травме, хроническом заболевании, беременности или возрасте 60+."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "condition_code": {
                    "type": "string",
                    "description": "Код из справочника health_conditions, например knee_pain",
                },
                "severity": {
                    "type": "integer",
                    "description": "Тяжесть по оценке пользователя: 1-3",
                },
                "active": {
                    "type": "boolean",
                    "description": "true — учитывать ограничение, false — снять его",
                },
            },
            "required": ["condition_code"],
        },
    },
    {
        "name": "set_food_preferences",
        "description": (
            "Сохранить пищевые предпочтения пользователя (нелюбимые продукты, "
            "особенности диеты) и СРАЗУ перегенерировать план питания на сегодня "
            "без исключённых продуктов. Вызывай ВСЕГДА, когда пользователь говорит, "
            "что что-то не ест / не любит / исключает («не ем рыбу», «я вегетарианец»)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "food_exclusions": {
                    "type": "string",
                    "description": "Продукты-исключения через запятую: «рыба, творог»",
                },
                "food_notes": {
                    "type": "string",
                    "description": "Особенности питания свободным текстом: «вегетарианец», «без лактозы»",
                },
            },
        },
    },
    {
        "name": "regenerate_meal_plan",
        "description": (
            "Перегенерировать план питания на сегодня с текущими сохранёнными "
            "предпочтениями. Вызывай, когда пользователь просит просто обновить "
            "план питания без изменения предпочтений."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]

# ═══════════════════════════════════════════════════════════════
# КОНСТАНТЫ ВАЛИДАЦИИ
# ═══════════════════════════════════════════════════════════════

MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}
MEAL_NAMES_RU = {
    "breakfast": "завтрак",
    "lunch": "обед",
    "dinner": "ужин",
    "snack": "перекус",
}

UPDATE_PROFILE_FIELDS = {"goal", "activity", "weight_kg", "height_cm", "age", "allergies", "city", "preferred_time", "timezone_offset", "sport"}
GOAL_VALUES = {"lose", "maintain", "gain"}
ACTIVITY_VALUES = {"sedentary", "moderate", "high"}

TRAINING_PLACES = {"home", "gym", "outdoor"}
# Синонимы на случай, если модель пришлёт значение не из enum
_TRAINING_PLACE_SYNONYMS = {
    "дома": "home", "дом": "home", "домашние": "home", "home": "home",
    "зал": "gym", "тренажерный зал": "gym", "тренажёрный зал": "gym", "gym": "gym",
    "улица": "outdoor", "на улице": "outdoor", "парк": "outdoor", "outdoor": "outdoor",
}

# Синонимы на случай, если модель пришлёт значение не из enum
_GOAL_SYNONYMS = {
    "похудение": "lose", "похудеть": "lose", "снижение": "lose",
    "набор": "gain", "масса": "gain", "набор массы": "gain",
    "поддержание": "maintain", "поддержка": "maintain",
}
_ACTIVITY_SYNONYMS = {
    "low": "sedentary", "низкая": "sedentary",
    "light": "moderate", "средняя": "moderate",
    "active": "high", "very_active": "high", "высокая": "high",
}


# ═══════════════════════════════════════════════════════════════
# ХЕЛПЕРЫ
# ═══════════════════════════════════════════════════════════════

def _to_float(value: Any) -> float | None:
    """Привести значение к float (модель может прислать строку)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════
# РЕАЛИЗАЦИИ ИНСТРУМЕНТОВ
# ═══════════════════════════════════════════════════════════════

def _tool_log_food(user_id: int, args: Dict) -> Dict:
    from core.nutrition_tracker import add_custom_food_entry

    product_name = str(args.get("product_name") or "").strip()
    if not product_name:
        return {"error": "не указано название продукта"}

    weight_g = _to_float(args.get("weight_g"))
    if weight_g is None or not (1 <= weight_g <= 5000):
        return {"error": "вес порции должен быть от 1 до 5000 г"}

    calories = _to_float(args.get("calories"))
    protein_g = _to_float(args.get("protein_g"))
    fat_g = _to_float(args.get("fat_g"))
    carbs_g = _to_float(args.get("carbs_g"))

    if calories is None or not (0 <= calories <= 5000):
        return {"error": "калории должны быть от 0 до 5000 ккал"}
    for label, val in (("белки", protein_g), ("жиры", fat_g), ("углеводы", carbs_g)):
        if val is None or not (0 <= val <= weight_g):
            return {"error": f"{label} должны быть от 0 до {weight_g} г"}

    meal_type = str(args.get("meal_type") or "").strip().lower()
    if meal_type not in MEAL_TYPES:
        return {"error": "meal_type должен быть breakfast/lunch/dinner/snack"}

    entry_id = add_custom_food_entry(
        user_id=user_id,
        product_name=product_name,
        weight_g=weight_g,
        calories=calories,
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
        meal_type=meal_type,
    )

    from core.ai.chat_history import append_event
    append_event(
        user_id,
        f"[событие: записано «{product_name}», {weight_g:g}г, "
        f"{calories:g} ккал, {MEAL_NAMES_RU[meal_type]}]",
    )

    return {
        "ok": True,
        "entry_id": entry_id,
        "product_name": product_name,
        "weight_g": weight_g,
        "calories": calories,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g,
        "meal_type": meal_type,
        "summary": (
            f"Записал: {product_name}, {weight_g:g} г — {calories:g} ккал "
            f"(Б {protein_g:g} / Ж {fat_g:g} / У {carbs_g:g}), "
            f"{MEAL_NAMES_RU[meal_type]}"
        ),
    }


LOG_FOOD_BATCH_MAX_ITEMS = 10


def _tool_log_food_batch(user_id: int, args: Dict) -> Dict:
    """Записать несколько блюд за раз: каждую позицию — через логику log_food.

    Невалидные позиции отклоняются по одной (их ошибки возвращаются модели),
    остальные записываются. Полный провал = ни одной записи.
    """
    items = args.get("items")
    if not isinstance(items, list) or not items:
        return {"error": "items должен быть непустым массивом позиций"}
    if len(items) > LOG_FOOD_BATCH_MAX_ITEMS:
        return {"error": f"слишком много позиций: {len(items)} (максимум {LOG_FOOD_BATCH_MAX_ITEMS})"}

    logged: list[Dict] = []
    rejected: list[str] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            rejected.append(f"позиция {idx}: не объект")
            continue
        result = _tool_log_food(user_id, item)
        if "error" in result:
            name = str(item.get("product_name") or "").strip() or f"позиция {idx}"
            rejected.append(f"«{name}»: {result['error']}")
        else:
            logged.append(result)

    if not logged:
        return {"error": "ни одна позиция не записана: " + "; ".join(rejected)}

    total_calories = round(sum(r["calories"] for r in logged), 1)
    names = [r["product_name"] for r in logged]
    names_text = ", ".join(names[:3])
    if len(names) > 3:
        names_text += ", …"

    summary = (
        f"Записал {len(logged)} приёмов пищи: {names_text} — всего {total_calories:g} ккал"
    )
    if rejected:
        summary += f". Не записано ({len(rejected)}): " + "; ".join(rejected)

    return {
        "ok": True,
        "logged_count": len(logged),
        "entry_ids": [r["entry_id"] for r in logged],
        "total_calories": total_calories,
        "rejected": rejected,
        "summary": summary,
    }


def _tool_adjust_last_food_entry(user_id: int, args: Dict) -> Dict:
    from datetime import date
    from core.database import get_db

    multiplier = _to_float(args.get("multiplier"))
    new_weight_g = _to_float(args.get("new_weight_g"))

    if multiplier is None and new_weight_g is None:
        return {"error": "укажи multiplier или new_weight_g"}
    if multiplier is not None and not (0.1 <= multiplier <= 10):
        return {"error": "multiplier должен быть от 0.1 до 10"}
    if new_weight_g is not None and not (1 <= new_weight_g <= 5000):
        return {"error": "new_weight_g должен быть от 1 до 5000 г"}

    conn = get_db()
    from core.nutrition_tracker import _local_today, _day_expr
    row = conn.execute(
        f"""SELECT * FROM food_log_new
           WHERE user_id = ? AND {_day_expr(user_id)} = ?
           ORDER BY logged_at DESC, id DESC LIMIT 1""",
        (user_id, _local_today(user_id)),
    ).fetchone()
    if not row:
        return {
            "error": (
                "сегодня ещё нет записей еды — если пользователь называет "
                "новый продукт, запиши его через log_food"
            )
        }

    old_weight = float(row["weight_g"] or 0)
    if old_weight <= 0:
        return {"error": "у последней записи некорректный вес, скорректировать нельзя"}

    if new_weight_g is not None:
        factor = new_weight_g / old_weight
        final_weight = new_weight_g
    else:
        factor = multiplier
        final_weight = old_weight * multiplier

    new_calories = round(float(row["calories"] or 0) * factor, 1)
    new_protein = round(float(row["protein_g"] or 0) * factor, 1)
    new_fat = round(float(row["fat_g"] or 0) * factor, 1)
    new_carbs = round(float(row["carbs_g"] or 0) * factor, 1)

    conn.execute(
        """UPDATE food_log_new
           SET weight_g = ?, calories = ?, protein_g = ?, fat_g = ?, carbs_g = ?
           WHERE id = ? AND user_id = ?""",
        (round(final_weight, 1), new_calories, new_protein, new_fat, new_carbs,
         row["id"], user_id),
    )
    conn.commit()

    name = row["product_name"]
    from core.ai.chat_history import append_event
    append_event(
        user_id,
        f"[событие: обновлено «{name}» ×{factor:g} — {final_weight:g}г, "
        f"{new_calories:g} ккал]",
    )

    return {
        "ok": True,
        "entry_id": row["id"],
        "product_name": name,
        "factor": round(factor, 3),
        "weight_g": round(final_weight, 1),
        "calories": new_calories,
        "protein_g": new_protein,
        "fat_g": new_fat,
        "carbs_g": new_carbs,
        "summary": f"Обновил: {name} ×{factor:g} — {new_calories:g} ккал",
    }


def _tool_get_today_nutrition(user_id: int, args: Dict) -> Dict:
    from core.nutrition_tracker import get_today_summary
    from core.nutrition_calc import get_nutrition_plan

    summary = get_today_summary(user_id)
    plan = get_nutrition_plan(user_id) or {}
    macros = plan.get("macros") or {}

    return {
        "ok": True,
        "date": summary.get("date"),
        "eaten": {
            "calories": summary.get("total_calories", 0),
            "protein_g": summary.get("total_protein_g", 0),
            "fat_g": summary.get("total_fat_g", 0),
            "carbs_g": summary.get("total_carbs_g", 0),
            "meals_count": summary.get("meals_count", 0),
            "by_meal_kcal": {
                "breakfast": summary.get("breakfast_calories", 0),
                "lunch": summary.get("lunch_calories", 0),
                "dinner": summary.get("dinner_calories", 0),
                "snack": summary.get("snack_calories", 0),
            },
        },
        "targets": {
            "calories": plan.get("target_calories"),
            "protein_g": macros.get("protein_g"),
            "fat_g": macros.get("fat_g"),
            "carbs_g": macros.get("carbs_g"),
        },
    }


def _tool_get_nutrition_history(user_id: int, args: Dict) -> Dict:
    from core.nutrition_tracker import get_nutrition_history

    days = _to_int(args.get("days"))
    if days is None or not (1 <= days <= 14):
        return {"error": "days должен быть от 1 до 14"}

    history = get_nutrition_history(user_id, days=days)
    return {"ok": True, "days": days, "history": history}


def _tool_log_weight(user_id: int, args: Dict) -> Dict:
    from core.database import log_weight, update_user

    weight_kg = _to_float(args.get("weight_kg"))
    if weight_kg is None or not (20 <= weight_kg <= 400):
        return {"error": "вес должен быть от 20 до 400 кг"}

    entry_id = log_weight(user_id, weight_kg)
    # Обновляем вес и в профиле, чтобы нормы питания пересчитались
    update_user(user_id, weight_kg=weight_kg)

    return {
        "ok": True,
        "entry_id": entry_id,
        "weight_kg": weight_kg,
        "summary": f"Записал вес: {weight_kg:g} кг",
    }


HEALTH_METRIC_RULES = {
    "steps": (1, 100000, "шаги"),
    "sleep_hours": (0.5, 24, "сон"),
    "resting_heart_rate": (30, 220, "пульс покоя"),
    "weight": (20, 400, "вес"),
}


def _tool_log_health_metric(user_id: int, args: Dict) -> Dict:
    from datetime import date, datetime, timedelta, timezone

    from core.database import get_user
    from core.health_data import _local_today, local_noon_utc, replace_manual_metric

    metric_type = str(args.get("metric_type") or "").strip().lower()
    if metric_type not in HEALTH_METRIC_RULES:
        return {"error": "metric_type должен быть steps/sleep_hours/resting_heart_rate/weight"}

    minimum, maximum, label = HEALTH_METRIC_RULES[metric_type]
    value = _to_float(args.get("value"))
    if value is None or not (minimum <= value <= maximum):
        return {"error": f"value для {metric_type} должен быть от {minimum:g} до {maximum:g}"}

    user = get_user(user_id)
    if not user:
        return {"error": "пользователь не найден"}
    offset = int(user.get("timezone_offset") or 0)
    raw_date = args.get("date")
    target_date = None
    if raw_date is not None and str(raw_date).strip():
        date_text = str(raw_date).strip().lower()
        if date_text == "yesterday":
            target_date = _local_today(offset) - timedelta(days=1)
        else:
            try:
                target_date = date.fromisoformat(date_text)
            except ValueError:
                return {"error": "date должен быть yesterday или YYYY-MM-DD"}

    ts = local_noon_utc(user_id, target_date) if target_date else datetime.now(timezone.utc)
    replace_manual_metric(user_id, metric_type, value, source="chat", ts=ts)

    if metric_type == "steps":
        value_text = f"{int(round(value)):,}".replace(",", " ")
    else:
        value_text = f"{value:g}"
    units = {"steps": "", "sleep_hours": " ч", "resting_heart_rate": " уд/мин", "weight": " кг"}
    if target_date == _local_today(offset) - timedelta(days=1):
        date_text = " за вчера"
    elif target_date:
        date_text = f" за {target_date.isoformat()}"
    else:
        date_text = ""
    action = "Обновил" if target_date else "Записал"
    summary = f"{action} {label}{date_text}: {value_text}{units[metric_type]}"

    from core.ai.chat_history import append_event
    append_event(user_id, f"[событие: {summary}]")
    return {
        "ok": True,
        "metric_type": metric_type,
        "value": value,
        "date": target_date.isoformat() if target_date else None,
        "summary": summary,
    }


def _tool_update_profile(user_id: int, args: Dict) -> Dict:
    from core.database import update_user

    field = str(args.get("field") or "").strip()
    if field not in UPDATE_PROFILE_FIELDS:
        return {
            "error": (
                f"поле «{field}» изменять нельзя; разрешены: "
                + ", ".join(sorted(UPDATE_PROFILE_FIELDS))
            )
        }

    raw_value = args.get("value")
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        return {"error": "не указано значение"}

    if field == "goal":
        value = str(raw_value).strip().lower()
        value = _GOAL_SYNONYMS.get(value, value)
        if value not in GOAL_VALUES:
            return {"error": "goal должен быть lose/maintain/gain"}
    elif field == "activity":
        value = str(raw_value).strip().lower()
        value = _ACTIVITY_SYNONYMS.get(value, value)
        if value not in ACTIVITY_VALUES:
            return {"error": "activity должен быть sedentary/moderate/high"}
    elif field == "weight_kg":
        value = _to_float(raw_value)
        if value is None or not (20 <= value <= 400):
            return {"error": "weight_kg должен быть от 20 до 400"}
    elif field == "height_cm":
        value = _to_float(raw_value)
        if value is None or not (100 <= value <= 250):
            return {"error": "height_cm должен быть от 100 до 250"}
    elif field == "allergies":
        value = str(raw_value).strip()[:300]
    elif field == "city":
        value = str(raw_value).strip()[:100]
    elif field == "preferred_time":
        import re
        value = str(raw_value).strip()
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            return {"error": "preferred_time должен быть в формате HH:MM, например 07:00"}
    elif field == "timezone_offset":
        value = _to_int(raw_value)
        if value is None or not (-720 <= value <= 840):
            return {"error": "timezone_offset должен быть минутами от UTC, например 180 для UTC+3"}
    elif field == "sport":
        from core.sports.catalog import get_all_sports, set_user_sport
        query = str(raw_value).strip().lower()
        for sport in get_all_sports():
            names = (str(sport.get("name_en", "")).lower(), str(sport.get("name_ru", "")).lower())
            if query in names or any(query in n for n in names if n):
                if set_user_sport(user_id, sport["id"]):
                    return {"ok": True, "field": field, "value": sport["id"],
                            "summary": f"Обновил спорт: {sport.get('name_ru') or sport.get('name_en')}"}
                return {"error": "не удалось обновить спорт"}
        return {"error": f"не знаю вид спорта «{raw_value}»"}
    else:  # age
        value = _to_int(raw_value)
        if value is None or not (10 <= value <= 100):
            return {"error": "age должен быть от 10 до 100"}

    updated = update_user(user_id, **{field: value})
    if not updated:
        return {"error": "не удалось обновить профиль"}

    return {
        "ok": True,
        "field": field,
        "value": value,
        "summary": f"Обновил профиль: {field} = {value}",
    }


def _tool_get_workout_plan_today(user_id: int, args: Dict) -> Dict:
    from core.training_service import get_daily_plan

    plan = get_daily_plan(user_id)
    if not plan:
        return {"ok": True, "plan": None, "message": "На сегодня плана тренировки нет"}

    exercises = [
        {
            "name": ex.get("name"),
            "muscle_group": ex.get("muscle_group"),
            "sets": ex.get("sets"),
            "reps": ex.get("reps"),
        }
        for ex in plan.get("exercises", [])
    ]

    return {
        "ok": True,
        "plan": {
            "date": plan.get("date"),
            "focus": plan.get("focus") or plan.get("title") or plan.get("notes"),
            "exercises": exercises,
        },
    }


def _tool_get_weekly_stats(user_id: int, args: Dict) -> Dict:
    from core.database.stats import get_weekly_stats

    stats = get_weekly_stats(user_id)
    return {"ok": True, "stats": stats}


WORKOUT_TYPES = {"strength", "cardio", "hiit", "yoga", "stretching"}
# Синонимы на случай, если модель пришлёт значение не из enum
_WORKOUT_TYPE_SYNONYMS = {
    "силовая": "strength", "сила": "strength", "strength": "strength",
    "кардио": "cardio", "бег": "cardio", "cardio": "cardio",
    "hiit": "hiit", "вит": "hiit",
    "йога": "yoga", "yoga": "yoga",
    "растяжка": "stretching", "stretching": "stretching",
}
WORKOUT_TYPE_NAMES_RU = {
    "strength": "силовая",
    "cardio": "кардио",
    "hiit": "HIIT",
    "yoga": "йога",
    "stretching": "растяжка",
}


def _tool_log_workout_done(user_id: int, args: Dict) -> Dict:
    """Записать выполненную тренировку в workout_sessions.

    Схема: type ограничен CHECK ('strength','cardio','hiit','yoga','stretching')
    — 'custom' невозможен, поэтому описание храним в notes. Запись через
    create_session подхватывается стриками/челленджами/статистикой автоматически.
    """
    from core.database.workout import create_session

    duration_min = _to_int(args.get("duration_min"))
    if duration_min is None or not (1 <= duration_min <= 600):
        return {"error": "duration_min должен быть от 1 до 600 минут"}

    description = str(args.get("description") or "").strip()
    if not description:
        return {"error": "не указано описание тренировки"}
    if len(description) > 500:
        return {"error": "description слишком длинный (макс 500 символов)"}

    exercises = args.get("exercises")
    exercise_names: list[str] = []
    if exercises is not None:
        if not isinstance(exercises, list):
            return {"error": "exercises должен быть массивом строк"}
        exercise_names = [str(e).strip() for e in exercises if str(e).strip()][:20]

    workout_type = str(args.get("workout_type") or "strength").strip().lower()
    workout_type = _WORKOUT_TYPE_SYNONYMS.get(workout_type, workout_type)
    if workout_type not in WORKOUT_TYPES:
        return {"error": "workout_type должен быть strength/cardio/hiit/yoga/stretching"}

    notes = description
    if exercise_names:
        notes += ": " + ", ".join(exercise_names)

    session_id = create_session(
        user_id=user_id,
        session_type=workout_type,
        duration_min=duration_min,
        notes=notes,
    )

    from core.ai.chat_history import append_event
    append_event(
        user_id,
        f"[событие: тренировка записана — {WORKOUT_TYPE_NAMES_RU[workout_type]}, "
        f"{duration_min} мин: {notes[:150]}]",
    )

    return {
        "ok": True,
        "session_id": session_id,
        "workout_type": workout_type,
        "duration_min": duration_min,
        "description": description,
        "exercises": exercise_names,
        "summary": (
            f"Записал тренировку: {duration_min} мин ({WORKOUT_TYPE_NAMES_RU[workout_type]}) — "
            f"{description[:100]}"
        ),
    }


# ── Предпочтения и перегенерация планов ──────────────────────────────────

def _invalidate_meal_plan_cache(user_id: int) -> None:
    """Сбросить in-memory кэш плана питания API (best-effort, тот же процесс)."""
    try:
        from api.routers.plans import _meal_plan_cache

        for key in [k for k in _meal_plan_cache if k[0] == user_id]:
            _meal_plan_cache.pop(key, None)
    except Exception:
        pass


def _build_meal_plan(user_id: int, refresh: bool = True) -> Dict | None:
    """Сгенерировать план питания; None, если профиль не заполнен."""
    from core.database import get_user
    from core.plans import generate_meal_plan

    user = get_user(user_id)
    if not user:
        return None
    required = ("weight_kg", "height_cm", "age", "gender", "activity", "goal")
    if any(not user.get(f) for f in required):
        return None
    return generate_meal_plan({**user, "user_id": user_id}, refresh=refresh)


def _tool_set_training_preferences(user_id: int, args: Dict) -> Dict:
    from core.preferences import set_preferences, describe_preferences

    fields: Dict = {}

    raw_place = args.get("training_place")
    if raw_place is not None and str(raw_place).strip():
        place = str(raw_place).strip().lower()
        place = _TRAINING_PLACE_SYNONYMS.get(place, place)
        if place not in TRAINING_PLACES:
            return {"error": "training_place должен быть home/gym/outdoor"}
        fields["training_place"] = place

    equipment = args.get("equipment")
    if equipment is not None and str(equipment).strip():
        equipment = str(equipment).strip()
        if len(equipment) > 200:
            return {"error": "equipment слишком длинный (макс 200 символов)"}
        fields["equipment"] = equipment

    wpw = args.get("workouts_per_week")
    if wpw is not None:
        wpw = _to_int(wpw)
        if wpw is None or not (1 <= wpw <= 7):
            return {"error": "workouts_per_week должен быть от 1 до 7"}
        fields["workouts_per_week"] = wpw

    wdm = args.get("workout_duration_min")
    if wdm is not None:
        wdm = _to_int(wdm)
        if wdm is None or not (10 <= wdm <= 180):
            return {"error": "workout_duration_min должен быть от 10 до 180"}
        fields["workout_duration_min"] = wdm

    if not fields:
        return {"error": "укажи хотя бы одну настройку тренировок"}

    prefs = set_preferences(user_id, **fields)

    from core.training_service import generate_daily_workout_plan
    plan = generate_daily_workout_plan(user_id, force_refresh=True)
    exercises_count = len(plan.get("exercises") or []) if plan else 0

    from core.ai.chat_history import append_event
    append_event(
        user_id,
        f"[событие: настройки тренировок — {describe_preferences(prefs)}; "
        f"план на сегодня перестроен]",
    )

    description = describe_preferences(prefs) or "обновлены"
    return {
        "ok": True,
        "preferences": {k: prefs[k] for k in (
            "training_place", "equipment", "workouts_per_week", "workout_duration_min")},
        "plan_exercises": exercises_count,
        "summary": (
            f"Настройки тренировок обновлены: {description}. "
            f"План на сегодня перестроен ({exercises_count} упражнений)"
        ),
    }


def _tool_regenerate_workout_plan(user_id: int, args: Dict) -> Dict:
    from core.training_service import generate_daily_workout_plan

    plan = generate_daily_workout_plan(user_id, force_refresh=True)
    exercises_count = len(plan.get("exercises") or []) if plan else 0
    if not exercises_count:
        return {"error": "не удалось перегенерировать план (нет упражнений в базе)"}

    from core.ai.chat_history import append_event
    append_event(user_id, "[событие: план тренировки на сегодня перегенерирован]")

    return {
        "ok": True,
        "plan_exercises": exercises_count,
        "summary": f"План тренировки на сегодня обновлён ({exercises_count} упражнений)",
    }


def _tool_set_health_condition(user_id: int, args: Dict) -> Dict:
    from core.database import get_db
    from core.safety import (
        HEALTH_CONDITION_CODES_TEXT,
        MEDICAL_DISCLAIMER,
        get_condition,
    )

    condition_code = str(args.get("condition_code") or "").strip().lower()
    condition = get_condition(condition_code)
    if not condition:
        return {"error": f"неизвестный condition_code; доступны: {HEALTH_CONDITION_CODES_TEXT}"}

    severity = _to_int(args.get("severity", 1))
    if severity is None or not (1 <= severity <= 3):
        return {"error": "severity должен быть от 1 до 3"}

    raw_active = args.get("active", True)
    if isinstance(raw_active, str):
        normalized = raw_active.strip().lower()
        if normalized in ("true", "1", "yes"):
            active = True
        elif normalized in ("false", "0", "no"):
            active = False
        else:
            return {"error": "active должен быть true/false"}
    elif isinstance(raw_active, bool) or raw_active in (0, 1):
        active = bool(raw_active)
    else:
        return {"error": "active должен быть true/false"}

    conn = get_db()
    previous = conn.execute(
        """SELECT is_active FROM user_health_conditions
           WHERE user_id = ? AND condition_code = ?""",
        (user_id, condition_code),
    ).fetchone()
    show_disclaimer = active and (not previous or not previous["is_active"])
    conn.execute(
        """INSERT INTO user_health_conditions
           (user_id, condition_code, severity, notes, is_active, updated_at)
           VALUES (?, ?, ?, '', ?, datetime('now'))
           ON CONFLICT(user_id, condition_code) DO UPDATE SET
               severity = excluded.severity,
               is_active = excluded.is_active,
               updated_at = excluded.updated_at""",
        (user_id, condition_code, severity, int(active)),
    )
    conn.commit()

    from core.training_service import generate_daily_workout_plan

    plan = generate_daily_workout_plan(user_id, force_refresh=True)
    exercises_count = len(plan.get("exercises") or []) if plan else 0
    name = condition["name_ru"]
    if active:
        if condition_code == "knee_pain":
            effect = "без приседаний и выпадов"
        else:
            effect = "с учётом ограничений"
        summary = f"Учту: {name.lower()} — план перестроен {effect}"
    else:
        summary = f"Ограничение «{name.lower()}» снято — план перестроен"
    if show_disclaimer:
        summary += f". {MEDICAL_DISCLAIMER}"

    from core.ai.chat_history import append_event

    append_event(user_id, f"[событие: {summary}]")
    result = {
        "ok": True,
        "condition_code": condition_code,
        "severity": severity,
        "active": active,
        "plan_exercises": exercises_count,
        "summary": summary,
    }
    if show_disclaimer:
        result["disclaimer"] = MEDICAL_DISCLAIMER
    return result


def _tool_set_food_preferences(user_id: int, args: Dict) -> Dict:
    from core.preferences import set_preferences

    fields: Dict = {}
    for key, limit in (("food_exclusions", 300), ("food_notes", 300)):
        value = args.get(key)
        if value is not None and str(value).strip():
            value = str(value).strip()
            if len(value) > limit:
                return {"error": f"{key} слишком длинный (макс {limit} символов)"}
            fields[key] = value

    if not fields:
        return {"error": "укажи food_exclusions или food_notes"}

    prefs = set_preferences(user_id, **fields)
    _invalidate_meal_plan_cache(user_id)
    plan = _build_meal_plan(user_id, refresh=True)

    parts = []
    if prefs.get("food_exclusions"):
        parts.append(f"исключил: {prefs['food_exclusions']}")
    if prefs.get("food_notes"):
        parts.append(f"учёл: {prefs['food_notes']}")
    summary = "Предпочтения питания сохранены (" + "; ".join(parts) + ")"
    if plan:
        meals = plan.get("meals") or {}
        names = [m.get("name") for m in meals.values() if m.get("name")]
        summary += f". План питания на сегодня перестроен: {', '.join(names)}"
    else:
        summary += ". План питания обновится при следующем запросе"

    from core.ai.chat_history import append_event
    append_event(user_id, f"[событие: предпочтения питания — {'; '.join(parts)}]")

    return {
        "ok": True,
        "preferences": {k: prefs[k] for k in ("food_exclusions", "food_notes")},
        "meal_plan_regenerated": plan is not None,
        "summary": summary,
    }


def _tool_regenerate_meal_plan(user_id: int, args: Dict) -> Dict:
    _invalidate_meal_plan_cache(user_id)
    plan = _build_meal_plan(user_id, refresh=True)
    if not plan:
        return {"error": "не удалось перегенерировать план питания (профиль не заполнен)"}

    meals = plan.get("meals") or {}
    names = [m.get("name") for m in meals.values() if m.get("name")]

    from core.ai.chat_history import append_event
    append_event(user_id, "[событие: план питания на сегодня перегенерирован]")

    return {
        "ok": True,
        "meals": names,
        "summary": f"План питания на сегодня обновлён: {', '.join(names)}",
    }


def _tool_delete_food_entry(user_id: int, args: Dict) -> Dict:
    """Удалить запись еды: по названию (части) за сегодня или последнюю."""
    from core.nutrition_tracker import delete_food_entry, get_food_log_today

    product_name = str((args or {}).get("product_name") or "").strip().lower()
    entries = get_food_log_today(user_id)  # свежие записи первыми
    if not entries:
        return {"error": "за сегодня нет записей еды — нечего удалять"}

    target = None
    if product_name:
        for entry in entries:
            if product_name in str(entry.get("product_name", "")).lower():
                target = entry
                break
        if target is None:
            return {
                "error": (
                    f"не нашёл «{product_name}» среди сегодняшних записей. "
                    "Уточни название или скажи «удали последнюю запись»"
                )
            }
    else:
        target = entries[0]

    if not delete_food_entry(target["id"], user_id):
        return {"error": "не удалось удалить запись"}

    from core.ai.chat_history import append_event
    append_event(user_id, f"[событие: удалено «{target['product_name']}»]")

    return {
        "ok": True,
        "deleted_id": target["id"],
        "summary": (
            f"Удалил: {target['product_name']}, "
            f"{target['weight_g']:g} г — {target['calories']:g} ккал"
        ),
    }


def _metric_day(user_id: int, date_arg) -> str:
    """Локальная дата для метрик: None → сегодня, 'yesterday' → вчера, иначе ISO."""
    from datetime import datetime, timedelta, timezone
    from core.nutrition_tracker import _local_today, _tz_offset

    if date_arg == "yesterday":
        offset = _tz_offset(user_id)
        today_local = (datetime.now(timezone.utc) + timedelta(minutes=offset)).date()
        return (today_local - timedelta(days=1)).isoformat()
    return date_arg or _local_today(user_id)


def _tool_delete_workout_session(user_id: int, args: Dict) -> Dict:
    """Удалить последнюю тренировку (или за указанную дату) с подходами."""
    from core.database import get_db

    day = _metric_day(user_id, (args or {}).get("date")) if (args or {}).get("date") else None
    conn = get_db()
    if day:
        row = conn.execute(
            "SELECT * FROM workout_sessions WHERE user_id = ? AND date = ? ORDER BY id DESC LIMIT 1",
            (user_id, day),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM workout_sessions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if not row:
        return {"error": "тренировка не найдена — нечего удалять"}

    session_id = row["id"]
    conn.execute(
        "DELETE FROM workout_sets WHERE workout_exercise_id IN "
        "(SELECT id FROM workout_exercises WHERE session_id = ?)",
        (session_id,),
    )
    conn.execute("DELETE FROM workout_exercises WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM workout_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
    conn.commit()

    from core.ai.chat_history import append_event
    append_event(user_id, f"[событие: удалена тренировка от {row['date']}]")

    return {
        "ok": True,
        "deleted_session_id": session_id,
        "summary": f"Удалил тренировку от {row['date']} ({row['type']}, {row['duration_min']} мин)",
    }


def _tool_delete_health_metric(user_id: int, args: Dict) -> Dict:
    """Удалить ручную метрику здоровья за день (сон/шаги/пульс/вес)."""
    from core.database import get_db
    from core.nutrition_tracker import _tz_offset

    metric_type = str((args or {}).get("metric_type") or "").strip()
    if metric_type not in ("steps", "sleep_hours", "resting_heart_rate", "weight"):
        return {"error": "metric_type должен быть steps/sleep_hours/resting_heart_rate/weight"}
    day = _metric_day(user_id, (args or {}).get("date"))

    conn = get_db()
    offset = _tz_offset(user_id)
    cur = conn.execute(
        f"""DELETE FROM health_metrics
            WHERE user_id = ? AND metric_type = ?
              AND date(ts, '{offset:+d} minutes') = ?
              AND source IN ('manual', 'chat')""",
        (user_id, metric_type, day),
    )
    conn.commit()
    if cur.rowcount == 0:
        return {"error": f"за {day} нет ручных записей «{metric_type}» — нечего удалять"}

    from core.ai.chat_history import append_event
    append_event(user_id, f"[событие: удалена метрика {metric_type} за {day}]")

    names = {"steps": "шаги", "sleep_hours": "сон", "resting_heart_rate": "пульс покоя", "weight": "вес"}
    return {
        "ok": True,
        "deleted_count": cur.rowcount,
        "summary": f"Удалил: {names[metric_type]} за {day}",
    }


def _tool_log_water(user_id: int, args: Dict) -> Dict:
    """Записать выпитую воду (мл)."""
    from core.gamification import add_water, get_today_water

    amount = _to_int((args or {}).get("amount_ml"))
    if amount is None or not (1 <= amount <= 5000):
        return {"error": "amount_ml должен быть от 1 до 5000 мл"}

    total = add_water(user_id, amount)
    from core.ai.chat_history import append_event
    append_event(user_id, f"[событие: вода +{amount} мл]")

    return {
        "ok": True,
        "amount_ml": amount,
        "today_ml": total,
        "summary": f"Записал воду: +{amount} мл (сегодня {total} мл)",
    }


def _tool_join_challenge(user_id: int, args: Dict) -> Dict:
    """Вступить в челлендж по коду."""
    from core.challenges import join_challenge, get_challenge_progress, CHALLENGES

    code = str((args or {}).get("code") or "").strip()
    if code not in CHALLENGES:
        return {"error": f"неизвестный челлендж «{code}»; доступны: {', '.join(CHALLENGES)}"}

    result = join_challenge(user_id, code)
    if result.get("error"):
        return result
    progress = get_challenge_progress(user_id, code)
    return {
        "ok": True,
        "summary": (
            f"Ты в челлендже «{CHALLENGES[code]['name']}»! "
            f"Прогресс: {progress.get('current', 0)}/{progress.get('target', 0)}"
        ),
    }


_HANDLERS = {
    "log_food": _tool_log_food,
    "log_food_batch": _tool_log_food_batch,
    "log_water": _tool_log_water,
    "join_challenge": _tool_join_challenge,
    "delete_food_entry": _tool_delete_food_entry,
    "delete_workout_session": _tool_delete_workout_session,
    "delete_health_metric": _tool_delete_health_metric,
    "adjust_last_food_entry": _tool_adjust_last_food_entry,
    "get_today_nutrition": _tool_get_today_nutrition,
    "get_nutrition_history": _tool_get_nutrition_history,
    "log_weight": _tool_log_weight,
    "log_health_metric": _tool_log_health_metric,
    "update_profile": _tool_update_profile,
    "get_workout_plan_today": _tool_get_workout_plan_today,
    "log_workout_done": _tool_log_workout_done,
    "get_weekly_stats": _tool_get_weekly_stats,
    "set_training_preferences": _tool_set_training_preferences,
    "regenerate_workout_plan": _tool_regenerate_workout_plan,
    "set_health_condition": _tool_set_health_condition,
    "set_food_preferences": _tool_set_food_preferences,
    "regenerate_meal_plan": _tool_regenerate_meal_plan,
}


# ═══════════════════════════════════════════════════════════════
# ДИСПЕТЧЕР
# ═══════════════════════════════════════════════════════════════

def execute_tool(user_id: int, name: str, args: Dict | None) -> Dict:
    """Выполнить инструмент по имени с валидацией аргументов.

    Возвращает dict с результатом ({"ok": True, ...}) или {"error": ...}.
    Никогда не бросает исключения — ошибка уходит модели в functionResponse.
    """
    logger.info("AI tool call: user=%s tool=%s args=%s", user_id, name, args)

    handler = _HANDLERS.get(name)
    if handler is None:
        logger.warning("AI tool: неизвестный инструмент %s", name)
        return {"error": f"неизвестный инструмент: {name}"}

    try:
        result = handler(user_id, args or {})
    except Exception as e:
        logger.exception("AI tool error: user=%s tool=%s", user_id, name)
        return {"error": f"внутренняя ошибка при выполнении {name}: {e}"}

    if "error" in result:
        logger.info("AI tool rejected: user=%s tool=%s error=%s", user_id, name, result["error"])
    else:
        logger.info("AI tool ok: user=%s tool=%s", user_id, name)

    return result
