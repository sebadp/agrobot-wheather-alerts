# Notas de Revisión Arquitectónica — Sistema de Alertas Climáticas

Documento de estudio que recopila todas las correcciones, críticas y decisiones tomadas durante la planificación del challenge.

---

## 1. Celery + Redis vs APScheduler

### Propuesta original
Celery + Redis con Beat para periodic tasks. Docker con 5 servicios (db, redis, app, worker, beat).

### Crítica
- **Sobreingeniería**: Para un solo job periódico simple en un challenge de ~5 horas, Celery es overkill.
- **Bridge sync→async**: Celery no es async-native. El bridge `asyncio.new_event_loop()` introduce:
  - Memory leaks: `loop.close()` no garantiza limpieza de recursos pendientes
  - Context vars perdidos entre loops
  - Testing nightmare para mockear
  - `autoretry_for=(Exception,)` captura `KeyboardInterrupt` y `SystemExit`
- **Infra innecesaria**: Redis + 3 servicios Docker extra para un `INSERT` periódico.

### Decisión final
APScheduler (AsyncIOScheduler). Async-native, in-process, `max_instances=1`. Zero infra extra. Docker: 2 servicios.

### Lección
No elegir tecnología para "demostrar que la conozco". Elegir la herramienta correcta para el scope. Documentar la alternativa (AWS SQS + Lambda + SNS) como mejora para producción.

---

## 2. Repository Pattern — Over-engineering

### Propuesta original
Capa `repositories/` con base genérica + repositorios específicos por modelo.

### Crítica
- 5 capas (models, schemas, repositories, services, routers) para 5 tablas en un challenge de 5 horas.
- Los repositorios serían "thin wrappers" que solo wrappean queries sin agregar valor.
- Huele a "architecture astronaut" — capas porque sí, no porque resuelven un problema.

### Decisión final
Services hacen queries SQLAlchemy directamente. Sin repositories.

### Lección
"Para este scope, el service layer es suficiente. En un sistema más grande introduciría repositories para testear con mocks sin DB." Eso muestra más criterio que tener la capa porque sí.

---

## 3. Strategy Pattern para Dispatchers — Premature Abstraction

### Propuesta original
`dispatchers/base.py` (Protocol), `log_dispatcher.py`, imports, `__init__.py`. 3-4 archivos para un `logger.info()`.

### Crítica
El challenge dice explícitamente: "No hace falta implementar ninguna integración con WhatsApp." Un reviewer ve una arquitectura de dispatchers para un `logger.info()` y piensa: "¿Dónde están los tests del evaluator?"

### Decisión final
El evaluator simplemente loggea. Una línea. En README se documenta: "Para producción, introduciría un NotificationDispatcher con Strategy Pattern."

### Lección
Comunicar la arquitectura que usarías en producción es tan valioso como implementarla — y cuesta 0 tiempo de debugging.

---

## 4. Redis Lock — Innecesario

### Propuesta original
Redis distributed lock para evitar ejecuciones concurrentes del evaluator.

### Crítica
- ON CONFLICT DO NOTHING ya garantiza correctness a nivel de datos.
- APScheduler con `max_instances=1` ya previene ejecuciones paralelas.
- El lock agrega dependencia de Redis, lógica de acquire/release, manejo de excepciones, un test más.

### Decisión final
Sin lock. La idempotencia de DB es suficiente para correctness. Lock documentado como mejora de eficiencia (evitar trabajo duplicado, no para correctness).

### Lección
Distinguir correctness de eficiencia. No agregar complejidad para optimizar algo que no es un problema real.

---

## 5. user_id Denormalizado en alert_configs

### Propuesta original
`user_id` en `alert_configs` para simplificar queries de "notificaciones del usuario" (1 JOIN vs 2).

### Crítica
- En agricultura, campos pueden cambiar de dueño. Con denormalización, borrar y recrear todas las alertas.
- El JOIN extra (`notifications → alert_configs → fields.user_id`) con indexes de FK es un index lookup — costo despreciable.
- Viola normalización sin beneficio real de performance.

### Decisión final
Sin denormalización. `user_id` solo en `fields`. Indexes cubren la performance.

### Lección
Un JOIN extra con indexes correctos es prácticamente gratis. No denormalizar hasta que haya evidencia de que es un bottleneck.

---

## 6. Migraciones como Servicio Separado en Docker

### Propuesta original
Servicio `migrate` que corre `alembic upgrade head` y muere, con `service_completed_successfully`.

### Crítica
Para un equipo pequeño con un solo backend, es overkill. Healthcheck, depends_on con condition, servicio fantasma en logs. Lo estándar: `alembic upgrade head && uvicorn` en el entrypoint.

### Decisión final
Migraciones en entrypoint de app. Alembic es idempotente, re-runs son seguros. Servicio separado documentado como mejora para multi-instancia.

### Lección
La solución "correcta para producción" no siempre es la correcta para un challenge. Optimizar para el contexto.

---

## 7. 14 Endpoints → 9 Endpoints

### Propuesta original
CRUD completo para users, fields, alerts, notifications, weather, jobs. 14 endpoints.

### Crítica
14 endpoints × ~20 min cada uno = 4.5 horas solo en endpoints. No queda tiempo para el evaluator (el core del challenge).

### Decisión final
9 endpoints:
- Health (1)
- Alert configs CRUD (4) — foco del challenge
- Notifications GET + mark delivered (2)
- Weather seed + evaluate trigger (2)

Users y fields se seedean automáticamente. Sin CRUD.

### Lección
Cada endpoint implica: router, schema, service call, error handling, y potencialmente test. Contar el costo real antes de diseñar.

---

## 8. PUT vs PATCH para Alert Update

### Propuesta original
`PUT /api/v1/alerts/{alert_id}` para actualizar threshold o is_active.

### Crítica
PUT semánticamente reemplaza el recurso completo. Si solo actualizás threshold, PATCH es más correcto.

### Decisión final
`PATCH /api/v1/alerts/{alert_id}` — partial update.

### Lección
Detalles semánticos de REST importan. Un reviewer que conoce REST bien lo nota.

---

## 9. `/notifications/{id}/read` vs `/deliver`

### Propuesta original
`PATCH /api/v1/notifications/{id}/read` que marca como `delivered`.

### Crítica
`read ≠ delivered`. El endpoint se llama `/read` pero el status es `delivered`. Inconsistencia semántica.

### Decisión final
`PATCH /api/v1/notifications/{id}/deliver` — consistente con status `delivered`.

### Lección
Nombrar las cosas correctamente. Los endpoints son la interfaz pública del sistema.

---

## 10. Seed Determinista vs Random

### Propuesta original
Seed con `random.random()` para probabilidades.

### Crítica
Si por mala suerte todos los valores quedan bajos y el reviewer crea una alerta con threshold 0.5 → trigger → 0 notificaciones → "no funciona".

### Decisión final
Seed determinista con valores garantizados:
- Altos (0.8-0.95): alertas con threshold 0.7 siempre disparan
- Medios (0.4-0.6): boundary cases
- Bajos (0.05-0.2): no disparan nada

UUIDs hardcodeados documentados en README para copy-paste.

### Lección
El demo path tiene que funcionar siempre, sin depender de suerte.

---

## 11. Dockerfile: libpq-dev

### Crítica (preventiva)
`asyncpg` compila contra libpq. Sin `libpq-dev` y `gcc` en el Dockerfile, el `pip install` falla silenciosamente o con errores crípticos. Puede costar 30+ minutos de debugging.

### Decisión final
```dockerfile
RUN apt-get install -y --no-install-recommends libpq-dev gcc
```
Definido desde el inicio, no dejado para el final.

---

## 12. Test DB: Permisos y Creación

### Propuesta original (v1)
Init script `scripts/init-test-db.sh` montado en Docker.

### Crítica
Externaliza configuración que puede manejarse desde el código de tests.

### Propuesta original (v2)
conftest.py crea la DB. Justificación: "agrobot es superuser por default".

### Corrección
La justificación era incorrecta. El user `agrobot` no es "superuser del DB agrobot" — es superuser **del cluster** porque `POSTGRES_USER` en la imagen oficial de PostgreSQL recibe el atributo `SUPERUSER`. Eso es lo que permite `CREATE DATABASE`. Saber por qué funciona, no solo que funciona.

### Decisión final
conftest.py crea la DB directamente. Justificación correcta documentada.

---

## 13. ON DELETE: CASCADE vs SET NULL

### Propuesta original
CASCADE en notifications → alert_config.

### Crítica
Si el usuario borra una alerta por error, pierde todo el historial de notificaciones. Data loss.

### Decisión final
SET NULL: si la alerta se borra, `alert_config_id` queda NULL en las notificaciones huérfanas. No se pierde data.

### Implicación técnica
El UNIQUE constraint `(alert_config_id, weather_data_id)` permite múltiples rows con `(NULL, weather_data_id)` porque en PostgreSQL `NULL != NULL` en constraints UNIQUE. Esto es correcto: si se borra una alerta y se crea una nueva para el mismo field+event, el evaluator puede generar nuevas notificaciones sin conflicto.

### Lección
Conocer el comportamiento de NULL en constraints UNIQUE de PostgreSQL. Es una pregunta clásica de entrevista.

---

## 14. Probability: Float vs Numeric

### Problema
`Float` en Python/PostgreSQL puede causar issues en comparaciones `>=` por floating point precision. `0.7 >= 0.7` puede ser `False` si uno es `0.6999999999`.

### Decisión final
`Numeric(3,2)` para `probability` y `threshold`. Precisión exacta, sin sorpresas en comparaciones.

### Lección
Para valores que se comparan con `>=` o `<=`, usar tipos de precisión exacta (Numeric/Decimal), no Float.

---

## 15. Paginación Básica

### Propuesta original
Sin paginación. "Con más tiempo haría cursor-based".

### Crítica
Un GET que lista notificaciones sin limit puede devolver miles de registros. Al menos `?limit=20&offset=0` default.

### Decisión final
Paginación básica con `limit` y `offset` query params.

### Lección
No necesitás cursor-based para el challenge, pero devolver la tabla entera tampoco es aceptable.

---

## 16. Makefile: Esperar Health Check

### Problema
`make setup` levanta Docker → el reviewer inmediatamente hace `make evaluate` → la app todavía está corriendo migraciones + seed → connection refused o 500.

### Decisión final
```makefile
setup:
    docker-compose up -d --build
    @until curl -sf http://localhost:8000/health > /dev/null 2>&1; do sleep 1; done
    @echo "Ready! Try: make evaluate"
```

### Lección
La DX del reviewer es parte del entregable. 2 líneas extra que evitan una mala primera impresión.

---

## 17. Patrones: No Overselling

### Propuesta original
5 patrones: Service Layer, Strategy Pattern, Idempotent Consumer, Bridge Pattern, Template Method.

### Crítica
- "Bridge Pattern" = `asyncio.run()`. No es un patrón, es una línea.
- "Template Method" = un f-string. No es un patrón.
- "Strategy Pattern" = un `logger.info()`. No implementado.

Un reviewer busca los patrones en el código. Si encuentra algo trivial disfrazado de patrón, pierde confianza.

### Decisión final
2 patrones reales:
- **Service Layer**: Lógica desacoplada de HTTP (sí, real)
- **Idempotent Consumer**: Doble capa query filter + DB constraint (sí, sustancial)

### Lección
Solo nombrar patrones que realmente implementás de forma sustancial.

---

## 18. Error Responses Consistentes

### Problema
Sin definir, los edge cases de negocio devuelven 500s genéricos.

### Decisión final
```
404: {"detail": "Field not found"}
409: {"detail": "Alert for this field and event type already exists. Use PATCH to update."}
422: Pydantic validation automática
```

### Lección
Definir error responses antes de implementar. Son parte de la API.

---

## 19. El Template de Mensaje como Valor de Producto

### Propuesta original
`message` en notifications sin formato definido.

### Decisión final
```
"⚠️ Alerta: probabilidad de helada del 85% en campo La Esperanza
para el 16/02/2026. Tu umbral configurado: 70%."
```

Con mapeo de event types a español (frost→helada, rain→lluvia, etc.).

### Lección
Un detalle de producto en un challenge técnico comunica: "Pienso en el usuario final, no solo en tablas y queries." Test `test_message_content` verifica que no salga "ClimateEventType.FROST".

---

## 20. Observabilidad: GET /jobs/stats

### Contexto
El enunciado dice "código production-ready" pero no pide métricas. `logger.info()` cumple el mínimo.

### Oportunidad
Un endpoint `GET /api/v1/jobs/stats` que devuelve:
```json
{"last_run": "2026-02-14T10:30:00Z", "notifications_created": 5, "duration_ms": 120}
```
Es una señal instant de production-readiness. Son 10 minutos de implementación (stats en memoria, module-level dict) y comunica: "el sistema tiene visibilidad operacional".

### Decisión
Agregado como endpoint #10. Stats guardados en memoria (no en DB — sería overkill). Se resetean al reiniciar la app.

### Lección
Buscar oportunidades de bajo costo / alto impacto. Un endpoint de stats es más valioso que un Strategy Pattern que nadie pidió.

---

## 21. Evolución del Modelo: De Idempotencia Simple a State Machine

### Modelo original
- UNIQUE constraint `(alert_config_id, weather_data_id)` + ON CONFLICT DO NOTHING
- LEFT JOIN + IS NULL para filtrar
- Una notificación por par, nunca se re-notifica

### Nuevos supuestos de negocio
- Los pronósticos son mutables (la probabilidad cambia durante el día)
- Si el riesgo baja del umbral → "all clear" (risk_ended)
- Si sube significativamente (delta >= 10%) → re-notificar
- Cooldown de 6h para evitar spam (excepto risk_ended)

### Impacto arquitectónico
- **UNIQUE constraint eliminado** → la tabla notifications crece (historial completo)
- **Nuevo índice** `(alert_config_id, weather_data_id, triggered_at DESC)` para lookup eficiente
- **CTE con ROW_NUMBER** para encontrar última notificación por par
- **determine_action()** como función pura (state machine) con 4 casos
- **Nuevos campos**: notification_type, probability_at_notification, previous_notification_id

### Lección
La idempotencia "simple" (UNIQUE + ON CONFLICT) solo funciona cuando cada evento genera exactamente una notificación. Cuando los datos son mutables y el sistema necesita tracking de evolución, el modelo cambia fundamentalmente: de "prevenir duplicados" a "trackear estado y decidir cuándo notificar".

### Trade-off
Más complejidad (CTE, state machine, cooldown), pero el sistema ahora es útil en el mundo real: un agricultor que ve que la probabilidad de helada bajó del 85% al 40% recibe un "✅ Riesgo mitigado", no silencio.

---

## 22. Credenciales en alembic.ini

### Problema
`sqlalchemy.url` en `alembic.ini` tenía la connection string con password hardcodeada (`postgresql+asyncpg://agrobot:agrobot@localhost:5432/agrobot`). Aunque son credenciales de desarrollo, establece un patrón riesgoso y un reviewer de seguridad lo marca inmediatamente.

### Decisión final
Blanquear `sqlalchemy.url =` en `alembic.ini`. `alembic/env.py` ya leía de `os.getenv("DATABASE_URL")` como fallback — solo faltaba eliminar el default inseguro del `.ini`.

### Lección
Las credenciales en archivos commiteados se notan. Aunque sean de dev, un reviewer infiere: "si lo hace aquí, lo hace en producción".

---

## 23. Notificaciones huérfanas (alert_config_id = NULL)

### Problema
Al borrar una alert_config, `ON DELETE SET NULL` deja `alert_config_id = NULL` en las notificaciones. El endpoint `list_notifications` usa INNER JOIN con AlertConfig, así que esas notificaciones desaparecen del listing del usuario.

### Alternativa evaluada
LEFT JOIN + filtro por `weather_data.field_id` para mantener visibilidad. Descartado porque:
1. Un LEFT JOIN con `alert_config_id IS NULL` sin filtro adicional filtra notificaciones de **todos** los usuarios (se pierde la cadena notification → alert → field → user).
2. Resolverlo via `weather_data.field_id` agrega complejidad (JOIN extra) para un edge case.
3. Semánticamente, si el usuario borró la alerta, no necesita ver las notificaciones viejas en su listing.

### Decisión final
INNER JOIN es intencional. Los datos se preservan en la DB para auditoría/admin. El endpoint de usuario solo muestra notificaciones de alertas activas.

### Lección
No todo lo que parece un bug lo es. A veces el comportamiento "incompleto" es la decisión correcta — pero debe ser explícita, no accidental.

---

## 24. RISK_DECREASED: reservado, no implementado

### Problema
`NotificationType.RISK_DECREASED` estaba definido en el enum pero ningún path del evaluator lo produce. El caso "bajó pero sigue sobre umbral" cae en Caso C y retorna `None` (no notifica).

### Decisión final
Mantener en el enum con comentario: "Reserved: validate with product to avoid spam before implementing." Implementarlo sin validación con producto podría generar notificaciones excesivas (cada fluctuación menor dispararía un mensaje).

### Lección
Dead code en un challenge es una señal negativa. Si se reserva para el futuro, documentar el por qué explícitamente.

---

## 25. Alineación de versión Python

### Problema
Dockerfile usaba Python 3.12, pero CI (`ci.yml`), `pyproject.toml` (requires-python, ruff target, mypy) usaban 3.11. Si se usara un feature de 3.12 en el código, CI no lo detectaría.

### Decisión final
Todo alineado a Python 3.12: Dockerfile, CI workflows, pyproject.toml (requires-python, ruff.target-version, mypy.python_version).

### Lección
La versión de Python debe ser consistente en todo el pipeline. Una discrepancia entre CI y producción es un bug latente.

---

## Resumen de Principios Aprendidos

1. **Herramienta correcta para el scope**: No Celery para un cron simple.
2. **No implementar features que nadie pidió**: Re-notificación, dispatchers, locks.
3. **Comunicar > Implementar**: Documentar lo que harías con más tiempo vale más que hacerlo mal.
4. **Contar el costo real**: 14 endpoints × 20 min = 4.5 horas. Hacer las cuentas antes.
5. **Semántica importa**: PUT vs PATCH, `/read` vs `/deliver`, patterns reales vs nombrados.
6. **El demo tiene que funcionar siempre**: Seed determinista, Makefile que espera, UUIDs documentados.
7. **Conocer las herramientas a nivel bajo**: NULL en UNIQUE, SUPERUSER en imagen PG, Numeric vs Float.
8. **Correctness vs Eficiencia**: ON CONFLICT es correctness. Lock es eficiencia. No confundir.
