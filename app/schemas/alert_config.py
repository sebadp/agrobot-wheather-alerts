import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.weather_data import ClimateEventType


class AlertConfigCreate(BaseModel):
    event_type: ClimateEventType
    threshold: float = Field(ge=0.0, le=1.0)


class AlertConfigUpdate(BaseModel):
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    is_active: bool | None = None


class AlertConfigResponse(BaseModel):
    id: uuid.UUID
    field_id: uuid.UUID
    event_type: str
    threshold: float
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
