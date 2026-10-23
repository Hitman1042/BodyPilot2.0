"""Тренировки: /api/v1/workouts/plan/today, /api/v1/workouts/history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_current_user_id
from api.schemas import WorkoutPlanOut, WorkoutSessionOut
from core.database import get_user
from core.training_service import (
    generate_daily_workout_plan,
    get_daily_plan,
    get_session_history,
)

router = APIRouter(prefix="/api/v1/workouts", tags=["workouts"])


@router.get("/plan/today", response_model=WorkoutPlanOut)
def workout_plan_today(user_id: int = Depends(get_current_user_id)) -> WorkoutPlanOut:
    if not get_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    plan = get_daily_plan(user_id)
    if plan is None:
        plan = generate_daily_workout_plan(user_id)
    if not plan:
        raise HTTPException(status_code=404, detail="No workout plan available")
    return WorkoutPlanOut(**plan)


@router.get("/history", response_model=list[WorkoutSessionOut])
def workout_history(
    days: int = Query(default=7, ge=1, le=365),
    user_id: int = Depends(get_current_user_id),
) -> list[WorkoutSessionOut]:
    return [WorkoutSessionOut(**s) for s in get_session_history(user_id, days)]
