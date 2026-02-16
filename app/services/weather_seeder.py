import uuid
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.field import Field
from app.models.user import User
from app.models.weather_data import WeatherData

SEED_USER_ID = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
SEED_FIELD_ESPERANZA_ID = uuid.UUID("f1e2d3c4-b5a6-7890-fedc-ba0987654321")
SEED_FIELD_PRIMAVERA_ID = uuid.UUID("f2e3d4c5-b6a7-8901-fedc-ba1098765432")

EVENT_LABELS = {
    "frost": "helada",
    "rain": "lluvia",
    "hail": "granizo",
    "drought": "sequía",
    "heat_wave": "ola de calor",
    "strong_wind": "viento fuerte",
}

SEED_WEATHER: dict[uuid.UUID, dict[str, list[float]]] = {
    SEED_FIELD_ESPERANZA_ID: {
        "frost": [0.85, 0.40, 0.15, 0.70, 0.05, 0.90, 0.30],
        "hail": [0.20, 0.55, 0.75, 0.30, 0.10, 0.60, 0.45],
        "rain": [0.50, 0.65, 0.80, 0.35, 0.70, 0.25, 0.55],
    },
    SEED_FIELD_PRIMAVERA_ID: {
        "drought": [0.30, 0.45, 0.60, 0.80, 0.90, 0.50, 0.20],
        "heat_wave": [0.70, 0.85, 0.55, 0.40, 0.75, 0.90, 0.15],
        "strong_wind": [0.10, 0.25, 0.50, 0.65, 0.35, 0.80, 0.45],
    },
}


async def seed_data(session: AsyncSession) -> dict:
    # Upsert user
    await session.execute(
        insert(User)
        .values(
            id=SEED_USER_ID,
            name="Juan Agricultor",
            phone="+54 9 11 1234-5678",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    # Upsert fields
    for field_id, field_name, lat, lon in [
        (SEED_FIELD_ESPERANZA_ID, "Campo La Esperanza", -33.94, -60.95),
        (SEED_FIELD_PRIMAVERA_ID, "Campo Primavera", -34.60, -58.38),
    ]:
        await session.execute(
            insert(Field)
            .values(
                id=field_id,
                user_id=SEED_USER_ID,
                name=field_name,
                latitude=lat,
                longitude=lon,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )

    # Upsert weather data
    today = date.today()
    weather_count = 0
    for field_id, events in SEED_WEATHER.items():
        for event_type, probs in events.items():
            for day_offset, prob in enumerate(probs):
                event_date = today + timedelta(days=day_offset)
                await session.execute(
                    insert(WeatherData)
                    .values(
                        id=uuid.uuid5(uuid.NAMESPACE_DNS, f"{field_id}-{event_date}-{event_type}"),
                        field_id=field_id,
                        event_date=event_date,
                        event_type=event_type,
                        probability=prob,
                    )
                    .on_conflict_do_update(
                        constraint="uq_weather_field_date_type",
                        set_={"probability": prob, "updated_at": text("now()")},
                    )
                )
                weather_count += 1

    await session.commit()

    return {
        "users": 1,
        "fields": 2,
        "weather_records": weather_count,
    }


async def seed_if_empty(session: AsyncSession) -> bool:
    result = await session.execute(text("SELECT count(*) FROM users"))
    count = result.scalar()
    if count == 0:
        await seed_data(session)
        return True
    return False
