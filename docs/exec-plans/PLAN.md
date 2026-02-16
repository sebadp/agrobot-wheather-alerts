
 Here is Claude's plan:
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 Plan: Sistema de Alertas Climáticas - Agrobot

 Contexto

 Challenge técnico ~5 horas. Usuarios configuran alertas con umbrales sobre campos agrícolas. Un background job evalúa datos
 meteorológicos y genera notificaciones. Los pronósticos son mutables — la probabilidad de un evento puede cambiar durante el día. El
  sistema debe notificar cambios significativos y "all clear" cuando el riesgo baja.

 ---
 Stack

 FastAPI + SQLAlchemy async + asyncpg + PostgreSQL + Alembic + APScheduler + Pydantic v2

 ---
 Estructura

 agrobot/
 ├── docker-compose.yml
 ├── Dockerfile
 ├── pyproject.toml
 ├── alembic.ini
 ├── Makefile
 ├── README.md
 ├── .env.example
 ├── alembic/
 │   ├── env.py
 │   └── versions/
 │       └── 001_initial_schema.py
 ├── app/
 │   ├── __init__.py
 │   ├── main.py                    # App factory + lifespan (scheduler + auto-seed)
 │   ├── config.py                  # Pydantic Settings
 │   ├── database.py                # Async engine + session factory
 │   ├── dependencies.py            # get_db
 │   ├── models/
 │   │   ├── __init__.py
 │   │   ├── user.py
 │   │   ├── field.py
 │   │   ├── weather_data.py
 │   │   ├── alert_config.py
 │   │   └── notification.py
 │   ├── schemas/
 │   │   ├── __init__.py
 │   │   ├── alert_config.py
 │   │   └── notification.py
 │   ├── services/
 │   │   ├── __init__.py
 │   │   ├── alert_evaluator.py     # Core: evaluación con tracking de evolución
 │   │   └── weather_seeder.py      # Seed determinista
 │   └── routers/
 │       ├── __init__.py
 │       ├── alert_configs.py
 │       ├── notifications.py
 │       └── jobs.py
 └── tests/
     ├── __init__.py
     ├── conftest.py
     ├── test_alert_evaluator.py
     └── test_routers/
         ├── __init__.py
         ├── test_alert_configs.py
         └── test_notifications.py

 ---
 Modelo de Datos

 Tablas

 1. users (seed, sin CRUD) — id (UUID PK), name, phone, created_at
 2. fields (seed, sin CRUD) — id (UUID PK), user_id (FK indexed), name, latitude, longitude, created_at
 3. weather_data — id (UUID PK), field_id (FK), event_date (DATE), event_type (enum), probability (Numeric(3,2)), created_at,
 updated_at
   - UNIQUE: (field_id, event_date, event_type)
   - INDEX: event_date
   - La probabilidad puede cambiar (UPSERT del job de ingesta)
 4. alert_configs — id (UUID PK), field_id (FK indexed, ON DELETE CASCADE), event_type, threshold (Numeric(3,2)), is_active,
 created_at, updated_at
   - UNIQUE: (field_id, event_type)
 5. notifications — id (UUID PK), alert_config_id (FK, ON DELETE SET NULL nullable), weather_data_id (FK), notification_type (enum),
 probability_at_notification (Numeric(3,2)), previous_notification_id (UUID FK self-referencing nullable), status, message,
 triggered_at, delivered_at
   - SIN UNIQUE constraint — múltiples notificaciones por (alert, weather) para tracking de evolución
   - INDEX: (alert_config_id, weather_data_id, triggered_at DESC) — lookup eficiente de última notificación
   - SET NULL en alert_config: historial no se pierde

 Enums

 class ClimateEventType(str, Enum):
     FROST = "frost"
     RAIN = "rain"
     HAIL = "hail"
     DROUGHT = "drought"
     HEAT_WAVE = "heat_wave"
     STRONG_WIND = "strong_wind"

 class NotificationType(str, Enum):
     RISK_INCREASED = "risk_increased"    # Nueva alerta o aumento significativo
     RISK_DECREASED = "risk_decreased"    # Bajó pero sigue sobre umbral (no se notifica, solo log)
     RISK_ENDED = "risk_ended"            # Bajó por debajo del umbral → all clear

 class NotificationStatus(str, Enum):
     PENDING = "pending"
     DELIVERED = "delivered"
     FAILED = "failed"

 Templates de mensaje

 TEMPLATES = {
     "risk_increased": "⚠️  Alerta: probabilidad de {event_label} {new_prob}% en campo {field_name} "
                       "para el {date}. Umbral: {threshold}%. {delta_text}",
     "risk_ended":     "✅ Riesgo mitigado: probabilidad de {event_label} bajó del {old_prob}% "
                       "al {new_prob}% en campo {field_name} para el {date}. "
                       "Ya no supera tu umbral de {threshold}%.",
 }
 # delta_text: "" si es primera notificación, "Subió del {old}% al {new}%" si es actualización

 ---
 API Endpoints (10)

 Health

 ┌────────┬─────────┬─────────────────────────────────────┐
 │ Method │  Path   │             Descripción             │
 ├────────┼─────────┼─────────────────────────────────────┤
 │ GET    │ /health │ {"status": "ok", "db": "connected"} │
 └────────┴─────────┴─────────────────────────────────────┘

 Alert Configs (core)

 ┌────────┬──────────────────────────────────┬─────────────────────────────────┐
 │ Method │               Path               │           Descripción           │
 ├────────┼──────────────────────────────────┼─────────────────────────────────┤
 │ POST   │ /api/v1/fields/{field_id}/alerts │ Crear alert config              │
 ├────────┼──────────────────────────────────┼─────────────────────────────────┤
 │ GET    │ /api/v1/fields/{field_id}/alerts │ Listar alertas del field        │
 ├────────┼──────────────────────────────────┼─────────────────────────────────┤
 │ PATCH  │ /api/v1/alerts/{alert_id}        │ Actualizar threshold y/o active │
 ├────────┼──────────────────────────────────┼─────────────────────────────────┤
 │ DELETE │ /api/v1/alerts/{alert_id}        │ Eliminar alert config           │
 └────────┴──────────────────────────────────┴─────────────────────────────────┘

 Notificaciones

 ┌────────┬───────────────────────────────────────────────────────────────┬─────────────────────────────────────────┐
 │ Method │                             Path                              │               Descripción               │
 ├────────┼───────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
 │ GET    │ /api/v1/users/{user_id}/notifications?type=&limit=20&offset=0 │ Listar con filtro por tipo y paginación │
 ├────────┼───────────────────────────────────────────────────────────────┼─────────────────────────────────────────┤
 │ PATCH  │ /api/v1/notifications/{id}/deliver                            │ Marcar como delivered                   │
 └────────┴───────────────────────────────────────────────────────────────┴─────────────────────────────────────────┘

 Operaciones

 ┌────────┬──────────────────────────────┬───────────────────────────┐
 │ Method │             Path             │        Descripción        │
 ├────────┼──────────────────────────────┼───────────────────────────┤
 │ POST   │ /api/v1/weather/seed         │ Regenerar mock data       │
 ├────────┼──────────────────────────────┼───────────────────────────┤
 │ POST   │ /api/v1/jobs/evaluate-alerts │ Trigger manual            │
 ├────────┼──────────────────────────────┼───────────────────────────┤
 │ GET    │ /api/v1/jobs/stats           │ Stats de última ejecución │
 └────────┴──────────────────────────────┴───────────────────────────┘

 Error responses

 404: {"detail": "Field not found"}
 409: {"detail": "Alert for this field and event type already exists. Use PATCH to update."}
 422: Pydantic validation automática

 ---
 Core: Alert Evaluator (lógica de evolución)

 Algoritmo por cada (alert_config, weather_data) activo

 1. Obtener última notificación para este par (triggered_at DESC LIMIT 1)

 2. Si NO hay notificación previa:
    - probability >= threshold → NOTIFICAR (risk_increased, primera vez)
    - probability < threshold → no hacer nada

 3. Si HAY notificación previa:

    Caso A: Antes >= threshold, ahora < threshold
    → NOTIFICAR (risk_ended) — siempre, ignora cooldown
    "✅ Riesgo mitigado..."

    Caso B: Antes >= threshold, sigue >= threshold, delta >= DELTA_THRESHOLD (10%)
    → NOTIFICAR (risk_increased) — si no hay cooldown activo
    "⚠️  Alerta actualizada: subió del 70% al 85%"

    Caso C: Antes >= threshold, sigue >= threshold, delta < DELTA_THRESHOLD
    → NO NOTIFICAR (evitar spam, solo log)

    Caso D: Antes < threshold, ahora >= threshold
    → NOTIFICAR (risk_increased) — si no hay cooldown activo
    "⚠️  Nueva alerta..."

 4. Cooldown: No notificar más de 1 vez cada COOLDOWN_HOURS (6h) por (alert_config, weather_data),
    EXCEPTO risk_ended que siempre notifica inmediatamente.

 Query con CTE para última notificación

 # CTE: última notificación por (alert_config_id, weather_data_id)
 latest_notification = (
     select(
         Notification.alert_config_id,
         Notification.weather_data_id,
         Notification.notification_type,
         Notification.probability_at_notification,
         Notification.triggered_at,
         Notification.id.label("notification_id"),
         func.row_number().over(
             partition_by=[Notification.alert_config_id, Notification.weather_data_id],
             order_by=Notification.triggered_at.desc()
         ).label("rn")
     )
     .where(Notification.alert_config_id.isnot(None))
     .cte("latest_notification")
 )

 latest = (
     select(latest_notification)
     .where(latest_notification.c.rn == 1)
     .cte("latest")
 )

 # Query principal
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
     .join(WeatherData, and_(
         WeatherData.field_id == AlertConfig.field_id,
         WeatherData.event_type == AlertConfig.event_type
     ))
     .outerjoin(latest, and_(
         latest.c.alert_config_id == AlertConfig.id,
         latest.c.weather_data_id == WeatherData.id
     ))
     .where(
         AlertConfig.is_active == True,
         WeatherData.event_date >= today,
     )
 )

 Lógica post-query

 for row in results:
     alert_config, weather_data, field_name, prev_type, prev_prob, prev_triggered, prev_id = row

     current_prob = float(weather_data.probability)
     threshold = float(alert_config.threshold)
     above_threshold = current_prob >= threshold

     # Determinar acción
     action = determine_action(
         has_previous=prev_type is not None,
         was_above=(prev_prob is not None and float(prev_prob) >= threshold),
         is_above=above_threshold,
         current_prob=current_prob,
         prev_prob=float(prev_prob) if prev_prob else None,
         prev_triggered=prev_triggered,
         delta_threshold=settings.DELTA_THRESHOLD,
         cooldown_hours=settings.COOLDOWN_HOURS,
     )

     if action is None:
         continue  # No notificar

     # Crear notificación
     notification = Notification(
         alert_config_id=alert_config.id,
         weather_data_id=weather_data.id,
         notification_type=action.type,
         probability_at_notification=current_prob,
         previous_notification_id=prev_id,
         status="pending",
         message=build_message(action.type, alert_config, weather_data, field_name, prev_prob),
     )
     session.add(notification)
     logger.info(notification.message)
     count += 1

 Función determine_action

 @dataclass
 class NotificationAction:
     type: NotificationType

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

     # Sin historial previo
     if not has_previous:
         if is_above:
             return NotificationAction(type=NotificationType.RISK_INCREASED)
         return None

     # Caso A: Estaba arriba, ahora abajo → all clear (ignora cooldown)
     if was_above and not is_above:
         return NotificationAction(type=NotificationType.RISK_ENDED)

     # Cooldown check (excepto risk_ended que ya se procesó arriba)
     if prev_triggered and is_within_cooldown(prev_triggered, cooldown_hours):
         return None

     # Caso B: Sigue arriba, delta significativo
     if was_above and is_above:
         delta = current_prob - (prev_prob or 0)
         if delta >= delta_threshold:
             return NotificationAction(type=NotificationType.RISK_INCREASED)
         return None  # Caso C: cambio menor, no notificar

     # Caso D: Estaba abajo, ahora arriba
     if not was_above and is_above:
         return NotificationAction(type=NotificationType.RISK_INCREASED)

     return None

 Transacción explícita

 Todo dentro de async with session.begin(). Si falla algo, rollback completo.

 ---
 Background Job: APScheduler

 scheduler = AsyncIOScheduler()

 @asynccontextmanager
 async def lifespan(app: FastAPI):
     await seed_if_empty()
     scheduler.add_job(
         run_evaluation,
         trigger=IntervalTrigger(minutes=settings.EVAL_INTERVAL_MINUTES),
         id="evaluate_alerts",
         max_instances=1,
         replace_existing=True,
     )
     scheduler.start()
     yield
     scheduler.shutdown()

 max_instances=1 previene ejecuciones paralelas. Sin bridge patterns, todo async-native.

 ---
 Config

 class Settings(BaseSettings):
     DATABASE_URL: str = "postgresql+asyncpg://agrobot:agrobot@localhost:5432/agrobot"
     EVAL_INTERVAL_MINUTES: int = 15
     DELTA_THRESHOLD: float = 0.10    # 10 puntos porcentuales
     COOLDOWN_HOURS: int = 6          # Mínimo entre notificaciones por par
     model_config = ConfigDict(env_file=".env")

 ---
 Dockerfile + Docker Compose

 Dockerfile

 FROM python:3.12-slim
 RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*
 WORKDIR /app
 COPY pyproject.toml .
 RUN pip install --no-cache-dir .
 COPY . .

 Docker Compose (2 servicios)

 services:
   db:
     image: postgres:16-alpine
     environment: { POSTGRES_USER: agrobot, POSTGRES_PASSWORD: agrobot, POSTGRES_DB: agrobot }
     ports: ["5432:5432"]
     volumes: [pgdata:/var/lib/postgresql/data]
     healthcheck: { test: ["CMD-SHELL", "pg_isready -U agrobot"], interval: 5s, retries: 5 }
   app:
     build: .
     ports: ["8000:8000"]
     environment:
       DATABASE_URL: postgresql+asyncpg://agrobot:agrobot@db:5432/agrobot
       DELTA_THRESHOLD: "0.10"
       COOLDOWN_HOURS: "6"
     depends_on: { db: { condition: service_healthy } }
     command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"
 volumes:
   pgdata:

 ---
 Makefile

 setup:     docker-compose up -d --build && wait for health
 down:      docker-compose down -v
 test:      docker-compose exec app pytest -v
 evaluate:  curl POST /jobs/evaluate-alerts
 logs:      docker-compose logs -f
 seed:      curl POST /weather/seed

 ---
 Seed Determinista

 UUIDs hardcodeados + probabilidades que cubren todos los escenarios:
 SEED_WEATHER = {
     SEED_FIELD_ESPERANZA_ID: {
         "frost": [0.85, 0.40, 0.15, 0.70, 0.05, 0.90, 0.30],
         # día 1: 85% → alert_config threshold 70% → notifica risk_increased
         # re-seed con 60%: baja por debajo → notifica risk_ended
         # re-seed con 95%: sube 35 puntos → notifica risk_increased (delta > 10%)
     },
 }

 ---
 Testing

 DB de tests

 conftest.py crea agrobot_test (POSTGRES_USER es SUPERUSER del cluster PG).

 Prioridad 1: Evaluator con evolución

 - test_no_alerts → 0 notificaciones
 - test_first_above_threshold → risk_increased
 - test_first_below_threshold → no notifica
 - test_risk_ended → prob baja de 85% a 60% con threshold 70% → risk_ended con mensaje "✅ Riesgo mitigado..."
 - test_risk_increased_delta → prob sube de 70% a 85% (delta 15% > 10%) → risk_increased
 - test_no_spam_small_changes → prob sube de 70% a 75% (delta 5% < 10%) → no notifica
 - test_cooldown_respected → 2 cambios en 1 hora, solo primera notifica
 - test_cooldown_bypass_for_ended → cooldown activo pero risk_ended → notifica igual
 - test_case_d_below_to_above → estaba abajo, ahora arriba → risk_increased
 - test_message_content_risk_increased → formato correcto
 - test_message_content_risk_ended → formato correcto "✅"
 - test_previous_notification_id_linked → notificación tiene ref a la anterior
 - test_idempotency → ejecutar 2x sin cambio → segunda 0 nuevas (misma prob, cooldown)
 - test_transaction_rollback

 Prioridad 2: Endpoints

 - POST alert → 201
 - POST duplicado → 409
 - PATCH threshold → 200
 - DELETE → 204
 - GET notifications con ?type=risk_ended → filtro funciona
 - GET notifications paginación

 ---
 Trade-offs (README)

 ┌─────────────────┬──────────────────────────────────────────────┬───────────────────────────────────────────────┐
 │    Decisión     │                   Elegido                    │                   Trade-off                   │
 ├─────────────────┼──────────────────────────────────────────────┼───────────────────────────────────────────────┤
 │ Background job  │ APScheduler in-process                       │ No escala horizontal, async-native            │
 ├─────────────────┼──────────────────────────────────────────────┼───────────────────────────────────────────────┤
 │ Idempotencia    │ Sin UNIQUE, tracking por última notificación │ Tabla crece más, pero historial completo      │
 ├─────────────────┼──────────────────────────────────────────────┼───────────────────────────────────────────────┤
 │ Cooldown        │ 6h configurable                              │ Puede perder cambios rápidos, evita spam      │
 ├─────────────────┼──────────────────────────────────────────────┼───────────────────────────────────────────────┤
 │ Delta threshold │ 10% configurable                             │ Arbitrario, pero razonable                    │
 ├─────────────────┼──────────────────────────────────────────────┼───────────────────────────────────────────────┤
 │ risk_ended      │ Siempre notifica (ignora cooldown)           │ Posible ruido si fluctúa cerca del umbral     │
 ├─────────────────┼──────────────────────────────────────────────┼───────────────────────────────────────────────┤
 │ CTE para lookup │ Row number + partition                       │ Query más complejo, pero eficiente con índice │
 ├─────────────────┼──────────────────────────────────────────────┼───────────────────────────────────────────────┤
 │ Delete alerts   │ SET NULL                                     │ Historial no se pierde                        │
 └─────────────────┴──────────────────────────────────────────────┴───────────────────────────────────────────────┘

 Patrones implementados

 - Service Layer: Lógica desacoplada de HTTP
 - State Machine: Evaluator como máquina de estados (above/below threshold × has/no previous)

 ---
 "Con más tiempo" (README)

 - Celery + Redis para jobs distribuidos
 - NotificationDispatcher Strategy Pattern
 - alert_notification_log para auditoría completa
 - Advisory locks de PostgreSQL para concurrencia
 - Rate limiting, paginación cursor-based
 - Logging estructurado + correlation IDs
 - Monitoring, CI/CD
 - Particionamiento de notifications históricas
 - Soft delete en alert_configs
 - Hysteresis: umbral de bajada diferente al de subida (evitar flip-flop)

 ---
 Secuencia

 1. Fundación: pyproject, config (con DELTA_THRESHOLD y COOLDOWN_HOURS), database, Dockerfile, compose, Makefile
 2. Modelos: SQLAlchemy models con NotificationType enum, sin UNIQUE en notifications, índice compuesto
 3. Schemas: Pydantic v2 con notification_type filter
 4. Services: determine_action (state machine pura) + evaluate_alerts (query con CTE) + build_message (templates) + weather_seeder
 5. Routers: 10 endpoints, filtro por type en notifications
 6. Scheduler: APScheduler lifespan + auto-seed
 7. Tests: conftest → evaluator con todos los cases → endpoints
 8. README: Setup, demo flow, trade-offs

 ---
 Verificación

 1. make setup → levanta db + app, migraciones, seed
 2. Crear alerta: curl POST /fields/{id}/alerts {"event_type": "frost", "threshold": 0.7}
 3. make evaluate → risk_increased (frost 85% > 70%)
 4. Re-seed con probabilidades más bajas → make evaluate → risk_ended
 5. Re-seed con probabilidades mucho más altas → make evaluate → risk_increased (delta)
 6. curl GET /users/{id}/notifications?type=risk_ended → filtro funciona
 7. curl GET /jobs/stats → stats actualizados
 8. make test → todos pasan