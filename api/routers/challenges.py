"""Челленджи: GET /api/v1/challenges, POST /api/v1/challenges/{code}/join."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user_id
from api.schemas import ChallengeOut
from core.challenges import CHALLENGES, get_challenge_progress, join_challenge

router = APIRouter(prefix="/api/v1/challenges", tags=["challenges"])


@router.get("", response_model=list[ChallengeOut])
def challenges_catalog(user_id: int = Depends(get_current_user_id)) -> list[ChallengeOut]:
    """Каталог челленджей со статусом и прогрессом пользователя."""
    return [
        ChallengeOut(**get_challenge_progress(user_id, code))
        for code in CHALLENGES
    ]


@router.post("/{code}/join", response_model=ChallengeOut, status_code=201)
def challenge_join(code: str, user_id: int = Depends(get_current_user_id)) -> ChallengeOut:
    try:
        progress = join_challenge(user_id, code)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ChallengeOut(**progress)
