"""Метрики здоровья с носимых устройств: /api/v1/health/metrics."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query

from api.auth import get_current_user_id
from api.deps import get_db
from api.schemas import (
    ALLOWED_METRIC_TYPES,
    HealthMetricOut,
    HealthMetricsCreated,
    HealthMetricsIn,
    HealthSummaryOut,
)

router = APIRouter(prefix="/api/v1/health", tags=["health_data"])


@router.post("/metrics", response_model=HealthMetricsCreated, status_code=201)
def post_metrics(
    payload: HealthMetricsIn,
    user_id: int = Depends(get_current_user_id),
) -> HealthMetricsCreated:
    conn = get_db()
    ids: list[int] = []
    for m in payload.metrics:
        cur = conn.execute(
            """INSERT INTO health_metrics (user_id, ts, metric_type, value, source)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, m.ts.isoformat(), m.metric_type, m.value, m.source),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return HealthMetricsCreated(inserted=len(ids), ids=ids)


@router.get("/metrics", response_model=list[HealthMetricOut])
def get_metrics(
    metric_type: str | None = Query(default=None, max_length=50),
    days: int = Query(default=7, ge=1, le=365),
    user_id: int = Depends(get_current_user_id),
) -> list[HealthMetricOut]:
    metric_type = metric_type.strip().lower() if metric_type else None
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    if metric_type:
        rows = conn.execute(
            """SELECT * FROM health_metrics
               WHERE user_id = ? AND metric_type = ? AND ts >= ?
               ORDER BY ts DESC""",
            (user_id, metric_type, cutoff),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM health_metrics
               WHERE user_id = ? AND ts >= ?
               ORDER BY ts DESC""",
            (user_id, cutoff),
        ).fetchall()
    return [HealthMetricOut(**dict(r)) for r in rows]


@router.get("/summary", response_model=HealthSummaryOut)
def get_summary(
    days: int = Query(default=7, ge=1, le=365),
    user_id: int = Depends(get_current_user_id),
) -> HealthSummaryOut:
    """Агрегаты за N дней (локальные даты пользователя); при days=7 — тренды недели."""
    from core.health_data import get_metrics_summary, get_weekly_health_stats

    data: dict = dict(get_metrics_summary(user_id, days=days))
    if days == 7:
        weekly = get_weekly_health_stats(user_id)
        data.update({
            "avg_steps": weekly["avg_steps"],
            "total_steps": weekly["total_steps"],
            "steps_trend_pct": weekly["steps_trend_pct"],
            "sleep_trend_pct": weekly["sleep_trend_pct"],
            "best_sleep_day": weekly["best_sleep_day"],
            "worst_sleep_day": weekly["worst_sleep_day"],
        })
    return HealthSummaryOut(**data)
