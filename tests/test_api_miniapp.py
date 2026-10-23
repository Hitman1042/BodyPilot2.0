"""HTTP API: эндпоинты Mini App (продукты, вода, вес, планы, удаление еды, статика)."""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.nutrition_tracker import add_food_product

TEST_API_KEY = "test-key-miniapp-0001"
OTHER_API_KEY = "test-key-miniapp-0002"
EMPTY_API_KEY = "test-key-miniapp-0003"


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def api_key(db_conn, test_user):
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
        (TEST_API_KEY, test_user, "pytest-miniapp"),
    )
    db_conn.commit()
    return TEST_API_KEY


@pytest.fixture(scope="session")
def other_key(db_conn):
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (2, "otheruser"),
    )
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
        (OTHER_API_KEY, 2, "pytest-other"),
    )
    db_conn.commit()
    return OTHER_API_KEY


@pytest.fixture(scope="session")
def empty_key(db_conn):
    """Пользователь 3 с дефолтным профилем."""
    db_conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (3, "emptyuser"),
    )
    db_conn.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, user_id, name) VALUES (?, ?, ?)",
        (EMPTY_API_KEY, 3, "pytest-empty"),
    )
    db_conn.commit()
    return EMPTY_API_KEY


@pytest.mark.parametrize("method,url", [
    ("DELETE", "/api/v1/nutrition/log/1"),
    ("GET", "/api/v1/nutrition/products"),
    ("GET", "/api/v1/plans/meal/today"),
    ("GET", "/api/v1/weight/history"),
    ("GET", "/api/v1/water/today"),
    ("POST", "/api/v1/water"),
])
def test_endpoints_require_auth(client, method, url):
    assert client.request(method, url).status_code == 401


def test_delete_own_food_entry(client, api_key):
    headers = {"X-API-Key": api_key}
    resp = client.post(
        "/api/v1/nutrition/log",
        json={"product_name": "Тест на удаление", "weight_g": 100, "calories": 200},
        headers=headers,
    )
    assert resp.status_code == 201
    entry_id = resp.json()["id"]

    assert client.delete(
        f"/api/v1/nutrition/log/{entry_id}", headers=headers
    ).status_code == 204

    log = client.get("/api/v1/nutrition/log", headers=headers).json()
    assert all(e["id"] != entry_id for e in log)


def test_delete_foreign_entry_404(client, api_key, other_key):
    resp = client.post(
        "/api/v1/nutrition/log",
        json={"product_name": "Чужая запись", "weight_g": 50, "calories": 100},
        headers={"X-API-Key": api_key},
    )
    entry_id = resp.json()["id"]
    assert client.delete(
        f"/api/v1/nutrition/log/{entry_id}",
        headers={"X-API-Key": other_key},
    ).status_code == 404


def test_delete_nonexistent_entry_404(client, api_key):
    assert client.delete(
        "/api/v1/nutrition/log/999999",
        headers={"X-API-Key": api_key},
    ).status_code == 404


def test_products_search(client, api_key):
    add_food_product(
        name="Уникальный Тестопродукт",
        category="snack",
        calories=150,
        protein=5,
        fat=3,
        carbs=20,
    )
    resp = client.get(
        "/api/v1/nutrition/products",
        params={"query": "Тестопродукт"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    items = resp.json()
    match = [p for p in items if p["name"] == "Уникальный Тестопродукт"]
    assert match, f"product not found in {items}"
    product = match[0]
    assert product["calories"] == 150
    assert product["protein_g"] == 5
    assert product["category"] == "snack"


def test_water_add_and_get(client, api_key):
    headers = {"X-API-Key": api_key}
    before = client.get("/api/v1/water/today", headers=headers).json()

    resp = client.post("/api/v1/water", json={"amount_ml": 300}, headers=headers)
    assert resp.status_code == 201

    after = client.get("/api/v1/water/today", headers=headers).json()
    assert after["amount_ml"] == before["amount_ml"] + 300
    assert after["target_ml"] > 0


def test_weight_history(client, api_key):
    headers = {"X-API-Key": api_key}
    client.patch(
        "/api/v1/profile", json={"weight_kg": 88.5}, headers=headers
    )
    resp = client.get(
        "/api/v1/weight/history", params={"days": 30}, headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data, "weight history is empty"
    assert {"date", "weight_kg"} <= set(data[-1])
    assert any(p["weight_kg"] == 88.5 for p in data)


def test_meal_plan_today(client, api_key):
    headers = {"X-API-Key": api_key}
    client.patch(
        "/api/v1/profile",
        json={
            "weight_kg": 80,
            "height_cm": 180,
            "age": 30,
            "gender": "male",
            "goal": "maintain",
            "activity": "moderate",
        },
        headers=headers,
    )
    resp = client.get("/api/v1/plans/meal/today", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["calorie_target"] > 0
    for meal in ("breakfast", "lunch", "dinner", "snack"):
        assert meal in body["meals"]
        assert "name" in body["meals"][meal]
    assert body["total"]["calories"] > 0

    # Кэш на день: повторный запрос возвращает тот же план
    assert client.get("/api/v1/plans/meal/today", headers=headers).json() == body


def test_meal_plan_default_profile_ok(client, empty_key):
    # У пользователя дефолтный профиль (users имеет DEFAULT-ы) — план строится
    resp = client.get(
        "/api/v1/plans/meal/today", headers={"X-API-Key": empty_key}
    )
    assert resp.status_code == 200
    assert resp.json()["calorie_target"] > 0


def test_profile_has_streak(client, api_key):
    body = client.get("/api/v1/profile", headers={"X-API-Key": api_key}).json()
    assert "streak" in body
    assert isinstance(body["streak"], int)
    assert body["streak"] >= 0


def test_webapp_static(client):
    resp = client.get("/app/")
    assert resp.status_code == 200
    assert "BodyPilot" in resp.text
