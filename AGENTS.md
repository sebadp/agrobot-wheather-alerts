# Agrobot — Mapa del Proyecto

Sistema de alertas climaticas para campos agricolas.
FastAPI + SQLAlchemy async + PostgreSQL + APScheduler.

---

## Codigo

```
app/
├── main.py              # Lifespan (scheduler + auto-seed), middleware, health
├── config.py            # Pydantic Settings (env vars)
├── database.py          # Async engine + session factory (pool tuning)
├── dependencies.py      # get_db (session per request)
├── logging_config.py    # JSON structured logging + correlation IDs
├── models/              # SQLAlchemy 2.x (5 tablas, CHECK constraints, cascades)
├── schemas/             # Pydantic v2 (input/output contracts)
├── services/            # Logica de negocio (evaluator + seeder)
│   ├── alert_evaluator.py   # Core: state machine + CTE query + advisory lock
│   └── weather_seeder.py    # Seed determinista con UUIDs fijos
└── routers/             # HTTP layer (10 endpoints)
    ├── alert_configs.py     # CRUD alertas (POST/GET/PATCH/DELETE)
    ├── notifications.py     # Listado + deliver
    └── jobs.py              # Seed, evaluate, stats (requieren rol admin)
```

**Regla de dependencias**: `routers/ → services/ → models/`. Los routers nunca contienen logica de negocio. Los services nunca manejan HTTP.

---

## Documentacion

### Decisiones de diseno → `docs/design-docs/`

| Archivo | Que contiene | Cuando leerlo |
|---------|-------------|---------------|
| [CHALLENGE.md](docs/design-docs/CHALLENGE.md) | Enunciado original del challenge | Para entender el scope y restricciones |
| [REVIEW_NOTES.md](docs/design-docs/REVIEW_NOTES.md) | 22 decisiones arquitectonicas con critica y justificacion | Antes de proponer cambios de arquitectura |
| [WALKTHROUGH.md](docs/design-docs/WALKTHROUGH.md) | Explicacion 0-a-100 del sistema con diagramas | Para entender el flujo completo |


### Planes de ejecucion → `docs/exec-plans/`

| Archivo | Que contiene | Estado |
|---------|-------------|--------|
| [PLAN.md](docs/exec-plans/PLAN.md) | Plan completo generado pre-implementacion | Completado |
| [IMPLEMENTATION_PLAN.md](docs/exec-plans/IMPLEMENTATION_PLAN.md) | Orden de ejecucion por fases con checkpoints | Completado |

---

## Conceptos clave

- **State machine**: `determine_action()` en `alert_evaluator.py:45-80` es una funcion pura que decide si notificar. 4 casos: sin historial, risk_ended, risk_increased (delta), anti-spam.
- **CTE query**: Una sola query SQL con `ROW_NUMBER() OVER (PARTITION BY)` resuelve toda la evaluacion. Ver `alert_evaluator.py:162-215`.
- **Advisory lock**: `pg_try_advisory_lock` previene evaluaciones concurrentes (scheduler vs endpoint manual).
- **UPSERT**: Los pronosticos son mutables — `ON CONFLICT DO UPDATE` actualiza probabilidad sin duplicar.
- **Seed determinista**: UUIDs fijos en `weather_seeder.py`. User: `a1b2c3d4-...`, Fields: `f1e2d3c4-...` y `f2e3d4c5-...`.

---

## Configuracion

| Variable | Default | Que controla |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Conexion a PostgreSQL |
| `DELTA_THRESHOLD` | `0.10` | Cambio minimo de probabilidad para re-notificar |
| `COOLDOWN_HOURS` | `6` | Horas minimas entre notificaciones por par |
| `EVAL_INTERVAL_MINUTES` | `15` | Frecuencia del job de evaluacion |

---

## Comandos

```bash
make setup      # Docker up + migraciones + seed + wait for health
make test       # pytest dentro del container
make evaluate   # Trigger manual del evaluador
make seed       # Regenerar datos de prueba
make logs       # Logs en tiempo real
make down       # Bajar todo
```

---

## Tests

32 tests, ~78% coverage. Core logic (`determine_action`, `evaluate_alerts`) ~100%.
DB de tests: SQLite in-memory con aiosqlite. Sin estado compartido entre tests.

---

## Migraciones

| Migracion | Que hace |
|-----------|---------|
| `001_initial_schema` | 5 tablas base (users, fields, weather_data, alert_configs, notifications) |
| `002_add_checks_indexes_cascades` | CHECK constraints, indice en field_id, SET NULL en previous_notification_id |
