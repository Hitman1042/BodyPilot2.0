"""Статистика: GET /api/v1/stats?days=7 (калории, вес, тоннаж), история веса."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import get_current_user_id
from api.schemas import StatsOut, WeightPointOut
from core.database import get_weight_history_local
from core.database.stats import get_stats_for_days

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])
weight_router = APIRouter(prefix="/api/v1/weight", tags=["weight"])


@router.get("", response_model=StatsOut)
def get_stats(
    days: int = Query(default=7, ge=1, le=365),
    user_id: int = Depends(get_current_user_id),
) -> StatsOut:
    return StatsOut(**get_stats_for_days(user_id, days))


@weight_router.get("/history", response_model=list[WeightPointOut])
def weight_history(
    days: int = Query(default=30, ge=1, le=365),
    user_id: int = Depends(get_current_user_id),
) -> list[WeightPointOut]:
    return [
        WeightPointOut(**row)
        for row in get_weight_history_local(user_id, days)
    ]
