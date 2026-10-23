"""Фото прогресса: сохранение/выборка, динамика веса, условия напоминания."""

from datetime import datetime, timezone

import core.reminders as reminders
from core.database import add_progress_photo, count_progress_photos, get_progress_photos
from core.reminders import (
    REMINDER_PROGRESS_PHOTO,
    build_progress_photo_text,
    get_users_due_for_progress_photo_reminder,
    mark_reminder_sent,
)
from bot.handlers.progress_photos import build_weight_dynamics


def _add_user(db_conn, user_id: int) -> None:
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, f"pp_{user_id}"),
    )
    db_conn.execute("DELETE FROM progress_photos WHERE user_id = ?", (user_id,))
    db_conn.execute("DELETE FROM reminder_log WHERE user_id = ?", (user_id,))
    db_conn.commit()


def _add_food(db_conn, user_id: int, logged_at: str) -> None:
    db_conn.execute(
        """INSERT INTO food_log_new
           (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g, meal_time, logged_at)
           VALUES (?, 'Тест', 100, 500, 20, 10, 50, '12:00', ?)""",
        (user_id, logged_at),
    )
    db_conn.commit()


def _freeze(monkeypatch, hour: int, minute: int = 1):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 20, hour, minute, tzinfo=timezone.utc)

    monkeypatch.setattr(reminders, "datetime", FixedDateTime)


# ── Сохранение и выборка ────────────────────────────────────────────────────

def test_add_and_get_progress_photos(db_conn):
    user_id = 973001
    _add_user(db_conn, user_id)

    first = add_progress_photo(user_id, "file_id_1", weight_kg=80.0, note="старт")
    second = add_progress_photo(user_id, "file_id_2")
    third = add_progress_photo(user_id, "file_id_3", weight_kg=78.5, note="месяц спустя")
    assert first and second and third

    assert count_progress_photos(user_id) == 3

    photos = get_progress_photos(user_id)
    assert len(photos) == 3
    # Новые первыми
    assert photos[0]["file_id"] == "file_id_3"
    assert photos[2]["file_id"] == "file_id_1"
    assert photos[0]["weight_kg"] == 78.5
    assert photos[1]["weight_kg"] is None
    assert photos[1]["note"] == ""
    assert photos[2]["note"] == "старт"

    limited = get_progress_photos(user_id, limit=2)
    assert [p["file_id"] for p in limited] == ["file_id_3", "file_id_2"]

    # Чужие фото не видны
    other = 973002
    _add_user(db_conn, other)
    assert count_progress_photos(other) == 0
    assert get_progress_photos(other) == []


def test_weight_dynamics():
    photos = [
        {"taken_at": "2026-10-14 09:00:00", "weight_kg": 78.5, "id": 3},
        {"taken_at": "2026-10-07 09:00:00", "weight_kg": None, "id": 2},
        {"taken_at": "2026-09-05 09:00:00", "weight_kg": 80.0, "id": 1},
    ]
    assert build_weight_dynamics(photos) == "📉 -1.5 кг с 05.09"

    gain = [
        {"taken_at": "2026-09-05 09:00:00", "weight_kg": 70.0, "id": 1},
        {"taken_at": "2026-10-14 09:00:00", "weight_kg": 72.0, "id": 2},
    ]
    assert build_weight_dynamics(gain) == "📈 +2.0 кг с 05.09"

    flat = [
        {"taken_at": "2026-09-05 09:00:00", "weight_kg": 70.0, "id": 1},
        {"taken_at": "2026-10-14 09:00:00", "weight_kg": 70.0, "id": 2},
    ]
    assert build_weight_dynamics(flat) == "➖ Вес без изменений с 05.09"

    # Меньше двух фото с весом — динамики нет
    assert build_weight_dynamics(gain[:1]) == ""
    assert build_weight_dynamics([{"taken_at": "2026-10-14", "weight_kg": None, "id": 1}]) == ""


# ── Напоминание «время фото прогресса» (11:00, не чаще раза в 14 дней) ──────

def test_progress_photo_reminder_selection(db_conn, monkeypatch):
    active_user, inactive_user, never_user = 973010, 973011, 973012
    for uid in (active_user, inactive_user, never_user):
        _add_user(db_conn, uid)
    _add_food(db_conn, active_user, "2026-10-19 12:00:00")    # активен вчера
    _add_food(db_conn, inactive_user, "2026-10-10 12:00:00")   # активность 10 дней назад

    _freeze(monkeypatch, 11)
    due_ids = [uid for uid, _ in get_users_due_for_progress_photo_reminder()]
    assert active_user in due_ids
    assert inactive_user not in due_ids
    assert never_user not in due_ids

    # Не в окне 11:00 — не отправляем
    _freeze(monkeypatch, 10)
    assert all(uid != active_user for uid, _ in get_users_due_for_progress_photo_reminder())


def test_progress_photo_reminder_cooldown(db_conn, monkeypatch):
    reminded_today, reminded_13, reminded_14 = 973013, 973014, 973015
    for uid in (reminded_today, reminded_13, reminded_14):
        _add_user(db_conn, uid)
        _add_food(db_conn, uid, "2026-10-19 12:00:00")
    mark_reminder_sent(reminded_today, REMINDER_PROGRESS_PHOTO, "2026-10-20")
    mark_reminder_sent(reminded_13, REMINDER_PROGRESS_PHOTO, "2026-10-07")
    mark_reminder_sent(reminded_14, REMINDER_PROGRESS_PHOTO, "2026-10-06")

    _freeze(monkeypatch, 11)
    due_ids = [uid for uid, _ in get_users_due_for_progress_photo_reminder()]
    assert reminded_today not in due_ids
    assert reminded_13 not in due_ids      # прошло 13 дней — ещё рано
    assert reminded_14 in due_ids          # прошло 14 дней — пора

    # Повторная отправка сегодня не дублируется (UNIQUE в reminder_log)
    mark_reminder_sent(reminded_14, REMINDER_PROGRESS_PHOTO, "2026-10-20")
    mark_reminder_sent(reminded_14, REMINDER_PROGRESS_PHOTO, "2026-10-20")
    assert all(uid != reminded_14 for uid, _ in get_users_due_for_progress_photo_reminder())


def test_progress_photo_reminder_text():
    text = build_progress_photo_text()
    assert "📸" in text
    assert "Прогресс" in text
    assert "только ты" in text
