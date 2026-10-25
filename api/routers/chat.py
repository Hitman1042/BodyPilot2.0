"""AI-чат: текст и голос через Gemini function calling."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.auth import get_current_user_id
from api.schemas import ChatIn, ChatOut, VoiceChatOut
from core.ai.chat_history import append_history, get_history
from core.ai.gemini_client import get_gemini_client

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

CHAT_TIMEOUT_SEC = 60
VOICE_TIMEOUT_SEC = 90
MAX_VOICE_BYTES = 20 * 1024 * 1024
VOICE_MIME_TYPES = {"audio/ogg", "audio/webm", "audio/mp4", "audio/mpeg"}
RATE_LIMIT_ANSWER = "⏳ Коуч временно перегружен, попробуй через минуту."
EMPTY_TRANSCRIPT_ANSWER = "🎤 Не расслышал. Попробуй записать сообщение ещё раз."

# Один запрос за раз на пользователя (async endpoint → один поток цикла,
# set достаточно). Не путать с rate-limit: это защита от многократных кликов.
_processing: set[int] = set()


def _tool_summaries(result: dict) -> list[str]:
    return [
        item["summary"]
        for item in (result.get("tools_used") or [])
        if item.get("summary")
    ]


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
        return ChatOut(answer=RATE_LIMIT_ANSWER, tools_used=[])

    answer = result.get("text", "")
    append_history(user_id, payload.question, answer)
    return ChatOut(answer=answer, tools_used=_tool_summaries(result))


@router.post("/voice", response_model=VoiceChatOut)
async def voice_chat(
    audio: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
) -> VoiceChatOut:
    mime_type = (audio.content_type or "").split(";", 1)[0].lower()
    if mime_type not in VOICE_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Supported audio: ogg, webm, mp4, mpeg")
    audio_bytes = await audio.read(MAX_VOICE_BYTES + 1)
    if len(audio_bytes) > MAX_VOICE_BYTES:
        raise HTTPException(status_code=413, detail="Audio file is larger than 20 MB")
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Audio file is empty")
    if user_id in _processing:
        raise HTTPException(status_code=409, detail="Previous question is still processing")
    client = get_gemini_client()
    if client is None:
        raise HTTPException(status_code=503, detail="AI coach is unavailable")

    _processing.add(user_id)
    try:
        async def process_voice():
            transcription = await client.transcribe_voice(audio_bytes, mime_type)
            if transcription is None:
                raise HTTPException(status_code=503, detail="Voice recognition is unavailable")
            if transcription.get("error") == "rate_limit":
                return VoiceChatOut(answer=RATE_LIMIT_ANSWER)
            transcript = (transcription.get("transcript") or "").strip()
            if not transcript:
                return VoiceChatOut(answer=EMPTY_TRANSCRIPT_ANSWER)
            question = f"[Голосовое сообщение, расшифровка]: {transcript}"
            result = await client.chat_with_tools(
                user_id=user_id,
                question=question,
                history=get_history(user_id),
            )
            if result is None:
                raise HTTPException(status_code=503, detail="AI coach is unavailable")
            if result.get("error") == "rate_limit":
                return VoiceChatOut(transcript=transcript, answer=RATE_LIMIT_ANSWER)
            answer = result.get("text", "")
            append_history(user_id, question, answer)
            return VoiceChatOut(
                transcript=transcript,
                answer=answer,
                tools_used=_tool_summaries(result),
            )

        return await asyncio.wait_for(process_voice(), timeout=VOICE_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Voice coach timed out")
    finally:
        _processing.discard(user_id)
