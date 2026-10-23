"""HTTP API v2: AI-чат, челленджи, фото прогресса (с прокси Telegram)."""

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app

TEST_API_KEY = "test-key-v2-0001"
FOREIGN_API_KEY = "test-key-v2-0002"


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def api_key(db_conn):
    """Пользователь 10 — отдельный, чтобы не зависеть от других тестов."""
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (10, "v2user"),
    )
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
        (TEST_API_KEY, 10, "pytest-v2"),
    )
    db_conn.commit()
    return TEST_API_KEY


@pytest.fixture(scope="session")
def foreign_key(db_conn):
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (11, "v2other"),
    )
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
        (FOREIGN_API_KEY, 11, "pytest-v2-other"),
    )
    db_conn.commit()
    return FOREIGN_API_KEY


@pytest.mark.parametrize("method,url", [
    ("POST", "/api/v1/chat"),
    ("GET", "/api/v1/challenges"),
    ("POST", "/api/v1/challenges/food_30/join"),
    ("GET", "/api/v1/progress/photos"),
    ("GET", "/api/v1/progress/photos/1/file"),
])
def test_v2_endpoints_require_auth(client, method, url):
    assert client.request(method, url).status_code == 401


# ── AI-чат ───────────────────────────────────────────────────────────────


class _FakeGemini:
    async def chat_with_tools(self, user_id, question, history=None):
        return {
            "text": "Записал твой завтрак!",
            "tools_used": [{"tool": "log_food", "summary": "Записал: овсянка, 300 ккал"}],
        }


def test_chat_ok(client, api_key, monkeypatch):
    monkeypatch.setattr("api.routers.chat.get_gemini_client", lambda: _FakeGemini())
    resp = client.post(
        "/api/v1/chat",
        json={"question": "я съел овсянку"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Записал твой завтрак!"
    assert body["tools_used"] == ["Записал: овсянка, 300 ккал"]

    from core.ai.chat_history import get_history
    assert get_history(10), "история диалога не сохранилась"


def test_chat_question_too_long(client, api_key):
    resp = client.post(
        "/api/v1/chat",
        json={"question": "а" * 2001},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 422


def test_chat_one_request_at_a_time(client, api_key, monkeypatch):
    monkeypatch.setattr("api.routers.chat.get_gemini_client", lambda: _FakeGemini())
    from api.routers import chat as chat_router
    chat_router._processing.add(10)
    try:
        resp = client.post(
            "/api/v1/chat",
            json={"question": "привет"},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 409
    finally:
        chat_router._processing.discard(10)


def test_chat_unavailable_without_client(client, api_key, monkeypatch):
    monkeypatch.setattr("api.routers.chat.get_gemini_client", lambda: None)
    resp = client.post(
        "/api/v1/chat",
        json={"question": "привет"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 503


# ── Челленджи ────────────────────────────────────────────────────────────


def test_challenges_catalog(client, api_key):
    resp = client.get("/api/v1/challenges", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 3
    for ch in items:
        assert ch["status"] in ("not_joined", "active", "completed", "failed")
        assert ch["target"] > 0
        assert {"code", "name", "condition", "unit", "current"} <= set(ch)


def test_challenge_join_and_idempotent(client, api_key):
    headers = {"X-API-Key": api_key}
    resp = client.post("/api/v1/challenges/workout_12/join", headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "active"
    assert body["code"] == "workout_12"
    assert body["target"] == 12

    # Повторный join идемпотентен — тот же челлендж
    again = client.post("/api/v1/challenges/workout_12/join", headers=headers)
    assert again.status_code == 201
    assert again.json()["status"] == "active"

    catalog = client.get("/api/v1/challenges", headers=headers).json()
    joined = [c for c in catalog if c["code"] == "workout_12"]
    assert joined[0]["status"] == "active"


def test_challenge_join_unknown_code_404(client, api_key):
    resp = client.post(
        "/api/v1/challenges/no_such_code/join",
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 404


# ── Фото прогресса ───────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def photo_id(db_conn, api_key):
    from core.database.progress_photos import add_progress_photo
    return add_progress_photo(10, file_id="tg-file-abc", weight_kg=80.5, note="до")


def test_photos_list(client, api_key, photo_id):
    resp = client.get("/api/v1/progress/photos", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    items = resp.json()
    match = [p for p in items if p["id"] == photo_id]
    assert match, f"photo not found in {items}"
    photo = match[0]
    assert photo["weight_kg"] == 80.5
    assert photo["note"] == "до"
    assert photo["taken_at"]
    assert "file_id" not in photo, "file_id не должен утекать в API"


_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_photo_file_proxy_and_cache(client, api_key, photo_id, monkeypatch):
    monkeypatch.setattr(
        "api.routers.progress.settings.TELEGRAM_BOT_TOKEN", "test-token", raising=False
    )
    calls = []

    def fake_get(url):
        calls.append(url)
        if "getFile" in url:
            return json.dumps({"ok": True, "result": {"file_path": "photos/f.jpg"}}).encode()
        return _JPEG

    monkeypatch.setattr("api.routers.progress._http_get_bytes", fake_get)
    from api.routers import progress as progress_router
    progress_router._photo_cache.clear()

    headers = {"X-API-Key": api_key}
    resp = client.get(f"/api/v1/progress/photos/{photo_id}/file", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.content == _JPEG

    # Второй запрос — из кэша, Telegram не дёргается
    resp2 = client.get(f"/api/v1/progress/photos/{photo_id}/file", headers=headers)
    assert resp2.status_code == 200
    assert len(calls) == 2, f"ожидали 2 HTTP-вызова (getFile+file), было {len(calls)}"


def test_photo_file_foreign_404(client, foreign_key, photo_id):
    resp = client.get(
        f"/api/v1/progress/photos/{photo_id}/file",
        headers={"X-API-Key": foreign_key},
    )
    assert resp.status_code == 404
