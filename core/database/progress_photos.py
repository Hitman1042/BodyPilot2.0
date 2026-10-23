"""Операции с фото прогресса (telegram file_id, байты не храним)."""

from __future__ import annotations

from typing import Any, Optional

from .connection import get_db


def add_progress_photo(
    user_id: int,
    file_id: str,
    weight_kg: Optional[float] = None,
    note: str = "",
) -> int:
    """Сохранить фото прогресса, вернуть id записи."""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO progress_photos (user_id, file_id, weight_kg, note) VALUES (?, ?, ?, ?)",
        (user_id, file_id, weight_kg, note),
    )
    conn.commit()
    return cur.lastrowid or 0


def get_progress_photos(user_id: int, limit: int = 0) -> list[dict[str, Any]]:
    """Фото прогресса пользователя, новые первыми. limit=0 — все."""
    conn = get_db()
    sql = "SELECT * FROM progress_photos WHERE user_id = ? ORDER BY taken_at DESC, id DESC"
    params: tuple = (user_id,)
    if limit > 0:
        sql += " LIMIT ?"
        params = (user_id, limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_progress_photo(photo_id: int, user_id: int) -> Optional[dict[str, Any]]:
    """Одно фото прогресса пользователя (проверка владельца) или None."""
    row = get_db().execute(
        "SELECT * FROM progress_photos WHERE id = ? AND user_id = ?",
        (photo_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def count_progress_photos(user_id: int) -> int:
    """Сколько фото прогресса у пользователя."""
    row = get_db().execute(
        "SELECT COUNT(*) AS cnt FROM progress_photos WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row["cnt"]) if row else 0
