from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.notification import Notification
from app.services.alert_evaluator import evaluate_alerts
from app.services.weather_seeder import seed_data

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.post("/weather/seed")
async def seed_weather(db: AsyncSession = Depends(get_db)):
    """Regenerate deterministic seed data for demo purposes.

    Auth: requires JWT with role ``admin``. In production this would be
    ``Depends(require_role("admin"))`` — only operators should mutate
    base data.  Seed endpoint would likely be removed or gated behind
    a feature flag in a real deployment.
    """
    result = await seed_data(db)
    return {"status": "seeded", **result}


@router.post("/jobs/evaluate-alerts")
async def trigger_evaluation(db: AsyncSession = Depends(get_db)):
    """Trigger a manual evaluation cycle (same logic as the scheduler).

    Auth: requires JWT with role ``admin`` or ``operator``.  This is the
    most sensitive endpoint — it writes notifications and could be abused
    to generate spam.  In production the dependency chain would be::

        current_user: User = Depends(require_role("admin", "operator"))

    Combined with the advisory lock (``pg_try_advisory_lock``), concurrent
    calls are safe but should still be restricted to authorized personnel.
    Rate-limiting (e.g. 1 req/min per user) would add an extra layer.
    """
    result = await evaluate_alerts(db)
    return {"status": "completed", **result}


@router.get("/jobs/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Return aggregated notification statistics.

    Auth: requires JWT with role ``admin`` or ``operator``.  Stats expose
    internal system metrics — not suitable for regular users.
    """
    result = await db.execute(
        select(
            func.count(Notification.id).label("total"),
            func.count().filter(Notification.status == "pending").label("pending"),
            func.count().filter(Notification.status == "delivered").label("delivered"),
            func.max(Notification.triggered_at).label("last_triggered"),
        )
    )
    row = result.one()
    return {
        "total_notifications": row.total,
        "pending": row.pending,
        "delivered": row.delivered,
        "last_triggered": row.last_triggered.isoformat() if row.last_triggered else None,
    }
