"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "fields",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "weather_data",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", UUID(as_uuid=True), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("probability", sa.Numeric(3, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "field_id", "event_date", "event_type", name="uq_weather_field_date_type"
        ),
    )
    op.create_index("ix_weather_event_date", "weather_data", ["event_date"])

    op.create_table(
        "alert_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "field_id",
            UUID(as_uuid=True),
            sa.ForeignKey("fields.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("threshold", sa.Numeric(3, 2), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("field_id", "event_type", name="uq_alert_field_event"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "alert_config_id",
            UUID(as_uuid=True),
            sa.ForeignKey("alert_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "weather_data_id", UUID(as_uuid=True), sa.ForeignKey("weather_data.id"), nullable=False
        ),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("probability_at_notification", sa.Numeric(3, 2), nullable=False),
        sa.Column(
            "previous_notification_id",
            UUID(as_uuid=True),
            sa.ForeignKey("notifications.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notification_lookup",
        "notifications",
        ["alert_config_id", "weather_data_id", "triggered_at"],
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("alert_configs")
    op.drop_table("weather_data")
    op.drop_table("fields")
    op.drop_table("users")
