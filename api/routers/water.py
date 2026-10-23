"""Вода: GET /api/v1/water/today, POST /api/v1/water."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import get_current_user_id
from api.schemas import WaterIn, WaterTodayOut
from core.gamification import add_water, get_today_water, get_water_target

router = APIRouter(prefix="/api/v1/water", tags=["water"])


@router.get("/today", response_model=WaterTodayOut)
def water_today(user_id: int = Depends(get_current_user_id)) -> WaterTodayOut:
    return WaterTodayOut(
        amount_ml=get_today_water(user_id),
        target_ml=get_water_target(user_id),
    )


@router.post("", response_model=WaterTodayOut, status_code=201)
def water_add(
    payload: WaterIn,
    user_id: int = Depends(get_current_user_id),
) -> WaterTodayOut:
    add_water(user_id, payload.amount_ml)
    return WaterTodayOut(
        amount_ml=get_today_water(user_id),
        target_ml=get_water_target(user_id),
    )
