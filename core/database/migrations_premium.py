"""Обёртки для Premium-таблиц. DDL перенесён в миграцию v10 (core/database/migrations.py)."""

from datetime import datetime, timedelta, timezone

from .connection import get_db
from .migrations import _migrate_v10


def create_premium_tables():
    """Создать таблицы для Premium и AI-лимитов (через миграцию v10)."""
    # Общее thread-local соединение: не закрывать
    conn = get_db()
    _migrate_v10(conn)
    conn.commit()

    print("✅ Таблицы Premium созданы (миграция v10)")


def add_trial_to_new_users():
    """Добавить 1 день триала всем новым пользователям."""
    conn = get_db()
    cursor = conn.cursor()

    # Находим всех пользователей без подписки
    cursor.execute("""
        SELECT users.user_id, users.created_at
        FROM users
        LEFT JOIN premium_subscriptions ON users.user_id = premium_subscriptions.user_id
        WHERE premium_subscriptions.user_id IS NULL
    """)

    users = cursor.fetchall()

    added = 0
    for user in users:
        uid = user["user_id"]
        created_at = user["created_at"]

        # Триал 1 день от даты регистрации
        try:
            started_at = datetime.fromisoformat(created_at) if created_at else datetime.now(timezone.utc)
        except Exception:
            started_at = datetime.now(timezone.utc)

        expires_at = started_at + timedelta(days=1)

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO premium_subscriptions
                (user_id, status, started_at, expires_at, trial_days, source)
                VALUES (?, 'trial', ?, ?, 1, 'new_user')
            """, (uid, started_at.isoformat(), expires_at.isoformat()))

            if cursor.rowcount > 0:
                added += 1
        except Exception as e:
            print(f"⚠️ Ошибка добавления триала пользователю {uid}: {e}")

    conn.commit()

    print(f"✅ Добавлено триалов: {added}")


if __name__ == "__main__":
    create_premium_tables()
    add_trial_to_new_users()
