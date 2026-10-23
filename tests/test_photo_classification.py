"""Тесты классификации фото (dish/label/receipt/other) и пересчёта КБЖУ этикетки.

Сеть не используется: ответы Gemini подменяются моками.
"""

import asyncio

import pytest

from core.ai.food_recognition import (
    parse_photo_result,
    scale_label_to_weight,
    analyze_food_photo,
)


# ═══════════════════════════════════════════════════════════════
# parse_photo_result
# ═══════════════════════════════════════════════════════════════

def test_parse_legacy_dish_without_photo_type():
    """Старый формат ответа без photo_type трактуется как dish."""
    result = {
        "food_name": "Гречка с курицей",
        "weight_g": 250,
        "calories": 320,
        "protein_g": 25,
        "fat_g": 8,
        "carbs_g": 40,
        "meal_type": "lunch",
        "confidence": 0.9,
        "health_score": 8,
        "suggestions": ["добавь овощи"],
    }
    parsed = parse_photo_result(result)
    assert parsed["photo_type"] == "dish"
    assert parsed["food_name"] == "Гречка с курицей"
    assert parsed["weight_g"] == 250.0
    assert parsed["calories"] == 320.0
    assert parsed["meal_type"] == "lunch"
    assert parsed["confidence"] == 0.9
    assert parsed["suggestions"] == ["добавь овощи"]


def test_parse_dish_with_photo_type():
    result = {
        "photo_type": "dish",
        "food_name": "Овсянка",
        "weight_g": "200",
        "calories": "180",
        "protein_g": 6,
        "fat_g": 3,
        "carbs_g": 30,
        "confidence": 0.8,
    }
    parsed = parse_photo_result(result)
    assert parsed["photo_type"] == "dish"
    assert parsed["weight_g"] == 200.0
    assert parsed["calories"] == 180.0
    assert parsed["meal_type"] == "snack"  # дефолт при отсутствии


def test_parse_label():
    result = {
        "photo_type": "label",
        "label": {
            "product_name": "Творог 5%",
            "brand": "Простоквашино",
            "calories_100g": 121,
            "protein_100g": 17,
            "fat_100g": 5,
            "carbs_100g": 1.8,
        },
        "confidence": 0.95,
    }
    parsed = parse_photo_result(result)
    assert parsed["photo_type"] == "label"
    label = parsed["label"]
    assert label["product_name"] == "Творог 5%"
    assert label["brand"] == "Простоквашино"
    assert label["calories_100g"] == 121.0
    assert label["protein_100g"] == 17.0
    assert parsed["confidence"] == 0.95


def test_parse_label_without_nutrition_becomes_other():
    result = {"photo_type": "label", "label": {"product_name": "Хлеб"}}
    parsed = parse_photo_result(result)
    assert parsed["photo_type"] == "other"


def test_parse_receipt():
    result = {
        "photo_type": "receipt",
        "receipt": {
            "items": [
                {"name": "Куриное филе", "weight_g": 500, "calories": 550,
                 "protein_g": 115, "fat_g": 10, "carbs_g": 0},
                {"name": "Яблоки", "weight_g": 1000, "calories": 470,
                 "protein_g": 4, "fat_g": 0, "carbs_g": 98},
            ]
        },
        "confidence": 0.9,
    }
    parsed = parse_photo_result(result)
    assert parsed["photo_type"] == "receipt"
    assert len(parsed["items"]) == 2
    assert parsed["items"][0]["name"] == "Куриное филе"
    assert parsed["items"][0]["calories"] == 550.0
    assert parsed["items"][1]["weight_g"] == 1000.0


def test_parse_receipt_filters_empty_items():
    result = {
        "photo_type": "receipt",
        "receipt": {"items": [{"name": ""}, {"name": "  "}, {"name": "Кефир", "calories": 120}]},
    }
    parsed = parse_photo_result(result)
    assert parsed["photo_type"] == "receipt"
    assert len(parsed["items"]) == 1
    assert parsed["items"][0]["weight_g"] == 100.0  # дефолт


def test_parse_empty_receipt_becomes_other():
    result = {"photo_type": "receipt", "receipt": {"items": []}}
    parsed = parse_photo_result(result)
    assert parsed["photo_type"] == "other"


def test_parse_other():
    parsed = parse_photo_result({"photo_type": "other", "reason": "на фото кот"})
    assert parsed["photo_type"] == "other"
    assert parsed["reason"] == "на фото кот"


def test_parse_error_and_none():
    assert parse_photo_result(None)["photo_type"] == "error"

    parsed = parse_photo_result({"error": "не распознано", "reason": "мутное фото"})
    assert parsed["photo_type"] == "error"
    assert parsed["reason"] == "мутное фото"
    assert not parsed["rate_limit"]

    parsed = parse_photo_result({"error": "rate_limit", "message": "лимит"})
    assert parsed["photo_type"] == "error"
    assert parsed["rate_limit"]


def test_parse_dish_bad_weight_defaults():
    parsed = parse_photo_result({
        "photo_type": "dish", "food_name": "Суп", "weight_g": 0, "calories": 100,
    })
    assert parsed["photo_type"] == "dish"
    assert parsed["weight_g"] == 100.0


# ═══════════════════════════════════════════════════════════════
# scale_label_to_weight
# ═══════════════════════════════════════════════════════════════

def test_scale_label_to_weight():
    label = {
        "product_name": "Творог 5%",
        "calories_100g": 121.0,
        "protein_100g": 17.0,
        "fat_100g": 5.0,
        "carbs_100g": 1.8,
    }
    food = scale_label_to_weight(label, 250)
    assert food["food_name"] == "Творог 5%"
    assert food["weight_g"] == 250
    assert food["calories"] == 302.5
    assert food["protein_g"] == 42.5
    assert food["fat_g"] == 12.5
    assert food["carbs_g"] == 4.5


def test_scale_label_100g_is_identity():
    label = {"product_name": "X", "calories_100g": 200.0,
             "protein_100g": 10.0, "fat_100g": 5.0, "carbs_100g": 20.0}
    food = scale_label_to_weight(label, 100)
    assert food["calories"] == 200.0
    assert food["carbs_g"] == 20.0


# ═══════════════════════════════════════════════════════════════
# analyze_food_photo (мок клиента, без сети)
# ═══════════════════════════════════════════════════════════════

class _FakeClient:
    def __init__(self, response):
        self._response = response

    async def recognize_food_from_photo(self, image_data):
        return self._response


def test_analyze_food_photo_uses_single_call(monkeypatch):
    fake = _FakeClient({
        "photo_type": "label",
        "label": {"product_name": "Йогурт", "brand": "",
                  "calories_100g": 60, "protein_100g": 3,
                  "fat_100g": 2, "carbs_100g": 7},
    })
    monkeypatch.setattr("core.ai.food_recognition.get_gemini_client", lambda: fake)

    parsed = asyncio.run(analyze_food_photo(b"fake-image-bytes"))
    assert parsed["photo_type"] == "label"
    assert parsed["label"]["product_name"] == "Йогурт"


def test_analyze_food_photo_no_client(monkeypatch):
    monkeypatch.setattr("core.ai.food_recognition.get_gemini_client", lambda: None)
    parsed = asyncio.run(analyze_food_photo(b"fake-image-bytes"))
    assert parsed["photo_type"] == "error"
