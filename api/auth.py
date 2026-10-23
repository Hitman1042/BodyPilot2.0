"""Авторизация HTTP API.

Три механизма:
1. Telegram Mini App — заголовок X-Telegram-Init-Data (initData, HMAC-SHA256).
2. API-ключ внешних интеграций — заголовок X-API-Key (таблица api_keys).
3. Админ — заголовок X-Admin-Key (settings.ADMIN_API_KEY), только для /api/v1/admin/*.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

from api.deps import get_db
from core.config import settings


def verify_telegram_init_data(init_data: str) -> int | None:
    """Проверить initData Telegram Mini App и вернуть user_id (или None)."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return None
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(
        b"WebAppData", settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    calculated = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None
    user_raw = data.get("user")
    if not user_raw:
        return None
    try:
        return int(json.loads(user_raw)["id"])
    except (ValueError, KeyError, TypeError):
        return None


def _user_id_by_api_key(api_key: str) -> int | None:
    """Найти user_id по активному API-ключу и обновить last_used_at."""
    conn = get_db()
    row = conn.execute(
        "SELECT id, user_id FROM api_keys WHERE api_key = ? AND is_active = 1",
        (api_key,),
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    conn.commit()
    return int(row["user_id"])


def get_current_user_id(
    x_telegram_init_data: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> int:
    """user_id по X-Telegram-Init-Data или X-API-Key. Иначе — 401."""
    if x_telegram_init_data:
        user_id = verify_telegram_init_data(x_telegram_init_data)
        if user_id is not None:
            return user_id
        raise HTTPException(status_code=401, detail="Invalid Telegram init data")
    if x_api_key:
        user_id = _user_id_by_api_key(x_api_key)
        if user_id is not None:
            return user_id
        raise HTTPException(status_code=401, detail="Invalid API key")
    raise HTTPException(
        status_code=401,
        detail="Authentication required: provide X-Telegram-Init-Data or X-API-Key",
    )


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    """Проверка админ-ключа (X-Admin-Key == settings.ADMIN_API_KEY)."""
    expected = settings.ADMIN_API_KEY
    if (
        not expected
        or not x_admin_key
        or not hmac.compare_digest(x_admin_key, expected)
    ):
        raise HTTPException(status_code=401, detail="Invalid admin key")
