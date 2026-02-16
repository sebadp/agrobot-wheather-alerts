import uuid
from datetime import date, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies import get_db
from app.models import Base
from app.models.field import Field
from app.models.user import User
from app.models.weather_data import WeatherData

# Use SQLite for tests (in-memory)
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


# Enable foreign keys for SQLite
@event.listens_for(test_engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Fixed UUIDs for tests
USER_ID = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
FIELD_ID = uuid.UUID("f1e2d3c4-b5a6-7890-fedc-ba0987654321")
FIELD_2_ID = uuid.UUID("f2e3d4c5-b6a7-8901-fedc-ba1098765432")


@pytest_asyncio.fixture
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seeded_session(db_session: AsyncSession):
    """Session with user, field, and sample weather data."""
    user = User(id=USER_ID, name="Test User", phone="+54 9 11 0000-0000")
    db_session.add(user)

    field = Field(
        id=FIELD_ID,
        user_id=USER_ID,
        name="Campo Test",
        latitude=-33.94,
        longitude=-60.95,
    )
    field2 = Field(
        id=FIELD_2_ID,
        user_id=USER_ID,
        name="Campo Primavera",
        latitude=-34.60,
        longitude=-58.38,
    )
    db_session.add_all([field, field2])
    await db_session.flush()

    today = date.today()
    weather_records = [
        WeatherData(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, f"{FIELD_ID}-{today}-frost"),
            field_id=FIELD_ID,
            event_date=today,
            event_type="frost",
            probability=0.85,
        ),
        WeatherData(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, f"{FIELD_ID}-{today + timedelta(days=1)}-frost"),
            field_id=FIELD_ID,
            event_date=today + timedelta(days=1),
            event_type="frost",
            probability=0.40,
        ),
        WeatherData(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, f"{FIELD_ID}-{today}-rain"),
            field_id=FIELD_ID,
            event_date=today,
            event_type="rain",
            probability=0.50,
        ),
    ]
    db_session.add_all(weather_records)
    await db_session.commit()
    return db_session


@pytest_asyncio.fixture
async def client(seeded_session: AsyncSession):
    from app.main import app

    async def override_get_db():
        yield seeded_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
