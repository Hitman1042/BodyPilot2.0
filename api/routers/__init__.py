"""Роутеры HTTP API."""

from api.routers import admin, health, health_data, nutrition, profile, stats, workouts

__all__ = [
    "admin",
    "health",
    "health_data",
    "nutrition",
    "profile",
    "stats",
    "workouts",
]
