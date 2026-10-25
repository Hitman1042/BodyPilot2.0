"""Mini App: голосовой коуч, онбординг, загрузка фото и админка."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.auth import get_current_user_id
from api.main import app
from core.database import get_user
from core.database.progress_photos import get_progress_photo
from core.referrals import check_subscription_active

TEST_API_KEY = "test-key-miniapp-parity"
TEST_USER_ID = 974001
ONBOARDING_USER_ID = 974010


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def api_key(db_conn):
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (TEST_USER_ID, "parity_user"),
    )
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
        (TEST_API_KEY, TEST_USER_ID, "pytest-miniapp-parity"),
    )
    db_conn.commit()
    return TEST_API_KEY


class FakeVoiceGemini:
    def __init__(self, transcription, chat_result=None):
        self.transcription = transcription
        self.chat_result = chat_result or {"text": "Записал", "tools_used": []}
        self.audio = None
        self.mime = None
        self.question = None

    async def transcribe_voice(self, audio_bytes, mime_type):
        self.audio = audio_bytes
        self.mime = mime_type
        return self.transcription

    async def chat_with_tools(self, user_id, question, history=None):
        self.question = question
        return self.chat_result


def test_voice_chat_transcribes_and_calls_coach(client, api_key, monkeypatch):
    fake = FakeVoiceGemini(
        {"transcript": "Я съел овсянку"},
        {"text": "Добавил овсянку", "tools_used": [{"summary": "Овсянка записана"}]},
    )
    monkeypatch.setattr("api.routers.chat.get_gemini_client", lambda: fake)
    response = client.post(
        "/api/v1/chat/voice",
        files={"audio": ("voice.webm", b"voice-bytes", "audio/webm;codecs=opus")},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    assert response.json() == {
        "transcript": "Я съел овсянку",
        "answer": "Добавил овсянку",
        "tools_used": ["Овсянка записана"],
    }
    assert fake.audio == b"voice-bytes"
    assert fake.mime == "audio/webm"
    assert fake.question == "[Голосовое сообщение, расшифровка]: Я съел овсянку"


def test_voice_chat_empty_transcript_returns_200(client, api_key, monkeypatch):
    fake = FakeVoiceGemini({"transcript": "  "})
    monkeypatch.setattr("api.routers.chat.get_gemini_client", lambda: fake)
    response = client.post(
        "/api/v1/chat/voice",
        files={"audio": ("voice.ogg", b"voice", "audio/ogg")},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    assert "Не расслышал" in response.json()["answer"]
    assert fake.question is None


def test_voice_chat_rate_limit_returns_200(client, api_key, monkeypatch):
    fake = FakeVoiceGemini({"error": "rate_limit"})
    monkeypatch.setattr("api.routers.chat.get_gemini_client", lambda: fake)
    response = client.post(
        "/api/v1/chat/voice",
        files={"audio": ("voice.mp4", b"voice", "audio/mp4")},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    assert "перегружен" in response.json()["answer"]


def test_onboarding_creates_profile_computes_norms_and_starts_trial(client, db_conn):
    app.dependency_overrides[get_current_user_id] = lambda: ONBOARDING_USER_ID
    try:
        assert client.get("/api/v1/profile").status_code == 404
        response = client.post("/api/v1/onboarding", json={
            "username": "Новый пользователь",
            "gender": "female",
            "age": 29,
            "height_cm": 168,
            "weight_kg": 62.5,
            "goal": "lose",
            "activity": "moderate",
            "allergies": "орехи",
            "city": "Москва",
            "timezone_offset": 180,
            "preferred_time": "08:30",
        })
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201
    body = response.json()
    assert body["profile"]["user_id"] == ONBOARDING_USER_ID
    assert body["profile"]["gender"] == "female"
    assert body["profile"]["is_premium"] is True
    assert body["computed"]["bmr"] > 0
    assert body["computed"]["tdee"] > body["computed"]["bmr"]
    assert body["computed"]["daily_calorie_goal"] < body["computed"]["tdee"]
    user = get_user(ONBOARDING_USER_ID)
    assert user["allergies"] == "орехи"
    assert user["timezone_offset"] == 180
    assert check_subscription_active(ONBOARDING_USER_ID)


def test_progress_photo_upload_uses_telegram_file_id(client, api_key, monkeypatch):
    async def fake_send(user_id, data, filename, content_type):
        assert user_id == TEST_USER_ID
        assert data == b"jpeg-bytes"
        assert filename == "progress.jpg"
        assert content_type == "image/jpeg"
        return "largest-telegram-file-id"

    monkeypatch.setattr("api.routers.progress._send_photo_to_telegram", fake_send)
    response = client.post(
        "/api/v1/progress/photos",
        files={"photo": ("progress.jpg", b"jpeg-bytes", "image/jpeg")},
        data={"weight_kg": "81.2", "note": "Первый месяц"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    photo = get_progress_photo(response.json()["id"], TEST_USER_ID)
    assert photo["file_id"] == "largest-telegram-file-id"
    assert photo["weight_kg"] == 81.2
    assert photo["note"] == "Первый месяц"


def test_progress_photo_telegram_error_is_502(client, api_key, monkeypatch):
    from fastapi import HTTPException

    async def fake_send(*args):
        raise HTTPException(status_code=502, detail="Telegram sendPhoto: Бот заблокирован пользователем")

    monkeypatch.setattr("api.routers.progress._send_photo_to_telegram", fake_send)
    response = client.post(
        "/api/v1/progress/photos",
        files={"photo": ("progress.png", b"png-bytes", "image/png")},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 502
    assert "заблокирован" in response.json()["detail"]


def test_admin_grant_premium_and_authorization(client, api_key, monkeypatch):
    monkeypatch.setattr("api.auth.settings.ADMIN_API_KEY", "test-admin-key")
    response = client.post(
        "/api/v1/admin/grant_premium",
        json={"user_id": TEST_USER_ID, "days": 14},
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == TEST_USER_ID
    assert body["days"] == 14
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(timezone.utc)
    assert check_subscription_active(TEST_USER_ID)
    assert client.post(
        "/api/v1/admin/grant_premium",
        json={"user_id": TEST_USER_ID, "days": 14},
    ).status_code == 401


def test_profile_contains_is_admin(client, api_key, monkeypatch):
    monkeypatch.setattr("api.routers.profile.settings.TELEGRAM_ADMIN_USER_IDS", f"12,{TEST_USER_ID}")
    response = client.get("/api/v1/profile", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert response.json()["is_admin"] is True
    monkeypatch.setattr("api.routers.profile.settings.TELEGRAM_ADMIN_USER_IDS", "12")
    response = client.get("/api/v1/profile", headers={"X-API-Key": api_key})
    assert response.json()["is_admin"] is False
