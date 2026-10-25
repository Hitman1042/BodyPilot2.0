"""Профиль пользователя: GET/PATCH /api/v1/profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user_id
from api.schemas import ProfileOut, ProfileUpdate
from core.config import settings
from core.database import get_user, log_weight, update_user
from core.gamification import get_streak
from core.referrals import check_subscription_active

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


def _build_profile(user_id: int) -> ProfileOut:
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    admin_ids = {
        item.strip()
        for item in (settings.TELEGRAM_ADMIN_USER_IDS or "").split(",")
        if item.strip()
    }
    return ProfileOut(
        **{k: user.get(k) for k in ProfileOut.model_fields
           if k not in ("is_premium", "is_admin", "streak")},
        is_premium=check_subscription_active(user_id),
        is_admin=str(user_id) in admin_ids,
        streak=get_streak(user_id)["current"],
    )


@router.get("", response_model=ProfileOut)
def get_profile(user_id: int = Depends(get_current_user_id)) -> ProfileOut:
    return _build_profile(user_id)


@router.patch("", response_model=ProfileOut)
def patch_profile(
    payload: ProfileUpdate,
    user_id: int = Depends(get_current_user_id),
) -> ProfileOut:
    if not get_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    updates = payload.model_dump(exclude_none=True)
    if updates:
        update_user(user_id, **updates)
        if "weight_kg" in updates:
            log_weight(user_id, updates["weight_kg"])
    return _build_profile(user_id)
