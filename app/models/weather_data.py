import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ClimateEventType(enum.StrEnum):
    FROST = "frost"
    RAIN = "rain"
    HAIL = "hail"
    DROUGHT = "drought"
    HEAT_WAVE = "heat_wave"
    STRONG_WIND = "strong_wind"


class WeatherData(Base):
    __tablename__ = "weather_data"
    __table_args__ = (
        UniqueConstraint("field_id", "event_date", "event_type", name="uq_weather_field_date_type"),
        CheckConstraint("probability >= 0 AND probability <= 1", name="chk_weather_probability"),
        Index("ix_weather_event_date", "event_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    probability: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
