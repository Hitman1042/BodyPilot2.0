"""Клиент для FatSecret Platform API (OAuth 2.0)."""

import httpx
from datetime import datetime, timedelta
from typing import Optional
import base64

from .config import settings

TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
API_BASE = "https://platform.fatsecret.com/rest/server.api"


class FatSecretClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._expires_at: Optional[datetime] = None

    async def _ensure_token(self):
        if self._token and self._expires_at and datetime.now() < self._expires_at:
            return
        # Формируем Basic Auth заголовок
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "client_credentials",
            "scope": "premier",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(TOKEN_URL, data=data, headers=headers)
            resp.raise_for_status()
            json_data = resp.json()
            self._token = json_data["access_token"]
            self._expires_at = datetime.now() + timedelta(seconds=json_data["expires_in"])

    async def search_foods(self, query: str, max_results: int = 10) -> list[dict]:
        """Поиск продуктов. Возвращает список с полями: name, brand, calories, protein, fat, carbs (на 100г)."""
        await self._ensure_token()
        params = {
            "method": "foods.search",
            "search_expression": query,
            "format": "json",
            "max_results": max_results,
            "include_food_data": "true",
        }
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(API_BASE, data=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            foods = data.get("foods", {}).get("food", [])
            if isinstance(foods, dict):
                foods = [foods]
            results = []
            for f in foods:
                servings = f.get("servings", {}).get("serving", [])
                if isinstance(servings, dict):
                    servings = [servings]
                gram_serving = None
                for s in servings:
                    if s.get("metric_serving_unit") == "g":
                        gram_serving = s
                        break
                if gram_serving:
                    factor = 100.0 / float(gram_serving.get("metric_serving_amount", 100))
                    results.append({
                        "name": f.get("food_name", "Unknown"),
                        "brand": f.get("brand_name", ""),
                        "source_id": f.get("food_id"),
                        "calories": float(gram_serving.get("calories", 0)) * factor,
                        "protein": float(gram_serving.get("protein", 0)) * factor,
                        "fat": float(gram_serving.get("fat", 0)) * factor,
                        "carbs": float(gram_serving.get("carbohydrate", 0)) * factor,
                    })
            return results


fatsecret_client = FatSecretClient(
    settings.FATSECRET_CLIENT_ID,
    settings.FATSECRET_CLIENT_SECRET,
)