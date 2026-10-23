"""Импорт AI шаблонов из JSON в базу данных."""

import json
from pathlib import Path
from core.database import get_db


def import_templates(json_path: str = "core/ai/ai_templates.json"):
    """Импортировать шаблоны из JSON файла."""

    # Читаем JSON
    json_file = Path(json_path)
    if not json_file.exists():
        print(f"❌ Файл не найден: {json_file}")
        return

    with open(json_file, "r", encoding="utf-8") as f:
        templates = json.load(f)

    print(f"📦 Загружено шаблонов из JSON: {len(templates)}")

    # Подключаемся к БД
    conn = get_db()

    imported = 0
    skipped = 0
    errors = 0

    for i, tpl in enumerate(templates):
        try:
            # Проверяем обязательные поля
            if not all(k in tpl for k in ["pattern", "category", "template"]):
                skipped += 1
                continue

            # Вставляем в БД
            conn.execute("""
                INSERT OR IGNORE INTO ai_question_templates 
                (pattern, category, template_text, priority, is_active)
                VALUES (?, ?, ?, ?, TRUE)
            """, (
                tpl["pattern"],
                tpl["category"],
                tpl["template"],
                tpl.get("priority", 5),
            ))

            if conn.total_changes > imported:
                imported += 1

            # Прогресс каждые 100 шаблонов
            if (i + 1) % 100 == 0:
                print(f"  ⏳ Импортировано: {imported}...")

        except Exception as e:
            errors += 1
            print(f"  ⚠️ Ошибка импорта шаблона {i}: {e}")

    conn.commit()

    # Статистика
    print("\n" + "=" * 50)
    print("✅ ИМПОРТ ЗАВЕРШЁН")
    print("=" * 50)
    print(f"📦 Всего в JSON: {len(templates)}")
    print(f"✅ Импортировано: {imported}")
    print(f"⏭️ Пропущено: {skipped}")
    print(f"❌ Ошибок: {errors}")
    print("=" * 50)

    # Проверка сколько всего в БД
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM ai_question_templates").fetchone()[0]
    print(f"📊 Всего шаблонов в БД: {total}")


if __name__ == "__main__":
    import_templates()