"""Генератор тестовых данных для BodyPilot (60 дней).

Запускать из корня проекта:
    python -m data.seed_test_data
"""

import random
from datetime import date, timedelta
from core.database import get_db, get_user

# ID пользователя, которого ты хочешь наполнить (hitman1042)
USER_ID = None  # заполним автоматически по username

def main():
    conn = get_db()
    # Найдём пользователя по username
    user = conn.execute("SELECT user_id FROM users WHERE username = 'hitman1042'").fetchone()
    if not user:
        # Если нет, возьмём первого попавшегося
        user = conn.execute("SELECT user_id FROM users LIMIT 1").fetchone()
    if not user:
        print("Нет пользователей в базе!")
        return
    USER_ID = user["user_id"]
    print(f"Генерируем данные для user_id={USER_ID}")

    end_date = date.today()
    start_date = end_date - timedelta(days=59)

    # Продукты для случайного логирования
    products = [
        ("Овсяная каша", 350, 12, 8, 60, "breakfast"),
        ("Яичница", 300, 20, 22, 5, "breakfast"),
        ("Куриная грудка с гречкой", 550, 45, 12, 65, "lunch"),
        ("Борщ", 400, 15, 18, 45, "lunch"),
        ("Рыба с овощами", 400, 35, 12, 30, "dinner"),
        ("Творог", 200, 18, 9, 10, "snack"),
        ("Яблоко", 80, 0.5, 0.3, 20, "snack"),
    ]
    # Упражнения
    exercises = [
        "Жим штанги лёжа",
        "Приседания со штангой",
        "Подтягивания",
        "Тяга гантели в наклоне",
        "Бег на беговой дорожке",
    ]

    total_food = 0
    total_workouts = 0
    total_weight = 0

    current_weight = 75.0  # начальный вес

    for day_offset in range(60):
        current_date = start_date + timedelta(days=day_offset)

        # 1-2 приёма пищи в день
        meals_count = random.randint(1, 2)
        for _ in range(meals_count):
            prod = random.choice(products)
            conn.execute(
                """INSERT INTO food_log_new (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g, meal_type, meal_time, logged_at)
                   VALUES (?, ?, 100, ?, ?, ?, ?, ?, '12:00', ?)""",
                (USER_ID, prod[0], prod[1], prod[2], prod[3], prod[4], prod[5], current_date.isoformat() + " 12:00:00")
            )
            total_food += 1

        # 3-4 тренировки в неделю (вероятность ~50%)
        if random.random() < 0.5:
            conn.execute(
                """INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date)
                   VALUES (?, 'strength', 60, 7, ?)""",
                (USER_ID, current_date.isoformat())
            )
            session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            ex_count = random.randint(1, 3)
            for _ in range(ex_count):
                ex_name = random.choice(exercises)
                conn.execute(
                    """INSERT INTO workout_exercises (session_id, custom_exercise_name, sort_order)
                       VALUES (?, ?, 1)""",
                    (session_id, ex_name)
                )
                we_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                for set_num in range(1, random.randint(2, 4)):
                    reps = random.randint(6, 12)
                    weight = round(random.uniform(20, 80), 1)
                    conn.execute(
                        """INSERT INTO workout_sets (workout_exercise_id, set_number, reps, weight_kg)
                           VALUES (?, ?, ?, ?)""",
                        (we_id, set_num, reps, weight)
                    )
                total_workouts += 1

        # Вес раз в 3 дня
        if day_offset % 3 == 0:
            weight_change = random.uniform(-0.3, 0.3)
            current_weight = round(current_weight + weight_change, 1)
            current_weight = max(60, min(90, current_weight))
            conn.execute(
                "INSERT INTO weight_log (user_id, weight_kg, logged_at) VALUES (?, ?, ?)",
                (USER_ID, current_weight, current_date.isoformat())
            )
            total_weight += 1

    conn.commit()
    print(f"Добавлено: {total_food} приёмов пищи, {total_workouts} тренировок, {total_weight} записей веса.")

if __name__ == "__main__":
    main()