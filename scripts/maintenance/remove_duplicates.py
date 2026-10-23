"""Удаление дублей шаблонов из БД."""

from core.database import get_db


def remove_duplicate_templates():
    """Удалить дубли шаблонов по pattern."""
    conn = get_db()

    # ═══════════════════════════════════════════════════════════════
    # ПРОВЕРКА ДО УДАЛЕНИЯ
    # ═══════════════════════════════════════════════════════════════

    total = conn.execute("SELECT COUNT(*) FROM ai_question_templates").fetchone()[0]
    unique = conn.execute("SELECT COUNT(DISTINCT pattern) FROM ai_question_templates").fetchone()[0]
    duplicates = total - unique

    print("=" * 60)
    print("📊 ПРОВЕРКА ДУБЛЕЙ")
    print("=" * 60)
    print(f"Всего шаблонов: {total}")
    print(f"Уникальных pattern: {unique}")
    print(f"Дублей: {duplicates}")
    print("=" * 60)

    if duplicates == 0:
        print("✅ Дублей нет!")
        conn.close()
        return

    # ═══════════════════════════════════════════════════════════════
    # НАХОДИМ ДУБЛИ
    # ═══════════════════════════════════════════════════════════════

    print("\n🔍 Поиск дублей...")

    duplicate_patterns = conn.execute("""
        SELECT pattern, COUNT(*) as cnt
        FROM ai_question_templates
        GROUP BY pattern
        HAVING cnt > 1
    """).fetchall()

    print(f"Найдено pattern с дублями: {len(duplicate_patterns)}")

    # ═══════════════════════════════════════════════════════════════
    # УДАЛЯЕМ ДУБЛИ (оставляем первый по id)
    # ═══════════════════════════════════════════════════════════════

    print("\n🗑️ Удаление дублей...")

    deleted = 0
    for dup in duplicate_patterns:
        pattern = dup["pattern"]
        count = dup["cnt"]

        # Находим все id с этим pattern
        ids = conn.execute("""
            SELECT id FROM ai_question_templates
            WHERE pattern = ?
            ORDER BY id
        """, (pattern,)).fetchall()

        # Оставляем первый, удаляем остальные
        for id_row in ids[1:]:
            conn.execute("DELETE FROM ai_question_templates WHERE id = ?", (id_row["id"],))
            deleted += 1

    conn.commit()

    # ═══════════════════════════════════════════════════════════════
    # ПРОВЕРКА ПОСЛЕ УДАЛЕНИЯ
    # ═══════════════════════════════════════════════════════════════

    total_after = conn.execute("SELECT COUNT(*) FROM ai_question_templates").fetchone()[0]
    unique_after = conn.execute("SELECT COUNT(DISTINCT pattern) FROM ai_question_templates").fetchone()[0]

    print("\n" + "=" * 60)
    print("✅ УДАЛЕНИЕ ЗАВЕРШЕНО")
    print("=" * 60)
    print(f"Всего шаблонов: {total_after}")
    print(f"Уникальных pattern: {unique_after}")
    print(f"Удалено дублей: {deleted}")
    print("=" * 60)

    conn.close()

    return deleted


if __name__ == "__main__":
    remove_duplicate_templates()