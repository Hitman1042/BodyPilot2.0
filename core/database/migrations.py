"""Миграции базы данных."""

from __future__ import annotations

import sqlite3
from typing import Any


def run_migrations(conn: sqlite3.Connection) -> None:
    """Запустить все миграции."""
    _migrate_v1(conn)
    _migrate_v2(conn)
    _migrate_v3(conn)
    _migrate_v4(conn)
    _migrate_v5(conn)
    _migrate_v6(conn)
    _migrate_v7(conn)
    _migrate_v8(conn)
    _migrate_v9(conn)
    _migrate_v10(conn)
    _migrate_v11(conn)
    _migrate_v12(conn)
    _migrate_v13(conn)
    _migrate_v14(conn)
    _migrate_v15(conn)
    _migrate_v16(conn)
    _migrate_v17(conn)
    _migrate_v18(conn)
    _migrate_v19(conn)
    _migrate_v20(conn)
    _migrate_v21(conn)
    _migrate_v22(conn)
    _migrate_v23(conn)

    # Установить текущую версию
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


SCHEMA_VERSION = 23


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Версия 1: Базовые таблицы."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 1:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            username     TEXT NOT NULL,
            gender       TEXT DEFAULT 'male' CHECK(gender IN ('male','female')),
            age          INTEGER DEFAULT 30,
            height_cm    REAL DEFAULT 175.0,
            weight_kg    REAL DEFAULT 70.0,
            goal         TEXT DEFAULT 'maintain' CHECK(goal IN ('lose','maintain','gain')),
            activity     TEXT DEFAULT 'moderate' CHECK(activity IN ('sedentary','moderate','high')),
            allergies    TEXT DEFAULT '',
            timezone_offset INTEGER DEFAULT 0 CHECK(timezone_offset BETWEEN -720 AND 840),
            preferred_time TEXT DEFAULT '07:00',
            referral_code TEXT UNIQUE,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS food_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(user_id),
            product_name TEXT NOT NULL,
            calories     REAL NOT NULL DEFAULT 0,
            protein_g    REAL NOT NULL DEFAULT 0,
            fat_g        REAL NOT NULL DEFAULT 0,
            carbs_g      REAL NOT NULL DEFAULT 0,
            weight_grams REAL DEFAULT 100,
            meal_type    TEXT DEFAULT 'snack' CHECK(meal_type IN ('breakfast','lunch','dinner','snack')),
            logged_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS weight_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(user_id),
            weight_kg  REAL NOT NULL,
            logged_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS daily_plans (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(user_id),
            plan_date    TEXT NOT NULL,
            meal_plan    TEXT DEFAULT '{}',
            workout_plan TEXT DEFAULT '{}',
            sent_at      TEXT,
            delivery_status TEXT DEFAULT 'pending',
            UNIQUE(user_id, plan_date)
        );
        CREATE INDEX IF NOT EXISTS idx_food_user ON food_log(user_id, logged_at);
        CREATE INDEX IF NOT EXISTS idx_weight_user ON weight_log(user_id, logged_at);
        CREATE INDEX IF NOT EXISTS idx_plans_user_date ON daily_plans(user_id, plan_date);
    """)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Версия 2: User chats."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 2:
        return

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_chats (
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            platform TEXT DEFAULT 'telegram',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    try:
        conn.execute("ALTER TABLE daily_plans ADD COLUMN delivery_status TEXT DEFAULT 'pending'")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "UPDATE daily_plans SET delivery_status = 'sent_to_host' "
        "WHERE sent_at IS NOT NULL AND delivery_status = 'pending'"
    )


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Версия 3: Подписки и рефералы."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 3:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY REFERENCES users(user_id),
            plan TEXT NOT NULL DEFAULT 'free' CHECK(plan IN ('free','premium')),
            expires_at TEXT,
            trial_used INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS bonus_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            days INTEGER NOT NULL CHECK(days > 0),
            source TEXT NOT NULL CHECK(source IN ('referral_signup','referral_payment','promo','trial')),
            source_user_id INTEGER,
            expires_at TEXT NOT NULL,
            activated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER NOT NULL REFERENCES users(user_id),
            invited_id INTEGER NOT NULL REFERENCES users(user_id),
            invited_paid INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(inviter_id, invited_id)
        );
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN referral_code TEXT UNIQUE")
    except sqlite3.OperationalError:
        pass


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """Версия 4: Город."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 4:
        return

    try:
        conn.execute("ALTER TABLE users ADD COLUMN city TEXT DEFAULT 'Moscow'")
    except sqlite3.OperationalError:
        pass


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """Версия 5: Категории еды."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 5:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS food_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            target_cal_ratio REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS food_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT DEFAULT '',
            category_id INTEGER REFERENCES food_categories(id),
            source TEXT NOT NULL DEFAULT 'custom',
            source_id TEXT,
            calories_100g REAL NOT NULL,
            protein_100g REAL NOT NULL,
            fat_100g REAL NOT NULL,
            carbs_100g REAL NOT NULL,
            serving_size_g REAL DEFAULT 100,
            added_by INTEGER REFERENCES users(user_id),
            is_verified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source, source_id)
        );
    """)


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """Версия 6: Счётчик использования продуктов."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 6:
        return

    try:
        conn.execute("ALTER TABLE food_items ADD COLUMN times_used INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE food_items ADD COLUMN is_deleted INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """Версия 7: Тренировки с упражнениями."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 7:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            muscle_group TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('strength','cardio','stretching')),
            equipment TEXT DEFAULT '',
            description TEXT DEFAULT '',
            is_custom INTEGER DEFAULT 0,
            added_by INTEGER REFERENCES users(user_id),
            source TEXT DEFAULT 'wger',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_exercises_muscle ON exercises(muscle_group);
        CREATE INDEX IF NOT EXISTS idx_exercises_type ON exercises(type);

        CREATE TABLE IF NOT EXISTS workout_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            type TEXT NOT NULL CHECK(type IN ('strength','cardio','hiit','yoga','stretching')),
            duration_min INTEGER,
            intensity INTEGER CHECK(intensity BETWEEN 1 AND 10),
            date DATE NOT NULL DEFAULT (date('now')),
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ws_user_date ON workout_sessions(user_id, date);

        CREATE TABLE IF NOT EXISTS workout_exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
            exercise_id INTEGER REFERENCES exercises(id),
            custom_exercise_name TEXT,
            sort_order INTEGER DEFAULT 0,
            rest_sec INTEGER DEFAULT 90,
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS workout_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_exercise_id INTEGER NOT NULL REFERENCES workout_exercises(id) ON DELETE CASCADE,
            set_number INTEGER NOT NULL,
            reps INTEGER NOT NULL,
            weight_kg REAL DEFAULT 0,
            rpe INTEGER CHECK(rpe BETWEEN 1 AND 10)
        );

        CREATE TABLE IF NOT EXISTS daily_workout_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            date DATE NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, date)
        );

        CREATE TABLE IF NOT EXISTS plan_exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES daily_workout_plans(id) ON DELETE CASCADE,
            exercise_id INTEGER REFERENCES exercises(id),
            sort_order INTEGER DEFAULT 0,
            sets INTEGER,
            reps_min INTEGER,
            reps_max INTEGER,
            weight_kg REAL,
            duration_min INTEGER,
            intensity INTEGER,
            rest_sec INTEGER DEFAULT 90,
            notes TEXT DEFAULT ''
        );
    """)


def _migrate_v8(conn: sqlite3.Connection) -> None:
    """Версия 8: Таблицы трекера питания."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 8:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS food_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_en TEXT,
            brand TEXT,
            category TEXT,
            calories_100g REAL NOT NULL DEFAULT 0,
            protein_100g REAL NOT NULL DEFAULT 0,
            fat_100g REAL NOT NULL DEFAULT 0,
            carbs_100g REAL NOT NULL DEFAULT 0,
            fiber_100g REAL DEFAULT 0,
            sugar_100g REAL DEFAULT 0,
            sodium_mg_100g REAL DEFAULT 0,
            potassium_mg_100g REAL DEFAULT 0,
            calcium_mg_100g REAL DEFAULT 0,
            iron_mg_100g REAL DEFAULT 0,
            vitamin_c_mg_100g REAL DEFAULT 0,
            vitamin_d_mcg_100g REAL DEFAULT 0,
            vitamin_b12_mcg_100g REAL DEFAULT 0,
            magnesium_mg_100g REAL DEFAULT 0,
            zinc_mg_100g REAL DEFAULT 0,
            glycemic_index INTEGER DEFAULT 50,
            serving_size_g REAL DEFAULT 100,
            is_verified INTEGER DEFAULT 0,
            times_used INTEGER DEFAULT 0,
            added_by INTEGER,
            source TEXT DEFAULT 'user',
            source_id TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_food_products_name ON food_products(name);
        CREATE INDEX IF NOT EXISTS idx_food_products_category ON food_products(category);

        CREATE TABLE IF NOT EXISTS food_log_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(user_id),
            product_id INTEGER REFERENCES food_products(id),
            product_name TEXT NOT NULL,
            weight_g REAL NOT NULL,
            calories REAL NOT NULL,
            protein_g REAL NOT NULL,
            fat_g REAL NOT NULL,
            carbs_g REAL NOT NULL,
            fiber_g REAL DEFAULT 0,
            sugar_g REAL DEFAULT 0,
            sodium_mg REAL DEFAULT 0,
            meal_type TEXT DEFAULT 'snack',
            meal_time TEXT NOT NULL,
            logged_at TEXT DEFAULT (datetime('now')),
            workout_session_id INTEGER,
            relative_to_workout TEXT,
            user_rating INTEGER CHECK(user_rating BETWEEN 1 AND 5),
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_food_log_user ON food_log_new(user_id, logged_at);
        CREATE INDEX IF NOT EXISTS idx_food_log_meal ON food_log_new(user_id, meal_type);

        CREATE TABLE IF NOT EXISTS daily_nutrition_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(user_id),
            date DATE NOT NULL,
            total_calories REAL DEFAULT 0,
            total_protein_g REAL DEFAULT 0,
            total_fat_g REAL DEFAULT 0,
            total_carbs_g REAL DEFAULT 0,
            total_fiber_g REAL DEFAULT 0,
            total_sugar_g REAL DEFAULT 0,
            total_sodium_mg REAL DEFAULT 0,
            meals_count INTEGER DEFAULT 0,
            breakfast_calories REAL DEFAULT 0,
            lunch_calories REAL DEFAULT 0,
            dinner_calories REAL DEFAULT 0,
            snack_calories REAL DEFAULT 0,
            workout_today INTEGER DEFAULT 0,
            pre_workout_meal INTEGER DEFAULT 0,
            post_workout_meal INTEGER DEFAULT 0,
            calorie_target REAL DEFAULT 0,
            calorie_diff REAL DEFAULT 0,
            protein_target REAL DEFAULT 0,
            protein_diff REAL DEFAULT 0,
            day_score INTEGER DEFAULT 0,
            insights TEXT DEFAULT '[]',
            UNIQUE(user_id, date)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_summary_user ON daily_nutrition_summary(user_id, date);
    """)


def _migrate_v9(conn: sqlite3.Connection) -> None:
    """Версия 9: Виды спорта и маппинг упражнений."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 9:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            name_en TEXT NOT NULL UNIQUE,
            description TEXT,
            icon TEXT DEFAULT '🏃',
            priority_modules TEXT DEFAULT '["special","strength","accessory"]',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sport_exercises (
            sport_id INTEGER REFERENCES sports(id),
            exercise_id INTEGER REFERENCES exercises(id),
            relevance REAL DEFAULT 1.0 CHECK(relevance BETWEEN 0 AND 1),
            module_preference TEXT DEFAULT 'accessory',
            PRIMARY KEY (sport_id, exercise_id)
        );
        CREATE INDEX IF NOT EXISTS idx_sport_exercises_sport ON sport_exercises(sport_id);
        CREATE INDEX IF NOT EXISTS idx_sport_exercises_exercise ON sport_exercises(exercise_id);
    """)

    try:
        conn.execute("ALTER TABLE users ADD COLUMN sport_id INTEGER REFERENCES sports(id)")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN sport_level TEXT DEFAULT 'beginner'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN training_phase TEXT DEFAULT 'general'")
    except sqlite3.OperationalError:
        pass

    existing = conn.execute("SELECT COUNT(*) FROM sports").fetchone()[0]
    if existing == 0:
        sports_data = [
            ("Бег (шоссе/трек)", "running", "Бег на средние и длинные дистанции", "🏃", '["mobility","special","strength"]'),
            ("Плавание", "swimming", "Плавание в бассейне или открытой воде", "🏊", '["mobility","special","strength"]'),
            ("Пауэрлифтинг", "powerlifting", "Троеборье: присед, жим, тяга", "🏋️", '["special","strength","accessory"]'),
            ("Велоспорт", "cycling", "Шоссейный или трековый велоспорт", "🚴", '["mobility","special","strength"]'),
            ("Единоборства", "martial_arts", "Бокс, ММА, борьба, дзюдо", "🥊", '["mobility","special","strength","accessory"]'),
            ("Игровые виды", "team_sports", "Футбол, баскетбол, волейбол", "🏀", '["mobility","special","strength"]'),
            ("Скалолазание", "climbing", "Скалодром или естественный рельеф", "🧗", '["mobility","special","strength","accessory"]'),
            ("Тяжёлая атлетика", "weightlifting", "Рывок и толчок штанги", "🏋️‍♀️", '["special","strength"]'),
            ("Кроссфит", "crossfit", "Функциональный фитнес, WOD", "🤸", '["mobility","special","strength","accessory"]'),
            ("Фитнес/ЗОЖ", "fitness", "Общее физическое развитие, здоровье", "🧘", '["warmup","mobility","strength","cool_down"]'),
        ]
        for name, name_en, desc, icon, priority in sports_data:
            conn.execute(
                "INSERT INTO sports (name, name_en, description, icon, priority_modules) VALUES (?, ?, ?, ?, ?)",
                (name, name_en, desc, icon, priority)
            )
        conn.commit()

def _migrate_v10(conn: sqlite3.Connection) -> None:
    """Версия 10: Premium-подписки, AI-лимиты и база знаний ИИ."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 10:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS premium_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            status TEXT DEFAULT 'trial',
            started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            trial_days INTEGER DEFAULT 1,
            source TEXT DEFAULT 'new_user',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ai_usage_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            feature TEXT NOT NULL,
            used_count INTEGER DEFAULT 0,
            limit_count INTEGER DEFAULT 0,
            reset_at TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, feature, reset_at)
        );
        CREATE TABLE IF NOT EXISTS premium_features_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            feature TEXT NOT NULL,
            used_at TEXT DEFAULT (datetime('now')),
            is_premium BOOLEAN DEFAULT FALSE,
            details TEXT
        );
        CREATE TABLE IF NOT EXISTS return_trials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            days_inactive INTEGER NOT NULL,
            trial_days INTEGER NOT NULL,
            granted_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL,
            used BOOLEAN DEFAULT FALSE,
            UNIQUE(user_id, days_inactive)
        );
        CREATE INDEX IF NOT EXISTS idx_premium_user_id ON premium_subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_premium_status ON premium_subscriptions(status);
        CREATE INDEX IF NOT EXISTS idx_ai_usage_user ON ai_usage_limits(user_id, feature);
        CREATE INDEX IF NOT EXISTS idx_ai_usage_reset ON ai_usage_limits(reset_at);
        CREATE INDEX IF NOT EXISTS idx_features_log_user ON premium_features_log(user_id, used_at);

        CREATE TABLE IF NOT EXISTS ai_knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_hash TEXT NOT NULL UNIQUE,
            question_template TEXT NOT NULL,
            answer_template TEXT NOT NULL,
            answer_full TEXT,
            context_tags TEXT,
            usage_count INTEGER DEFAULT 0,
            avg_rating REAL DEFAULT 0,
            total_ratings INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ai_response_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            route TEXT NOT NULL,
            gemini_cost REAL DEFAULT 0,
            response_time_ms INTEGER DEFAULT 0,
            user_rating INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ai_question_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL,
            category TEXT NOT NULL,
            template_text TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_hash ON ai_knowledge_base(question_hash);
        CREATE INDEX IF NOT EXISTS idx_knowledge_category ON ai_knowledge_base(context_tags);
        CREATE INDEX IF NOT EXISTS idx_response_log_user ON ai_response_log(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_response_log_route ON ai_response_log(route);
        CREATE INDEX IF NOT EXISTS idx_templates_pattern ON ai_question_templates(pattern);
    """)

    # Сидинг базовых regex-шаблонов (только если таблица пуста)
    existing = conn.execute("SELECT COUNT(*) FROM ai_question_templates").fetchone()[0]
    if existing == 0:
        templates = [
            (r"(?i).*сколько.*белк.*", "nutrition",
             "Для вашей цели {goal} и веса {weight}кг нужно {protein}г белка в день. Источники: курица, рыба, творог, яйца.", 10),
            (r"(?i).*сколько.*калорий.*", "nutrition",
             "Ваша норма: {calories} ккал/день. Для {goal}: {target_calories} ккал.", 10),
            (r"(?i).*как.*набрать.*вес.*", "nutrition",
             "Для набора веса создайте профицит 300-500 ккал. Добавьте 2-3 приёма пищи, увеличьте порции углеводов.", 9),
            (r"(?i).*как.*похудеть.*", "nutrition",
             "Для похудения создайте дефицит 300-500 ккал. Увеличьте белок, добавьте кардио.", 9),
            (r"(?i).*что.*съесть.*", "nutrition", "Рекомендую: {food_options}. КБЖУ: {kbzhu}.", 8),
            (r"(?i).*как.*тренировать.*", "workout",
             "Для {muscle} рекомендую: {exercises}. 3-4 подхода по 8-12 повторений.", 9),
            (r"(?i).*программ.*тренировк.*", "workout",
             "Ваш план: {workout_plan}. Частота: {frequency} раз/неделю.", 8),
            (r"(?i).*плато.*тренировк.*", "workout",
             "Плато — это нормально. Попробуйте: сменить упражнения, увеличить веса, добавить отдых.", 7),
            (r"(?i).*почему.*нет.*прогресс.*", "progress",
             "Прогресс зависит от: питания (40%), тренировок (30%), восстановления (30%). Проверьте: {check_list}.", 8),
            (r"(?i).*как.*ускорить.*прогресс.*", "progress",
             "Для ускорения: 1) Увеличьте калории на 200, 2) Добавьте 1 тренировку, 3) Спите 8+ часов.", 7),
            (r"(?i).*что.*такое.*кбжу.*", "general",
             "КБЖУ = Калории, Белки, Жиры, Углеводы. Основа питания для любой цели.", 10),
            (r"(?i).*что.*такое.*дефицит.*", "general",
             "Дефицит калорий = едите меньше чем тратите. Нужно для похудения.", 9),
            (r"(?i).*что.*такое.*профицит.*", "general",
             "Профицит калорий = едите больше чем тратите. Нужно для набора массы.", 9),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO ai_question_templates (pattern, category, template_text, priority) "
            "VALUES (?, ?, ?, ?)",
            templates,
        )


def _migrate_v11(conn: sqlite3.Connection) -> None:
    """Версия 11: объединение трекеров питания.

    Переносит данные из старых таблиц (food_log, food_items) в новые
    (food_log_new, food_products). Старые таблицы не удаляются (бэкап).
    Идемпотентно: повторный запуск не создаёт дублей.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 11:
        return

    # food_items → food_products (категория — по имени из food_categories)
    conn.execute("""
        INSERT INTO food_products
            (name, brand, category, calories_100g, protein_100g, fat_100g, carbs_100g,
             serving_size_g, is_verified, times_used, added_by, source, source_id, created_at)
        SELECT fi.name, fi.brand,
               COALESCE((SELECT fc.name FROM food_categories fc WHERE fc.id = fi.category_id), ''),
               fi.calories_100g, fi.protein_100g, fi.fat_100g, fi.carbs_100g,
               fi.serving_size_g, fi.is_verified, fi.times_used, fi.added_by,
               fi.source, fi.source_id, fi.created_at
        FROM food_items fi
        WHERE fi.is_deleted = 0
          AND NOT EXISTS (
              SELECT 1 FROM food_products fp
              WHERE fp.name = fi.name
                AND COALESCE(fp.source, '') = COALESCE(fi.source, '')
                AND COALESCE(fp.source_id, '') = COALESCE(fi.source_id, '')
          )
    """)

    # Дозаполнить категории у продуктов, скопированных ранее без категории
    conn.execute("""
        UPDATE food_products
        SET category = (
            SELECT fc.name FROM food_items fi
            JOIN food_categories fc ON fc.id = fi.category_id
            WHERE fi.name = food_products.name
            LIMIT 1
        )
        WHERE COALESCE(category, '') = ''
          AND EXISTS (
              SELECT 1 FROM food_items fi
              JOIN food_categories fc ON fc.id = fi.category_id
              WHERE fi.name = food_products.name
          )
    """)

    # food_log → food_log_new (product_id — по совпадению имени продукта)
    conn.execute("""
        INSERT INTO food_log_new
            (user_id, product_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g,
             meal_type, meal_time, logged_at, created_at)
        SELECT fl.user_id,
               (SELECT fp.id FROM food_products fp WHERE fp.name = fl.product_name LIMIT 1),
               fl.product_name, COALESCE(fl.weight_grams, 100),
               fl.calories, fl.protein_g, fl.fat_g, fl.carbs_g,
               COALESCE(fl.meal_type, 'snack'),
               COALESCE(time(fl.logged_at), '00:00'),
               fl.logged_at, fl.logged_at
        FROM food_log fl
        WHERE NOT EXISTS (
            SELECT 1 FROM food_log_new fln
            WHERE fln.user_id = fl.user_id
              AND fln.product_name = fl.product_name
              AND fln.logged_at = fl.logged_at
        )
    """)
    conn.commit()


def _migrate_v12(conn: sqlite3.Connection) -> None:
    """Версия 12: HTTP API — API-ключи и метрики здоровья с носимых устройств."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 12:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key      TEXT NOT NULL UNIQUE,
            user_id      INTEGER NOT NULL REFERENCES users(user_id),
            name         TEXT DEFAULT '',
            is_active    INTEGER DEFAULT 1,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            last_used_at TEXT
        );

        CREATE TABLE IF NOT EXISTS health_metrics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(user_id),
            ts          TEXT NOT NULL,
            metric_type TEXT NOT NULL,
            value       REAL NOT NULL,
            source      TEXT DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_health_metrics_user
            ON health_metrics(user_id, metric_type, ts);
    """)
    conn.commit()


def _migrate_v13(conn: sqlite3.Connection) -> None:
    """Версия 13: опрос самочувствия после тренировки (петля обратной связи)."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 13:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS workout_feedback (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(user_id),
            session_id    INTEGER,
            feedback_date TEXT NOT NULL,
            difficulty    INTEGER CHECK(difficulty BETWEEN 1 AND 5),
            soreness      INTEGER CHECK(soreness BETWEEN 1 AND 5),
            energy        INTEGER CHECK(energy BETWEEN 1 AND 5),
            comment       TEXT DEFAULT '',
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_workout_feedback_user_date
            ON workout_feedback(user_id, feedback_date);
    """)
    conn.commit()


def _migrate_v14(conn: sqlite3.Connection) -> None:
    """Версия 14: вечерний чек-ин (итоги дня от пользователя)."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 14:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_checkins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(user_id),
            checkin_date  TEXT NOT NULL,
            status        TEXT NOT NULL
                          CHECK(status IN ('ok','overate','skipped_workout','custom','pending')),
            note          TEXT DEFAULT '',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, checkin_date)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_checkins_user
            ON daily_checkins(user_id, checkin_date);
    """)
    conn.commit()


def _migrate_v15(conn: sqlite3.Connection) -> None:
    """Версия 15: достижения и трекер воды."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 15:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS achievements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(user_id),
            code        TEXT NOT NULL,
            unlocked_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, code)
        );

        CREATE TABLE IF NOT EXISTS water_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(user_id),
            amount_ml  INTEGER NOT NULL,
            logged_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_water_log_user_logged
            ON water_log(user_id, logged_at);
    """)
    conn.commit()


def _migrate_v16(conn: sqlite3.Connection) -> None:
    """Версия 16: журнал еженедельных отчётов для защиты от дублей."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 16:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS report_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(user_id),
            report_type TEXT NOT NULL DEFAULT 'weekly',
            report_date TEXT NOT NULL,
            sent_at     TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, report_type, report_date)
        );
        CREATE INDEX IF NOT EXISTS idx_report_log_user_type_sent
            ON report_log(user_id, report_type, sent_at);
    """)
    conn.commit()


def _migrate_v17(conn: sqlite3.Connection) -> None:
    """Версия 17: пользовательские челленджи."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 17:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS challenges (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(user_id),
            code         TEXT NOT NULL,
            started_at   TEXT NOT NULL DEFAULT (datetime('now')),
            target_days  INTEGER NOT NULL,
            status       TEXT NOT NULL DEFAULT 'active'
                         CHECK(status IN ('active','completed','failed')),
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_challenges_user
            ON challenges(user_id, status);
    """)
    conn.commit()


def _migrate_v18(conn: sqlite3.Connection) -> None:
    """Версия 18: журнал дневных микросоветов."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 18:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tip_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL REFERENCES users(user_id),
            tip_date TEXT NOT NULL,
            sent_at  TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, tip_date)
        );
    """)
    conn.commit()


def _migrate_v19(conn: sqlite3.Connection) -> None:
    """Версия 19: журнал умных напоминаний для защиты от дублей."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 19:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reminder_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(user_id),
            reminder_type TEXT NOT NULL,
            sent_date     TEXT NOT NULL,
            sent_at       TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, reminder_type, sent_date)
        );
        CREATE INDEX IF NOT EXISTS idx_reminder_log_user
            ON reminder_log(user_id, reminder_type, sent_date);
    """)
    conn.commit()


def _migrate_v20(conn: sqlite3.Connection) -> None:
    """Версия 20: фото прогресса (храним telegram file_id, не байты)."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 20:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS progress_photos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(user_id),
            file_id    TEXT NOT NULL,
            weight_kg  REAL,
            note       TEXT NOT NULL DEFAULT '',
            taken_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_progress_photos_user
            ON progress_photos(user_id, taken_at);
    """)
    conn.commit()


def _migrate_v21(conn: sqlite3.Connection) -> None:
    """Версия 21: предпочтения пользователя (тренировки и питание).

    AI-коуч сохраняет сюда условия тренировок (место, инвентарь, частота,
    длительность) и ограничения питания (нелюбимые продукты, заметки),
    генераторы планов учитывают их при построении.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 21:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id             INTEGER PRIMARY KEY REFERENCES users(user_id),
            training_place      TEXT DEFAULT '' CHECK(training_place IN ('','home','gym','outdoor')),
            equipment           TEXT DEFAULT '',
            workouts_per_week   INTEGER DEFAULT 0,
            workout_duration_min INTEGER DEFAULT 0,
            food_exclusions     TEXT DEFAULT '',
            food_notes          TEXT DEFAULT '',
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # exercises.category используется генератором планов, но в схеме v7
    # её не было (в проде колонка появилась вне миграций) — добавляем
    try:
        conn.execute("ALTER TABLE exercises ADD COLUMN category TEXT DEFAULT 'accessory'")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def _migrate_v22(conn: sqlite3.Connection) -> None:
    """Версия 22: справочник и пользовательские ограничения здоровья."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 22:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS health_conditions (
            code              TEXT PRIMARY KEY,
            name_ru           TEXT NOT NULL,
            category          TEXT NOT NULL
                              CHECK(category IN ('injury','chronic','age','special')),
            severity_default  INTEGER NOT NULL CHECK(severity_default BETWEEN 1 AND 3),
            excluded_patterns TEXT NOT NULL DEFAULT '[]',
            load_cap          REAL NOT NULL DEFAULT 1.0,
            impact_forbidden  INTEGER NOT NULL DEFAULT 0 CHECK(impact_forbidden IN (0, 1)),
            note_ru           TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS user_health_conditions (
            user_id        INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            condition_code TEXT NOT NULL REFERENCES health_conditions(code),
            severity       INTEGER NOT NULL DEFAULT 1 CHECK(severity BETWEEN 1 AND 3),
            notes          TEXT NOT NULL DEFAULT '',
            is_active      INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
            updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, condition_code)
        );
        CREATE INDEX IF NOT EXISTS idx_user_health_conditions_active
            ON user_health_conditions(user_id, is_active);
    """)

    existing = conn.execute("SELECT COUNT(*) FROM health_conditions").fetchone()[0]
    if existing == 0:
        import json
        from core.safety import HEALTH_CONDITIONS

        conn.executemany(
            """INSERT INTO health_conditions
               (code, name_ru, category, severity_default, excluded_patterns,
                load_cap, impact_forbidden, note_ru)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    item["code"], item["name_ru"], item["category"],
                    item["severity_default"],
                    json.dumps(item["excluded_patterns"], ensure_ascii=False),
                    item["load_cap"], item["impact_forbidden"], item["note_ru"],
                )
                for item in HEALTH_CONDITIONS
            ],
        )
    conn.commit()


def _migrate_v23(conn: sqlite3.Connection) -> None:
    """Версия 23: поддержка друзей (Kudos) для событий социальной ленты."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 23:
        return

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kudos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            to_user_id   INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            target_type  TEXT NOT NULL
                         CHECK(target_type IN ('workout','record','challenge','streak')),
            target_id    INTEGER NOT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(from_user_id, to_user_id, target_type, target_id)
        );
        CREATE INDEX IF NOT EXISTS idx_kudos_to_user ON kudos(to_user_id);
    """)
    conn.commit()
