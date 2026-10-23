"""Каталог видов спорта BodyPilot."""

from typing import Dict, List, Optional
from ..database import get_db

SPORT_ICONS = {
    "running": "🏃", "swimming": "🏊", "powerlifting": "🏋️", "cycling": "🚴",
    "martial_arts": "🥊", "team_sports": "🏀", "climbing": "🧗",
    "weightlifting": "🏋️‍♀️", "crossfit": "🤸", "fitness": "🧘",
}

SPORT_DESCRIPTIONS = {
    "running": "Бег на средние и длинные дистанции",
    "swimming": "Плавание в бассейне или открытой воде",
    "powerlifting": "Троеборье: присед, жим, тяга",
    "cycling": "Шоссейный или трековый велоспорт",
    "martial_arts": "Бокс, ММА, борьба, дзюдо",
    "team_sports": "Футбол, баскетбол, волейбол",
    "climbing": "Скалодром или естественный рельеф",
    "weightlifting": "Рывок и толчок штанги",
    "crossfit": "Функциональный фитнес, WOD",
    "fitness": "Общее физическое развитие, здоровье",
}

SPORT_NUTRITION_NORMS = {
    "running": {"lose": {"protein": 1.6, "carbs": 4.0, "fat": 0.8}, "maintain": {"protein": 1.4, "carbs": 5.0, "fat": 1.0}, "gain": {"protein": 1.8, "carbs": 6.0, "fat": 1.0}},
    "swimming": {"lose": {"protein": 1.8, "carbs": 4.0, "fat": 0.9}, "maintain": {"protein": 1.6, "carbs": 5.0, "fat": 1.0}, "gain": {"protein": 2.0, "carbs": 6.0, "fat": 1.1}},
    "powerlifting": {"lose": {"protein": 2.0, "carbs": 3.0, "fat": 1.0}, "maintain": {"protein": 2.2, "carbs": 4.0, "fat": 1.0}, "gain": {"protein": 2.2, "carbs": 5.0, "fat": 1.2}},
    "cycling": {"lose": {"protein": 1.6, "carbs": 4.5, "fat": 0.8}, "maintain": {"protein": 1.4, "carbs": 6.0, "fat": 1.0}, "gain": {"protein": 1.8, "carbs": 7.0, "fat": 1.0}},
    "martial_arts": {"lose": {"protein": 1.8, "carbs": 3.5, "fat": 0.9}, "maintain": {"protein": 1.6, "carbs": 4.5, "fat": 1.0}, "gain": {"protein": 2.0, "carbs": 5.5, "fat": 1.1}},
    "team_sports": {"lose": {"protein": 1.6, "carbs": 4.0, "fat": 0.8}, "maintain": {"protein": 1.4, "carbs": 5.0, "fat": 1.0}, "gain": {"protein": 1.8, "carbs": 6.0, "fat": 1.0}},
    "climbing": {"lose": {"protein": 1.8, "carbs": 3.5, "fat": 0.9}, "maintain": {"protein": 1.6, "carbs": 4.5, "fat": 1.0}, "gain": {"protein": 2.0, "carbs": 5.5, "fat": 1.1}},
    "weightlifting": {"lose": {"protein": 2.0, "carbs": 3.0, "fat": 1.0}, "maintain": {"protein": 2.2, "carbs": 4.0, "fat": 1.0}, "gain": {"protein": 2.2, "carbs": 5.0, "fat": 1.2}},
    "crossfit": {"lose": {"protein": 2.0, "carbs": 3.5, "fat": 0.9}, "maintain": {"protein": 1.8, "carbs": 4.5, "fat": 1.0}, "gain": {"protein": 2.2, "carbs": 5.5, "fat": 1.1}},
    "fitness": {"lose": {"protein": 1.8, "carbs": 3.0, "fat": 0.8}, "maintain": {"protein": 1.6, "carbs": 4.0, "fat": 1.0}, "gain": {"protein": 2.0, "carbs": 5.0, "fat": 1.0}},
}

def get_all_sports() -> List[Dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM sports ORDER BY id").fetchall()
    return [dict(row) for row in rows]

def get_sport(sport_id: int) -> Optional[Dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM sports WHERE id = ?", (sport_id,)).fetchone()
    return dict(row) if row else None

def get_sport_by_name(name_en: str) -> Optional[Dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM sports WHERE name_en = ?", (name_en,)).fetchone()
    return dict(row) if row else None

def get_sport_icon(name_en: str) -> str:
    return SPORT_ICONS.get(name_en, "🏃")

def get_sport_description(name_en: str) -> str:
    return SPORT_DESCRIPTIONS.get(name_en, "Общее физическое развитие")

def get_sport_nutrition_norms(name_en: str, goal: str) -> Dict[str, float]:
    norms = SPORT_NUTRITION_NORMS.get(name_en, SPORT_NUTRITION_NORMS["fitness"])
    return norms.get(goal, norms["maintain"])

def get_user_sport(user_id: int) -> Optional[Dict]:
    conn = get_db()
    row = conn.execute("""
        SELECT u.sport_id, u.sport_level, u.training_phase, s.*
        FROM users u
        LEFT JOIN sports s ON s.id = u.sport_id
        WHERE u.user_id = ?
    """, (user_id,)).fetchone()
    return dict(row) if row else None

def set_user_sport(user_id: int, sport_id: int, sport_level: str = "beginner") -> bool:
    try:
        conn = get_db()
        conn.execute("UPDATE users SET sport_id = ?, sport_level = ?, training_phase = 'general' WHERE user_id = ?", (sport_id, sport_level, user_id))
        conn.commit()
        return True
    except Exception:
        return False