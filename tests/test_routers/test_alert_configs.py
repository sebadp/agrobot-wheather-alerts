import uuid

import pytest

from tests.conftest import FIELD_ID


@pytest.mark.asyncio
async def test_create_alert(client):
    resp = await client.post(
        f"/api/v1/fields/{FIELD_ID}/alerts",
        json={"event_type": "frost", "threshold": 0.7},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["event_type"] == "frost"
    assert data["threshold"] == 0.7
    assert data["is_active"] is True
    assert data["field_id"] == str(FIELD_ID)


@pytest.mark.asyncio
async def test_create_duplicate_alert(client):
    await client.post(
        f"/api/v1/fields/{FIELD_ID}/alerts",
        json={"event_type": "frost", "threshold": 0.7},
    )
    resp = await client.post(
        f"/api/v1/fields/{FIELD_ID}/alerts",
        json={"event_type": "frost", "threshold": 0.5},
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_alert_field_not_found(client):
    fake_id = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/fields/{fake_id}/alerts",
        json={"event_type": "frost", "threshold": 0.7},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Field not found"


@pytest.mark.asyncio
async def test_list_alerts(client):
    await client.post(
        f"/api/v1/fields/{FIELD_ID}/alerts",
        json={"event_type": "frost", "threshold": 0.7},
    )
    await client.post(
        f"/api/v1/fields/{FIELD_ID}/alerts",
        json={"event_type": "rain", "threshold": 0.5},
    )
    resp = await client.get(f"/api/v1/fields/{FIELD_ID}/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    event_types = {a["event_type"] for a in data}
    assert event_types == {"frost", "rain"}


@pytest.mark.asyncio
async def test_update_alert(client):
    create_resp = await client.post(
        f"/api/v1/fields/{FIELD_ID}/alerts",
        json={"event_type": "frost", "threshold": 0.7},
    )
    alert_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/alerts/{alert_id}",
        json={"threshold": 0.5, "is_active": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["threshold"] == 0.5
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_delete_alert(client):
    create_resp = await client.post(
        f"/api/v1/fields/{FIELD_ID}/alerts",
        json={"event_type": "frost", "threshold": 0.7},
    )
    alert_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/alerts/{alert_id}")
    assert resp.status_code == 204

    list_resp = await client.get(f"/api/v1/fields/{FIELD_ID}/alerts")
    assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_validation_threshold_out_of_range(client):
    resp = await client.post(
        f"/api/v1/fields/{FIELD_ID}/alerts",
        json={"event_type": "frost", "threshold": 1.5},
    )
    assert resp.status_code == 422
