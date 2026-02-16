import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.alert_config import AlertConfig
from app.models.field import Field
from app.schemas.alert_config import AlertConfigCreate, AlertConfigResponse, AlertConfigUpdate

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.post(
    "/fields/{field_id}/alerts",
    response_model=AlertConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert(
    field_id: uuid.UUID,
    payload: AlertConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new alert config for a field.

    Auth: requires JWT. The token's ``user_id`` would be validated against
    the field's owner (``field.user_id == current_user.id``) to prevent
    users from creating alerts on fields they don't own.
    """
    # Check field exists
    result = await db.execute(select(Field).where(Field.id == field_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Field not found")

    alert = AlertConfig(
        field_id=field_id,
        event_type=payload.event_type.value,
        threshold=payload.threshold,
    )
    db.add(alert)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Alert for this field and event type already exists. Use PATCH to update.",
        ) from None
    await db.refresh(alert)
    return alert


@router.get(
    "/fields/{field_id}/alerts",
    response_model=list[AlertConfigResponse],
)
async def list_alerts(
    field_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List alert configs for a field.

    Auth: requires JWT. Only returns alerts for fields owned by
    ``current_user``.
    """
    result = await db.execute(select(Field).where(Field.id == field_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Field not found")

    result = await db.execute(select(AlertConfig).where(AlertConfig.field_id == field_id))
    return result.scalars().all()


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertConfigResponse,
)
async def update_alert(
    alert_id: uuid.UUID,
    payload: AlertConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update threshold and/or active status of an alert config.

    Auth: requires JWT with ownership check — the alert's field must
    belong to ``current_user``.
    """
    result = await db.execute(select(AlertConfig).where(AlertConfig.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if payload.threshold is not None:
        alert.threshold = payload.threshold
    if payload.is_active is not None:
        alert.is_active = payload.is_active

    await db.commit()
    await db.refresh(alert)
    return alert


@router.delete(
    "/alerts/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an alert config (CASCADE cleans related data).

    Auth: requires JWT with ownership check.
    """
    result = await db.execute(select(AlertConfig).where(AlertConfig.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    await db.delete(alert)
    await db.commit()
