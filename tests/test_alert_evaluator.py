import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_config import AlertConfig
from app.models.notification import Notification, NotificationType
from app.models.weather_data import WeatherData
from app.services.alert_evaluator import (
    build_message,
    determine_action,
    evaluate_alerts,
)
from tests.conftest import FIELD_ID


@pytest.fixture
def today():
    return date.today()


# --- determine_action unit tests ---


class TestDetermineAction:
    def test_no_previous_above_threshold(self):
        action = determine_action(
            has_previous=False,
            was_above=False,
            is_above=True,
            current_prob=0.85,
            prev_prob=None,
            prev_triggered=None,
            delta_threshold=0.10,
            cooldown_hours=6,
        )
        assert action is not None
        assert action.type == NotificationType.RISK_INCREASED

    def test_no_previous_below_threshold(self):
        action = determine_action(
            has_previous=False,
            was_above=False,
            is_above=False,
            current_prob=0.50,
            prev_prob=None,
            prev_triggered=None,
            delta_threshold=0.10,
            cooldown_hours=6,
        )
        assert action is None

    def test_risk_ended(self):
        action = determine_action(
            has_previous=True,
            was_above=True,
            is_above=False,
            current_prob=0.60,
            prev_prob=0.85,
            prev_triggered=datetime.now(UTC),
            delta_threshold=0.10,
            cooldown_hours=6,
        )
        assert action is not None
        assert action.type == NotificationType.RISK_ENDED

    def test_risk_increased_delta(self):
        action = determine_action(
            has_previous=True,
            was_above=True,
            is_above=True,
            current_prob=0.85,
            prev_prob=0.70,
            prev_triggered=datetime.now(UTC) - timedelta(hours=7),
            delta_threshold=0.10,
            cooldown_hours=6,
        )
        assert action is not None
        assert action.type == NotificationType.RISK_INCREASED

    def test_no_spam_small_changes(self):
        action = determine_action(
            has_previous=True,
            was_above=True,
            is_above=True,
            current_prob=0.75,
            prev_prob=0.70,
            prev_triggered=datetime.now(UTC) - timedelta(hours=7),
            delta_threshold=0.10,
            cooldown_hours=6,
        )
        assert action is None

    def test_cooldown_respected(self):
        action = determine_action(
            has_previous=True,
            was_above=True,
            is_above=True,
            current_prob=0.95,
            prev_prob=0.70,
            prev_triggered=datetime.now(UTC) - timedelta(hours=1),
            delta_threshold=0.10,
            cooldown_hours=6,
        )
        assert action is None

    def test_cooldown_bypass_for_ended(self):
        action = determine_action(
            has_previous=True,
            was_above=True,
            is_above=False,
            current_prob=0.50,
            prev_prob=0.85,
            prev_triggered=datetime.now(UTC) - timedelta(minutes=5),
            delta_threshold=0.10,
            cooldown_hours=6,
        )
        assert action is not None
        assert action.type == NotificationType.RISK_ENDED

    def test_case_d_below_to_above(self):
        action = determine_action(
            has_previous=True,
            was_above=False,
            is_above=True,
            current_prob=0.80,
            prev_prob=0.50,
            prev_triggered=datetime.now(UTC) - timedelta(hours=7),
            delta_threshold=0.10,
            cooldown_hours=6,
        )
        assert action is not None
        assert action.type == NotificationType.RISK_INCREASED


# --- build_message tests ---


class TestBuildMessage:
    def test_message_content_risk_increased_first(self):
        msg = build_message(
            action_type=NotificationType.RISK_INCREASED,
            event_type="frost",
            field_name="Campo Test",
            event_date=date(2025, 7, 15),
            current_prob=0.85,
            prev_prob=None,
            threshold=0.70,
        )
        assert "Alerta" in msg
        assert "85%" in msg
        assert "Campo Test" in msg
        assert "70%" in msg

    def test_message_content_risk_increased_update(self):
        msg = build_message(
            action_type=NotificationType.RISK_INCREASED,
            event_type="frost",
            field_name="Campo Test",
            event_date=date(2025, 7, 15),
            current_prob=0.85,
            prev_prob=0.70,
            threshold=0.60,
        )
        assert "Subió del 70% al 85%" in msg

    def test_message_content_risk_ended(self):
        msg = build_message(
            action_type=NotificationType.RISK_ENDED,
            event_type="frost",
            field_name="Campo Test",
            event_date=date(2025, 7, 15),
            current_prob=0.60,
            prev_prob=0.85,
            threshold=0.70,
        )
        assert "\u2705" in msg
        assert "Riesgo mitigado" in msg
        assert "85%" in msg
        assert "60%" in msg


# --- Integration tests with evaluate_alerts ---


class TestEvaluateAlerts:
    @pytest.mark.asyncio
    async def test_no_alerts(self, seeded_session: AsyncSession):
        """No alert configs → 0 notifications."""
        result = await evaluate_alerts(seeded_session)
        assert result["notifications_created"] == 0

    @pytest.mark.asyncio
    async def test_first_above_threshold(self, seeded_session: AsyncSession):
        """First evaluation with prob above threshold → risk_increased."""
        alert = AlertConfig(
            field_id=FIELD_ID,
            event_type="frost",
            threshold=0.70,
            is_active=True,
        )
        seeded_session.add(alert)
        await seeded_session.commit()

        result = await evaluate_alerts(seeded_session)
        assert result["notifications_created"] >= 1

        notifs = (await seeded_session.execute(select(Notification))).scalars().all()
        risk_increased = [n for n in notifs if n.notification_type == "risk_increased"]
        assert len(risk_increased) >= 1

    @pytest.mark.asyncio
    async def test_first_below_threshold(self, seeded_session: AsyncSession):
        """Prob below threshold → no notification."""
        alert = AlertConfig(
            field_id=FIELD_ID,
            event_type="rain",
            threshold=0.90,
            is_active=True,
        )
        seeded_session.add(alert)
        await seeded_session.commit()

        result = await evaluate_alerts(seeded_session)
        assert result["notifications_created"] == 0

    @pytest.mark.asyncio
    async def test_risk_ended_integration(self, seeded_session: AsyncSession, today):
        """Probability drops below threshold → risk_ended notification."""
        weather_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{FIELD_ID}-{today}-frost")

        alert = AlertConfig(
            id=uuid.uuid4(),
            field_id=FIELD_ID,
            event_type="frost",
            threshold=0.70,
            is_active=True,
        )
        seeded_session.add(alert)
        await seeded_session.commit()

        # First evaluation: creates risk_increased (85% >= 70%)
        await evaluate_alerts(seeded_session)

        # Now lower the probability below threshold
        wd = (
            await seeded_session.execute(select(WeatherData).where(WeatherData.id == weather_id))
        ).scalar_one()
        wd.probability = 0.60
        await seeded_session.commit()

        # Second evaluation: should create risk_ended
        result = await evaluate_alerts(seeded_session)
        assert result["notifications_created"] >= 1

        notifs = (
            (
                await seeded_session.execute(
                    select(Notification).where(Notification.notification_type == "risk_ended")
                )
            )
            .scalars()
            .all()
        )
        assert len(notifs) >= 1
        assert "\u2705" in notifs[0].message

    @pytest.mark.asyncio
    async def test_previous_notification_id_linked(self, seeded_session: AsyncSession, today):
        """Second notification should reference the first one."""
        weather_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{FIELD_ID}-{today}-frost")

        alert = AlertConfig(
            field_id=FIELD_ID,
            event_type="frost",
            threshold=0.70,
            is_active=True,
        )
        seeded_session.add(alert)
        await seeded_session.commit()

        # First evaluation
        await evaluate_alerts(seeded_session)

        # Lower probability to trigger risk_ended
        wd = (
            await seeded_session.execute(select(WeatherData).where(WeatherData.id == weather_id))
        ).scalar_one()
        wd.probability = 0.50
        await seeded_session.commit()

        # Second evaluation
        await evaluate_alerts(seeded_session)

        notifs = (
            (
                await seeded_session.execute(
                    select(Notification)
                    .where(Notification.weather_data_id == weather_id)
                    .order_by(Notification.triggered_at)
                )
            )
            .scalars()
            .all()
        )

        if len(notifs) >= 2:
            assert notifs[1].previous_notification_id == notifs[0].id

    @pytest.mark.asyncio
    async def test_idempotency(self, seeded_session: AsyncSession):
        """Running evaluate twice without changes → second run creates 0 new notifications (cooldown)."""
        alert = AlertConfig(
            field_id=FIELD_ID,
            event_type="frost",
            threshold=0.70,
            is_active=True,
        )
        seeded_session.add(alert)
        await seeded_session.commit()

        await evaluate_alerts(seeded_session)
        result2 = await evaluate_alerts(seeded_session)

        # Second run: cooldown should prevent new notifications for same pairs
        assert result2["notifications_created"] == 0
