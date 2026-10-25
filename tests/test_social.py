"""Друзья, приватная лента, Kudos и групповые челленджи."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from bot.handlers.social import send_kudos
from core.challenges import join_challenge
from core.social import get_feed, get_friends, get_group_challenge, give_kudos

OWNER = 940001
INVITER = 940002
INVITED = 940003
STRANGER = 940004
USER_IDS = (OWNER, INVITER, INVITED, STRANGER)
API_KEY = "test-social-key-0001"


@pytest.fixture
def social_users(db_conn):
    for user_id in USER_IDS:
        db_conn.execute("DELETE FROM kudos WHERE from_user_id = ? OR to_user_id = ?", (user_id, user_id))
        db_conn.execute("DELETE FROM referrals WHERE inviter_id = ? OR invited_id = ?", (user_id, user_id))
        db_conn.execute("DELETE FROM challenges WHERE user_id = ?", (user_id,))
        db_conn.execute("DELETE FROM achievements WHERE user_id = ?", (user_id,))
        db_conn.execute("DELETE FROM workout_sessions WHERE user_id = ?", (user_id,))
        db_conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
            (user_id, f"friend_{user_id}"),
        )
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, 'pytest-social')",
        (API_KEY, OWNER),
    )
    db_conn.commit()
    return OWNER


def _refer(db_conn, inviter: int, invited: int) -> None:
    db_conn.execute(
        "INSERT INTO referrals (inviter_id, invited_id) VALUES (?, ?)",
        (inviter, invited),
    )
    db_conn.commit()


def _workout(db_conn, user_id: int, duration: int = 45) -> int:
    cursor = db_conn.execute(
        """INSERT INTO workout_sessions (user_id, type, duration_min, intensity, date, created_at)
           VALUES (?, 'strength', ?, 7, date('now'), ?)""",
        (user_id, duration, datetime.now(timezone.utc).isoformat()),
    )
    db_conn.commit()
    return int(cursor.lastrowid)


def test_friends_include_both_referral_sides(social_users, db_conn):
    _refer(db_conn, INVITER, OWNER)
    _refer(db_conn, OWNER, INVITED)
    assert get_friends(OWNER) == [INVITER, INVITED]
    assert get_friends(INVITER) == [OWNER]
    assert get_friends(STRANGER) == []


def test_feed_is_private_and_kudos_are_idempotent(social_users, db_conn):
    _refer(db_conn, OWNER, INVITED)
    friend_workout = _workout(db_conn, INVITED)
    _workout(db_conn, STRANGER)

    feed = get_feed(OWNER)
    assert [item["id"] for item in feed] == [friend_workout]
    assert feed[0]["from_user_id"] == INVITED
    assert "45 мин" in feed[0]["text"]

    first = give_kudos(OWNER, "workout", friend_workout)
    second = give_kudos(OWNER, "workout", friend_workout)
    assert first == {"ok": True, "to_user_id": INVITED, "count": 1}
    assert second["ok"] is False
    assert second["error"] == "already_given"
    assert second["count"] == 1
    assert db_conn.execute("SELECT COUNT(*) FROM kudos").fetchone()[0] == 1
    assert give_kudos(STRANGER, "workout", friend_workout)["error"] == "not_friends"


def test_feed_includes_recent_achievement(social_users, db_conn):
    _refer(db_conn, OWNER, INVITED)
    cursor = db_conn.execute(
        "INSERT INTO achievements (user_id, code) VALUES (?, 'streak_3')",
        (INVITED,),
    )
    db_conn.commit()
    feed = get_feed(OWNER)
    assert len(feed) == 1
    assert feed[0]["type"] == "streak"
    assert feed[0]["id"] == -cursor.lastrowid
    assert "Серия 3 дня" in feed[0]["text"]


def test_feed_includes_recent_weight_record(social_users, db_conn):
    _refer(db_conn, OWNER, INVITED)
    session_id = _workout(db_conn, INVITED)
    exercise = db_conn.execute(
        "INSERT INTO exercises (name, muscle_group, type) VALUES ('Жим лёжа', 'chest', 'strength')"
    )
    workout_exercise = db_conn.execute(
        "INSERT INTO workout_exercises (session_id, exercise_id) VALUES (?, ?)",
        (session_id, exercise.lastrowid),
    )
    db_conn.execute(
        """INSERT INTO workout_sets (workout_exercise_id, set_number, reps, weight_kg)
           VALUES (?, 1, 5, 80)""",
        (workout_exercise.lastrowid,),
    )
    db_conn.commit()

    record = next(item for item in get_feed(OWNER) if item["type"] == "record")
    assert record["id"] == session_id
    assert "Жим лёжа" in record["text"]
    assert "80 кг" in record["text"]
    assert give_kudos(OWNER, "record", session_id)["ok"] is True


def test_kudos_handler_stores_record_and_notifies_friend(social_users, db_conn):
    _refer(db_conn, OWNER, INVITED)
    workout_id = _workout(db_conn, INVITED)
    callback = MagicMock()
    callback.data = f"kudos_workout_{workout_id}"
    callback.from_user.id = OWNER
    callback.from_user.full_name = "Аня <b>"
    callback.from_user.username = "anya"
    callback.answer = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.bot.send_message = AsyncMock()

    asyncio.run(send_kudos(callback))

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_awaited_with("Отправлено 👏")
    callback.bot.send_message.assert_awaited_once()
    recipient, notification = callback.bot.send_message.await_args.args
    assert recipient == INVITED
    assert "поддержал тебя" in notification
    assert "45 мин" in notification
    assert "&lt;b&gt;" in notification
    assert db_conn.execute(
        "SELECT to_user_id FROM kudos WHERE from_user_id = ?", (OWNER,)
    ).fetchone()[0] == INVITED


def test_group_challenge_progress_for_two_friends(social_users, db_conn):
    _refer(db_conn, INVITER, OWNER)
    _refer(db_conn, OWNER, INVITED)
    for user_id in (OWNER, INVITER, INVITED):
        join_challenge(user_id, "workout_12")
    _workout(db_conn, OWNER)
    _workout(db_conn, INVITER)
    _workout(db_conn, INVITER)
    _workout(db_conn, INVITED)

    group = get_group_challenge(OWNER, "workout_12")
    assert group["user_joined"] is True
    assert [item["current"] for item in group["participants"]] == [1, 2, 1]
    assert [item["target"] for item in group["participants"]] == [12, 12, 12]
    assert {item["username"] for item in group["participants"]} == {
        "Вы", f"friend_{INVITER}", f"friend_{INVITED}"
    }


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/v1/social/feed", None),
    ("GET", "/api/v1/social/challenge/workout_12", None),
    ("POST", "/api/v1/social/kudos", {"target_type": "workout", "target_id": 1}),
])
def test_social_api_requires_auth(client, method, path, payload):
    assert client.request(method, path, json=payload).status_code == 401


def test_social_api_feed_and_group_challenge_200(client, social_users):
    headers = {"X-API-Key": API_KEY}
    feed = client.get("/api/v1/social/feed", headers=headers)
    challenge = client.get("/api/v1/social/challenge/workout_12", headers=headers)
    assert feed.status_code == 200
    assert feed.json() == []
    assert challenge.status_code == 200
    assert challenge.json()["participants"][0]["username"] == "Вы"


def test_social_api_kudos_200_and_duplicate_409(client, social_users, db_conn):
    _refer(db_conn, OWNER, INVITED)
    workout_id = _workout(db_conn, INVITED)
    headers = {"X-API-Key": API_KEY}
    payload = {"target_type": "workout", "target_id": workout_id}
    response = client.post("/api/v1/social/kudos", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "to_user_id": INVITED, "count": 1}
    assert client.post("/api/v1/social/kudos", json=payload, headers=headers).status_code == 409
