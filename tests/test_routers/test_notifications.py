import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_config import AlertConfig
from app.models.notification import Notification
from tests.conftest import FIELD_ID, USER_ID


async def _create_alert_and_notification(
    db: AsyncSession,
    event_type: str = "frost",
    notification_type: str = "risk_increased",
    probability: float = 0.85,
) -> tuple[AlertConfig, Notification]:
    """Helper: create an alert config and a notification for it."""
    alert = AlertConfig(
        field_id=FIELD_ID,
        event_type=event_type,
        threshold=0.7,
    )
    db.add(alert)
    await db.flush()

    # Get weather_data id for frost today
    from sqlalchemy import select

    from app.models.weather_data import WeatherData

    result = await db.execute(
        select(WeatherData).where(
            WeatherData.field_id == FIELD_ID,
            WeatherData.event_type == event_type,
        )
    )
    weather = result.scalars().first()

    notification = Notification(
        alert_config_id=alert.id,
        weather_data_id=weather.id,
        notification_type=notification_type,
        probability_at_notification=probability,
        status="pending",
        message=f"Test notification for {event_type}",
        triggered_at=datetime.now(UTC),
    )
    db.add(notification)
    await db.commit()
    return alert, notification


@pytest.mark.asyncio
async def test_list_notifications(client, seeded_session):
    await _create_alert_and_notification(seeded_session)
    resp = await client.get(f"/api/v1/users/{USER_ID}/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["notification_type"] == "risk_increased"


@pytest.mark.asyncio
async def test_list_notifications_filter_by_type(client, seeded_session):
    await _create_alert_and_notification(seeded_session, notification_type="risk_increased")
    # Create a risk_ended for rain
    await _create_alert_and_notification(
        seeded_session,
        event_type="rain",
        notification_type="risk_ended",
        probability=0.30,
    )

    resp = await client.get(f"/api/v1/users/{USER_ID}/notifications?type=risk_ended")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["notification_type"] == "risk_ended"


@pytest.mark.asyncio
async def test_list_notifications_pagination(client, seeded_session):
    await _create_alert_and_notification(seeded_session)
    await _create_alert_and_notification(
        seeded_session,
        event_type="rain",
        notification_type="risk_ended",
        probability=0.30,
    )

    resp = await client.get(f"/api/v1/users/{USER_ID}/notifications?limit=1&offset=0")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp2 = await client.get(f"/api/v1/users/{USER_ID}/notifications?limit=1&offset=1")
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1

    # Different notifications
    assert resp.json()[0]["id"] != resp2.json()[0]["id"]


@pytest.mark.asyncio
async def test_list_notifications_user_not_found(client):
    fake_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/users/{fake_id}/notifications")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"


@pytest.mark.asyncio
async def test_deliver_notification(client, seeded_session):
    _, notification = await _create_alert_and_notification(seeded_session)

    resp = await client.patch(f"/api/v1/notifications/{notification.id}/deliver")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "delivered"
    assert data["delivered_at"] is not None


@pytest.mark.asyncio
async def test_deliver_notification_not_found(client):
    fake_id = uuid.uuid4()
    resp = await client.patch(f"/api/v1/notifications/{fake_id}/deliver")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Notification not found"
