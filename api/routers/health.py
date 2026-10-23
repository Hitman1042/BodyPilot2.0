"""GET /health — проверка живости сервиса и БД (для Docker healthcheck)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.deps import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"db unavailable: {exc}")
    return {"status": "ok", "db": "ok"}
