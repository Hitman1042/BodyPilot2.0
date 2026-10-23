"""Обёртка для таблиц AI базы знаний. DDL и сидинг перенесены в миграцию v10 (core/database/migrations.py)."""

from .connection import get_db
from .migrations import _migrate_v10


def create_ai_knowledge_tables():
    """Создать таблицы для AI базы знаний (через миграцию v10)."""
    # Общее thread-local соединение: не закрывать
    conn = get_db()
    _migrate_v10(conn)
    conn.commit()

    print("✅ Таблицы AI созданы (миграция v10)")


if __name__ == "__main__":
    create_ai_knowledge_tables()
