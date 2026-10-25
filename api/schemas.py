"""Pydantic-схемы запросов и ответов HTTP API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class ErrorResponse(BaseModel):
    detail: str


# ── Профиль ──────────────────────────────────────────────────────────────

class ProfileOut(BaseModel):
    user_id: int
    username: str
    gender: Optional[str] = None
    age: Optional[int] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    goal: Optional[str] = None
    activity: Optional[str] = None
    allergies: str = ""
    city: Optional[str] = None
    timezone_offset: int = 0
    preferred_time: Optional[str] = None
    sport_id: Optional[int] = None
    sport_level: Optional[str] = None
    referral_code: Optional[str] = None
    is_premium: bool = False
    is_admin: bool = False
    streak: Optional[int] = None


class ProfileUpdate(BaseModel):
    weight_kg: Optional[float] = Field(default=None, gt=20, lt=500)
    height_cm: Optional[float] = Field(default=None, gt=80, lt=300)
    age: Optional[int] = Field(default=None, ge=10, le=120)
    gender: Optional[Literal["male", "female"]] = None
    goal: Optional[Literal["lose", "maintain", "gain"]] = None
    activity: Optional[Literal["sedentary", "moderate", "high"]] = None
    allergies: Optional[str] = Field(default=None, max_length=500)


class OnboardingIn(BaseModel):
    username: Optional[str] = Field(default=None, max_length=100)
    gender: Literal["male", "female"]
    age: int = Field(ge=10, le=120)
    height_cm: float = Field(gt=80, lt=300)
    weight_kg: float = Field(gt=20, lt=500)
    goal: Literal["lose", "maintain", "gain"]
    activity: Literal["sedentary", "moderate", "high"]
    allergies: Optional[str] = Field(default=None, max_length=500)
    city: Optional[str] = Field(default=None, max_length=100)
    timezone_offset: Optional[int] = Field(default=None, ge=-720, le=840)
    preferred_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class ComputedProfileOut(BaseModel):
    bmi: float
    bmi_category: str
    bmr: int
    tdee: int
    daily_calorie_goal: int
    protein_g_target: float
    fat_g_target: float
    carbs_g_target: float


class OnboardingOut(BaseModel):
    profile: ProfileOut
    computed: ComputedProfileOut


# ── Питание ──────────────────────────────────────────────────────────────

class FoodEntryIn(BaseModel):
    """Запись в дневник питания: product_id ИЛИ product_name + КБЖУ."""

    product_id: Optional[int] = None
    product_name: Optional[str] = Field(default=None, max_length=200)
    weight_g: float = Field(gt=0, le=10000)
    calories: Optional[float] = Field(default=None, ge=0)
    protein_g: Optional[float] = Field(default=None, ge=0)
    fat_g: Optional[float] = Field(default=None, ge=0)
    carbs_g: Optional[float] = Field(default=None, ge=0)
    meal_type: MealType = "snack"


class FoodEntryOut(BaseModel):
    id: int
    product_id: Optional[int] = None
    product_name: str
    weight_g: float
    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float
    meal_type: Optional[str] = None
    meal_time: Optional[str] = None
    logged_at: Optional[str] = None


class NutritionTodayOut(BaseModel):
    date: str
    total_calories: float = 0
    total_protein_g: float = 0
    total_fat_g: float = 0
    total_carbs_g: float = 0
    meals_count: int = 0
    breakfast_calories: float = 0
    lunch_calories: float = 0
    dinner_calories: float = 0
    snack_calories: float = 0
    target_calories: Optional[float] = None
    target_protein_g: Optional[float] = None
    target_fat_g: Optional[float] = None
    target_carbs_g: Optional[float] = None


class NutritionDaySummary(BaseModel):
    day: str
    calories: float = 0
    protein_g: float = 0
    fat_g: float = 0
    carbs_g: float = 0
    meals_count: int = 0


class ProductOut(BaseModel):
    """Продукт из food_products (КБЖУ на 100 г)."""

    id: int
    name: str
    calories: float = 0
    protein_g: float = 0
    fat_g: float = 0
    carbs_g: float = 0
    category: str = ""


# ── Вода ─────────────────────────────────────────────────────────────────

class WaterTodayOut(BaseModel):
    amount_ml: int = 0
    target_ml: int = 0


class WaterIn(BaseModel):
    amount_ml: int = Field(gt=0, le=5000)


# ── План питания ─────────────────────────────────────────────────────────

class MealItemOut(BaseModel):
    name: str
    cal: float = 0
    p: float = 0
    f: float = 0
    c: float = 0


class MacrosTargetOut(BaseModel):
    protein_g: float = 0
    fat_g: float = 0
    carbs_g: float = 0


class MealPlanTotalOut(BaseModel):
    calories: float = 0
    protein_g: float = 0
    fat_g: float = 0
    carbs_g: float = 0


class MealPlanOut(BaseModel):
    date: str
    calorie_target: float = 0
    macros_target: MacrosTargetOut
    meals: dict[str, MealItemOut]
    total: MealPlanTotalOut


# ── Вес ──────────────────────────────────────────────────────────────────

class WeightPointOut(BaseModel):
    date: str
    weight_kg: float


# ── Тренировки ───────────────────────────────────────────────────────────

class WorkoutPlanOut(BaseModel):
    """План тренировки (структура из core.training_service, поля гибкие)."""

    model_config = ConfigDict(extra="allow")

    id: Optional[int] = None
    user_id: Optional[int] = None
    date: Optional[str] = None
    is_active: Optional[int] = None
    exercises: list[dict[str, Any]] = []
    modules: dict[str, Any] = {}


class WorkoutSessionOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    type: str
    duration_min: Optional[int] = None
    intensity: Optional[int] = None
    date: str
    notes: str = ""
    exercises: list[dict[str, Any]] = []


# ── Статистика ───────────────────────────────────────────────────────────

class StatsOut(BaseModel):
    days: int
    total_calories: float = 0
    avg_daily_calories: float = 0
    total_protein_g: float = 0
    workout_days: int = 0
    current_weight_kg: Optional[float] = None
    weight_change_kg: Optional[float] = None
    tonnage: float = 0


# ── AI-чат ───────────────────────────────────────────────────────────────

class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ChatOut(BaseModel):
    answer: str
    tools_used: list[str] = []


class VoiceChatOut(ChatOut):
    transcript: str = ""


# ── Челленджи ────────────────────────────────────────────────────────────

class ChallengeOut(BaseModel):
    code: str
    name: str
    description: str = ""
    condition: str = ""
    target: int = 0
    target_days: int = 0
    unit: str = ""
    status: str = "not_joined"
    current: int = 0
    streak_days: int = 0
    start_date: Optional[str] = None
    end_date: Optional[str] = None


# ── Друзья и Kudos ───────────────────────────────────────────────────────

class SocialFeedItemOut(BaseModel):
    id: int
    type: Literal["workout", "record", "challenge", "streak"]
    text: str
    from_user_id: int
    from_username: str
    date: str
    kudos_count: int = 0
    kudosed: bool = False


class KudosIn(BaseModel):
    target_type: Literal["workout", "record", "challenge", "streak"]
    target_id: int


class KudosOut(BaseModel):
    ok: bool
    to_user_id: Optional[int] = None
    count: int = 0


class GroupChallengeParticipantOut(BaseModel):
    user_id: int
    username: str
    current: int
    target: int
    status: str
    is_self: bool = False


class GroupChallengeOut(BaseModel):
    code: str
    name: str
    unit: str
    participants: list[GroupChallengeParticipantOut]
    user_joined: bool


# ── Фото прогресса ───────────────────────────────────────────────────────

class ProgressPhotoOut(BaseModel):
    id: int
    weight_kg: Optional[float] = None
    note: str = ""
    taken_at: str


# ── Метрики здоровья (носимые устройства) ────────────────────────────────

ALLOWED_METRIC_TYPES = {
    "steps",
    "heart_rate",
    "resting_heart_rate",
    "sleep_hours",
    "weight",
    "calories_burned",
    "distance_km",
    "active_minutes",
    "floors_climbed",
    "blood_oxygen",
    "body_fat_pct",
    "water_ml",
}

_METRIC_TYPE_RE = re.compile(r"^[a-z0-9_]{1,50}$")


class HealthMetricIn(BaseModel):
    ts: datetime
    metric_type: str = Field(max_length=50)
    value: float
    source: str = Field(default="", max_length=50)

    @field_validator("metric_type")
    @classmethod
    def _check_metric_type(cls, v: str) -> str:
        v = v.strip().lower()
        if not _METRIC_TYPE_RE.match(v):
            raise ValueError("metric_type must match ^[a-z0-9_]{1,50}$")
        if v not in ALLOWED_METRIC_TYPES:
            raise ValueError(
                f"unknown metric_type '{v}'; allowed: {sorted(ALLOWED_METRIC_TYPES)}"
            )
        return v


class HealthMetricsIn(BaseModel):
    metrics: list[HealthMetricIn] = Field(min_length=1, max_length=500)


class HealthMetricOut(BaseModel):
    id: int
    ts: datetime
    metric_type: str
    value: float
    source: str = ""
    created_at: Optional[str] = None


class HealthMetricsCreated(BaseModel):
    inserted: int
    ids: list[int]


class HealthSleepDayOut(BaseModel):
    date: str
    weekday: str
    hours: float


class HealthSummaryOut(BaseModel):
    """Агрегаты метрик здоровья за N дней; при days=7 — ещё и тренды недели."""

    days: int
    steps_today: Optional[float] = None
    steps_yesterday: Optional[float] = None
    avg_sleep_hours: Optional[float] = None
    sleep_last_night: Optional[float] = None
    avg_resting_heart_rate: Optional[float] = None
    resting_hr_today: Optional[float] = None
    avg_steps: Optional[int] = None
    total_steps: Optional[int] = None
    steps_trend_pct: Optional[float] = None
    sleep_trend_pct: Optional[float] = None
    best_sleep_day: Optional[HealthSleepDayOut] = None
    worst_sleep_day: Optional[HealthSleepDayOut] = None


# ── Админ ────────────────────────────────────────────────────────────────

class AdminMetricsOut(BaseModel):
    users_total: int
    users_active_7d: int
    food_entries_24h: int
    ai_requests_24h: int
    ai_requests_total: int
    premium_active: int


class AdminGrantPremiumIn(BaseModel):
    user_id: int
    days: int = Field(ge=1, le=3650)


class AdminGrantPremiumOut(BaseModel):
    user_id: int
    days: int
    expires_at: str


# ── Рекорды и аналитика нагрузки ─────────────────────────────────────────

class ExerciseRecordOut(BaseModel):
    exercise_id: Optional[int] = None
    name: str
    max_weight_kg: Optional[float] = None
    max_weight_date: Optional[str] = None
    max_reps: Optional[int] = None
    max_reps_date: Optional[str] = None


class SessionRecordOut(BaseModel):
    value_kg: Optional[float] = None
    value_min: Optional[int] = None
    date: str
    session_id: int


class StepsRecordOut(BaseModel):
    value: int
    date: str


class ProteinRecordOut(BaseModel):
    value_g: float
    date: str


class PersonalRecordsOut(BaseModel):
    exercises: list[ExerciseRecordOut]
    session_tonnage: Optional[SessionRecordOut] = None
    session_duration: Optional[SessionRecordOut] = None
    steps: Optional[StepsRecordOut] = None
    protein: Optional[ProteinRecordOut] = None


class LoadPointOut(BaseModel):
    date: str
    effort: float
    fitness: float
    fatigue: float
    freshness: float


class FreshnessOut(LoadPointOut):
    interpretation: str
    history_days: int


class LoadOut(BaseModel):
    weeks: int
    days: list[LoadPointOut]
    current: FreshnessOut


class CalendarDayOut(BaseModel):
    date: str
    has_food: bool
    has_workout: bool
    steps: Optional[int] = None
    water_ml: int = 0
    calories: float = 0


class CalendarOut(BaseModel):
    month: str
    days: list[CalendarDayOut]
