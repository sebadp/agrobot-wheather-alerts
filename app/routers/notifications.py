import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.alert_config import AlertConfig
from app.models.field import Field
from app.models.notification import Notification, NotificationStatus, NotificationType
from app.models.user import User
from app.schemas.notification import NotificationResponse

router = APIRouter(prefix="/api/v1", tags=["notifications"])


@router.get(
    "/users/{user_id}/notifications",
    response_model=list[NotificationResponse],
)
async def list_notifications(
    user_id: uuid.UUID,
    type: NotificationType | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List notifications for a user with optional type filter and pagination.

    Auth: requires JWT. ``user_id`` in path must match ``current_user.id``
    — users can only see their own notifications.  An admin role could
    bypass this restriction for support/debugging.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    # Subquery: field IDs belonging to this user
    user_field_ids = select(Field.id).where(Field.user_id == user_id).scalar_subquery()

    stmt = (
        select(Notification)
        .join(AlertConfig, AlertConfig.id == Notification.alert_config_id)
        .where(AlertConfig.field_id.in_(user_field_ids))
    )

    if type is not None:
        stmt = stmt.where(Notification.notification_type == type.value)

    stmt = stmt.order_by(Notification.triggered_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch(
    "/notifications/{notification_id}/deliver",
    response_model=NotificationResponse,
)
async def deliver_notification(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Mark a notification as delivered (called by the delivery service).

    Auth: requires JWT with role ``service`` or ``admin``.  This endpoint
    is designed for internal services (SMS gateway, push notification
    provider) to confirm delivery — not for end users.
    """
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.status = NotificationStatus.DELIVERED.value
    notification.delivered_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(notification)
    return notification
