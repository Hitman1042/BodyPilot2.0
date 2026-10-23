"""Челленджи, рейтинг друзей и share-карточка на временной БД."""

from datetime import datetime, timedelta, timezone

import pytest

from core.challenges import (
    CHALLENGES,
    check_challenges,
    get_active_challenges,
    get_challenge_progress,
    join_challenge,
)
from core.charts import build_share_card
from core.nutrition_calc import get_nutrition_plan
from core.referrals import get_friend_rating


@pytest.fixture
def challenge_user(db_conn):
    user_id = 930001
    for table in ("challenges", "food_log_new", "workout_sessions"):
        db_conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, "challenge_user"),
    )
    db_conn.execute("UPDATE users SET timezone_offset = 0 WHERE user_id = ?", (user_id,))
    db_conn.commit()
    return user_id


def _add_food(db_conn, user_id: int, day, calories: float = 500) -> None:
    db_conn.execute(
        """INSERT INTO food_log_new
           (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g, meal_time, logged_at)
           VALUES (?, 'Челлендж', 100, ?, 20, 10, 40, '12:00', ?)""",
        (user_id, calories, f"{day.isoformat()} 12:00:00"),
    )


def _add_workout(db_conn, user_id: int, day) -> None:
    db_conn.execute(
        "INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date) VALUES (?, 'strength', 45, 7, ?)",
        (user_id, day.isoformat()),
    )


def _backdate_challenge(db_conn, user_id: int, code: str, days: int) -> None:
    started_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    db_conn.execute(
        "UPDATE challenges SET started_at = ? WHERE user_id = ? AND code = ?",
        (started_at, user_id, code),
    )
    db_conn.commit()


def test_join_challenge_is_idempotent(challenge_user, db_conn):
    progress = join_challenge(challenge_user, "food_30")
    assert progress["status"] == "active"
    assert progress["current"] == 0
    assert progress["target"] == 30

    join_challenge(challenge_user, "food_30")
    count = db_conn.execute(
        "SELECT COUNT(*) FROM challenges WHERE user_id = ? AND code = 'food_30' AND status = 'active'",
        (challenge_user,),
    ).fetchone()[0]
    assert count == 1
    assert [item["code"] for item in get_active_challenges(challenge_user)] == ["food_30"]


def test_food_challenge_progress(challenge_user, db_conn):
    join_challenge(challenge_user, "food_30")
    _backdate_challenge(db_conn, challenge_user, "food_30", 2)
    today = datetime.now(timezone.utc).date()
    for days_ago in (2, 1, 0):
        _add_food(db_conn, challenge_user, today - timedelta(days=days_ago))
    db_conn.commit()

    progress = get_challenge_progress(challenge_user, "food_30")
    assert progress["current"] == 3
    assert progress["target"] == 30
    assert progress["streak_days"] == 3
    assert progress["status"] == "active"


def test_workout_challenge_completed_once(challenge_user, db_conn):
    join_challenge(challenge_user, "workout_12")
    today = datetime.now(timezone.utc).date()
    for _ in range(12):
        _add_workout(db_conn, challenge_user, today)
    db_conn.commit()

    completed = check_challenges(challenge_user)
    assert [item["code"] for item in completed] == ["workout_12"]
    assert completed[0]["status"] == "completed"
    assert completed[0]["current"] == 12
    assert check_challenges(challenge_user) == []
    status = db_conn.execute(
        "SELECT status FROM challenges WHERE user_id = ? AND code = 'workout_12'",
        (challenge_user,),
    ).fetchone()[0]
    assert status == "completed"
    assert get_challenge_progress(challenge_user, "workout_12")["status"] == "completed"


def test_calorie_week_completed(challenge_user, db_conn):
    join_challenge(challenge_user, "calorie_week")
    _backdate_challenge(db_conn, challenge_user, "calorie_week", 6)
    target = round(get_nutrition_plan(challenge_user)["target_calories"])
    today = datetime.now(timezone.utc).date()
    for days_ago in range(6, -1, -1):
        _add_food(db_conn, challenge_user, today - timedelta(days=days_ago), calories=target)
    db_conn.commit()

    completed = check_challenges(challenge_user)
    assert [item["code"] for item in completed] == ["calorie_week"]
    assert completed[0]["status"] == "completed"
    assert completed[0]["current"] == 7


def test_friend_rating_formula(db_conn):
    owner_id, friend_id = 930010, 930011
    for user_id in (owner_id, friend_id):
        db_conn.execute("DELETE FROM food_log_new WHERE user_id = ?", (user_id,))
        db_conn.execute("DELETE FROM workout_sessions WHERE user_id = ?", (user_id,))
        db_conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
            (user_id, f"rating_{user_id}"),
        )
    db_conn.execute("DELETE FROM referrals WHERE inviter_id = ?", (owner_id,))
    db_conn.execute("INSERT INTO referrals (inviter_id, invited_id) VALUES (?, ?)", (owner_id, friend_id))

    today = datetime.now(timezone.utc).date()
    _add_food(db_conn, owner_id, today)
    _add_workout(db_conn, owner_id, today)
    for days_ago in (2, 1, 0):
        _add_food(db_conn, friend_id, today - timedelta(days=days_ago))
    _add_workout(db_conn, friend_id, today)
    _add_workout(db_conn, friend_id, today - timedelta(days=1))
    db_conn.commit()

    rating = get_friend_rating(owner_id)
    assert rating[0]["user_id"] == friend_id
    assert rating[0]["points"] == 2 * 10 + 3 * 5 + 3 * 3
    assert rating[1]["user_id"] == owner_id
    assert rating[1]["points"] == 1 * 10 + 1 * 5 + 1 * 3


def test_share_card_is_valid_png(challenge_user, db_conn):
    today = datetime.now(timezone.utc).date()
    _add_food(db_conn, challenge_user, today)
    _add_workout(db_conn, challenge_user, today)
    db_conn.commit()

    image = build_share_card(challenge_user)
    assert image is not None
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(image) > 10_000


def test_challenge_catalog():
    assert set(CHALLENGES) == {"food_30", "workout_12", "calorie_week"}
