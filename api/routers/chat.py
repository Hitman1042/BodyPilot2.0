"""AI-чат: POST /api/v1/chat (Gemini function calling, история в памяти)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user_id
from api.schemas import ChatIn, ChatOut
from core.ai.chat_history import append_history, get_history
from core.ai.gemini_client import get_gemini_client

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

CHAT_TIMEOUT_SEC = 60

# Один запрос за раз на пользователя (async endpoint → один поток цикла,
# set достаточно). Не путать с rate-limit: это защита от многократных кликов.
_processing: set[int] = set()


@router.post("", response_model=ChatOut)
async def chat(
    payload: ChatIn,
    user_id: int = Depends(get_current_user_id),
) -> ChatOut:
    if user_id in _processing:
        raise HTTPException(status_code=409, detail="Previous question is still processing")
    client = get_gemini_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI coach is unavailable")

    _processing.add(user_id)
    try:
        result = await asyncio.wait_for(
            client.chat_with_tools(
                user_id=user_id,
                question=payload.question,
                history=get_history(user_id),
            ),
            timeout=CHAT_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="AI coach timed out")
    finally:
        _processing.discard(user_id)

    if result is None:
        raise HTTPException(status_code=503, detail="AI coach is unavailable")
    if result.get("error") == "rate_limit":
        return ChatOut(
            answer="⏳ Коуч временно перегружен, попробуй через минуту.",
            tools_used=[],
        )

    answer = result.get("text", "")
    summaries = [
        u["summary"]
        for u in (result.get("tools_used") or [])
        if u.get("summary")
    ]
    append_history(user_id, payload.question, answer)
    return ChatOut(answer=answer, tools_used=summaries)
