"""Правила медицинской безопасности для генератора тренировок."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable


MEDICAL_DISCLAIMER = (
    "BodyPilot не является медицинской рекомендацией; при травмах/хронических "
    "заболеваниях — согласуйте нагрузку с врачом"
)


def _condition(
    code: str,
    name_ru: str,
    category: str,
    severity_default: int,
    excluded_patterns: list[str],
    load_cap: float,
    impact_forbidden: bool,
    note_ru: str,
) -> Dict[str, Any]:
    return {
        "code": code,
        "name_ru": name_ru,
        "category": category,
        "severity_default": severity_default,
        "excluded_patterns": excluded_patterns,
        "load_cap": load_cap,
        "impact_forbidden": int(impact_forbidden),
        "note_ru": note_ru,
    }


HEALTH_CONDITIONS = [
    _condition(
        "knee_pain", "Колени", "injury", 2,
        ["squat", "lunge", "jump", "присед", "выпад", "прыг"], 1.0, True,
        "Вместо приседаний/выпадов: ягодичный мост, махи ногой; без прыжков.",
    ),
    _condition(
        "lower_back_pain", "Поясница", "injury", 2,
        ["deadlift", "good_morning", "superman", "становая", "гууд морнинг", "гиперэкстенз"],
        0.9, False,
        "Без осевой нагрузки и резких наклонов: ягодичный мост, мягкая мобилизация.",
    ),
    _condition(
        "shoulder_injury", "Плечи", "injury", 2,
        ["overhead_press", "vertical_press", "dip", "upright_row", "жим над головой",
         "армейский жим", "брусь", "тяга к подбородку"],
        0.9, False,
        "Без жимов над головой и болезненной амплитуды; мягкие движения ниже уровня плеч.",
    ),
    _condition(
        "wrist_injury", "Запястья", "injury", 2,
        ["push_up", "plank", "burpee", "отжим", "планк", "бёрпи", "берпи"],
        1.0, False,
        "Без опоры на ладони: упражнения стоя, на предплечьях или с нейтральным хватом.",
    ),
    _condition(
        "elbow_pain", "Локти", "injury", 2,
        ["dip", "triceps_extension", "skullcrusher", "pull_up", "брусь", "разгибан",
         "подтягиван", "французский жим"],
        0.9, False,
        "Без болезненных разгибаний и тяги; уменьшить амплитуду и нагрузку на руки.",
    ),
    _condition(
        "neck_pain", "Шея", "injury", 2,
        ["neck_bridge", "shrug", "overhead", "мост ше", "шраг", "над головой"],
        0.9, False,
        "Без нагрузки на голову и плечевой пояс над головой; мягкая подвижность без боли.",
    ),
    _condition(
        "hypertension", "Гипертония", "chronic", 3,
        ["valsalva", "breath_hold", "maximal", "hiit", "задержк", "максимальн"],
        1.0, False,
        "Без пиковой нагрузки, ВМ и задержки дыхания; дышать ровно, темп умеренный.",
    ),
    _condition(
        "asthma", "Астма", "chronic", 2,
        ["sprint", "hiit", "jump", "run", "спринт", "бег", "прыг"],
        0.85, False,
        "Кардио мягче: спокойная ходьба, постепенная разминка, без спринтов и HIIT.",
    ),
    _condition(
        "diabetes_type2", "Диабет 2 типа", "chronic", 2,
        [], 1.0, False,
        "Держать перекус и воду доступными; при слабости или признаках гипогликемии — остановиться.",
    ),
    _condition(
        "pregnancy", "Беременность", "special", 3,
        ["jump", "twist", "crunch", "plank", "burpee", "jump", "прыг", "скруч", "планк", "бёрпи", "берпи"],
        0.8, True,
        "Без ударных, скручиваний и планки: спокойная ходьба, мягкая мобилизация.",
    ),
    _condition(
        "senior_60", "Возраст 60+", "age", 2,
        ["jump", "plyometric", "burpee", "sprint", "прыг", "бёрпи", "берпи", "спринт"],
        0.9, True,
        "Без ударных и спринтов; умеренный темп, упражнения на баланс с опорой.",
    ),
    _condition(
        "senior_70", "Возраст 70+", "age", 3,
        ["jump", "plyometric", "burpee", "sprint", "complex_coordination", "прыг", "бёрпи", "берпи", "спринт"],
        0.8, True,
        "Баланс у опоры и ходьба вместо сложной координации; плавные переходы и отдых.",
    ),
    _condition(
        "hip_pain", "Тазобедренные суставы", "injury", 2,
        ["deep_squat", "lunge", "lateral_jump", "глубокий присед", "выпад", "прыг"],
        0.9, True,
        "Без глубоких приседаний и болезненной амплитуды; мягкие махи и мост.",
    ),
    _condition(
        "ankle_injury", "Голеностоп", "injury", 2,
        ["jump", "calf_raise", "run", "hop", "прыг", "подъём на носки", "бег"],
        1.0, True,
        "Без прыжков и бега; упражнения сидя/лёжа и спокойная нагрузка без боли.",
    ),
    _condition(
        "osteoporosis", "Остеопороз", "chronic", 3,
        ["jump", "plyometric", "spinal_flexion", "twist", "crunch", "прыг", "скруч"],
        0.8, True,
        "Без ударных и скручиваний позвоночника; вертикальная осанка и умеренная нагрузка.",
    ),
]

HEALTH_CONDITION_CODES = {item["code"] for item in HEALTH_CONDITIONS}
HEALTH_CONDITION_CODES_TEXT = ", ".join(sorted(HEALTH_CONDITION_CODES))

_IMPACT_MARKERS = (
    "jump", "plyometric", "high-impact", "high_impact", "high impact",
    "burpee", "hop", "прыг", "бёрпи", "берпи",
)


def get_condition(condition_code: str) -> Dict[str, Any] | None:
    """Получить состояние из справочника БД."""
    from core.database import get_db

    row = get_db().execute(
        "SELECT * FROM health_conditions WHERE code = ?", (condition_code,)
    ).fetchone()
    return dict(row) if row else None


def _age_condition(age: int | None) -> str | None:
    if age is None:
        return None
    if age >= 70:
        return "senior_70"
    if age >= 60:
        return "senior_60"
    return None


def get_safety_rules(user_id: int) -> Dict[str, Any]:
    """Собрать активные ограничения пользователя и возрастные правила."""
    from core.database import get_db

    conn = get_db()
    rows = conn.execute(
        """SELECT uhc.severity, uhc.notes AS user_notes, hc.*
           FROM user_health_conditions uhc
           JOIN health_conditions hc ON hc.code = uhc.condition_code
           WHERE uhc.user_id = ? AND uhc.is_active = 1
           ORDER BY hc.code""",
        (user_id,),
    ).fetchall()
    conditions = [dict(row) for row in rows]

    user = conn.execute("SELECT age FROM users WHERE user_id = ?", (user_id,)).fetchone()
    age_code = _age_condition(int(user["age"]) if user and user["age"] is not None else None)
    active_codes = {item["code"] for item in conditions}
    if age_code and age_code not in active_codes:
        row = conn.execute(
            "SELECT * FROM health_conditions WHERE code = ?", (age_code,)
        ).fetchone()
        if row:
            automatic = dict(row)
            automatic["severity"] = automatic["severity_default"]
            automatic["user_notes"] = ""
            conditions.append(automatic)

    excluded_patterns: set[str] = set()
    load_cap = 1.0
    impact_forbidden = False
    notes: list[str] = []
    condition_names: list[str] = []
    for item in conditions:
        condition_names.append(item["name_ru"])
        try:
            patterns = json.loads(item["excluded_patterns"] or "[]")
        except (json.JSONDecodeError, TypeError):
            patterns = []
        excluded_patterns.update(str(p).strip().casefold() for p in patterns if str(p).strip())
        load_cap = min(load_cap, float(item["load_cap"] or 1.0))
        impact_forbidden = impact_forbidden or bool(item["impact_forbidden"])
        if item["note_ru"]:
            notes.append(item["note_ru"])
        if item.get("user_notes"):
            notes.append(f"{item['name_ru']}: {item['user_notes']}")

    return {
        "excluded_patterns": excluded_patterns,
        "load_cap": load_cap,
        "impact_forbidden": impact_forbidden,
        "notes": notes,
        "condition_names": condition_names,
        "conditions": conditions,
    }


def _searchable_values(exercise: Dict[str, Any]) -> Iterable[str]:
    for key in ("pattern", "movement_pattern", "muscle_groups", "muscle_group", "name"):
        value = exercise.get(key)
        if isinstance(value, (list, tuple, set)):
            yield " ".join(str(part) for part in value)
        elif value is not None:
            yield str(value)

    description = exercise.get("description")
    if isinstance(description, str) and description.strip().startswith("{"):
        try:
            metadata = json.loads(description)
        except json.JSONDecodeError:
            metadata = {}
        if isinstance(metadata, dict):
            for key in ("pattern", "movement_pattern", "muscle_groups", "secondary_muscles"):
                value = metadata.get(key)
                if isinstance(value, list):
                    yield " ".join(str(part) for part in value)
                elif value is not None:
                    yield str(value)


def is_exercise_allowed(exercise: Dict[str, Any], rules: Dict[str, Any]) -> bool:
    """Проверить упражнение по движению, мышцам, названию и ударной нагрузке."""
    searchable = " ".join(_searchable_values(exercise)).casefold()
    if any(pattern.casefold() in searchable for pattern in rules.get("excluded_patterns", ())):
        return False
    if rules.get("impact_forbidden") and any(marker in searchable for marker in _IMPACT_MARKERS):
        return False
    return True


def filter_exercises(exercises: Iterable[Dict[str, Any]], rules: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [exercise for exercise in exercises if is_exercise_allowed(exercise, rules)]


def get_safe_fallback_exercises(
    rules: Dict[str, Any], allowed_equipment: tuple | None = None, limit: int = 10
) -> list[Dict[str, Any]]:
    """Найти разрешённые альтернативы вне исходной группы/модуля."""
    from core.database import get_db

    conn = get_db()
    query = "SELECT * FROM exercises WHERE is_custom = 0"
    params: list[Any] = []
    if allowed_equipment is not None:
        placeholders = ",".join("?" * len(allowed_equipment))
        query += f" AND COALESCE(equipment, '') IN ({placeholders})"
        params.extend(allowed_equipment)
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    safe = filter_exercises(rows, rules)

    def priority(exercise: Dict[str, Any]) -> tuple[int, str]:
        name = (exercise.get("name") or "").casefold()
        if "ходьб" in name:
            rank = 0
        elif "ягодичный мост" in name:
            rank = 1
        elif "растяж" in name or "мобил" in name:
            rank = 2
        else:
            rank = 3
        return rank, name

    safe.sort(key=priority)
    return safe[:limit]
