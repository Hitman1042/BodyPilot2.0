"""FastAPI-приложение BodyPilot.

Запуск: py -3.12 -m uvicorn api.main:app --port 8000
Документация: /docs (Swagger UI).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import (
    admin,
    challenges,
    chat,
    health,
    health_data,
    nutrition,
    plans,
    profile,
    progress,
    stats,
    water,
    workouts,
)

app = FastAPI(
    title="BodyPilot API",
    version="2.0.0",
    description="HTTP API для Telegram Mini App, сайта/приложения и внешних интеграций.",
    docs_url="/docs",
)

# TODO: сузить allow_origins до домена Mini App / сайта, когда он появится
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(profile.router)
app.include_router(nutrition.router)
app.include_router(workouts.router)
app.include_router(stats.router)
app.include_router(stats.weight_router)
app.include_router(health_data.router)
app.include_router(admin.router)
app.include_router(plans.router)
app.include_router(water.router)
app.include_router(chat.router)
app.include_router(challenges.router)
app.include_router(progress.router)

# Статика Mini App (фронт собирается отдельным этапом)
app.mount("/app", StaticFiles(directory="webapp", html=True), name="webapp")
