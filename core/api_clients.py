"""External API clients for BodyPilot (async version)."""

import httpx
from typing import Any, Dict, List, Optional

from core.config import settings

OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
WGER_EXERCISE_URL = "https://wger.de/api/v2/exercise/"
WGER_MUSCLE_URL = "https://wger.de/api/v2/muscle/"
OSM_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def _wger_headers() -> Dict[str, str]:
    """Заголовки для wger API. Токен опционален — публичные эндпоинты работают без него."""
    if settings.WGER_API_TOKEN:
        return {"Authorization": f"Token {settings.WGER_API_TOKEN}"}
    return {}

# ID мышц из документации wger
MUSCLE_IDS = {
    "грудь": 4,       # Pectoralis major
    "спина": 12,      # Latissimus dorsi
    "плечи": 2,       # Anterior deltoid
    "бицепс": 1,      # Biceps brachii
    "трицепс": 5,     # Triceps brachii
    "пресс": 7,       # Rectus abdominis
    "ноги": 10,       # Quadriceps femoris
    "ягодицы": 8,     # Gluteus maximus
    "икры": 6,        # Gastrocnemius
    "широчайшие": 12, # Latissimus dorsi
    "трапеции": 3,    # Trapezius
    "квадрицепс": 10, # Quadriceps femoris
}

# Запасной справочник упражнений (если API недоступен)
FALLBACK_EXERCISES = {
    "грудь": [
        {"name": "Жим штанги лёжа", "description": "Базовое упражнение для грудных мышц."},
        {"name": "Жим гантелей лёжа", "description": "Аналог жима штанги с большей амплитудой."},
        {"name": "Разведение гантелей лёжа", "description": "Изолированное упражнение для растяжки груди."},
        {"name": "Отжимания от пола", "description": "Упражнение с собственным весом."},
        {"name": "Сведение рук в кроссовере", "description": "Изолированная работа на блоке."},
    ],
    "спина": [
        {"name": "Подтягивания", "description": "Базовое упражнение для широчайших мышц."},
        {"name": "Тяга штанги в наклоне", "description": "Нагружает всю толщину спины."},
        {"name": "Тяга верхнего блока", "description": "Аналог подтягиваний с регулируемой нагрузкой."},
        {"name": "Становая тяга", "description": "Мощное базовое упражнение для спины и ног."},
    ],
    "плечи": [
        {"name": "Жим гантелей сидя", "description": "Базовое упражнение для дельтовидных мышц."},
        {"name": "Армейский жим", "description": "Жим штанги над головой."},
        {"name": "Махи гантелями в стороны", "description": "Изолированное упражнение на средний пучок дельт."},
    ],
    "бицепс": [
        {"name": "Подъём штанги на бицепс", "description": "Классическое упражнение для двуглавой мышцы."},
        {"name": "Молотки с гантелями", "description": "Нагружает бицепс и брахиалис."},
    ],
    "трицепс": [
        {"name": "Французский жим лёжа", "description": "Базовое упражнение для трицепса."},
        {"name": "Отжимания на брусьях", "description": "Упражнение с собственным весом."},
    ],
    "пресс": [
        {"name": "Скручивания", "description": "Базовое упражнение на прямую мышцу живота."},
        {"name": "Планка", "description": "Статическое упражнение на кор."},
    ],
    "ноги": [
        {"name": "Приседания со штангой", "description": "Главное упражнение для ног."},
        {"name": "Жим ногами", "description": "Базовое упражнение в тренажёре."},
    ],
}



async def search_exercises_wger(muscle: str = "", limit: int = 8) -> List[Dict[str, Any]]:
    """Ищет упражнения в wger по русскому названию группы мышц.

    Использует ID мышц из документации и параметр status=2 (только утверждённые).
    При недоступности API возвращает встроенный справочник.
    """
    headers = _wger_headers()

    # Получаем ID мышцы
    muscle_id = MUSCLE_IDS.get(muscle.lower())
    if not muscle_id:
        return []

    # Пробуем wger API
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                WGER_EXERCISE_URL,
                params={
                    "muscles": muscle_id,
                    "language": 2,
                    "status": 2,       # ✅ только утверждённые
                    "limit": limit,
                },
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                exercises = data.get("results", [])
                if exercises:
                    return [{"name": e["name"], "description": (e.get("description") or "")[:200]} for e in exercises[:limit]]
    except Exception:
        pass

    # Fallback: встроенный справочник
    return FALLBACK_EXERCISES.get(muscle.lower(), [])[:limit]


async def list_muscles_wger() -> List[Dict[str, Any]]:
    """List all muscle groups from wger (async, with API token)."""
    headers = _wger_headers()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                WGER_MUSCLE_URL,
                params={"language": 2, "limit": 50},
                headers=headers
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
    except Exception:
        return []


async def find_places_osm(lat: float, lon: float, place_type: str = "sports",
                          radius: int = 2000, limit: int = 5) -> List[Dict[str, Any]]:
    """Find places via OpenStreetMap Nominatim (async)."""
    osm_tags = {
        "sports": "[leisure=fitness_centre][leisure=sports_centre]",
        "food": "[amenity=cafe][amenity=restaurant]",
        "park": "[leisure=park]",
    }
    tag = osm_tags.get(place_type, osm_tags["sports"])
    params = {
        "q": tag,
        "format": "json",
        "limit": limit,
        "viewbox": f"{lon-0.05},{lat+0.05},{lon+0.05},{lat-0.05}",
        "bounded": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(OSM_NOMINATIM_URL, params=params,
                                    headers={"User-Agent": "BodyPilot/2.0"})
            resp.raise_for_status()
            results = resp.json()
            return [{"name": r.get("display_name", "").split(",")[0],
                    "address": r.get("display_name", ""),
                    "lat": r.get("lat"), "lon": r.get("lon")} for r in results[:limit]]
    except Exception:
        return []


async def search_food_off(query: str, page_size: int = 5) -> List[Dict[str, Any]]:
    """Поиск продуктов в OpenFoodFacts."""
    print(f"🔍 OFF поиск: {query}")

    try:
        async with httpx.AsyncClient(
                timeout=15,
                headers={"User-Agent": "BodyPilot/2.0 (Fitness Tracker Bot)"}
        ) as client:
            url = "https://world.openfoodfacts.org/cgi/search.pl"
            params = {
                "search_terms": query,
                "search_simple": 1,
                "json": 1,
                "page_size": page_size,
            }

            print(f"📡 Запрос: {url}")

            resp = await client.get(url, params=params)

            print(f"📊 Статус: {resp.status_code}")

            if resp.status_code == 200:
                data = resp.json()
                products = data.get("products", [])

                print(f"✅ Найдено продуктов: {len(products)}")

                if len(products) == 0:
                    print(f"⚠️ Пустой результат — возможно продукт не в базе OFF")

                results = []
                for p in products:
                    nut = p.get("nutriments") or {}
                    results.append({
                        "name": p.get("product_name") or "Неизвестный продукт",
                        "brand": p.get("brands", ""),
                        "calories_100g": nut.get("energy-kcal_100g", 0) or 0,
                        "protein_100g": nut.get("proteins_100g", 0) or 0,
                        "fat_100g": nut.get("fat_100g", 0) or 0,
                        "carbs_100g": nut.get("carbohydrates_100g", 0) or 0,
                    })

                return results[:page_size]
            else:
                print(f"❌ OFF ошибка: {resp.status_code}")
                return []

    except Exception as e:
        print(f"❌ OFF exception: {e}")
        return []

# ═══════════════════════════════════════════════════════════════
# WGER — ПОИСК ПО НАЗВАНИЮ УПРАЖНЕНИЯ
# ═══════════════════════════════════════════════════════════════

async def search_exercises_by_name_wger(
        query: str,
        limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Поиск упражнений по названию (на английском).

    wger API не поддерживает прямой поиск по названию,
    поэтому используем fallback на встроенную базу.
    """
    headers = _wger_headers()

    # ═══════════════════════════════════════════════════════════════
    # 1. ПЫТАЕМСЯ ИСКАТЬ ЧЕРЕЗ API (endpoint /exercise/)
    # ═══════════════════════════════════════════════════════════════

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Получаем все упражнения и фильтруем локально
            resp = await client.get(
                WGER_EXERCISE_URL,
                params={
                    "language": 2,
                    "status": 2,
                    "limit": 100,  # Берём больше для фильтрации
                },
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json()
                exercises = data.get("results", [])

                # Фильтруем по названию локально
                query_lower = query.lower()
                matched = []
                for ex in exercises:
                    name = ex.get("name", "").lower()
                    if query_lower in name:
                        matched.append({
                            "id": ex.get("id"),
                            "name": ex.get("name", "Unknown"),
                            "category": ex.get("category", {}).get("name", "Other") if ex.get("category") else "Other",
                            "muscles": ex.get("muscles", []),
                            "difficulty": ex.get("difficulty", "beginner"),
                            "description": (ex.get("description") or "")[:500],
                        })

                if matched:
                    return matched[:limit]

    except Exception as e:
        print(f"wger search by name error: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 2. FALLBACK — ВСТРОЕННАЯ БАЗА
    # ═══════════════════════════════════════════════════════════════

    # Словарь популярных упражнений
    exercise_db = {
        "bench": [
            {"id": 1, "name": "Bench Press (Barbell)", "category": "Strength", "muscles": ["chest", "triceps"],
             "difficulty": "intermediate", "description": "Classic chest exercise with barbell."},
            {"id": 2, "name": "Incline Bench Press", "category": "Strength", "muscles": ["chest", "shoulders"],
             "difficulty": "intermediate", "description": "Bench press on incline bench."},
            {"id": 3, "name": "Dumbbell Bench Press", "category": "Strength", "muscles": ["chest", "triceps"],
             "difficulty": "beginner", "description": "Bench press with dumbbells."},
        ],
        "squat": [
            {"id": 10, "name": "Squat (Barbell)", "category": "Strength", "muscles": ["quadriceps", "glutes"],
             "difficulty": "intermediate", "description": "Classic leg exercise with barbell."},
            {"id": 11, "name": "Front Squat", "category": "Strength", "muscles": ["quadriceps", "core"],
             "difficulty": "advanced", "description": "Squat with barbell on front shoulders."},
        ],
        "deadlift": [
            {"id": 20, "name": "Deadlift", "category": "Strength", "muscles": ["back", "glutes", "hamstrings"],
             "difficulty": "advanced", "description": "Classic pulling exercise."},
            {"id": 21, "name": "Romanian Deadlift", "category": "Strength", "muscles": ["hamstrings", "glutes"],
             "difficulty": "intermediate", "description": "Deadlift variant focusing on hamstrings."},
        ],
        "pull": [
            {"id": 30, "name": "Pull-ups", "category": "Strength", "muscles": ["back", "biceps"],
             "difficulty": "intermediate", "description": "Classic bodyweight back exercise."},
        ],
        "press": [
            {"id": 40, "name": "Overhead Press", "category": "Strength", "muscles": ["shoulders", "triceps"],
             "difficulty": "intermediate", "description": "Military press with barbell."},
        ],
    }

    query_lower = query.lower()
    for key, exercises in exercise_db.items():
        if key in query_lower:
            return exercises[:limit]

    return []


async def get_exercise_detail_wger(exercise_id: int) -> Optional[Dict[str, Any]]:
    """
    Получить детали упражнения по ID.
    """
    headers = _wger_headers()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # wger требует language параметр для получения локализованного названия
            resp = await client.get(
                f"{WGER_EXERCISE_URL}{exercise_id}/",
                params={"language": 2},  # Английский
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json()
                return {
                    "id": data.get("id"),
                    "name": data.get("name", "Unknown"),
                    "category": data.get("category", {}).get("name", "Other") if data.get("category") else "Other",
                    "muscles": data.get("muscles", []),
                    "difficulty": data.get("difficulty", "beginner"),
                    "description": data.get("description", ""),
                    "video_url": data.get("video", ""),
                }

    except Exception as e:
        print(f"wger detail error: {e}")

    # FALLBACK — возвращаем из встроенной базы
    fallback_db = {
        1: {"id": 1, "name": "Bench Press (Barbell)", "category": "Strength", "muscles": ["chest", "triceps"],
            "difficulty": "intermediate",
            "description": "Classic chest exercise with barbell. Lie on bench, lower bar to chest, press up.",
            "video_url": ""},
        2: {"id": 2, "name": "Incline Bench Press", "category": "Strength", "muscles": ["chest", "shoulders"],
            "difficulty": "intermediate", "description": "Bench press on incline bench targets upper chest.",
            "video_url": ""},
        3: {"id": 3, "name": "Dumbbell Bench Press", "category": "Strength", "muscles": ["chest", "triceps"],
            "difficulty": "beginner", "description": "Bench press with dumbbells allows greater range of motion.",
            "video_url": ""},
        10: {"id": 10, "name": "Squat (Barbell)", "category": "Strength", "muscles": ["quadriceps", "glutes"],
             "difficulty": "intermediate", "description": "Classic leg exercise. Bar on back, squat down, drive up.",
             "video_url": ""},
        11: {"id": 11, "name": "Front Squat", "category": "Strength", "muscles": ["quadriceps", "core"],
             "difficulty": "advanced", "description": "Squat with barbell on front shoulders. More quad focus.",
             "video_url": ""},
        20: {"id": 20, "name": "Deadlift", "category": "Strength", "muscles": ["back", "glutes", "hamstrings"],
             "difficulty": "advanced", "description": "Classic pulling exercise. Lift bar from floor to hip level.",
             "video_url": ""},
        21: {"id": 21, "name": "Romanian Deadlift", "category": "Strength", "muscles": ["hamstrings", "glutes"],
             "difficulty": "intermediate",
             "description": "Deadlift variant focusing on hamstrings. Keep legs slightly bent.", "video_url": ""},
        30: {"id": 30, "name": "Pull-ups", "category": "Strength", "muscles": ["back", "biceps"],
             "difficulty": "intermediate", "description": "Classic bodyweight back exercise. Pull chin over bar.",
             "video_url": ""},
        40: {"id": 40, "name": "Overhead Press", "category": "Strength", "muscles": ["shoulders", "triceps"],
             "difficulty": "intermediate", "description": "Military press with barbell. Press bar overhead.",
             "video_url": ""},
    }

    return fallback_db.get(exercise_id)


# ═══════════════════════════════════════════════════════════════
# OPENFOODFACTS — ПОИСК ПО ШТРИХ-КОДУ
# ═══════════════════════════════════════════════════════════════

async def get_product_by_barcode_off(barcode: str) -> Optional[Dict[str, Any]]:
    """
    Получить продукт по штрих-коду из OpenFoodFacts + barcode-list.ru.
    """
    # ═══════════════════════════════════════════════════════════════
    # 1. ПЫТАЕМСЯ НАЙТИ В OPENFOODFACTS
    # ═══════════════════════════════════════════════════════════════

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
            )

            if resp.status_code == 200:
                data = resp.json()

                if data.get("status") == 1:
                    product = data.get("product", {})
                    nutriments = product.get("nutriments", {})

                    return {
                        "barcode": barcode,
                        "name": product.get("product_name", "Unknown"),
                        "brand": product.get("brands", "Unknown"),
                        "calories_100g": nutriments.get("energy-kcal_100g", 0) or 0,
                        "protein_100g": nutriments.get("proteins_100g", 0) or 0,
                        "fat_100g": nutriments.get("fat_100g", 0) or 0,
                        "carbs_100g": nutriments.get("carbohydrates_100g", 0) or 0,
                        "fiber_100g": nutriments.get("fiber_100g", 0) or 0,
                        "image_url": product.get("image_front_url", ""),
                    }

    except Exception as e:
        print(f"OpenFoodFacts barcode error: {e}")

    # ═══════════════════════════════════════════════════════════════
    # 2. ПЫТАЕМСЯ НАЙТИ В barcode-list.ru (ПРАВИЛЬНЫЙ URL!)
    # ═══════════════════════════════════════════════════════════════

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # ✅ ПРАВИЛЬНЫЙ ФОРМАТ URL
            url = f"https://barcode-list.ru/barcode/RU/Поиск.htm?barcode={barcode}"

            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )

            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'html.parser')

                # Ищем таблицу с результатами
                table = soup.find('table', class_='table')
                if table:
                    rows = table.find_all('tr')
                    if len(rows) >= 2:
                        # Первая строка после заголовка — продукт
                        cells = rows[1].find_all('td')
                        if len(cells) >= 2:
                            name = cells[1].get_text().strip()

                            # Ищем КБЖУ в странице
                            calories = 0
                            protein = 0
                            fat = 0
                            carbs = 0

                            # Пробуем найти нутриенты
                            nutrition_text = soup.find(string=lambda t: 'ккал' in str(t).lower() if t else False)

                            return {
                                "barcode": barcode,
                                "name": name,
                                "brand": "Неизвестно",
                                "calories_100g": calories,
                                "protein_100g": protein,
                                "fat_100g": fat,
                                "carbs_100g": carbs,
                                "image_url": "",
                                "source": "barcode-list.ru",
                            }

    except Exception as e:
        print(f"barcode-list.ru error: {e}")

    return None

async def search_food_off_detailed(query: str, page_size: int = 10) -> List[Dict[str, Any]]:
    """Поиск продуктов в OpenFoodFacts с ID для дедупликации."""
    print(f"🔍 OFF detailed поиск: {query}")

    try:
        async with httpx.AsyncClient(
                timeout=15,
                headers={"User-Agent": "BodyPilot/2.0 (Fitness Tracker Bot)"}
        ) as client:
            url = "https://world.openfoodfacts.org/cgi/search.pl"
            params = {
                "search_terms": query,
                "search_simple": 1,
                "json": 1,
                "page_size": page_size,
            }

            resp = await client.get(url, params=params)

            if resp.status_code == 200:
                data = resp.json()
                products = data.get("products", [])

                print(f"✅ Найдено продуктов: {len(products)}")

                results = []
                for p in products:
                    nut = p.get("nutriments") or {}
                    results.append({
                        "name": p.get("product_name") or "Неизвестный продукт",
                        "brand": p.get("brands", ""),
                        "source_id": str(p.get("_id") or ""),
                        "calories": nut.get("energy-kcal_100g", 0) or 0,
                        "protein": nut.get("proteins_100g", 0) or 0,
                        "fat": nut.get("fat_100g", 0) or 0,
                        "carbs": nut.get("carbohydrates_100g", 0) or 0,
                    })
                return results[:page_size]

    except Exception as e:
        print(f"❌ OFF detailed exception: {e}")

    return []

# ═══════════════════════════════════════════════════════════════
# УМНЫЙ ПЕРЕВОД УПРАЖНЕНИЙ (сохраняет уникальность)
# ═══════════════════════════════════════════════════════════════

# Ключевые слова EN → RU
KEYWORDS_EN_RU = {
    # Упражнения
    "bench press": "жим лёжа",
    "incline bench": "жим на наклонной",
    "decline bench": "жим на наклонной вниз",
    "dumbbell press": "жим гантелей",
    "barbell press": "жим штанги",
    "overhead press": "жим над головой",
    "military press": "армейский жим",
    "squat": "приседания",
    "front squat": "фронтальные приседания",
    "back squat": "приседания со штангой на спине",
    "deadlift": "становая тяга",
    "romanian deadlift": "румынская тяга",
    "sumo deadlift": "становая тяга сумо",
    "pull up": "подтягивания",
    "chin up": "подтягивания обратным хватом",
    "push up": "отжимания",
    "dip": "отжимания на брусьях",
    "row": "тяга",
    "barbell row": "тяга штанги",
    "dumbbell row": "тяга гантели",
    "cable row": "тяга блока",
    "lat pulldown": "тяга верхнего блока",
    "bicep curl": "подъём на бицепс",
    "hammer curl": "молотки",
    "tricep extension": "разгибание на трицепс",
    "french press": "французский жим",
    "leg press": "жим ногами",
    "leg curl": "сгибание ног",
    "leg extension": "разгибание ног",
    "lunge": "выпады",
    "calf raise": "подъём на носки",
    "plank": "планка",
    "crunch": "скручивания",
    "leg raise": "подъём ног",
    "hyperextension": "гиперэкстензия",
    "good morning": "доброе утро",
    "shrug": "шраги",
    "face pull": "тяга к лицу",
    "lateral raise": "махи в стороны",
    "front raise": "подъём перед собой",
    "reverse fly": "махи в наклоне",
    "cable fly": "сведение в кроссовере",
    "farmer walk": "прогулка фермера",
    "burpee": "берпи",
    "mountain climber": "альпинист",
    "kettlebell swing": "махи гирей",

    # Оборудование
    "barbell": "штанга",
    "dumbbell": "гантели",
    "kettlebell": "гиря",
    "cable": "блок",
    "machine": "тренажёр",
    "smith": "машина Смита",
    "bodyweight": "с собственным весом",

    # Мышцы
    "chest": "грудь",
    "pectorals": "грудные",
    "back": "спина",
    "lats": "широчайшие",
    "shoulders": "плечи",
    "deltoids": "дельты",
    "biceps": "бицепс",
    "triceps": "трицепс",
    "quadriceps": "квадрицепс",
    "quads": "квадрицепс",
    "hamstrings": "бицепс бедра",
    "glutes": "ягодицы",
    "calves": "икры",
    "abs": "пресс",
    "core": "кор",
    "forearms": "предплечья",
    "traps": "трапеции",
    "obliques": "косые",
}

# Ключевые слова RU → EN для поиска
KEYWORDS_RU_EN = {
    "жим": "bench press",
    "жим лёжа": "bench press",
    "жим лежа": "bench press",
    "на наклонной": "incline",
    "гантели": "dumbbell",
    "штанга": "barbell",
    "присед": "squat",
    "становая": "deadlift",
    "тяга": "row",
    "подтягивания": "pull up",
    "отжимания": "push up",
    "брусья": "dip",
    "бицепс": "bicep curl",
    "трицепс": "tricep extension",
    "плечи": "shoulders",
    "грудь": "chest",
    "спина": "back",
    "ноги": "legs",
    "пресс": "abs",
    "ягодицы": "glutes",
}


def translate_exercise_name(en_name: str) -> str:
    """
    Умный перевод названия упражнения.
    Переводит ключевые слова, сохраняя уникальность.
    """
    result = en_name
    result_lower = result.lower()

    # ═══════════════════════════════════════════════════════════════
    # СПЕЦИАЛЬНЫЕ ПРАВИЛА ДЛЯ ПОПУЛЯРНЫХ УПРАЖНЕНИЙ
    # ═══════════════════════════════════════════════════════════════

    special_rules = {
        "bench press (barbell)": "Жим штанги лёжа",
        "incline bench press": "Жим штанги на наклонной скамье",
        "dumbbell bench press": "Жим гантелей лёжа",
        "decline bench press": "Жим штанги на наклонной вниз",
        "squat (barbell)": "Приседания со штангой",
        "front squat": "Фронтальные приседания",
        "back squat": "Приседания со штангой на спине",
        "deadlift": "Становая тяга",
        "romanian deadlift": "Румынская тяга",
        "sumo deadlift": "Становая тяга сумо",
        "pull-ups": "Подтягивания",
        "chin-ups": "Подтягивания обратным хватом",
        "push-ups": "Отжимания от пола",
        "dips": "Отжимания на брусьях",
        "barbell row": "Тяга штанги в наклоне",
        "dumbbell row": "Тяга гантели в наклоне",
        "lat pulldown": "Тяга верхнего блока",
        "cable row": "Тяга горизонтального блока",
        "bicep curl": "Подъём штанги на бицепс",
        "hammer curl": "Молотки с гантелями",
        "tricep extension": "Французский жим",
        "overhead press": "Армейский жим",
        "military press": "Армейский жим",
        "leg press": "Жим ногами",
        "leg curl": "Сгибание ног в тренажёре",
        "leg extension": "Разгибание ног в тренажёре",
        "lunge": "Выпады",
        "calf raise": "Подъём на носки",
        "plank": "Планка",
        "crunches": "Скручивания на пресс",
        "leg raise": "Подъём ног в висе",
        "hyperextension": "Гиперэкстензия",
        "good morning": "Доброе утро",
        "shrug": "Шраги",
        "face pull": "Тяга к лицу",
        "lateral raise": "Махи гантелями в стороны",
        "front raise": "Подъём рук перед собой",
        "reverse fly": "Махи в наклоне",
        "cable fly": "Сведение рук в кроссовере",
        "farmer walk": "Прогулка фермера",
        "burpee": "Берпи",
        "mountain climber": "Альпинист",
        "kettlebell swing": "Махи гирей",
    }

    # Проверяем специальные правила
    for en, ru in special_rules.items():
        if en in result_lower:
            return ru

    # ═══════════════════════════════════════════════════════════════
    # ОБЩИЕ ПРАВИЛА (ключевые слова)
    # ═══════════════════════════════════════════════════════════════

    # Сортируем по длине (сначала длинные ключи)
    sorted_keywords = sorted(KEYWORDS_EN_RU.items(), key=lambda x: len(x[0]), reverse=True)

    for en, ru in sorted_keywords:
        if en.lower() in result_lower:
            result = result.replace(en, ru, 1)
            result = result.replace(en.title(), ru, 1)

    return result


def translate_query_ru_to_en(query: str) -> str:
    """
    Перевод поискового запроса RU → EN для wger.
    """
    query_lower = query.lower().strip()

    # Проверяем точные совпадения
    if query_lower in KEYWORDS_RU_EN:
        return KEYWORDS_RU_EN[query_lower]

    # Собираем перевод из ключевых слов
    en_terms = []
    for ru, en in KEYWORDS_RU_EN.items():
        if ru in query_lower:
            en_terms.append(en)

    if en_terms:
        # Возвращаем самый релевантный термин
        return en_terms[0]

    # Если не нашли перевод — возвращаем как есть (пользователь ввёл EN)
    return query_lower


def translate_muscle_name(en_name: str) -> str:
    """Перевести название мышцы."""
    return KEYWORDS_EN_RU.get(en_name.lower(), en_name)