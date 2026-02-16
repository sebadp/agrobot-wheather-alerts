# Plan de Implementación — Sistema de Alertas Climáticas

Orden de ejecución optimizado. Cada fase tiene un checkpoint de verificación antes de avanzar.

---

## Fase 1: Fundación (~30 min)

### 1.1 Inicializar git
```bash
git init
```

### 1.2 pyproject.toml
```toml
[project]
name = "agrobot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.35",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "pydantic-settings>=2.6.0",
    "apscheduler>=3.10.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]
```

### 1.3 app/config.py
- `Settings(BaseSettings)` con:
  - `DATABASE_URL: str` (default para docker)
  - `EVAL_INTERVAL_MINUTES: int = 15`
  - `model_config = ConfigDict(env_file=".env")`

### 1.4 app/database.py
- `create_async_engine(settings.DATABASE_URL)`
- `async_session_factory = async_sessionmaker(engine, class_=AsyncSession)`
- `Base = declarative_base()`

### 1.5 app/dependencies.py
- `async def get_db() -> AsyncGenerator[AsyncSession, None]`

### 1.6 app/main.py (esqueleto)
- FastAPI app con lifespan vacío (llenar después)
- Health endpoint: `GET /health` → ping DB

### 1.7 Dockerfile
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY . .
```

### 1.8 docker-compose.yml
- db (postgres:16-alpine + healthcheck)
- app (build + depends_on db healthy + entrypoint con alembic + uvicorn)

### 1.9 Makefile
- setup, down, test, evaluate, logs, seed

### 1.10 .env.example
```
DATABASE_URL=postgresql+asyncpg://agrobot:agrobot@localhost:5432/agrobot
EVAL_INTERVAL_MINUTES=15
```

### 1.11 Alembic init
```bash
alembic init alembic
```
- Editar `alembic.ini`: sqlalchemy.url desde env var
- Editar `alembic/env.py`: importar modelos, usar URL de config, soporte async

### Checkpoint Fase 1
```bash
docker-compose up -d --build
curl http://localhost:8000/health  # → {"status": "ok", "db": "connected"}
docker-compose down -v
```

---

## Fase 2: Modelos (~30 min)

### 2.1 app/models/__init__.py
- Importar todos los modelos (necesario para Alembic autogenerate)

### 2.2 app/models/user.py
```python
class User(Base):
    __tablename__ = "users"
    id = Column(UUID, primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # relationship: fields
```

### 2.3 app/models/field.py
```python
class Field(Base):
    __tablename__ = "fields"
    id = Column(UUID, primary_key=True, default=uuid4)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # relationship: user, alert_configs
```

### 2.4 app/models/weather_data.py
```python
class WeatherData(Base):
    __tablename__ = "weather_data"
    id = Column(UUID, primary_key=True, default=uuid4)
    field_id = Column(UUID, ForeignKey("fields.id"), nullable=False)
    event_date = Column(Date, nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # ClimateEventType
    probability = Column(Numeric(3, 2), nullable=False)  # Precisión exacta
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("field_id", "event_date", "event_type", name="uq_weather_field_date_event"),
        CheckConstraint("probability >= 0 AND probability <= 1", name="ck_weather_probability"),
    )
```

### 2.5 app/models/alert_config.py
```python
class AlertConfig(Base):
    __tablename__ = "alert_configs"
    id = Column(UUID, primary_key=True, default=uuid4)
    field_id = Column(UUID, ForeignKey("fields.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    threshold = Column(Numeric(3, 2), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("field_id", "event_type", name="uq_alert_field_event"),
        CheckConstraint("threshold > 0 AND threshold <= 1", name="ck_alert_threshold"),
    )
```

### 2.6 app/models/notification.py
```python
class Notification(Base):
    __tablename__ = "notifications"
    id = Column(UUID, primary_key=True, default=uuid4)
    alert_config_id = Column(UUID, ForeignKey("alert_configs.id", ondelete="SET NULL"), nullable=True)
    weather_data_id = Column(UUID, ForeignKey("weather_data.id"), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    message = Column(Text, nullable=False)
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("alert_config_id", "weather_data_id", name="uq_notification_alert_weather"),
    )
```

### 2.7 Enums (en models/__init__.py o separado)
```python
class ClimateEventType(str, Enum):
    FROST = "frost"
    RAIN = "rain"
    HAIL = "hail"
    DROUGHT = "drought"
    HEAT_WAVE = "heat_wave"
    STRONG_WIND = "strong_wind"

EVENT_TYPE_LABELS = {
    "frost": "helada",
    "rain": "lluvia",
    "hail": "granizo",
    "drought": "sequía",
    "heat_wave": "ola de calor",
    "strong_wind": "viento fuerte",
}
```

### 2.8 Migración Alembic
```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

### Checkpoint Fase 2
```bash
docker-compose up -d --build
# Migraciones corren en entrypoint
docker-compose exec db psql -U agrobot -c "\dt"
# → users, fields, weather_data, alert_configs, notifications
docker-compose down -v
```

---

## Fase 3: Schemas (~20 min)

### 3.1 app/schemas/alert_config.py
```python
class AlertConfigCreate(BaseModel):
    event_type: ClimateEventType
    threshold: float = Field(gt=0, le=1)

class AlertConfigUpdate(BaseModel):
    threshold: float | None = Field(default=None, gt=0, le=1)
    is_active: bool | None = None

class AlertConfigResponse(BaseModel):
    id: UUID
    field_id: UUID
    event_type: str
    threshold: float
    is_active: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

### 3.2 app/schemas/notification.py
```python
class NotificationResponse(BaseModel):
    id: UUID
    alert_config_id: UUID | None
    weather_data_id: UUID
    status: str
    message: str
    triggered_at: datetime
    delivered_at: datetime | None
    model_config = ConfigDict(from_attributes=True)

class PaginatedNotifications(BaseModel):
    items: list[NotificationResponse]
    total: int
    limit: int
    offset: int
```

### Checkpoint Fase 3
No verificable aislado — se valida con routers.

---

## Fase 4: Services (~45 min) ⭐ CORE

### 4.1 app/services/alert_evaluator.py ⭐ (archivo más importante)

```python
async def evaluate_alerts(session: AsyncSession) -> int:
    today = datetime.now(timezone.utc).date()

    # Query SARGable
    stmt = (
        select(AlertConfig, WeatherData, Field.name.label("field_name"))
        .join(Field, Field.id == AlertConfig.field_id)
        .join(WeatherData, and_(
            WeatherData.field_id == AlertConfig.field_id,
            WeatherData.event_type == AlertConfig.event_type
        ))
        .outerjoin(Notification, and_(
            Notification.alert_config_id == AlertConfig.id,
            Notification.weather_data_id == WeatherData.id
        ))
        .where(
            AlertConfig.is_active == True,
            WeatherData.event_date >= today,
            WeatherData.probability >= AlertConfig.threshold,
            Notification.id == None
        )
    )

    result = await session.execute(stmt)
    rows = result.all()

    count = 0
    for alert_config, weather_data, field_name in rows:
        message = build_message(alert_config, weather_data, field_name)

        insert_stmt = pg_insert(Notification).values(
            id=uuid4(),
            alert_config_id=alert_config.id,
            weather_data_id=weather_data.id,
            status="pending",
            message=message,
        ).on_conflict_do_nothing(
            index_elements=["alert_config_id", "weather_data_id"]
        )
        res = await session.execute(insert_stmt)
        if res.rowcount > 0:
            logger.info(message)
            count += 1

    return count


def build_message(alert_config, weather_data, field_name: str) -> str:
    label = EVENT_TYPE_LABELS.get(alert_config.event_type, alert_config.event_type)
    prob_pct = int(weather_data.probability * 100)
    threshold_pct = int(alert_config.threshold * 100)
    date_str = weather_data.event_date.strftime("%d/%m/%Y")
    return (
        f"⚠️ Alerta: probabilidad de {label} del {prob_pct}% "
        f"en campo {field_name} para el {date_str}. "
        f"Tu umbral configurado: {threshold_pct}%."
    )
```

### 4.2 app/services/weather_seeder.py

```python
# UUIDs hardcodeados
SEED_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
SEED_USER_2_ID = UUID("22222222-2222-2222-2222-222222222222")
SEED_FIELD_ESPERANZA_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SEED_FIELD_PROGRESO_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
SEED_FIELD_SANMARTIN_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

SEED_WEATHER = {
    SEED_FIELD_ESPERANZA_ID: {
        "frost": [0.85, 0.40, 0.15, 0.70, 0.05, 0.90, 0.30],
        "rain":  [0.60, 0.75, 0.80, 0.20, 0.10, 0.55, 0.95],
        "hail":  [0.10, 0.20, 0.05, 0.85, 0.70, 0.15, 0.30],
        "drought": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35],
        "heat_wave": [0.70, 0.80, 0.45, 0.30, 0.60, 0.85, 0.50],
        "strong_wind": [0.40, 0.55, 0.65, 0.20, 0.75, 0.30, 0.10],
    },
    # ... similar para otros fields
}

async def seed_if_empty(session: AsyncSession):
    """Seed users, fields, weather data si DB vacía."""
    # Check si ya hay datos
    result = await session.execute(select(func.count(User.id)))
    if result.scalar() > 0:
        return

    # Seed users
    # Seed fields
    # Seed weather data con UPSERT
    ...

async def seed_weather(session: AsyncSession):
    """Re-seed weather data (llamado desde endpoint)."""
    today = datetime.now(timezone.utc).date()
    rows = []
    for field_id, events in SEED_WEATHER.items():
        for event_type, probabilities in events.items():
            for day_offset, prob in enumerate(probabilities):
                rows.append({
                    "id": uuid4(),
                    "field_id": field_id,
                    "event_date": today + timedelta(days=day_offset),
                    "event_type": event_type,
                    "probability": prob,
                })

    stmt = pg_insert(WeatherData).values(rows).on_conflict_do_update(
        index_elements=["field_id", "event_date", "event_type"],
        set_={"probability": pg_insert(WeatherData).excluded.probability},
    )
    await session.execute(stmt)
```

### Checkpoint Fase 4
Todavía no verificable vía HTTP — se testea directamente en Fase 7 (tests).
Pero se puede verificar importación:
```bash
docker-compose exec app python -c "from app.services.alert_evaluator import evaluate_alerts; print('OK')"
```

---

## Fase 5: Routers (~40 min)

### 5.1 app/routers/alert_configs.py

```python
router = APIRouter(prefix="/api/v1", tags=["alerts"])

@router.post("/fields/{field_id}/alerts", status_code=201, response_model=AlertConfigResponse)
async def create_alert(field_id: UUID, data: AlertConfigCreate, db: AsyncSession = Depends(get_db)):
    # Verificar field existe
    field = await db.get(Field, field_id)
    if not field:
        raise HTTPException(404, "Field not found")

    # Verificar no duplicado
    existing = await db.execute(
        select(AlertConfig).where(
            AlertConfig.field_id == field_id,
            AlertConfig.event_type == data.event_type.value
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Alert for this field and event type already exists. Use PATCH to update.")

    alert = AlertConfig(field_id=field_id, event_type=data.event_type.value, threshold=data.threshold)
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert

@router.get("/fields/{field_id}/alerts", response_model=list[AlertConfigResponse])
async def list_alerts(field_id: UUID, db: AsyncSession = Depends(get_db)):
    ...

@router.patch("/alerts/{alert_id}", response_model=AlertConfigResponse)
async def update_alert(alert_id: UUID, data: AlertConfigUpdate, db: AsyncSession = Depends(get_db)):
    ...

@router.delete("/alerts/{alert_id}", status_code=204)
async def delete_alert(alert_id: UUID, db: AsyncSession = Depends(get_db)):
    ...
```

### 5.2 app/routers/notifications.py

```python
router = APIRouter(prefix="/api/v1", tags=["notifications"])

@router.get("/users/{user_id}/notifications", response_model=PaginatedNotifications)
async def list_notifications(
    user_id: UUID,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    # JOIN notifications → alert_configs → fields WHERE fields.user_id == user_id
    ...

@router.patch("/notifications/{notification_id}/deliver", response_model=NotificationResponse)
async def mark_delivered(notification_id: UUID, db: AsyncSession = Depends(get_db)):
    ...
```

### 5.3 app/routers/jobs.py

```python
router = APIRouter(prefix="/api/v1", tags=["jobs"])

# Stats en memoria
job_stats: dict = {"last_run": None, "notifications_created": 0, "duration_ms": 0}

@router.post("/jobs/evaluate-alerts")
async def trigger_evaluation(db: AsyncSession = Depends(get_db)):
    start = time.monotonic()
    async with db.begin():
        count = await evaluate_alerts(db)
    duration_ms = round((time.monotonic() - start) * 1000)

    job_stats.update(
        last_run=datetime.now(timezone.utc).isoformat(),
        notifications_created=count,
        duration_ms=duration_ms,
    )
    return {"notifications_created": count, "duration_ms": duration_ms}

@router.get("/jobs/stats")
async def get_stats():
    return job_stats

@router.post("/weather/seed")
async def seed_weather_endpoint(db: AsyncSession = Depends(get_db)):
    async with db.begin():
        await seed_weather(db)
    return {"status": "seeded"}
```

### 5.4 Registrar routers en app/main.py
```python
app.include_router(alert_configs.router)
app.include_router(notifications.router)
app.include_router(jobs.router)
```

### Checkpoint Fase 5
```bash
docker-compose up -d --build
curl http://localhost:8000/docs  # Swagger UI con todos los endpoints
curl http://localhost:8000/health
# Crear alerta (field seed debe existir):
curl -X POST http://localhost:8000/api/v1/fields/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/alerts \
  -H "Content-Type: application/json" \
  -d '{"event_type": "frost", "threshold": 0.7}'
# → 201
```

---

## Fase 6: Scheduler + Lifespan (~20 min)

### 6.1 Actualizar app/main.py lifespan

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-seed
    async with async_session_factory() as session:
        async with session.begin():
            await seed_if_empty(session)

    # Start scheduler
    scheduler.add_job(
        run_evaluation,
        trigger=IntervalTrigger(minutes=settings.EVAL_INTERVAL_MINUTES),
        id="evaluate_alerts",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started: evaluating every {settings.EVAL_INTERVAL_MINUTES} min")
    yield
    scheduler.shutdown()

async def run_evaluation():
    start = time.monotonic()
    async with async_session_factory() as session:
        async with session.begin():
            count = await evaluate_alerts(session)
    duration_ms = round((time.monotonic() - start) * 1000)
    # Actualizar stats compartidos con el router
    from app.routers.jobs import job_stats
    job_stats.update(
        last_run=datetime.now(timezone.utc).isoformat(),
        notifications_created=count,
        duration_ms=duration_ms,
    )
    logger.info(f"Evaluation complete: {count} notifications in {duration_ms}ms")
```

### Checkpoint Fase 6
```bash
docker-compose up -d --build
# Esperar seed automático
curl http://localhost:8000/health
# Crear alerta
curl -X POST http://localhost:8000/api/v1/fields/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/alerts \
  -H "Content-Type: application/json" \
  -d '{"event_type": "frost", "threshold": 0.7}'
# Trigger manual
curl -X POST http://localhost:8000/api/v1/jobs/evaluate-alerts
# → {"notifications_created": N, "duration_ms": X}
# Ver notificaciones
curl http://localhost:8000/api/v1/users/11111111-1111-1111-1111-111111111111/notifications
# → Notificaciones con mensaje "⚠️ Alerta: probabilidad de helada del 85%..."
# Ver stats
curl http://localhost:8000/api/v1/jobs/stats
```

**Este es el checkpoint más importante. Si esto funciona, el core del challenge está resuelto.**

---

## Fase 7: Tests (~45 min)

### 7.1 tests/conftest.py

```python
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

TEST_DB_URL = "postgresql+asyncpg://agrobot:agrobot@localhost:5432/agrobot_test"
ADMIN_DB_URL = "postgresql+asyncpg://agrobot:agrobot@localhost:5432/postgres"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Crear DB de test si no existe + correr migraciones."""
    # Conectar a postgres DB para crear agrobot_test
    engine = create_async_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 FROM pg_database WHERE datname='agrobot_test'"))
        if not result.scalar():
            await conn.execute(text("CREATE DATABASE agrobot_test"))
    await engine.dispose()

    # Crear tablas
    test_engine = create_async_engine(TEST_DB_URL)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await test_engine.dispose()

@pytest_asyncio.fixture
async def db_session():
    """Session por test con rollback."""
    engine = create_async_engine(TEST_DB_URL)
    session_factory = async_sessionmaker(engine, class_=AsyncSession)
    async with session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()
    await engine.dispose()

@pytest_asyncio.fixture
async def client(db_session):
    """Test client con DB override."""
    app.dependency_overrides[get_db] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
```

### 7.2 tests/test_alert_evaluator.py (PRIORIDAD 1)

```python
# Helper: crear user, field, weather_data, alert_config en DB de test

async def test_no_alerts(db_session):
    """Sin alertas configuradas → 0 notificaciones."""
    count = await evaluate_alerts(db_session)
    assert count == 0

async def test_below_threshold(db_session):
    """Probabilidad menor que threshold → sin notificación."""
    # weather: frost 0.30, alert threshold 0.50
    count = await evaluate_alerts(db_session)
    assert count == 0

async def test_above_threshold(db_session):
    """Probabilidad mayor que threshold → 1 notificación."""
    # weather: frost 0.85, alert threshold 0.70
    count = await evaluate_alerts(db_session)
    assert count == 1

async def test_exact_threshold(db_session):
    """Probabilidad == threshold → SÍ notifica (>=)."""
    # weather: frost 0.70, alert threshold 0.70
    count = await evaluate_alerts(db_session)
    assert count == 1

async def test_idempotency(db_session):
    """Ejecutar 2 veces → segunda vez 0 nuevas."""
    count1 = await evaluate_alerts(db_session)
    count2 = await evaluate_alerts(db_session)
    assert count1 > 0
    assert count2 == 0

async def test_inactive_alert_skipped(db_session):
    """Alerta con is_active=False → sin notificación."""

async def test_past_date_skipped(db_session):
    """Weather data de ayer → no evaluada."""

async def test_multiple_fields_events(db_session):
    """Escenario mixto: múltiples fields y event types."""

async def test_message_content(db_session):
    """Verifica formato del mensaje: 'probabilidad de helada del 85%' no 'ClimateEventType.FROST'."""
    await evaluate_alerts(db_session)
    notification = await db_session.execute(select(Notification))
    notif = notification.scalar_one()
    assert "probabilidad de helada del 85%" in notif.message
    assert "La Esperanza" in notif.message
    assert "70%" in notif.message  # threshold

async def test_transaction_rollback(db_session):
    """Si hay error en inserts, no queda estado parcial."""
```

### 7.3 tests/test_routers/test_alert_configs.py (PRIORIDAD 2)

```python
async def test_create_alert(client, db_session):
    """POST /fields/{id}/alerts → 201."""

async def test_create_duplicate_alert(client, db_session):
    """POST duplicado → 409 con mensaje claro."""

async def test_create_alert_nonexistent_field(client, db_session):
    """POST con field_id inexistente → 404."""

async def test_create_alert_invalid_threshold(client, db_session):
    """POST con threshold > 1 → 422."""

async def test_patch_alert(client, db_session):
    """PATCH /alerts/{id} → 200, threshold actualizado."""

async def test_delete_alert(client, db_session):
    """DELETE /alerts/{id} → 204."""
```

### 7.4 tests/test_routers/test_notifications.py (PRIORIDAD 2)

```python
async def test_list_notifications_after_evaluate(client, db_session):
    """GET /users/{id}/notifications después de evaluate → resultados."""

async def test_list_notifications_pagination(client, db_session):
    """Verifica limit y offset."""

async def test_mark_delivered(client, db_session):
    """PATCH /notifications/{id}/deliver → 200, status cambia."""

async def test_delete_alert_notifications_set_null(client, db_session):
    """DELETE alert → notificaciones quedan con alert_config_id NULL."""
```

### Checkpoint Fase 7
```bash
docker-compose up -d  # DB debe estar corriendo
docker-compose exec app pytest -v
# → Todos pasan
```

---

## Fase 8: README (~30 min)

### Estructura del README
1. **Qué es**: Sistema de Alertas Climáticas para Agrobot
2. **Cómo correrlo**: `make setup` → listo
3. **Demo flow**: Paso a paso con curl commands y UUIDs del seed
4. **Arquitectura**: Diagrama ASCII simple (app → DB, scheduler → evaluator → notifications)
5. **Decisiones de diseño**: Tabla de trade-offs
6. **Endpoints**: Tabla con los 10 endpoints
7. **Testing**: `make test`
8. **Con más tiempo haría**: Lista priorizada

### Demo flow en README
```bash
# 1. Levantar
make setup

# 2. Crear alerta de helada con threshold 70%
curl -s -X POST http://localhost:8000/api/v1/fields/f1e2d3c4-b5a6-7890-fedc-ba0987654321/alerts -H "Content-Type: application/json" -d '{"event_type": "frost", "threshold": 0.7}'

# 3. Evaluar alertas
make evaluate

# 4. Ver notificaciones
curl -s "http://localhost:8000/api/v1/users/a1b2c3d4-e5f6-7890-abcd-ef1234567890/notifications"

# 5. Ver stats del job
curl http://localhost:8000/api/v1/jobs/stats

# 6. Correr tests
make test
```

### Checkpoint Fase 8
Leer el README de principio a fin. Seguir el demo flow. Todo debe funcionar.

---

## Orden de prioridades si se acaba el tiempo

Si quedan 2 horas:
1. ✅ Fase 1-4 (fundación + modelos + schemas + services)
2. ✅ Fase 5-6 (routers + scheduler)
3. ⚠️ Fase 7 solo tests del evaluator (Prioridad 1)
4. ⚠️ README mínimo

Si queda 1 hora:
1. ✅ Fase 1-6 (todo menos tests y README)
2. ⚠️ README con "cómo correr" + demo flow
3. ⚠️ Documentar en README: "Tests del evaluator están diseñados, faltó tiempo para implementarlos. Ver IMPLEMENTATION_PLAN.md para la especificación."

**Lo que NUNCA se sacrifica**: El evaluator funcionando + trigger manual + demo flow.

---

## Riesgos y Mitigaciones

| Riesgo | Mitigación |
|--------|-----------|
| Dockerfile falla (asyncpg compile) | libpq-dev + gcc ya incluidos. Testear en Fase 1. |
| Alembic env.py async no funciona | Verificar import de modelos y url config en Fase 1. |
| conftest.py no puede crear DB test | agrobot user es SUPERUSER del cluster PG. Verificar en Fase 7 temprano. |
| APScheduler no corre job | max_instances=1, replace_existing=True. Verificar en Fase 6. |
| Bridge de stats entre scheduler y router | Module-level dict compartido. Verificar import circular. |
| ON CONFLICT syntax con SQLAlchemy | `from sqlalchemy.dialects.postgresql import insert as pg_insert`. Testear en Fase 4. |
