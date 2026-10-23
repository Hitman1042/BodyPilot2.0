"""AI-поиск продуктов с синонимами и опечатками."""

import re
from typing import List, Dict, Optional
from core.database import get_db

# ═══════════════════════════════════════════════════════════════
# БАЗА СИНОНИМОВ
# ═══════════════════════════════════════════════════════════════

SYNONYMS = {
    # Курица
    "курица": ["куриная грудка", "куриное филе", "курочка", "курятина", "chicken"],
    "куриная грудка": ["курица", "куриное филе", "курочка", "филе курицы"],

    # Гречка
    "гречка": ["гречневая каша", "гречневая крупа", "греча", "ядрица"],
    "гречневая каша": ["гречка", "греча", "ядрица"],

    # Рис
    "рис": ["рисовая каша", "рис белый", "рис бурый", "басмати", "жасмин"],
    "рисовая каша": ["рис"],

    # Овсянка
    "овсянка": ["овсяная каша", "геркулес", "овсяные хлопья", "овёс"],
    "овсяная каша": ["овсянка", "геркулес", "овсяные хлопья"],

    # Творог
    "творог": ["творожок", "кисломолочный творог", "cottage cheese"],
    "творожок": ["творог", "творожная масса"],

    # Яйца
    "яйца": ["яйцо куриное", "яичко", "eggs"],
    "яйцо": ["яйца", "яичный белок", "яичный желток"],

    # Рыба
    "рыба": ["рыбное филе", "морепродукты", "fish"],
    "рыбное филе": ["рыба", "филе рыбы"],

    # Мясо
    "мясо": ["говядина", "свинина", "телятина", "meat"],
    "говядина": ["говяжье мясо", "beef", "красное мясо"],

    # Овощи
    "овощи": ["овощные культуры", "vegetables"],
    "помидор": ["томат", "помидоры", "tomato"],
    "огурец": ["огурцы", "cucumber"],
    "картошка": ["картофель", "potato", "картоха"],
    "капуста": ["белокочанная капуста", "cabbage"],

    # Фрукты
    "яблоко": ["яблоки", "apple"],
    "банан": ["бананы", "banana"],
    "апельсин": ["апельсины", "orange", "мандарин"],

    # Орехи
    "орехи": ["орешки", "nuts"],
    "арахис": ["арахисовые орехи", "peanut"],
    "миндаль": ["миндальные орехи", "almond"],

    # Молочка
    "молоко": ["коровье молоко", "milk"],
    "кефир": ["кисломолочный кефир", "yogurt"],
    "йогурт": ["йогурт натуральный", "греческий йогурт"],

    # Хлеб
    "хлеб": ["хлебобулочные изделия", "bread", "булка"],
    "батон": ["хлеб белый", "булка"],

    # Макароны
    "макароны": ["паста", "спагетти", "macaroni", "pasta"],
    "паста": ["макароны", "спагетти"],

    # Масло
    "масло": ["масло растительное", "масло оливковое", "oil"],
    "оливковое масло": ["оливковое", "olive oil", "растительное масло"],

    # Сахар
    "сахар": ["сахарный песок", "sugar", "сладкое"],
    "мёд": ["мед", "honey", "пчелиный мёд"],

    # Напитки
    "вода": ["питьевая вода", "water", "h2o"],
    "чай": ["чай чёрный", "чай зелёный", "tea"],
    "кофе": ["кофейный напиток", "coffee", "эспрессо"],

    # Сладости
    "шоколад": ["шоколадка", "chocolate", "какао"],
    "конфеты": ["конфетка", "candy", "сладости"],

    # Фастфуд
    "бургер": ["гамбургер", "cheeseburger", "бутерброд"],
    "пицца": ["pizza", "пицца с сыром"],
    "картошка фри": ["фри", "french fries", "жареный картофель"],
}


# ═══════════════════════════════════════════════════════════════
# ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════

def normalize_query(query: str) -> str:
    """Нормализовать поисковый запрос."""
    # Приводим к нижнему регистру
    query = query.lower().strip()

    # Убираем лишние пробелы
    query = re.sub(r'\s+', ' ', query)

    # Убираем спецсимволы
    query = re.sub(r'[^\w\sа-яё]', '', query)

    return query


def find_synonyms(query: str) -> List[str]:
    """Найти синонимы для запроса."""
    normalized = normalize_query(query)
    synonyms = [normalized]

    # Ищем прямые совпадения
    for key, values in SYNONYMS.items():
        if key in normalized:
            synonyms.extend(values)
        for value in values:
            if value in normalized:
                synonyms.append(key)
                synonyms.extend([v for v in values if v != value])

    # Ищем частичные совпадения
    words = normalized.split()
    for word in words:
        for key, values in SYNONYMS.items():
            if word in key or key in word:
                synonyms.extend(values)

    return list(set(synonyms))  # Убираем дубли


def search_products(
        query: str,
        limit: int = 10,
        use_synonyms: bool = True,
) -> List[Dict]:
    """
    Поиск продуктов с поддержкой синонимов.

    Args:
        query: Поисковый запрос
        limit: Максимум результатов
        use_synonyms: Использовать синонимы

    Returns:
        Список продуктов [{"id": int, "name": str, "calories": float, ...}]
    """
    # Общее thread-local соединение: не закрывать и не менять row_factory
    conn = get_db()

    results = []

    # ═══════════════════════════════════════════════════════════════
    # ПОИСК ПО ОСНОВНОМУ ЗАПРОСУ
    # ═══════════════════════════════════════════════════════════════

    normalized = normalize_query(query)

    # Точное совпадение
    exact = conn.execute("""
        SELECT * FROM food_products
        WHERE LOWER(name) LIKE ?
        LIMIT ?
    """, (f"%{normalized}%", limit)).fetchall()

    results.extend(dict(row) for row in exact)

    # ═══════════════════════════════════════════════════════════════
    # ПОИСК ПО СИНОНИМАМ
    # ═══════════════════════════════════════════════════════════════

    if use_synonyms and len(results) < limit:
        synonyms = find_synonyms(query)

        for synonym in synonyms:
            if synonym == normalized:
                continue

            synonym_results = conn.execute("""
                SELECT * FROM food_products
                WHERE LOWER(name) LIKE ?
                LIMIT ?
            """, (f"%{synonym}%", limit - len(results))).fetchall()

            for product in synonym_results:
                if product["id"] not in [r["id"] for r in results]:
                    results.append(dict(product))

            if len(results) >= limit:
                break

    return results[:limit]


def get_product_alternatives(product_id: int, limit: int = 5) -> List[Dict]:
    """
    Найти аналоги продукта.

    Args:
        product_id: ID продукта
        limit: Максимум результатов

    Returns:
        Список аналогов [{"id": int, "name": str, "similarity": float, ...}]
    """
    conn = get_db()

    # Получаем исходный продукт
    product = conn.execute("""
        SELECT * FROM food_products WHERE id = ?
    """, (product_id,)).fetchone()

    if not product:
        return []

    product = dict(product)

    # ИСПРАВЛЕНО: используем правильные имена полей
    calories = product.get("calories_100g", 0)
    protein = product.get("protein_100g", 0)
    fat = product.get("fat_100g", 0)
    carbs = product.get("carbs_100g", 0)

    # Ищем продукты с похожим КБЖУ
    alternatives = conn.execute("""
        SELECT *,
            ABS(calories_100g - ?) as cal_diff,
            ABS(protein_100g - ?) as prot_diff,
            ABS(fat_100g - ?) as fat_diff,
            ABS(carbs_100g - ?) as carb_diff
        FROM food_products
        WHERE id != ?
        ORDER BY cal_diff + prot_diff + fat_diff + carb_diff
        LIMIT ?
    """, (
        calories,
        protein,
        fat,
        carbs,
        product_id,
        limit,
    )).fetchall()

    return [dict(row) for row in alternatives]


def ai_search_products(query: str, user_goal: str = "maintain") -> Dict:
    """
    Умный поиск продуктов с AI-рекомендациями.

    Returns:
        {
            "products": [...],
            "alternatives": [...],
            "ai_tip": str,
        }
    """
    products = search_products(query, limit=10)

    if not products:
        return {
            "products": [],
            "alternatives": [],
            "ai_tip": f"❌ Продукт '{query}' не найден. Попробуйте другое название.",
        }

    # Находим аналоги для первого продукта
    if products and len(products) > 0:
        alternatives = get_product_alternatives(products[0]["id"], limit=3)
    else:
        alternatives = []

    # AI-совет на основе цели
    goal_tips = {
        "lose": "🔥 Для похудения выбирайте продукты с высоким белком и низкой калорийностью.",
        "gain": "💪 Для набора массы выбирайте продукты с высоким содержанием белка и углеводов.",
        "maintain": "⚖️ Для поддержания веса соблюдайте баланс КБЖУ.",
    }

    ai_tip = goal_tips.get(user_goal, goal_tips["maintain"])

    return {
        "products": products,
        "alternatives": alternatives,
        "ai_tip": ai_tip,
    }