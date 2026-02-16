"""add check constraints, indexes, and cascade fixes

Revision ID: 002
Revises: 001
Create Date: 2025-01-02 00:00:00.000000
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # P1: Index on weather_data.field_id for evaluator JOIN performance
    op.create_index("ix_weather_data_field_id", "weather_data", ["field_id"])

    # P1: CHECK constraints on probability and threshold (0..1 range)
    op.create_check_constraint(
        "chk_weather_probability",
        "weather_data",
        "probability >= 0 AND probability <= 1",
    )
    op.create_check_constraint(
        "chk_alert_threshold",
        "alert_configs",
        "threshold >= 0 AND threshold <= 1",
    )

    # P1: SET NULL on notifications.previous_notification_id for chain integrity
    op.drop_constraint(
        "notifications_previous_notification_id_fkey", "notifications", type_="foreignkey"
    )
    op.create_foreign_key(
        "notifications_previous_notification_id_fkey",
        "notifications",
        "notifications",
        ["previous_notification_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "notifications_previous_notification_id_fkey", "notifications", type_="foreignkey"
    )
    op.create_foreign_key(
        "notifications_previous_notification_id_fkey",
        "notifications",
        "notifications",
        ["previous_notification_id"],
        ["id"],
    )

    op.drop_constraint("chk_alert_threshold", "alert_configs", type_="check")
    op.drop_constraint("chk_weather_probability", "weather_data", type_="check")
    op.drop_index("ix_weather_data_field_id", "weather_data")
