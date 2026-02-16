# Agrobot - Sistema de Alertas Climaticas

Sistema de alertas climaticas para campos agricolas. Los usuarios configuran umbrales sobre eventos meteorologicos; un background job evalua datos periodicamente y genera notificaciones con tracking de evolucion (primera alerta, actualizacion por cambio significativo, "all clear" cuando el riesgo baja).

## Stack

FastAPI + SQLAlchemy 2.x async + asyncpg + PostgreSQL + Alembic + APScheduler + Pydantic v2

## Requisitos

- Python >= 3.11
- Docker y Docker Compose
- Make (preinstalado en macOS/Linux; Windows: `choco install make` o usar WSL)

## Setup local (desarrollo)

```bash
make dev                    # Crea venv, instala deps, configura pre-commit
source .venv/bin/activate
cp .env.example .env
```

## Como correrlo

```bash
make setup      # Levanta DB + App, corre migraciones, seed automatico, espera health
make up         # Levanta en background (detached)
make up-logs    # Levanta con logs en foreground
make logs       # Logs en tiempo real
make down       # Baja todo (incluyendo volumenes)
make test       # Corre los 30 tests (SQLite in-memory, no requiere Docker)
```

## Demo

```bash
# 1. Crear alerta de helada con umbral 70% en Campo La Esperanza
curl -s -X POST http://localhost:8000/api/v1/fields/f1e2d3c4-b5a6-7890-fedc-ba0987654321/alerts \
  -H "Content-Type: application/json" \
  -d '{"event_type": "frost", "threshold": 0.7}' | python3 -m json.tool

# 2. Evaluar → genera risk_increased (frost 85% > 70%)
make evaluate

# 3. Re-seed con nuevas probabilidades y evaluar de nuevo
make seed && make evaluate

# 4. Ver notificaciones del usuario
curl -s http://localhost:8000/api/v1/users/a1b2c3d4-e5f6-7890-abcd-ef1234567890/notifications | python3 -m json.tool

# 5. Filtrar por tipo
curl -s "http://localhost:8000/api/v1/users/a1b2c3d4-e5f6-7890-abcd-ef1234567890/notifications?type=risk_ended" | python3 -m json.tool

# 6. Stats y health
curl -s http://localhost:8000/api/v1/jobs/stats | python3 -m json.tool
curl -s http://localhost:8000/health | python3 -m json.tool
```

IDs de seed (deterministas, para copy-paste):
- **User**: `a1b2c3d4-e5f6-7890-abcd-ef1234567890`
- **Campo La Esperanza**: `f1e2d3c4-b5a6-7890-fedc-ba0987654321`
- **Campo Primavera**: `f2e3d4c5-b6a7-8901-fedc-ba1098765432`

## API

| Method | Path | Descripcion |
|--------|------|-------------|
| GET | `/health` | Health check (503 si la DB esta caida) |
| POST | `/api/v1/fields/{field_id}/alerts` | Crear alert config (201, 404, 409) |
| GET | `/api/v1/fields/{field_id}/alerts` | Listar alertas del field |
| PATCH | `/api/v1/alerts/{alert_id}` | Actualizar threshold y/o active |
| DELETE | `/api/v1/alerts/{alert_id}` | Eliminar alert config (204) |
| GET | `/api/v1/users/{user_id}/notifications?type=&limit=&offset=` | Listar notificaciones con filtro y paginacion |
| PATCH | `/api/v1/notifications/{id}/deliver` | Marcar como delivered |
| POST | `/api/v1/weather/seed` | Regenerar datos mock |
| POST | `/api/v1/jobs/evaluate-alerts` | Trigger manual de evaluacion |
| GET | `/api/v1/jobs/stats` | Stats de notificaciones |

---

## Decisiones tomadas

### Codigo production-ready

- **Service Layer desacoplado de HTTP**: la logica de negocio vive en `app/services/`, los routers solo manejan HTTP. 17 de 30 tests son del servicio directamente, sin pasar por HTTP.
- **`determine_action()` como funcion pura**: recibe datos, devuelve una decision. Sin side effects, sin I/O, sin sesion de DB. 8 tests unitarios cubren todos los estados de la maquina.
- **Error handling en scheduler**: `try/except` con logging estructurado, correlation IDs y deteccion de backpressure (warning si la evaluacion tarda mas del 80% del intervalo).
- **Health endpoint resiliente**: devuelve `503 Service Unavailable` cuando la DB esta caida, no un 500 generico.
- **Connection pool tuneado**: `pool_pre_ping=True` (verifica conexiones stale), `pool_recycle=3600` (renueva antes de timeout de PG).
- **Logging estructurado**: JSON con correlation IDs por request y por ejecucion del scheduler. Parseable por CloudWatch, Datadog, ELK.
- **Multi-stage Dockerfile**: imagen de produccion sin pytest, httpx, ni aiosqlite.
- **Configuracion externalizada**: `DELTA_THRESHOLD`, `COOLDOWN_HOURS`, `EVAL_INTERVAL_MINUTES` son env vars. Cambiar comportamiento sin tocar codigo.

### Modelo de datos solido

5 tablas normalizadas con integridad referencial:

```
users -1:N-> fields -1:N-> alert_configs
               |                 |
               +-1:N-> weather_data
                                 |
               alert_configs ---+-> notifications
                                     (self-ref: previous_notification_id)
```

- **CHECK constraints a nivel de DB**: `probability BETWEEN 0 AND 1`, `threshold BETWEEN 0 AND 1`. La validacion no depende solo de Pydantic.
- **UNIQUE constraints**: `(field_id, event_date, event_type)` en weather_data; `(field_id, event_type)` en alert_configs.
- **ON DELETE CASCADE** en `alert_configs.field_id`: borrar campo limpia alertas.
- **ON DELETE SET NULL** en `notifications.alert_config_id` y `previous_notification_id`: borrar alerta o notificacion preserva historial.
- **Sin UNIQUE en notifications** (intencionalmente): multiples notificaciones por par (alert, weather) es el mecanismo de tracking de evolucion.
- **UPSERT** para datos meteorologicos mutables: `ON CONFLICT DO UPDATE` actualiza probabilidad sin duplicar registros.
- **Indices optimizados**: `ix_weather_data_field_id` para el JOIN del evaluator, `ix_notification_lookup` para el CTE, `ix_weather_event_date` para filtro temporal.
- **Timestamps timezone-aware**: `DateTime(timezone=True)` con `server_default=func.now()`.

### Asincronia

Stack 100% async de punta a punta:

```
Request -> FastAPI (async) -> Router (async def) -> SQLAlchemy (async session) -> asyncpg -> PostgreSQL
```

- No hay bridges sync-to-async, no hay `run_in_executor()`, no hay `loop.run_until_complete()`.
- **APScheduler con `AsyncIOScheduler`**: corre en el mismo event loop que FastAPI. No crea threads ni procesos. `max_instances=1` previene ejecuciones paralelas del scheduler.
- **Advisory lock de PostgreSQL** (`pg_try_advisory_lock`): previene evaluaciones concurrentes entre scheduler y endpoint manual. Non-blocking: si otra evaluacion esta corriendo, devuelve `False` inmediatamente.
- **Sesion por request** via dependency injection: cada request obtiene su propia sesion, que se cierra automaticamente.
- **Una sola query SQL** con CTEs (`ROW_NUMBER() OVER PARTITION BY`) resuelve toda la evaluacion. 1 roundtrip a la DB por ciclo, no N+1.

---

## Logica de evaluacion

El evaluator funciona como una maquina de estados por cada par (alert_config, weather_data):

| Estado | Condicion | Resultado |
|--------|-----------|-----------|
| Sin historial | prob >= umbral | `risk_increased` |
| Sin historial | prob < umbral | No notifica |
| Caso A | Estaba arriba, ahora abajo | `risk_ended` (ignora cooldown) |
| Caso B | Sigue arriba, delta >= 10% | `risk_increased` (respeta cooldown) |
| Caso C | Sigue arriba, delta < 10% | No notifica (anti-spam) |
| Caso D | Estaba abajo, ahora arriba | `risk_increased` (respeta cooldown) |

`previous_notification_id` arma una linked list que preserva la cadena de evolucion completa.

---

## Trade-offs

| Decision | Elegido | Alternativa | Justificacion |
|----------|---------|-------------|---------------|
| Background job | APScheduler in-process | Celery + Redis | Async-native, zero infra extra. Celery no es async y requiere bridge patterns. Para escalar: Celery podría considerarse como mejora aunque SQS + ECS Workers es una mejor alternativa para escalabilidad horizontal. |
| Matcheo weather-field | Directo por FK (`field_id`) | PostGIS geoespacial | El challenge dice "datos ya disponibles". El seeder simula el job de ingesta. |
| Enums | String(50) en DB | PostgreSQL ENUM | Portabilidad (SQLite en tests) y flexibilidad (agregar tipos sin migracion). |
| Idempotencia | Sin UNIQUE, tracking por ultima notificacion | UNIQUE constraint | Tabla crece, pero historial completo de evolucion. |
| Cooldown | 6h configurable | Sin cooldown | Evita spam. `risk_ended` siempre notifica inmediatamente (ignora cooldown). |
| Delete alerts | SET NULL en FK | CASCADE | Historial de notificaciones no se pierde al borrar una alerta. |

---

## Tests

32 tests, ~78% coverage global. Core logic (`determine_action`, `evaluate_alerts`) ~100%.

```
tests/
├── test_alert_evaluator.py      # 17 tests: state machine + CTE + mensajes
└── test_routers/
    ├── test_alert_configs.py    # 7 tests: CRUD + validacion + 409
    └── test_notifications.py    # 6 tests: filtro + paginacion + deliver
```

DB de tests: SQLite in-memory con aiosqlite. Cada test crea una DB limpia, ejecuta y destruye. Sin estado compartido.

---

## Con mas tiempo

| Prioridad | Mejora | Impacto |
|-----------|--------|---------|
| P2 | Autenticacion (JWT con ownership check por campo) | Seguridad |
| P3 | SQS + ECS Workers para jobs distribuidos | Escalabilidad horizontal |
| P3 | PostGIS para matcheo geoespacial en ingesta | Ingesta real de datos |
| P3 | Cursor-based pagination | Performance con datasets grandes |
| P3 | Hysteresis (umbral de bajada != umbral de subida) | Evitar flip-flop cerca del umbral |
| P3 | Digest de notificaciones (agrupar por campo+evento en ventana temporal) | Reducir volumen de mensajes en produccion |
| P3 | Observabilidad: Prometheus `/metrics`, pending queue age, evaluations counter, alerting si pending crece sin delivered | Operabilidad en produccion |
| P3 | Suscripciones multi-usuario por campo (separar ownership de quien recibe notificaciones, con rol y canal preferido) | Modelado para equipos reales |
| P3 | Granularidad horaria en weather_data (pronostico por hora en vez de por dia). Simplificado a un valor diario por el scope del challenge | Precision de alertas |

---

## CI

El pipeline de GitHub Actions ejecuta tres jobs en paralelo:

- **Lint** — `ruff check` + `ruff format --check`
- **Type check** — `mypy app/`
- **Test** — `pytest` (corre despues de lint y typecheck)

En PRs a `main`:

- **AI Review** — Gemini 2.0 Flash analiza el diff y postea un code review
- **AI Description** — Genera titulo y descripcion del PR automaticamente

## Pre-commit

Los mismos checks corren localmente antes de cada commit:

```bash
pre-commit run --all-files  # correr manualmente
make check                  # lint + typecheck + tests
```

Hooks: ruff (lint + format), mypy, pytest.

---

## Documentacion adicional

- [`docs/design-docs/WALKTHROUGH.md`](docs/design-docs/WALKTHROUGH.md) — Explicacion 0-a-100 del sistema
- [`docs/design-docs/REVIEW_NOTES.md`](docs/design-docs/REVIEW_NOTES.md) — 22 decisiones arquitectonicas
- [`AGENTS.md`](AGENTS.md) — Mapa del proyecto
