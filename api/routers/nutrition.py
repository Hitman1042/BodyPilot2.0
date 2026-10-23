"""Питание: /api/v1/nutrition/* (сводка, дневник, история)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.auth import get_current_user_id
from api.schemas import (
    FoodEntryIn,
    FoodEntryOut,
    NutritionDaySummary,
    NutritionTodayOut,
    ProductOut,
)
from core.nutrition_calc import get_nutrition_plan
from core.nutrition_tracker import (
    _local_today,
    add_custom_food_entry,
    add_food_entry,
    delete_food_entry,
    get_food_by_id,
    get_food_log_by_date,
    get_nutrition_history,
    get_today_summary,
    search_food,
)

router = APIRouter(prefix="/api/v1/nutrition", tags=["nutrition"])


@router.get("/today", response_model=NutritionTodayOut)
def nutrition_today(user_id: int = Depends(get_current_user_id)) -> NutritionTodayOut:
    summary = get_today_summary(user_id)
    plan = get_nutrition_plan(user_id)
    macros = plan.get("macros", {}) or {}
    return NutritionTodayOut(
        **{k: summary.get(k) for k in (
            "date", "total_calories", "total_protein_g", "total_fat_g",
            "total_carbs_g", "meals_count", "breakfast_calories",
            "lunch_calories", "dinner_calories", "snack_calories",
        )},
        target_calories=plan.get("target_calories"),
        target_protein_g=macros.get("protein_g"),
        target_fat_g=macros.get("fat_g"),
        target_carbs_g=macros.get("carbs_g"),
    )


@router.get("/log", response_model=list[FoodEntryOut])
def food_log(
    day: date | None = Query(default=None, alias="date"),
    user_id: int = Depends(get_current_user_id),
) -> list[FoodEntryOut]:
    target = (day or date.today()).isoformat()
    return [FoodEntryOut(**row) for row in get_food_log_by_date(user_id, target)]


@router.post("/log", response_model=FoodEntryOut, status_code=201)
def add_food(
    payload: FoodEntryIn,
    user_id: int = Depends(get_current_user_id),
) -> FoodEntryOut:
    if payload.product_id is not None:
        product = get_food_by_id(payload.product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        entry_id = add_food_entry(
            user_id=user_id,
            product_id=payload.product_id,
            product_name=product["name"],
            weight_g=payload.weight_g,
            calories_100g=product.get("calories_100g", 0),
            protein_100g=product.get("protein_100g", 0),
            fat_100g=product.get("fat_100g", 0),
            carbs_100g=product.get("carbs_100g", 0),
            meal_type=payload.meal_type,
        )
    else:
        if not payload.product_name:
            raise HTTPException(
                status_code=422,
                detail="Provide product_id or product_name with calories",
            )
        if payload.calories is None:
            raise HTTPException(
                status_code=422,
                detail="calories is required for custom food entry",
            )
        entry_id = add_custom_food_entry(
            user_id=user_id,
            product_name=payload.product_name,
            weight_g=payload.weight_g,
            calories=payload.calories,
            protein_g=payload.protein_g or 0,
            fat_g=payload.fat_g or 0,
            carbs_g=payload.carbs_g or 0,
            meal_type=payload.meal_type,
        )
    today = _local_today(user_id)
    entry = next(
        (r for r in get_food_log_by_date(user_id, today) if r["id"] == entry_id),
        None,
    )
    if entry is None:
        raise HTTPException(status_code=500, detail="Failed to create food entry")
    return FoodEntryOut(**entry)


@router.delete("/log/{entry_id}", status_code=204, response_model=None, response_class=Response)
def delete_food(
    entry_id: int,
    user_id: int = Depends(get_current_user_id),
) -> None:
    if not delete_food_entry(entry_id, user_id):
        raise HTTPException(status_code=404, detail="Food entry not found")


@router.get("/products", response_model=list[ProductOut])
def products_search(
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
) -> list[ProductOut]:
    return [
        ProductOut(
            id=row["id"],
            name=row["name"],
            calories=row.get("calories_100g") or 0,
            protein_g=row.get("protein_100g") or 0,
            fat_g=row.get("fat_100g") or 0,
            carbs_g=row.get("carbs_100g") or 0,
            category=row.get("category") or "",
        )
        for row in search_food(query, limit)
    ]


@router.get("/summary", response_model=list[NutritionDaySummary])
def nutrition_summary(
    days: int = Query(default=7, ge=1, le=365),
    user_id: int = Depends(get_current_user_id),
) -> list[NutritionDaySummary]:
    return [NutritionDaySummary(**row) for row in get_nutrition_history(user_id, days)]
