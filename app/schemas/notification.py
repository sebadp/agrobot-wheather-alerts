import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.notification import NotificationType


class NotificationResponse(BaseModel):
    id: uuid.UUID
    alert_config_id: uuid.UUID | None
    weather_data_id: uuid.UUID
    notification_type: str
    probability_at_notification: float
    previous_notification_id: uuid.UUID | None
    status: str
    message: str
    triggered_at: datetime
    delivered_at: datetime | None

    model_config = {"from_attributes": True}


class NotificationListParams(BaseModel):
    type: NotificationType | None = None
    limit: int = 20
    offset: int = 0
