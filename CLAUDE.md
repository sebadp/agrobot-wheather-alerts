# Agrobot - Sistema de Alertas Climáticas

## Proyecto

Aplicación FastAPI async para alertas climáticas en campos agrícolas. Un background job (APScheduler) evalúa pronósticos meteorológicos contra umbrales configurados por el usuario y genera notificaciones, incluyendo tracking de evolución y "all clear" cuando el riesgo baja.

## Stack

- **Runtime**: Python 3.11+
- **API**: FastAPI con async/await nativo
- **ORM**: SQLAlchemy 2.x async (asyncpg para PostgreSQL, aiosqlite para tests)
- **Migraciones**: Alembic (async)
- **Scheduler**: APScheduler (AsyncIOScheduler)
- **Validación**: Pydantic v2 (pydantic-settings para config)
- **Tests**: pytest + pytest-asyncio + httpx (ASGI transport)

## Estructura del proyecto

```
app/
├── main.py              # App factory + lifespan (scheduler + auto-seed)
├── config.py            # Pydantic Settings (env vars)
├── database.py          # Async engine + session factory
├── dependencies.py      # get_db (FastAPI dependency)
├── models/              # SQLAlchemy declarative models
├── schemas/             # Pydantic v2 request/response schemas
├── services/            # Lógica de negocio (alert_evaluator, weather_seeder)
└── routers/             # FastAPI routers (alert_configs, notifications, jobs)
tests/
├── conftest.py          # Fixtures: SQLite in-memory, seeded_session, ASGI client
├── test_alert_evaluator.py  # Unit + integration tests del core
└── test_routers/        # Endpoint tests
```

## Arquitectura y patrones clave

### Service Layer
La lógica de negocio vive en `app/services/`, NO en los routers. Los routers solo manejan HTTP (parsing, status codes, errores). Cuando agregues funcionalidad nueva, creá el servicio primero y después el router que lo consume.

### State Machine (alert_evaluator)
`determine_action()` es una función pura que decide si notificar basándose en:
- `has_previous`: si existe notificación previa para ese par (alert_config, weather_data)
- `was_above` / `is_above`: si la probabilidad estaba/está por encima del umbral
- delta y cooldown

Los casos son: A (risk_ended), B (delta significativo), C (cambio menor, no notificar), D (below→above).
**risk_ended siempre ignora el cooldown.** El resto respeta `COOLDOWN_HOURS`.

### CTE Query
`evaluate_alerts()` usa un CTE con `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY triggered_at DESC)` para obtener la última notificación por cada par (alert_config_id, weather_data_id) en una sola query. No cambies esto a N+1 queries.

### Transacciones
`evaluate_alerts()` opera dentro de `async with session.begin()`. Si falla algo, rollback completo. No mezcles commits parciales.

## Convenciones de código

### Models
- Todos los IDs son `UUID(as_uuid=True)` con `default=uuid.uuid4`
- Timestamps con `DateTime(timezone=True)` y `server_default=func.now()`
- Los enums se almacenan como `String(50)` en la DB, no como `Enum` nativo de PostgreSQL (más portable)
- Las FK de `notifications.alert_config_id` usan `ON DELETE SET NULL` para preservar historial

### Schemas (Pydantic v2)
- Siempre usar `model_config = {"from_attributes": True}` en schemas de response
- Validación con `Field(ge=0.0, le=1.0)` para probabilidades/thresholds

### Routers
- Prefijo: `/api/v1/`
- POST crea → 201, DELETE → 204, errores → 404/409/422
- Siempre verificar existencia del recurso padre antes de operar (field exists before creating alert)
- Duplicados de UNIQUE constraint → catch `IntegrityError` → 409 con mensaje descriptivo

### Tests
- DB: SQLite in-memory con `aiosqlite` (no requiere PostgreSQL corriendo)
- Fixtures en `conftest.py`: `db_session` (tablas limpias), `seeded_session` (con datos), `client` (ASGI)
- UUIDs fijos para datos seed (`USER_ID`, `FIELD_ID`, `FIELD_2_ID` en conftest)
- Los tests de integración del evaluator manipulan `WeatherData.probability` directamente y re-evalúan
- Override de `get_db` en el fixture `client` para inyectar la sesión de test

## Skills (slash commands)

Definidos en `.claude/skills/`. Usar con `/nombre` en el chat:

| Skill | Uso | Qué hace |
|-------|-----|----------|
| `/evaluate-alerts` | Sin argumentos | Ejecuta el job de evaluación, muestra stats y últimas notificaciones generadas |
| `/add-alert` | `frost 0.7` | Crea una alerta para un campo con evento y umbral dados. Si ya existe, ofrece PATCH |

## Comandos

```bash
# Desarrollo con Docker
make setup          # docker compose up + wait for health
make down           # docker compose down -v
make test           # pytest dentro del container
make evaluate       # POST /api/v1/jobs/evaluate-alerts
make seed           # POST /api/v1/weather/seed
make logs           # docker compose logs -f

# Tests locales (requiere aiosqlite)
python -m pytest tests/ -v --timeout=30

# Solo unit tests (rápidos, sin DB)
python -m pytest tests/test_alert_evaluator.py::TestDetermineAction -v

# Solo integration tests
python -m pytest tests/test_alert_evaluator.py::TestEvaluateAlerts -v
```

## Seed data

UUIDs hardcodeados en `app/services/weather_seeder.py`:
- **User**: `a1b2c3d4-e5f6-7890-abcd-ef1234567890`
- **Campo La Esperanza**: `f1e2d3c4-b5a6-7890-fedc-ba0987654321`
- **Campo Primavera**: `f2e3d4c5-b6a7-8901-fedc-ba1098765432`

El seed usa `ON CONFLICT DO UPDATE` (upsert) para las probabilidades, así se puede re-seedear para simular cambios.

## Configuración (env vars)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://agrobot:agrobot@localhost:5432/agrobot` | Connection string |
| `EVAL_INTERVAL_MINUTES` | `15` | Intervalo del scheduler |
| `DELTA_THRESHOLD` | `0.10` | Cambio mínimo de probabilidad para re-notificar (10 puntos) |
| `COOLDOWN_HOURS` | `6` | Mínimo entre notificaciones por par (excepto risk_ended) |

## Cosas a tener en cuenta

- **No hay autenticación**. Los endpoints asumen confianza (challenge scope).
- **APScheduler corre in-process**, no escala horizontal. Para producción sería Celery + Redis.
- **`notifications` no tiene UNIQUE constraint** — múltiples notificaciones por par (alert, weather) es intencional para tracking de evolución.
- **SQLite para tests**: algunas features de PostgreSQL (como `ON CONFLICT ... DO UPDATE` con constraints nombrados) no funcionan en SQLite. El seeder usa PostgreSQL-specific syntax y no se testea con SQLite. Los tests del evaluator y routers sí corren en SQLite.
- **Alembic migrations**: al agregar un modelo nuevo, registrarlo en `app/models/__init__.py` para que Alembic lo detecte.

## Errores conocidos y soluciones aplicadas

### Dockerfile: paquete `app` no encontrado por Alembic
**Problema**: `pip install ".[dev]"` corre antes del `COPY . .`, instalando dependencias pero no el paquete. Alembic falla con `ModuleNotFoundError: No module named 'app'`.
**Solución**: Agregar `RUN pip install --no-cache-dir --no-deps -e .` después del `COPY . .` para registrar el paquete sin reinstalar dependencias.

### SQLAlchemy: transacción duplicada en servicios
**Problema**: `async_session_factory()` inicia una transacción implícita. Usar `async with session.begin()` dentro de un servicio lanza `InvalidRequestError: A transaction is already begun`.
**Solución**: NO usar `session.begin()` explícito en servicios. Usar `await session.commit()` al final. Esto aplica tanto a `seed_data()` como a `evaluate_alerts()`.

## Coverage

78% total (30 tests). La lógica de negocio (evaluator, models, schemas) tiene ~100%. Lo que baja el número:
- `weather_seeder.py` (44%): usa syntax PostgreSQL, no se testea con SQLite
- `main.py` (56%): lifespan y scheduler no se ejecutan en tests
- Routers (42-51%): se testean vía ASGI client pero la cobertura no se registra correctamente por el transport
