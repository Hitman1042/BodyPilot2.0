"""Регистрация нового пользователя Mini App."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user_id
from api.routers.profile import _build_profile
from api.schemas import OnboardingIn, OnboardingOut
from core.database import get_or_create_user, get_user, update_user
from core.nutrition_calc import compute_profile
from core.referrals import start_trial

router = APIRouter(prefix="/api/v1", tags=["onboarding"])


@router.post("/onboarding", response_model=OnboardingOut, status_code=201)
def onboarding(
    payload: OnboardingIn,
    user_id: int = Depends(get_current_user_id),
) -> OnboardingOut:
    if get_user(user_id):
        raise HTTPException(status_code=409, detail="User is already registered")

    values = payload.model_dump()
    values["username"] = (values.get("username") or "").strip() or "Пользователь"
    values["allergies"] = values.get("allergies") or ""
    values["city"] = values.get("city") or "Moscow"
    values["timezone_offset"] = values.get("timezone_offset") or 0
    values["preferred_time"] = values.get("preferred_time") or "07:00"

    get_or_create_user(user_id, values["username"])
    update_user(user_id, **values)
    start_trial(user_id)
    computed = compute_profile(
        weight_kg=values["weight_kg"],
        height_cm=values["height_cm"],
        age=values["age"],
        gender=values["gender"],
        activity=values["activity"],
        goal=values["goal"],
    )
    return OnboardingOut(profile=_build_profile(user_id), computed=computed)
