"""Лента друзей, Kudos и групповой прогресс челленджей."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .challenges import CHALLENGES, get_challenge_progress
from .database import get_db, get_user
from .gamification import ACHIEVEMENTS
from .records import get_personal_records

KUDOS_TARGET_TYPES = {"workout", "record", "challenge", "streak"}
_WORKOUT_TYPES = {
    "strength": "силовая",
    "cardio": "кардио",
    "hiit": "HIIT",
    "yoga": "йога",
    "stretching": "растяжка",
}


def get_friends(user_id: int) -> list[int]:
    """Друзья по обеим сторонам реферальной связи, без самого пользователя."""
    rows = get_db().execute(
        """SELECT invited_id AS friend_id FROM referrals WHERE inviter_id = ?
           UNION
           SELECT inviter_id AS friend_id FROM referrals WHERE invited_id = ?""",
        (user_id, user_id),
    ).fetchall()
    return sorted(
        int(row["friend_id"])
        for row in rows
        if int(row["friend_id"]) != user_id and get_user(int(row["friend_id"]))
    )


def _date_label(value: str) -> str:
    try:
        day = datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return str(value)
    today = datetime.now(timezone.utc).date()
    if day == today:
        return "сегодня"
    if day == today - timedelta(days=1):
        return "вчера"
    return day.strftime("%d.%m")


def _workout_feed(friend_ids: list[int]) -> list[dict[str, Any]]:
    if not friend_ids:
        return []
    placeholders = ",".join("?" for _ in friend_ids)
    rows = get_db().execute(
        f"""SELECT s.id, s.user_id, u.username, s.type, s.duration_min, s.date,
                   s.created_at,
                   COALESCE(SUM(ws.weight_kg * ws.reps), 0) AS tonnage_kg
            FROM workout_sessions s
            JOIN users u ON u.user_id = s.user_id
            LEFT JOIN workout_exercises we ON we.session_id = s.id
            LEFT JOIN workout_sets ws ON ws.workout_exercise_id = we.id
            WHERE s.user_id IN ({placeholders})
            GROUP BY s.id, s.user_id, u.username, s.type, s.duration_min, s.date, s.created_at
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT 100""",
        friend_ids,
    ).fetchall()
    items = []
    for row in rows:
        details = [f"{_WORKOUT_TYPES.get(row['type'], row['type'])} тренировка"]
        if row["duration_min"]:
            details.append(f"{int(row['duration_min'])} мин")
        details.append(_date_label(row["date"]))
        text = ", ".join(details)
        tonnage = float(row["tonnage_kg"] or 0)
        if tonnage > 0:
            text += f" · тоннаж {tonnage:g} кг"
        items.append({
            "id": int(row["id"]),
            "type": "workout",
            "text": text,
            "from_user_id": int(row["user_id"]),
            "from_username": row["username"] or "друг",
            "date": str(row["created_at"] or row["date"]),
        })
    return items


def _record_session_id(user_id: int, item: dict[str, Any]) -> int | None:
    if item["exercise_id"] is not None:
        exercise_clause = "we.exercise_id = ?"
        exercise_param: Any = item["exercise_id"]
    else:
        exercise_clause = "we.exercise_id IS NULL AND we.custom_exercise_name = ?"
        exercise_param = item["name"]
    row = get_db().execute(
        f"""SELECT s.id
            FROM workout_sessions s
            JOIN workout_exercises we ON we.session_id = s.id
            JOIN workout_sets ws ON ws.workout_exercise_id = we.id
            WHERE s.user_id = ? AND s.date = ? AND {exercise_clause} AND ws.weight_kg = ?
            ORDER BY s.created_at DESC, s.id DESC LIMIT 1""",
        (user_id, item["max_weight_date"], exercise_param, item["max_weight_kg"]),
    ).fetchone()
    return int(row["id"]) if row else None


def _record_feed(friend_ids: list[int]) -> list[dict[str, Any]]:
    first_day = (datetime.now(timezone.utc).date() - timedelta(days=6)).isoformat()
    items = []
    for friend_id in friend_ids:
        profile = get_user(friend_id)
        if not profile:
            continue
        records = get_personal_records(friend_id)
        for record in records["exercises"]:
            record_date = record["max_weight_date"]
            weight = record["max_weight_kg"]
            if not record_date or record_date < first_day or weight is None:
                continue
            session_id = _record_session_id(friend_id, record)
            if session_id is None:
                continue
            items.append({
                "id": session_id,
                "type": "record",
                "text": f"рекорд: {record['name']} — {weight:g} кг ({_date_label(record_date)})",
                "from_user_id": friend_id,
                "from_username": profile.get("username") or "друг",
                "date": f"{record_date}T23:59:59",
            })
    return items


def _achievement_feed(friend_ids: list[int]) -> list[dict[str, Any]]:
    if not friend_ids:
        return []
    placeholders = ",".join("?" for _ in friend_ids)
    rows = get_db().execute(
        f"""SELECT a.id, a.user_id, u.username, a.code, a.unlocked_at
            FROM achievements a
            JOIN users u ON u.user_id = a.user_id
            WHERE a.user_id IN ({placeholders})
              AND a.unlocked_at >= datetime('now', '-7 days')
            ORDER BY a.unlocked_at DESC, a.id DESC LIMIT 100""",
        friend_ids,
    ).fetchall()
    items = []
    for row in rows:
        achievement = ACHIEVEMENTS.get(row["code"])
        if not achievement:
            continue
        target_type = "streak" if row["code"].startswith("streak_") else "record"
        items.append({
            "id": -int(row["id"]),
            "type": target_type,
            "text": f"{achievement['emoji']} достижение «{achievement['name']}» ({_date_label(row['unlocked_at'])})",
            "from_user_id": int(row["user_id"]),
            "from_username": row["username"] or "друг",
            "date": str(row["unlocked_at"]),
        })
    return items


def _kudos_count(target_type: str, target_id: int) -> int:
    return int(get_db().execute(
        "SELECT COUNT(*) FROM kudos WHERE target_type = ? AND target_id = ?",
        (target_type, target_id),
    ).fetchone()[0])


def get_feed(user_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """События только друзей: тренировки, рекорды и достижения за 7 дней."""
    limit = max(1, min(int(limit), 50))
    friends = get_friends(user_id)
    items = _workout_feed(friends) + _record_feed(friends) + _achievement_feed(friends)
    items.sort(key=lambda item: (item["date"], item["type"], item["id"]), reverse=True)
    result = []
    for item in items[:limit]:
        item["kudos_count"] = _kudos_count(item["type"], item["id"])
        item["kudosed"] = bool(get_db().execute(
            """SELECT 1 FROM kudos
               WHERE from_user_id = ? AND target_type = ? AND target_id = ?""",
            (user_id, item["type"], item["id"]),
        ).fetchone())
        result.append(item)
    return result


def _target_owner(target_type: str, target_id: int) -> int | None:
    conn = get_db()
    if target_type in {"workout", "record"} and target_id > 0:
        row = conn.execute(
            "SELECT user_id FROM workout_sessions WHERE id = ?", (target_id,)
        ).fetchone()
    elif target_type in {"record", "streak"} and target_id < 0:
        row = conn.execute(
            "SELECT user_id FROM achievements WHERE id = ?", (-target_id,)
        ).fetchone()
    elif target_type == "challenge":
        row = conn.execute(
            "SELECT user_id FROM challenges WHERE id = ?", (target_id,)
        ).fetchone()
    else:
        return None
    return int(row["user_id"]) if row else None


def give_kudos(from_user_id: int, target_type: str, target_id: int) -> dict[str, Any]:
    """Поставить один Kudos событию друга; повтор возвращает already_given."""
    if target_type not in KUDOS_TARGET_TYPES:
        return {"ok": False, "error": "invalid_target"}
    if not get_user(from_user_id):
        return {"ok": False, "error": "user_not_found"}
    to_user_id = _target_owner(target_type, int(target_id))
    if to_user_id is None:
        return {"ok": False, "error": "target_not_found"}
    if to_user_id == from_user_id or to_user_id not in get_friends(from_user_id):
        return {"ok": False, "error": "not_friends"}

    conn = get_db()
    cursor = conn.execute(
        """INSERT OR IGNORE INTO kudos (from_user_id, to_user_id, target_type, target_id)
           VALUES (?, ?, ?, ?)""",
        (from_user_id, to_user_id, target_type, int(target_id)),
    )
    conn.commit()
    count = _kudos_count(target_type, int(target_id))
    if cursor.rowcount != 1:
        return {
            "ok": False,
            "error": "already_given",
            "to_user_id": to_user_id,
            "count": count,
        }
    return {"ok": True, "to_user_id": to_user_id, "count": count}


def get_group_challenge(user_id: int, code: str) -> dict[str, Any]:
    """Прогресс пользователя и всех его друзей по одному челленджу."""
    if code not in CHALLENGES:
        raise ValueError("Неизвестный челлендж")
    if not get_user(user_id):
        raise ValueError("Пользователь не найден")
    participants = []
    for participant_id in [user_id] + get_friends(user_id):
        profile = get_user(participant_id)
        progress = get_challenge_progress(participant_id, code)
        participants.append({
            "user_id": participant_id,
            "username": "Вы" if participant_id == user_id else (profile.get("username") or "друг"),
            "current": progress["current"],
            "target": progress["target"],
            "status": progress["status"],
            "is_self": participant_id == user_id,
        })
    catalog = CHALLENGES[code]
    return {
        "code": code,
        "name": catalog["name"],
        "unit": catalog["unit"],
        "participants": participants,
        "user_joined": participants[0]["status"] != "not_joined",
    }
