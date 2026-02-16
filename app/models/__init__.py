from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.models.alert_config import AlertConfig  # noqa: E402, F401
from app.models.field import Field  # noqa: E402, F401
from app.models.notification import (  # noqa: E402, F401
    Notification,
    NotificationStatus,
    NotificationType,
)
from app.models.user import User  # noqa: E402, F401
from app.models.weather_data import ClimateEventType, WeatherData  # noqa: E402, F401
