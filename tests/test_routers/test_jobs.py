from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_config import AlertConfig
from app.models.notification import Notification
from tests.conftest import FIELD_ID


async def _create_notification(
    db: AsyncSession,
    status: str = "pending",
) -> Notification:
    from sqlalchemy import select

    from app.models.weather_data import WeatherData

    alert = AlertConfig(field_id=FIELD_ID, event_type="frost", threshold=0.7)
    db.add(alert)
    await db.flush()

    weather = (
        (
            await db.execute(
                select(WeatherData).where(
                    WeatherData.field_id == FIELD_ID,
                    WeatherData.event_type == "frost",
                )
            )
        )
        .scalars()
        .first()
    )

    notification = Notification(
        alert_config_id=alert.id,
        weather_data_id=weather.id,
        notification_type="risk_increased",
        probability_at_notification=0.85,
        status=status,
        message="Test notification",
        triggered_at=datetime.now(UTC),
        delivered_at=datetime.now(UTC) if status == "delivered" else None,
    )
    db.add(notification)
    await db.commit()
    return notification


@pytest.mark.asyncio
async def test_stats_empty(client):
    resp = await client.get("/api/v1/jobs/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_notifications"] == 0
    assert data["pending"] == 0
    assert data["delivered"] == 0
    assert data["last_triggered"] is None


@pytest.mark.asyncio
async def test_stats_with_notifications(client, seeded_session):
    await _create_notification(seeded_session, status="pending")
    resp = await client.get("/api/v1/jobs/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_notifications"] == 1
    assert data["pending"] == 1
    assert data["delivered"] == 0
    assert data["last_triggered"] is not None
