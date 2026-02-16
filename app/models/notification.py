import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class NotificationType(str, enum.Enum):
    RISK_INCREASED = "risk_increased"
    RISK_DECREASED = (
        "risk_decreased"  # Reserved: validate with product to avoid spam before implementing
    )
    RISK_ENDED = "risk_ended"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notification_lookup", "alert_config_id", "weather_data_id", "triggered_at"),
        CheckConstraint(
            "probability_at_notification >= 0 AND probability_at_notification <= 1",
            name="chk_notification_probability",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_configs.id", ondelete="SET NULL"), nullable=True
    )
    weather_data_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("weather_data.id"), nullable=False
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    probability_at_notification: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    previous_notification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NotificationStatus.PENDING.value
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
