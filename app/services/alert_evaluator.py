import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.alert_config import AlertConfig
from app.models.field import Field
from app.models.notification import Notification, NotificationType
from app.models.weather_data import WeatherData
from app.services.weather_seeder import EVENT_LABELS

logger = logging.getLogger(__name__)

# Advisory lock ID for evaluation job (arbitrary constant)
EVALUATION_LOCK_ID = 8675309

TEMPLATES = {
    "risk_increased": (
        "\u26a0\ufe0f Alerta: probabilidad de {event_label} {new_prob}% en campo {field_name} "
        "para el {date}. Umbral: {threshold}%. {delta_text}"
    ),
    "risk_ended": (
        "\u2705 Riesgo mitigado: probabilidad de {event_label} bajó del {old_prob}% "
        "al {new_prob}% en campo {field_name} para el {date}. "
        "Ya no supera tu umbral de {threshold}%."
    ),
}


@dataclass
class NotificationAction:
    type: NotificationType


def is_within_cooldown(prev_triggered: datetime, cooldown_hours: int) -> bool:
    now = datetime.now(UTC)
    if prev_triggered.tzinfo is None:
        prev_triggered = prev_triggered.replace(tzinfo=UTC)
    return (now - prev_triggered) < timedelta(hours=cooldown_hours)


def determine_action(
    has_previous: bool,
    was_above: bool,
    is_above: bool,
    current_prob: float,
    prev_prob: float | None,
    prev_triggered: datetime | None,
    delta_threshold: float,
    cooldown_hours: int,
) -> NotificationAction | None:
    # No previous notification
    if not has_previous:
        if is_above:
            return NotificationAction(type=NotificationType.RISK_INCREASED)
        return None

    # Case A: Was above, now below → all clear (ignores cooldown)
    if was_above and not is_above:
        return NotificationAction(type=NotificationType.RISK_ENDED)

    # Cooldown check (risk_ended already handled above)
    if prev_triggered and is_within_cooldown(prev_triggered, cooldown_hours):
        return None

    # Case B: Still above, significant delta
    if was_above and is_above:
        delta = current_prob - (prev_prob or 0)
        if delta >= delta_threshold:
            return NotificationAction(type=NotificationType.RISK_INCREASED)
        return None  # Case C: minor change

    # Case D: Was below, now above
    if not was_above and is_above:
        return NotificationAction(type=NotificationType.RISK_INCREASED)

    return None


def build_message(
    action_type: NotificationType,
    event_type: str,
    field_name: str,
    event_date: date,
    current_prob: float,
    prev_prob: float | None,
    threshold: float,
) -> str:
    event_label = EVENT_LABELS.get(event_type, event_type)
    new_prob_pct = int(current_prob * 100)
    threshold_pct = int(threshold * 100)
    date_str = event_date.strftime("%Y-%m-%d")

    if action_type == NotificationType.RISK_ENDED:
        old_prob_pct = int((prev_prob or 0) * 100)
        return TEMPLATES["risk_ended"].format(
            event_label=event_label,
            old_prob=old_prob_pct,
            new_prob=new_prob_pct,
            field_name=field_name,
            date=date_str,
            threshold=threshold_pct,
        )

    delta_text = ""
    if prev_prob is not None:
        old_pct = int(prev_prob * 100)
        delta_text = f"Subió del {old_pct}% al {new_prob_pct}%"

    return (
        TEMPLATES["risk_increased"]
        .format(
            event_label=event_label,
            new_prob=new_prob_pct,
            field_name=field_name,
            date=date_str,
            threshold=threshold_pct,
            delta_text=delta_text,
        )
        .rstrip()
    )


async def _try_acquire_advisory_lock(session: AsyncSession) -> bool:
    """Try to acquire a PostgreSQL advisory lock. Returns False if already held."""
    try:
        result = await session.execute(text(f"SELECT pg_try_advisory_lock({EVALUATION_LOCK_ID})"))
        return result.scalar()
    except Exception:
        # Not PostgreSQL (e.g. SQLite in tests) — skip locking
        return True


async def _release_advisory_lock(session: AsyncSession) -> None:
    """Release the PostgreSQL advisory lock."""
    try:
        await session.execute(text(f"SELECT pg_advisory_unlock({EVALUATION_LOCK_ID})"))
    except Exception:
        pass  # Not PostgreSQL


async def evaluate_alerts(session: AsyncSession) -> dict:
    # Advisory lock: prevent concurrent evaluations
    acquired = await _try_acquire_advisory_lock(session)
    if not acquired:
        logger.warning("Evaluation skipped — another instance is already running")
        return {"evaluated": 0, "notifications_created": 0, "skipped": 0, "locked": True}

    try:
        return await _do_evaluate(session)
    finally:
        await _release_advisory_lock(session)


async def _do_evaluate(session: AsyncSession) -> dict:
    today = date.today()

    # CTE: latest notification per (alert_config_id, weather_data_id)
    latest_notification = (
        select(
            Notification.alert_config_id,
            Notification.weather_data_id,
            Notification.notification_type,
            Notification.probability_at_notification,
            Notification.triggered_at,
            Notification.id.label("notification_id"),
            func.row_number()
            .over(
                partition_by=[Notification.alert_config_id, Notification.weather_data_id],
                order_by=Notification.triggered_at.desc(),
            )
            .label("rn"),
        )
        .where(Notification.alert_config_id.isnot(None))
        .cte("latest_notification")
    )

    latest = select(latest_notification).where(latest_notification.c.rn == 1).cte("latest")

    # Main query
    stmt = (
        select(
            AlertConfig,
            WeatherData,
            Field.name.label("field_name"),
            latest.c.notification_type.label("prev_type"),
            latest.c.probability_at_notification.label("prev_probability"),
            latest.c.triggered_at.label("prev_triggered_at"),
            latest.c.notification_id.label("prev_notification_id"),
        )
        .join(Field, Field.id == AlertConfig.field_id)
        .join(
            WeatherData,
            and_(
                WeatherData.field_id == AlertConfig.field_id,
                WeatherData.event_type == AlertConfig.event_type,
            ),
        )
        .outerjoin(
            latest,
            and_(
                latest.c.alert_config_id == AlertConfig.id,
                latest.c.weather_data_id == WeatherData.id,
            ),
        )
        .where(
            AlertConfig.is_active == True,  # noqa: E712
            WeatherData.event_date >= today,
        )
    )

    count = 0
    skipped = 0

    result = await session.execute(stmt)
    rows = result.all()

    for row in rows:
        alert_config = row[0]
        weather_data = row[1]
        field_name = row[2]
        prev_type = row[3]
        prev_prob = row[4]
        prev_triggered = row[5]
        prev_id = row[6]

        current_prob = float(weather_data.probability)
        threshold = float(alert_config.threshold)
        above_threshold = current_prob >= threshold

        prev_prob_float = float(prev_prob) if prev_prob is not None else None
        was_above = prev_prob_float is not None and prev_prob_float >= threshold

        action = determine_action(
            has_previous=prev_type is not None,
            was_above=was_above,
            is_above=above_threshold,
            current_prob=current_prob,
            prev_prob=prev_prob_float,
            prev_triggered=prev_triggered,
            delta_threshold=settings.DELTA_THRESHOLD,
            cooldown_hours=settings.COOLDOWN_HOURS,
        )

        if action is None:
            skipped += 1
            continue

        message = build_message(
            action_type=action.type,
            event_type=alert_config.event_type,
            field_name=field_name,
            event_date=weather_data.event_date,
            current_prob=current_prob,
            prev_prob=prev_prob_float,
            threshold=threshold,
        )

        notification = Notification(
            alert_config_id=alert_config.id,
            weather_data_id=weather_data.id,
            notification_type=action.type.value,
            probability_at_notification=current_prob,
            previous_notification_id=prev_id,
            status="pending",
            message=message,
        )
        session.add(notification)
        logger.info(message)
        count += 1

    await session.commit()

    return {
        "evaluated": len(rows),
        "notifications_created": count,
        "skipped": skipped,
    }
