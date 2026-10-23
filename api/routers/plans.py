"""Планы питания: GET /api/v1/plans/meal/today."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user_id
from api.schemas import MealPlanOut
from core.database import get_user
from core.plans import generate_meal_plan
from core.preferences import get_preferences

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])

_REQUIRED_PROFILE_FIELDS = ("weight_kg", "height_cm", "age", "gender", "activity", "goal")

# Кэш плана на локальный день пользователя: {(user_id, local_date): plan}
_meal_plan_cache: dict[tuple[int, str], dict] = {}


def _local_today(user: dict) -> str:
    offset = int(user.get("timezone_offset") or 0)
    local_now = datetime.now(timezone.utc) + timedelta(minutes=offset)
    return local_now.date().isoformat()


@router.get("/meal/today", response_model=MealPlanOut)
def meal_plan_today(user_id: int = Depends(get_current_user_id)) -> MealPlanOut:
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    missing = [f for f in _REQUIRED_PROFILE_FIELDS if not user.get(f)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Profile incomplete, fill: {', '.join(missing)}",
        )
    today = _local_today(user)
    # Изменение предпочтений/аллергий сбрасывает кэш даже из другого процесса
    prefs = get_preferences(user_id)
    key = (user_id, today, prefs.get("updated_at") or "", user.get("allergies") or "")
    if key not in _meal_plan_cache:
        _meal_plan_cache[key] = generate_meal_plan({**user, "user_id": user_id})
    return MealPlanOut(date=today, **_meal_plan_cache[key])
