"""Характер коуча и дневные микросоветы."""

from datetime import date, datetime, timedelta, timezone

from core.ai.gemini_client import CHAT_TOOLS_SYSTEM_INSTRUCTION, COACH_PERSONA
from core.scheduler import _get_users_due_for_tip, _mark_tip_sent
from core.tips import TIP_BANK, build_daily_tip, select_tip


def test_coach_persona_is_shared():
    assert "свой тренер" in COACH_PERSONA
    assert "Никогда не ругай за срывы" in COACH_PERSONA
    assert COACH_PERSONA in CHAT_TOOLS_SYSTEM_INSTRUCTION


def test_tip_bank_size_and_topics():
    assert set(TIP_BANK) == {"protein", "water", "sleep", "recovery", "workouts"}
    assert sum(len(items) for items in TIP_BANK.values()) == 30


def test_tip_rotation_is_deterministic_without_adjacent_repeats():
    days = [
        date(2026, 10, 20),
        date(2026, 10, 23),
        date(2026, 10, 27),
        date(2026, 10, 30),
    ]
    first = [select_tip(12345, day)["index"] for day in days]
    second = [select_tip(12345, day)["index"] for day in days]
    assert first == second
    assert all(current != previous for current, previous in zip(first, first[1:]))


def test_daily_tip_personalization(db_conn, monkeypatch):
    import core.tips as tips

    user_id = 960001
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
        (user_id, "tips_user"),
    )
    db_conn.commit()
    monkeypatch.setattr(
        tips,
        "select_tip",
        lambda *_args, **_kwargs: {"topic": "protein", "text": "Цель по белку: {protein_g} г.", "index": 0},
    )

    text = build_daily_tip(user_id, date(2026, 10, 20))
    assert text.startswith("💡 Совет дня:")
    assert "Цель по белку:" in text
    assert "Записал уже обед? Просто напиши, что съел." in text


def test_tip_scheduler_activity_and_dedupe(db_conn, monkeypatch):
    import core.scheduler as scheduler

    active_user = 960002
    inactive_user = 960003
    for user_id in (active_user, inactive_user):
        db_conn.execute("DELETE FROM tip_log WHERE user_id = ?", (user_id,))
        db_conn.execute("DELETE FROM food_log_new WHERE user_id = ?", (user_id,))
        db_conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, timezone_offset) VALUES (?, ?, 0)",
            (user_id, f"tips_{user_id}"),
        )
    db_conn.execute(
        """INSERT INTO food_log_new
           (user_id, product_name, weight_g, calories, protein_g, fat_g, carbs_g, meal_time, logged_at)
           VALUES (?, 'Активность', 100, 500, 20, 10, 50, '12:00', '2026-10-19 12:00:00')""",
        (active_user,),
    )
    db_conn.commit()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 20, 13, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(scheduler, "datetime", FixedDateTime)
    due = _get_users_due_for_tip()
    assert (active_user, "2026-10-20") in due
    assert all(user_id != inactive_user for user_id, _ in due)

    _mark_tip_sent(active_user, "2026-10-20")
    assert all(user_id != active_user for user_id, _ in _get_users_due_for_tip())
