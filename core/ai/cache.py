"""Кэш для AI-ответов BodyPilot."""

import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

CACHE_DIR = Path("data/ai_cache")
CACHE_DIR.mkdir(exist_ok=True)

CACHE_TTL = {
    "nutrition_analysis": timedelta(hours=6),
    "workout_analysis": timedelta(hours=12),
    "product_recommendations": timedelta(hours=1),
    "chat_answer": timedelta(hours=24),
    "daily_digest": timedelta(hours=24),
}


def _get_cache_key(prefix: str, data: Dict) -> str:
    """Создать хэш-ключ для кэша."""
    content = json.dumps(data, sort_keys=True)
    hash_md5 = hashlib.md5(content.encode()).hexdigest()
    return f"{prefix}_{hash_md5}"


def get_cached(prefix: str, data: Dict) -> Optional[Any]:
    """Получить из кэша если не истёк TTL."""
    key = _get_cache_key(prefix, data)
    cache_file = CACHE_DIR / f"{key}.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cached = json.load(f)

        # Проверяем TTL
        created_at = datetime.fromisoformat(cached["created_at"])
        ttl = CACHE_TTL.get(prefix, timedelta(hours=1))

        if datetime.now() - created_at > ttl:
            cache_file.unlink()  # Удаляем просроченное
            return None

        return cached["data"]

    except Exception as e:
        print(f"Cache read error: {e}")
        return None


def set_cached(prefix: str, data: Dict, result: Any):
    """Сохранить в кэш."""
    key = _get_cache_key(prefix, data)
    cache_file = CACHE_DIR / f"{key}.json"

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "created_at": datetime.now().isoformat(),
                "data": result,
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Cache write error: {e}")


def clear_cache():
    """Очистить весь кэш."""
    for cache_file in CACHE_DIR.glob("*.json"):
        cache_file.unlink()
    print("AI cache cleared.")