"""Фото прогресса: GET /api/v1/progress/photos, прокси файла из Telegram."""

from __future__ import annotations

import json
import time
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from api.auth import get_current_user_id
from api.schemas import ProgressPhotoOut
from core.config import settings
from core.database.progress_photos import get_progress_photo, get_progress_photos

router = APIRouter(prefix="/api/v1/progress/photos", tags=["progress-photos"])

# Кэш скачанных фото: file_id → (bytes, unixtime), TTL 1 час
_photo_cache: dict[str, tuple[bytes, float]] = {}
_CACHE_TTL_SEC = 3600


def _http_get_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=20) as resp:
        return resp.read()


def _load_telegram_file(file_id: str) -> bytes:
    """file_id → bytes через Bot API getFile + скачивание, с кэшем на 1 час."""
    cached = _photo_cache.get(file_id)
    if cached and time.time() - cached[1] < _CACHE_TTL_SEC:
        return cached[0]

    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise HTTPException(status_code=503, detail="Telegram bot token is not configured")

    try:
        meta = json.loads(_http_get_bytes(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"))
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to reach Telegram API")
    file_path = (meta.get("result") or {}).get("file_path")
    if not meta.get("ok") or not file_path:
        raise HTTPException(status_code=502, detail="Telegram getFile failed")

    try:
        data = _http_get_bytes(f"https://api.telegram.org/file/bot{token}/{file_path}")
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to download file from Telegram")

    _photo_cache[file_id] = (data, time.time())
    return data


@router.get("", response_model=list[ProgressPhotoOut])
def progress_photos(user_id: int = Depends(get_current_user_id)) -> list[ProgressPhotoOut]:
    return [
        ProgressPhotoOut(
            id=row["id"],
            weight_kg=row.get("weight_kg"),
            note=row.get("note") or "",
            taken_at=str(row.get("taken_at") or ""),
        )
        for row in get_progress_photos(user_id)
    ]


@router.get("/{photo_id}/file", response_class=Response)
def progress_photo_file(photo_id: int, user_id: int = Depends(get_current_user_id)) -> Response:
    photo = get_progress_photo(photo_id, user_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    data = _load_telegram_file(photo["file_id"])
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )
