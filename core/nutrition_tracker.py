"""Трекер питания: поиск, добавление, аналитика."""

from typing import Optional, List, Dict
from datetime import datetime, date, timedelta, timezone
from .database import get_db, get_user


# ═══════════════════════════════════════════════════════════════
# ЛОКАЛЬНОЕ ВРЕМЯ ПОЛЬЗОВАТЕЛЯ
# logged_at в БД хранится в UTC (datetime('now')), а "сегодня" для
# пользователя — по его timezone_offset (минуты). Все сравнения дат
# дневника идут через сдвиг на offset.
# ═══════════════════════════════════════════════════════════════

def _tz_offset(user_id: int) -> int:
    """timezone_offset пользователя в минутах (0 при отсутствии)."""
    user = get_user(user_id)
    try:
        return int(user.get("timezone_offset") or 0) if user else 0
    except (TypeError, ValueError):
        return 0


def _local_today(user_id: int) -> str:
    """Сегодняшняя дата по локальному времени пользователя (YYYY-MM-DD)."""
    offset = _tz_offset(user_id)
    return (datetime.now(timezone.utc) + timedelta(minutes=offset)).date().isoformat()


def _day_expr(user_id: int) -> str:
    """SQL-фрагмент: локальная дата записи, напр. DATE(logged_at, '+180 minutes')."""
    return f"DATE(logged_at, '{_tz_offset(user_id):+d} minutes')"


def _local_now_hm(user_id: int) -> str:
    """Локальное время пользователя HH:MM (для meal_time)."""
    offset = _tz_offset(user_id)
    return (datetime.now(timezone.utc) + timedelta(minutes=offset)).strftime("%H:%M")


# ═══════════════════════════════════════════════════════════════
# ПОИСК ПРОДУКТОВ
# ═══════════════════════════════════════════════════════════════

def search_food(query: str, limit: int = 10) -> List[Dict]:
    """Поиск продуктов по названию."""
    conn = get_db()
    # Пробуем оба регистра
    rows = conn.execute(
        """SELECT * FROM food_products 
           WHERE name LIKE ? OR name LIKE ?
           ORDER BY times_used DESC, name
           LIMIT ?""",
        (f"%{query}%", f"%{query.lower()}%", limit)
    ).fetchall()

    # Если не найдено, пробуем с заглавной
    if not rows:
        rows = conn.execute(
            """SELECT * FROM food_products 
               WHERE name LIKE ?
               ORDER BY times_used DESC, name
               LIMIT ?""",
            (f"%{query.title()}%", limit)
        ).fetchall()

    return [dict(r) for r in rows]

def get_food_by_id(food_id: int) -> Optional[Dict]:
    """Получить продукт по ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM food_products WHERE id = ?", (food_id,)).fetchone()
    return dict(row) if row else None


def add_food_product(
        name: str,
        category: str = "",
        calories: float = 0,
        protein: float = 0,
        fat: float = 0,
        carbs: float = 0,
        brand: str = "",
        source: str = "custom",
        source_id: str = None,
        added_by: int = None,
        is_verified: int = 0,
        serving: float = 100,
) -> Optional[int]:
    """Добавить продукт в базу (food_products). Возвращает ID или None, если дубликат."""
    conn = get_db()
    existing = conn.execute(
        """SELECT id FROM food_products
           WHERE name = ? AND COALESCE(source, '') = ? AND COALESCE(source_id, '') = ?""",
        (name, source, source_id or ""),
    ).fetchone()
    if existing:
        return None
    cur = conn.execute(
        """INSERT INTO food_products
           (name, brand, category, calories_100g, protein_100g, fat_100g, carbs_100g,
            serving_size_g, is_verified, added_by, source, source_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, brand, category, calories, protein, fat, carbs,
         serving, is_verified, added_by, source, source_id),
    )
    conn.commit()
    return cur.lastrowid


def get_products_by_category(category: str, verified_only: bool = False) -> List[Dict]:
    """Получить продукты по категории."""
    conn = get_db()
    query = "SELECT * FROM food_products WHERE category = ?"
    params: list = [category]
    if verified_only:
        query += " AND is_verified = 1"
    query += " ORDER BY is_verified DESC, times_used DESC, created_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def increment_product_usage(product_id: int) -> None:
    """Увеличить счётчик использования продукта (крауд-верификация)."""
    conn = get_db()
    conn.execute("UPDATE food_products SET times_used = times_used + 1 WHERE id = ?", (product_id,))
    conn.execute(
        "UPDATE food_products SET is_verified = 1 WHERE id = ? AND times_used >= 3 AND is_verified = 0",
        (product_id,),
    )
    conn.commit()


def cleanup_unused_products(days: int = 30) -> int:
    """Удалить невостребованные продукты (не проверенные и не использованные)."""
    from datetime import timedelta
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    cur = conn.execute(
        "DELETE FROM food_products WHERE is_verified = 0 AND times_used = 0 AND created_at < ?",
        (cutoff,),
    )
    conn.commit()
    return cur.rowcount


# ═══════════════════════════════════════════════════════════════
# ДОБАВЛЕНИЕ В ДНЕВНИК
# ═══════════════════════════════════════════════════════════════

def add_food_entry(
        user_id: int,
        product_id: int,
        product_name: str,
        weight_g: float,
        calories_100g: float,
        protein_100g: float,
        fat_100g: float,
        carbs_100g: float,
        meal_type: str = "snack",
        workout_session_id: int = None,
        relative_to_workout: str = None,
) -> int:
    """
    Добавить запись в дневник питания.

    Возвращает ID записи.
    """
    # Расчёт КБЖУ на вес
    multiplier = weight_g / 100.0
    calories = round(calories_100g * multiplier, 1)
    protein = round(protein_100g * multiplier, 1)
    fat = round(fat_100g * multiplier, 1)
    carbs = round(carbs_100g * multiplier, 1)

    conn = get_db()
    cur = conn.execute(
        """INSERT INTO food_log_new 
           (user_id, product_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g,
            meal_type, meal_time, workout_session_id, relative_to_workout)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, product_id, product_name, weight_g, calories, protein, fat, carbs,
         meal_type, _local_now_hm(user_id), workout_session_id, relative_to_workout)
    )
    conn.commit()

    # Обновляем счётчик использования продукта
    conn.execute("UPDATE food_products SET times_used = times_used + 1 WHERE id = ?", (product_id,))
    conn.commit()

    return cur.lastrowid


def add_custom_food_entry(
        user_id: int,
        product_name: str,
        weight_g: float,
        calories: float,
        protein_g: float,
        fat_g: float,
        carbs_g: float,
        meal_type: str = "snack",
) -> int:
    """Добавить кастомную еду (без продукта в базе)."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO food_log_new 
           (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g, meal_type, meal_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g,
         meal_type, _local_now_hm(user_id))
    )
    conn.commit()
    return cur.lastrowid


def delete_food_entry(entry_id: int, user_id: int) -> bool:
    """Удалить запись дневника питания. False, если не найдена или чужая."""
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM food_log_new WHERE id = ? AND user_id = ?",
        (entry_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


# ═══════════════════════════════════════════════════════════════
# АНАЛИТИКА ЗА ДЕНЬ
# ═══════════════════════════════════════════════════════════════

def get_today_summary(user_id: int) -> Dict:
    """Получить сводку за сегодня (по локальной дате пользователя)."""
    conn = get_db()
    today = _local_today(user_id)
    day_expr = _day_expr(user_id)

    # Проверяем кэш
    cached = conn.execute(
        "SELECT * FROM daily_nutrition_summary WHERE user_id = ? AND date = ?",
        (user_id, today)
    ).fetchone()

    if cached:
        return dict(cached)

    # Считаем заново
    rows = conn.execute(
        f"""SELECT
               SUM(calories) as total_calories,
               SUM(protein_g) as total_protein,
               SUM(fat_g) as total_fat,
               SUM(carbs_g) as total_carbs,
               COUNT(*) as meals_count,
               SUM(CASE WHEN meal_type = 'breakfast' THEN calories ELSE 0 END) as breakfast_calories,
               SUM(CASE WHEN meal_type = 'lunch' THEN calories ELSE 0 END) as lunch_calories,
               SUM(CASE WHEN meal_type = 'dinner' THEN calories ELSE 0 END) as dinner_calories,
               SUM(CASE WHEN meal_type = 'snack' THEN calories ELSE 0 END) as snack_calories
           FROM food_log_new
           WHERE user_id = ? AND {day_expr} = ?""",
        (user_id, today)
    ).fetchone()

    summary = {
        "user_id": user_id,
        "date": today,
        "total_calories": rows["total_calories"] or 0,
        "total_protein_g": rows["total_protein"] or 0,
        "total_fat_g": rows["total_fat"] or 0,
        "total_carbs_g": rows["total_carbs"] or 0,
        "meals_count": rows["meals_count"] or 0,
        "breakfast_calories": rows["breakfast_calories"] or 0,
        "lunch_calories": rows["lunch_calories"] or 0,
        "dinner_calories": rows["dinner_calories"] or 0,
        "snack_calories": rows["snack_calories"] or 0,
    }

    return summary


def get_food_log_today(user_id: int) -> List[Dict]:
    """Получить все записи за сегодня (по локальной дате пользователя)."""
    conn = get_db()
    today = _local_today(user_id)
    day_expr = _day_expr(user_id)

    rows = conn.execute(
        f"""SELECT * FROM food_log_new
           WHERE user_id = ? AND {day_expr} = ?
           ORDER BY logged_at DESC""",
        (user_id, today)
    ).fetchall()

    return [dict(r) for r in rows]


def get_food_log(user_id: int, days: int = 7) -> List[Dict]:
    """Получить лог питания за последние N дней."""
    from datetime import timedelta
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM food_log_new WHERE user_id = ? AND logged_at >= ? ORDER BY logged_at DESC",
        (user_id, cutoff)
    ).fetchall()
    return [dict(r) for r in rows]


def get_food_log_by_date(user_id: int, day: str) -> List[Dict]:
    """Получить записи за конкретную ЛОКАЛЬНУЮ дату пользователя (YYYY-MM-DD)."""
    conn = get_db()
    day_expr = _day_expr(user_id)
    rows = conn.execute(
        f"""SELECT * FROM food_log_new
           WHERE user_id = ? AND {day_expr} = ?
           ORDER BY logged_at DESC""",
        (user_id, day)
    ).fetchall()
    return [dict(r) for r in rows]


def get_nutrition_history(user_id: int, days: int = 7) -> List[Dict]:
    """Получить КБЖУ по дням за последние N дней (локальные дни пользователя)."""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    day_expr = _day_expr(user_id)
    rows = conn.execute(
        f"""SELECT {day_expr} as day,
                  SUM(calories) as calories,
                  SUM(protein_g) as protein_g,
                  SUM(fat_g) as fat_g,
                  SUM(carbs_g) as carbs_g,
                  COUNT(*) as meals_count
           FROM food_log_new
           WHERE user_id = ? AND logged_at >= ?
           GROUP BY day ORDER BY day""",
        (user_id, cutoff)
    ).fetchall()
    return [dict(r) for r in rows]


def get_today_calories(user_id: int) -> float:
    """Получить сумму калорий за сегодня (локальная дата пользователя)."""
    conn = get_db()
    today = _local_today(user_id)
    day_expr = _day_expr(user_id)
    row = conn.execute(
        f"SELECT COALESCE(SUM(calories), 0) FROM food_log_new WHERE user_id = ? AND {day_expr} = ?",
        (user_id, today)
    ).fetchone()
    return float(row[0]) if row else 0.0


def get_calories_history(user_id: int, days: int = 30) -> List[Dict]:
    """Получить историю калорий по дням (локальные дни пользователя)."""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    day_expr = _day_expr(user_id)
    rows = conn.execute(
        f"SELECT {day_expr} as day, SUM(calories) as total_cal "
        "FROM food_log_new WHERE user_id = ? AND logged_at >= ? "
        "GROUP BY day ORDER BY day",
        (user_id, cutoff)
    ).fetchall()
    return [{"day": r["day"], "calories": r["total_cal"]} for r in rows]


# ═══════════════════════════════════════════════════════════════
# КАЛЬКУЛЯТОР ОЦЕНКИ ДНЯ (0-100)
# ═══════════════════════════════════════════════════════════════

def calculate_day_score(user_id: int, summary: Dict) -> int:
    """
    Рассчитать оценку дня питания (0-100).

    Критерии:
    - Калории в цели (±10%): 30 баллов
    - Белок в цели (±10%): 30 баллов
    - 3+ приёма пищи: 20 баллов
    - Питание вокруг тренировки: 20 баллов
    """
    from .nutrition_calc import get_nutrition_plan

    score = 0
    insights = []

    # Получаем цели пользователя
    plan = get_nutrition_plan(user_id)
    calorie_target = plan.get("target_calories", 2000)
    protein_target = plan.get("macros", {}).get("protein_g", 150)

    # Калории (30 баллов)
    cal_diff = abs(summary["total_calories"] - calorie_target) / calorie_target
    if cal_diff <= 0.1:
        score += 30
    elif cal_diff <= 0.2:
        score += 20
    elif cal_diff <= 0.3:
        score += 10

    # Белок (30 баллов)
    protein_diff = abs(summary["total_protein_g"] - protein_target) / protein_target
    if protein_diff <= 0.1:
        score += 30
    elif protein_diff <= 0.2:
        score += 20
    elif protein_diff <= 0.3:
        score += 10

    # Приёмы пищи (20 баллов)
    if summary["meals_count"] >= 3:
        score += 20
    elif summary["meals_count"] >= 2:
        score += 10

    # Питание вокруг тренировки (20 баллов)
    # TODO: проверить наличие записей до/после тренировки

    return score