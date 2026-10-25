"""Админ-метрики: GET /api/v1/admin/metrics (только X-Admin-Key)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_admin
from api.deps import get_db
from api.schemas import AdminGrantPremiumIn, AdminGrantPremiumOut, AdminMetricsOut
from core.database import get_user
from core.database.premium import activate_premium

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/metrics", response_model=AdminMetricsOut)
def admin_metrics() -> AdminMetricsOut:
    conn = get_db()
    now = datetime.now()
    week_ago = (now - timedelta(days=7)).isoformat()
    day_ago = (now - timedelta(days=1)).isoformat()

    users_total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    users_active_7d = conn.execute(
        """SELECT COUNT(DISTINCT user_id) FROM (
               SELECT user_id FROM food_log_new WHERE logged_at >= ?
               UNION
               SELECT user_id FROM workout_sessions WHERE date >= ?
           )""",
        (week_ago, week_ago),
    ).fetchone()[0]
    food_entries_24h = conn.execute(
        "SELECT COUNT(*) FROM food_log_new WHERE logged_at >= ?",
        (day_ago,),
    ).fetchone()[0]
    ai_requests_24h = conn.execute(
        "SELECT COUNT(*) FROM ai_response_log WHERE created_at >= ?",
        (day_ago,),
    ).fetchone()[0]
    ai_requests_total = conn.execute(
        "SELECT COUNT(*) FROM ai_response_log"
    ).fetchone()[0]
    premium_active = conn.execute(
        """SELECT COUNT(*) FROM premium_subscriptions
           WHERE status IN ('trial', 'active') AND expires_at > ?""",
        (now.isoformat(),),
    ).fetchone()[0]

    return AdminMetricsOut(
        users_total=users_total,
        users_active_7d=users_active_7d,
        food_entries_24h=food_entries_24h,
        ai_requests_24h=ai_requests_24h,
        ai_requests_total=ai_requests_total,
        premium_active=premium_active,
    )


@router.post("/grant_premium", response_model=AdminGrantPremiumOut)
def grant_premium(payload: AdminGrantPremiumIn) -> AdminGrantPremiumOut:
    if not get_user(payload.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    result = activate_premium(
        user_id=payload.user_id,
        days=payload.days,
        source="admin",
        extend=True,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Failed to grant Premium")
    return AdminGrantPremiumOut(
        user_id=payload.user_id,
        days=payload.days,
        expires_at=result["expires_at"],
    )
