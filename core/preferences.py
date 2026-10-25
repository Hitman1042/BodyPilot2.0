"""Предпочтения пользователя: условия тренировок и ограничения питания.

Хранятся в таблице user_preferences (миграция v21). Их выставляет AI-коуч
через инструменты set_training_preferences / set_food_preferences, а
генераторы планов (training_service, plans) учитывают при построении.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from .database import get_db

DEFAULTS: Dict[str, Any] = {
    "training_place": "",       # '', 'home', 'gym', 'outdoor'
    "equipment": "",            # свободный текст: «без инвентаря», «гантели 5 кг»
    "workouts_per_week": 0,     # 0 = не задано
    "workout_duration_min": 0,  # 0 = не задано
    "food_exclusions": "",      # «рыба, творог»
    "food_notes": "",           # «вегетарианец», «без лактозы»
}

_FIELDS = tuple(DEFAULTS)

TRAINING_PLACE_NAMES = {
    "home": "дома",
    "gym": "в зале",
    "outdoor": "на улице",
}

# Маркеры в свободном тексте equipment, означающие «только свой вес»
NO_EQUIPMENT_MARKERS = (
    "без инвентаря",
    "нет инвентаря",
    "без оборудования",
    "нет оборудования",
    "дома",
    "своим весом",
    "собственный вес",
    "собственным весом",
    "bodyweight",
)

# Значения exercises.equipment, доступные без инвентаря
BODYWEIGHT_EQUIPMENT = ("bodyweight", "")


def get_preferences(user_id: int) -> Dict[str, Any]:
    """Предпочтения пользователя; дефолты, если записи нет."""
    prefs: Dict[str, Any] = dict(DEFAULTS)
    prefs["user_id"] = user_id
    prefs["updated_at"] = None

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        row = None  # таблицы ещё нет (старая БД без миграции v21)

    if row:
        for field in _FIELDS:
            if row[field] is not None:
                prefs[field] = row[field]
        prefs["updated_at"] = row["updated_at"]
    return prefs


def set_preferences(user_id: int, **fields) -> Dict[str, Any]:
    """Upsert предпочтений; обновляет только переданные известные поля."""
    assignments = {k: v for k, v in fields.items() if k in _FIELDS}
    if assignments:
        cols = ", ".join(assignments)
        placeholders = ", ".join("?" for _ in assignments)
        updates = ", ".join(f"{k} = excluded.{k}" for k in assignments)
        conn = get_db()
        conn.execute(
            f"""INSERT INTO user_preferences (user_id, {cols}, updated_at)
                VALUES (?, {placeholders}, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET {updates},
                    updated_at = datetime('now')""",
            (user_id, *assignments.values()),
        )
        conn.commit()
    return get_preferences(user_id)


def is_bodyweight_only(prefs: Dict[str, Any]) -> bool:
    """True, если тренировки должны быть без инвентаря (дома / «без инвентаря»)."""
    if (prefs.get("training_place") or "").lower() == "home":
        return True
    equipment = (prefs.get("equipment") or "").lower()
    return any(marker in equipment for marker in NO_EQUIPMENT_MARKERS)


_PROTEIN_CANDIDATES = (
    ("курица", ("куриц", "курин", "chicken"), "meat"),
    ("рыба", ("рыб", "fish"), "fish"),
    ("яйца", ("яйц", "яич", "egg"), "eggs"),
    ("творог", ("творог", "творож", "cottage cheese"), "dairy"),
    ("бобовые", ("бобов", "фасол", "чечевиц", "нут", "beans", "lentils"), "plant"),
    ("тофу", ("тофу", "tofu"), "plant"),
    ("протеин", ("протеин", "protein"), "protein"),
    ("орехи", ("орех", "арахис", "nuts", "peanut"), "nuts"),
)

_ANIMAL_MARKERS = {
    "meat": ("куриц", "курин", "мяс", "говядин", "свинин", "индейк", "chicken", "meat", "beef", "pork"),
    "fish": ("рыб", "лосос", "семг", "сёмг", "тунц", "fish", "salmon", "tuna"),
    "eggs": ("яйц", "яич", "омлет", "egg"),
    "dairy": ("творог", "творож", "молок", "молоч", "сыр", "йогурт", "кефир", "dairy", "milk", "cheese", "yogurt"),
}


def _is_vegan(text: str) -> bool:
    return "веган" in text or "vegan" in text


def _is_vegetarian(text: str) -> bool:
    return "вегетариан" in text or "vegetarian" in text


def is_food_excluded(name: str, *restriction_texts: str) -> bool:
    """Проверить название продукта/блюда по ограничениям свободным текстом."""
    food = (name or "").lower()
    restrictions = " ".join(str(text or "") for text in restriction_texts).lower()
    if not food or not restrictions.strip():
        return False

    for part in restrictions.replace(";", ",").replace("\n", ",").split(","):
        part = part.strip()
        if part and (part in food or food in part):
            return True

    vegan = _is_vegan(restrictions)
    vegetarian = _is_vegetarian(restrictions)
    for group, markers in _ANIMAL_MARKERS.items():
        if not any(marker in food for marker in markers):
            continue
        if vegan or (vegetarian and group in ("meat", "fish")):
            return True
        if any(marker in restrictions for marker in markers):
            return True

    nut_markers = ("орех", "арахис", "nuts", "peanut")
    if any(marker in food for marker in nut_markers) and any(
            marker in restrictions for marker in nut_markers
    ):
        return True
    return False


def protein_examples(user_id: int) -> str:
    """Примеры источников белка с учётом аллергий и пищевых исключений."""
    from .database import get_user

    user = get_user(user_id) or {}
    prefs = get_preferences(user_id)
    restrictions = (
        str(user.get("allergies") or ""),
        str(prefs.get("food_exclusions") or ""),
        str(prefs.get("food_notes") or ""),
    )
    allowed = [
        name for name, markers, _group in _PROTEIN_CANDIDATES
        if not is_food_excluded(name, *restrictions)
        and not any(any(marker in text.lower() for marker in markers) for text in restrictions)
    ]
    return ", ".join(allowed) if allowed else "бобовые и протеин"


def describe_preferences(prefs: Dict[str, Any]) -> Optional[str]:
    """Короткая строка предпочтений для контекста коуча/сообщений (или None)."""
    parts = []
    place = TRAINING_PLACE_NAMES.get(prefs.get("training_place") or "")
    if place:
        parts.append(f"тренировки {place}")
    equipment = (prefs.get("equipment") or "").strip()
    if equipment:
        parts.append(f"инвентарь: {equipment}")
    per_week = prefs.get("workouts_per_week") or 0
    duration = prefs.get("workout_duration_min") or 0
    if per_week:
        freq = f"{per_week} раза в неделю"
        parts.append(f"{freq} по ~{duration} мин" if duration else freq)
    elif duration:
        parts.append(f"по ~{duration} мин")
    exclusions = (prefs.get("food_exclusions") or "").strip()
    if exclusions:
        parts.append(f"не ест: {exclusions}")
    notes = (prefs.get("food_notes") or "").strip()
    if notes:
        parts.append(f"питание: {notes}")
    return "; ".join(parts) if parts else None
