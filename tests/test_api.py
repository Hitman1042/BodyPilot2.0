"""HTTP API: healthcheck и авторизация (API-ключ)."""

import pytest
from fastapi.testclient import TestClient

from api.main import app

TEST_API_KEY = "test-key-0000000001"


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def api_key(db_conn, test_user):
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
        (TEST_API_KEY, test_user, "pytest"),
    )
    db_conn.commit()
    return TEST_API_KEY


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_profile_requires_auth(client):
    assert client.get("/api/v1/profile").status_code == 401


def test_health_metrics_require_auth(client):
    resp = client.post(
        "/api/v1/health/metrics",
        json=[{"ts": "2026-10-11T08:00:00", "metric_type": "steps", "value": 1000}],
    )
    assert resp.status_code == 401


def test_invalid_api_key_rejected(client):
    resp = client.get("/api/v1/profile", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


def test_profile_with_api_key(client, api_key):
    resp = client.get("/api/v1/profile", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == 1
    assert body["username"] == "testuser"
    assert "is_premium" in body


def test_admin_metrics_require_admin_key(client):
    assert client.get("/api/v1/admin/metrics").status_code == 401
