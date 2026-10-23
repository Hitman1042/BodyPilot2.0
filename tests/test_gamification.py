"""Стрики, достижения и вода на временной БД."""

from datetime import datetime, timedelta, timezone

import pytest

from core.gamification import (
    ACHIEVEMENTS,
    _achievements_text,
    add_water,
    check_and_unlock_achievements,
    get_streak,
    get_today_water,
)


@pytest.fixture
def gamification_user(db_conn):
    user_id = 910001
    for table in ("achievements", "water_log", "food_log_new", "workout_sessions", "weight_log"):
        db_conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, "gamification_user"),
    )
    db_conn.execute("UPDATE users SET timezone_offset = 0 WHERE user_id = ?", (user_id,))
    db_conn.commit()
    return user_id


def _add_food(db_conn, user_id: int, day) -> None:
    db_conn.execute(
        """INSERT INTO food_log_new
           (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g,
            meal_time, logged_at)
           VALUES (?, 'Тестовый продукт', 100, 100, 10, 5, 10, '12:00', ?)""",
        (user_id, f"{day.isoformat()} 12:00:00"),
    )


def _add_workout(db_conn, user_id: int, day) -> None:
    db_conn.execute(
        """INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date)
           VALUES (?, 'strength', 45, 7, ?)""",
        (user_id, day.isoformat()),
    )


def _add_weight(db_conn, user_id: int, day) -> None:
    db_conn.execute(
        "INSERT INTO weight_log (user_id, weight_kg, logged_at) VALUES (?, 75.0, ?)",
        (user_id, f"{day.isoformat()} 08:00:00"),
    )


def _unlocked_codes(user_id: int) -> list[str]:
    return [item["code"] for item in check_and_unlock_achievements(user_id)]


def test_streak_after_three_days(gamification_user, db_conn):
    today = datetime.now(timezone.utc).date()
    for days_ago in (2, 1, 0):
        _add_food(db_conn, gamification_user, today - timedelta(days=days_ago))
    db_conn.commit()

    assert get_streak(gamification_user) == {"current": 3, "best": 3}


def test_streak_break(gamification_user, db_conn):
    today = datetime.now(timezone.utc).date()
    for days_ago in (0, 2, 3):
        _add_food(db_conn, gamification_user, today - timedelta(days=days_ago))
    db_conn.commit()

    assert get_streak(gamification_user) == {"current": 1, "best": 2}


def test_first_food_unlocked_once(gamification_user, db_conn):
    assert check_and_unlock_achievements(gamification_user) == []

    today = datetime.now(timezone.utc).date()
    _add_food(db_conn, gamification_user, today)
    db_conn.commit()

    unlocked = check_and_unlock_achievements(gamification_user)
    assert [item["code"] for item in unlocked] == ["first_food"]
    assert check_and_unlock_achievements(gamification_user) == []
    count = db_conn.execute(
        "SELECT COUNT(*) FROM achievements WHERE user_id = ? AND code = 'first_food'",
        (gamification_user,),
    ).fetchone()[0]
    assert count == 1


def test_add_and_get_today_water(gamification_user):
    assert get_today_water(gamification_user) == 0
    assert add_water(gamification_user, 250) > 0
    assert add_water(gamification_user, 500) > 0
    assert get_today_water(gamification_user) == 750


def test_food_only_user_gets_no_workout_or_weight_achievements(gamification_user, db_conn):
    """Одна запись еды → только first_food; тренировочные/весовые не выдаются."""
    today = datetime.now(timezone.utc).date()
    _add_food(db_conn, gamification_user, today)
    db_conn.commit()

    unlocked = _unlocked_codes(gamification_user)
    assert unlocked == ["first_food"]
    for code in ("first_workout", "first_weight", "workouts_5", "workouts_10",
                 "streak_3", "food_week", "water_2l"):
        assert code not in unlocked


def test_five_workouts_unlock_workouts_5_but_not_10(gamification_user, db_conn):
    today = datetime.now(timezone.utc).date()
    for days_ago in range(5):
        _add_workout(db_conn, gamification_user, today - timedelta(days=days_ago))
    db_conn.commit()

    unlocked = _unlocked_codes(gamification_user)
    assert "first_workout" in unlocked
    assert "workouts_5" in unlocked
    assert "workouts_10" not in unlocked
    assert "first_food" not in unlocked
    assert "first_weight" not in unlocked


def test_ten_workouts_unlock_workouts_10(gamification_user, db_conn):
    today = datetime.now(timezone.utc).date()
    for days_ago in range(10):
        _add_workout(db_conn, gamification_user, today - timedelta(days=days_ago))
    db_conn.commit()

    unlocked = _unlocked_codes(gamification_user)
    assert "first_workout" in unlocked
    assert "workouts_5" in unlocked
    assert "workouts_10" in unlocked


def test_first_weight_requires_weight_entry(gamification_user, db_conn):
    assert "first_weight" not in _unlocked_codes(gamification_user)

    today = datetime.now(timezone.utc).date()
    _add_weight(db_conn, gamification_user, today)
    db_conn.commit()

    assert _unlocked_codes(gamification_user) == ["first_weight"]


def test_streak_achievements_follow_real_food_days(gamification_user, db_conn):
    today = datetime.now(timezone.utc).date()
    for days_ago in (2, 1, 0):
        _add_food(db_conn, gamification_user, today - timedelta(days=days_ago))
    db_conn.commit()

    unlocked = _unlocked_codes(gamification_user)
    assert "first_food" in unlocked
    assert "streak_3" in unlocked
    assert "streak_7" not in unlocked
    assert "food_week" not in unlocked

    for days_ago in range(3, 7):
        _add_food(db_conn, gamification_user, today - timedelta(days=days_ago))
    db_conn.commit()

    unlocked = _unlocked_codes(gamification_user)
    assert "streak_7" in unlocked
    assert "food_week" in unlocked
    assert "streak_14" not in unlocked


def test_water_2l_requires_two_litres_in_one_day(gamification_user):
    add_water(gamification_user, 1000)
    add_water(gamification_user, 500)
    assert "water_2l" not in _unlocked_codes(gamification_user)

    add_water(gamification_user, 500)
    assert "water_2l" in _unlocked_codes(gamification_user)


def test_achievements_text_single_and_multiple():
    single = _achievements_text([ACHIEVEMENTS["first_food"]])
    assert single == "🏆 Достижение разблокировано: 🍽️ Первая запись в дневнике"

    multiple = _achievements_text([ACHIEVEMENTS["first_food"], ACHIEVEMENTS["streak_3"]])
    assert multiple.startswith("🏆 Новые достижения:")
    assert "• 🍽️ Первая запись в дневнике" in multiple
    assert "• 🔥 Серия 3 дня" in multiple
    assert multiple.count("🏆") == 1
