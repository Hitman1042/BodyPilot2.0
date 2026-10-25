"""Фото прогресса: GET /api/v1/progress/photos, прокси файла из Telegram."""

from __future__ import annotations

import json
import time
import urllib.request

import aiohttp
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from api.auth import get_current_user_id
from api.schemas import ProgressPhotoOut
from core.config import settings
from core.database.progress_photos import (
    add_progress_photo,
    get_progress_photo,
    get_progress_photos,
)

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


MAX_PHOTO_BYTES = 20 * 1024 * 1024


async def _send_photo_to_telegram(
    user_id: int,
    data: bytes,
    filename: str,
    content_type: str,
) -> str:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise HTTPException(status_code=503, detail="Telegram bot token is not configured")
    form = aiohttp.FormData()
    form.add_field("chat_id", str(user_id))
    form.add_field("caption", "📸 Фото прогресса из Mini App")
    form.add_field("photo", data, filename=filename, content_type=content_type)
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.post(
                f"https://api.telegram.org/bot{token}/sendPhoto", data=form
            ) as response:
                payload = await response.json(content_type=None)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to reach Telegram API") from exc

    if response.status != 200 or not payload.get("ok"):
        description = payload.get("description") or f"HTTP {response.status}"
        if "blocked" in description.lower():
            description = "Бот заблокирован пользователем"
        raise HTTPException(status_code=502, detail=f"Telegram sendPhoto: {description}")
    photos = (payload.get("result") or {}).get("photo") or []
    if not photos:
        raise HTTPException(status_code=502, detail="Telegram sendPhoto returned no file_id")
    largest = max(
        photos,
        key=lambda item: (
            item.get("file_size") or 0,
            (item.get("width") or 0) * (item.get("height") or 0),
        ),
    )
    return largest["file_id"]


@router.post("", status_code=201)
async def upload_progress_photo(
    photo: UploadFile = File(...),
    weight_kg: float | None = Form(default=None, gt=20, lt=500),
    note: str = Form(default="", max_length=500),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, int]:
    content_type = (photo.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="An image file is required")
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo is larger than 20 MB")
    if not data:
        raise HTTPException(status_code=422, detail="Photo file is empty")
    file_id = await _send_photo_to_telegram(
        user_id, data, photo.filename or "progress.jpg", content_type
    )
    photo_id = add_progress_photo(user_id, file_id, weight_kg=weight_kg, note=note.strip())
    return {"id": photo_id}


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
