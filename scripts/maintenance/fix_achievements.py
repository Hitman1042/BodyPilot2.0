"""Удалить ложные достижения из таблицы achievements.

Для каждой выданной записи заново проверяется условие по реальным данным
пользователя (та же логика, что у бота — core.gamification.evaluate_achievements).
Строки, чьё условие НЕ выполняется, удаляются.

Запуск из корня проекта:
    py -3.12 scripts/maintenance/fix_achievements.py --dry-run   # только показать
    py -3.12 scripts/maintenance/fix_achievements.py             # удалить ложные
    py -3.12 scripts/maintenance/fix_achievements.py --db path/to/other.db
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="только показать, ничего не удалять")
    parser.add_argument("--db", help="путь к файлу БД (по умолчанию — из настроек)")
    args = parser.parse_args()

    if args.db:
        os.environ["DATABASE_PATH"] = str(Path(args.db).resolve())

    from core.database import get_db
    from core.gamification import ACHIEVEMENTS, evaluate_achievements

    conn = get_db()
    rows = conn.execute(
        "SELECT id, user_id, code FROM achievements ORDER BY user_id, id"
    ).fetchall()
    if not rows:
        print("Таблица achievements пуста — нечего проверять.")
        return

    by_user: dict[int, list] = {}
    for row in rows:
        by_user.setdefault(row["user_id"], []).append(row)

    to_delete: list[int] = []
    for user_id, user_rows in by_user.items():
        try:
            qualified = evaluate_achievements(user_id)
        except Exception as exc:
            print(f"user_id={user_id}: ОШИБКА проверки ({exc}) — записи не тронуты")
            continue
        kept, removed, unknown = [], [], []
        for row in user_rows:
            code = row["code"]
            if code not in ACHIEVEMENTS:
                unknown.append(code)
            elif code in qualified:
                kept.append(code)
            else:
                removed.append(code)
                to_delete.append(row["id"])
        parts = [f"user_id={user_id}: оставлены [{', '.join(kept) or '—'}]"]
        if removed:
            parts.append(f"удалены [{', '.join(removed)}]")
        if unknown:
            parts.append(f"неизвестные коды (оставлены) [{', '.join(unknown)}]")
        print("; ".join(parts))

    if not to_delete:
        print("Ложных достижений не найдено.")
        return

    if args.dry_run:
        print(f"DRY-RUN: было бы удалено записей: {len(to_delete)}")
        return

    conn.executemany("DELETE FROM achievements WHERE id = ?", [(row_id,) for row_id in to_delete])
    conn.commit()
    print(f"Удалено ложных достижений: {len(to_delete)}")


if __name__ == "__main__":
    main()
