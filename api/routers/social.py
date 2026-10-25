"""Друзья: лента, Kudos и групповой прогресс челленджей."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_current_user_id
from api.schemas import (
    GroupChallengeOut,
    KudosIn,
    KudosOut,
    SocialFeedItemOut,
)
from core.social import get_feed, get_group_challenge, give_kudos

router = APIRouter(prefix="/api/v1/social", tags=["social"])


@router.get("/feed", response_model=list[SocialFeedItemOut])
def social_feed(
    limit: int = Query(default=10, ge=1, le=50),
    user_id: int = Depends(get_current_user_id),
) -> list[SocialFeedItemOut]:
    return [SocialFeedItemOut(**item) for item in get_feed(user_id, limit)]


@router.post("/kudos", response_model=KudosOut)
def social_kudos(
    payload: KudosIn,
    user_id: int = Depends(get_current_user_id),
) -> KudosOut:
    result = give_kudos(user_id, payload.target_type, payload.target_id)
    if not result["ok"]:
        status_by_error = {
            "already_given": 409,
            "not_friends": 403,
            "target_not_found": 404,
            "user_not_found": 404,
        }
        raise HTTPException(
            status_code=status_by_error.get(result["error"], 422),
            detail=result["error"],
        )
    return KudosOut(**result)


@router.get("/challenge/{code}", response_model=GroupChallengeOut)
def social_challenge(
    code: str,
    user_id: int = Depends(get_current_user_id),
) -> GroupChallengeOut:
    try:
        return GroupChallengeOut(**get_group_challenge(user_id, code))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
