Agrobot de 0 a 100                                                                                                                                                                               
                                                                                                                                                                                                                
  El modelo mental                                                                                                                                                                                           
                                                                                                                                                                                                                
  El sistema tiene dos procesos desacoplados:

  INGESTA (escribir datos)          EVALUACIÓN (leer y decidir)
           │                                  │
           ▼                                  ▼
  ┌─────────────────┐               ┌──────────────────┐
  │  weather_data   │──────────────▶│  alert_evaluator  │
  │  (por field_id) │               │  (cada 15 min)    │
  └─────────────────┘               └────────┬─────────┘
                                             │
                                             ▼
                                     ┌──────────────┐
                                     │ notifications │
                                     └──────────────┘


  El matcheo es directo por FK, no geoespacial. Mirá weather_data.py:29:

  field_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("fields.id"))

  Cada registro de weather_data ya viene con el field_id asignado. No hay búsqueda por latitud/longitud ni por región. El job de ingesta (en nuestro caso el seeder) ya sabe a qué campo pertenece cada
  pronóstico.

  Se itera field_id → event_type → probabilidades y se inserta directamente con ese field_id. En producción, un job de ingesta real haría algo como:

  1. API meteorológica → dame pronóstico para lat=-33.94, lon=-60.95
  2. Buscar qué field tiene esas coordenadas (o está en ese radio)
  3. Insertar weather_data con ese field_id

  Ese paso 2 (el matcheo geoespacial) no existe en esta implementación. Es un trade-off del scope del challenge: field tiene latitude/longitude pero nadie los usa. El seeder simplifica asumiendo que ya sabés
  a qué campo van los datos. Es algo explícito para el "Con más tiempo" del README.

  El job de evaluación: cómo arranca

  En main.py:26-48, el lifespan de FastAPI hace dos cosas al iniciar:

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # 1. Seed si la DB está vacía
      async with async_session_factory() as session:
          await seed_if_empty(session)

      # 2. Registrar el job periódico
      scheduler.add_job(
          run_evaluation,                                    # ← esta función
          trigger=IntervalTrigger(minutes=settings.EVAL_INTERVAL_MINUTES),  # 15 min
          max_instances=1,           # nunca 2 evaluaciones en paralelo
          replace_existing=True,
      )
      scheduler.start()
      yield           # ← app corriendo, scheduler tirando cada 15 min
      scheduler.shutdown()

  APScheduler es in-process (mismo proceso que FastAPI). Cada 15 minutos llama a run_evaluation() (main.py:20-23):

  async def run_evaluation():
      async with async_session_factory() as session:
          result = await evaluate_alerts(session)

  Crea su propia sesión de DB y llama al evaluator. También podés triggerear manualmente via POST /api/v1/jobs/evaluate-alerts (mismo código, diferente caller).

  El flujo completo de evaluate_alerts

  Todo pasa en alert_evaluator.py:120-245. Son 3 fases:

  Fase 1: La query con CTE (líneas 123-177)

  Construye UNA sola query SQL que trae todo lo necesario. Conceptualmente:

  -- Paso A: Para cada par (alert_config, weather_data),
  --         encontrar la ÚLTIMA notificación que mandamos
  WITH latest_notification AS (
      SELECT *, ROW_NUMBER() OVER (
          PARTITION BY alert_config_id, weather_data_id
          ORDER BY triggered_at DESC
      ) AS rn
      FROM notifications
      WHERE alert_config_id IS NOT NULL
  ),
  latest AS (
      SELECT * FROM latest_notification WHERE rn = 1
  )

  -- Paso B: Cruzar alert_configs activas × weather_data futuros
  --         + la última notificación (si existe) como contexto
  SELECT
      alert_config,
      weather_data,
      field.name,
      latest.notification_type,          -- qué le mandamos antes?
      latest.probability_at_notification, -- con qué probabilidad?
      latest.triggered_at,               -- cuándo?
      latest.notification_id             -- ID para linkear
  FROM alert_configs
  JOIN fields ON fields.id = alert_configs.field_id
  JOIN weather_data ON
      weather_data.field_id = alert_configs.field_id     -- ← MISMO CAMPO
      AND weather_data.event_type = alert_configs.event_type  -- ← MISMO EVENTO
  LEFT JOIN latest ON
      latest.alert_config_id = alert_configs.id
      AND latest.weather_data_id = weather_data.id
  WHERE
      alert_configs.is_active = true
      AND weather_data.event_date >= today

  El JOIN clave está en las líneas 159-164:

  .join(
      WeatherData,
      and_(
          WeatherData.field_id == AlertConfig.field_id,      # mismo campo
          WeatherData.event_type == AlertConfig.event_type,   # mismo evento
      ),
  )


  Fase 2: La máquina de estados (líneas 185-214)

  Por cada fila del resultado (un par alert_config + weather_data + contexto previo), se llama a determine_action():

                      ┌─────────────────────┐
                      │  ¿Hay notificación  │
                      │     previa?         │
                      └──────┬──────────────┘
                             │
                      ┌──────┴──────┐
                      │             │
                     NO            SÍ
                      │             │
                ┌─────┴─────┐   ┌──┴───────────────────────┐
                │ prob >=    │   │ ¿Estaba arriba y ahora   │
                │ threshold? │   │   bajó del umbral?       │
                └─────┬──┬──┘   └──┬────────────────────┬──┘
                      │  │         │                     │
                     SÍ  NO      SÍ (Caso A)           NO
                      │  │         │                     │
               RISK_  nada    RISK_ENDED          ┌─────┴─────┐
             INCREASED        (ignora cooldown)   │ Cooldown  │
                                                  │ activo?   │
                                                  └──┬─────┬──┘
                                                     │     │
                                                    SÍ    NO
                                                     │     │
                                                   nada  ┌─┴──────────┐
                                                         │ ¿Sigue     │
                                                         │  arriba?   │
                                                         └──┬──────┬──┘
                                                            │      │
                                                           SÍ     NO→SÍ
                                                            │    (Caso D)
                                                      ┌─────┴────┐  │
                                                      │ delta >= │ RISK_
                                                      │  10%?    │ INCREASED
                                                      └──┬────┬──┘
                                                         │    │
                                                        SÍ   NO
                                                   (Caso B) (Caso C)
                                                         │    │
                                                    RISK_   nada
                                                  INCREASED (anti-spam)

  Fase 3: Crear notificación (líneas 216-237)

  Si determine_action devuelve algo (no None), se arma el mensaje con build_message() y se crea la notificación:

  notification = Notification(
      alert_config_id=alert_config.id,
      weather_data_id=weather_data.id,
      notification_type=action.type.value,       # "risk_increased" o "risk_ended"
      probability_at_notification=current_prob,   # snapshot de la prob actual
      previous_notification_id=prev_id,           # ← cadena de historial
      status="pending",
      message=message,
  )

  previous_notification_id arma una linked list: cada notificación apunta a la anterior para ese mismo par. Así podés reconstruir la evolución completa.

  Al final, await session.commit() — todo o nada.

  Ejemplo concreto con números

  Estado inicial de weather_data:
    Campo Esperanza, frost, 2026-02-15 → probability: 0.85

  Usuario crea:
    alert_config: campo=Esperanza, event=frost, threshold=0.70

  ── Evaluación 1 (10:00) ──
    Query: Esperanza + frost → prob 0.85, no hay notificación previa
    determine_action(has_previous=False, is_above=True)
    → RISK_INCREASED
    → "⚠️  Alerta: probabilidad de helada 85% en campo Campo La Esperanza..."
    → Se crea Notification #N1

  ── Ingesta actualiza prob a 0.60 (bajó del umbral) ──

  ── Evaluación 2 (10:15) ──
    Query: prob 0.60, última notificación = N1 (prob_at=0.85, type=risk_increased)
    determine_action(has_previous=True, was_above=True, is_above=False)
    → Caso A → RISK_ENDED (ignora cooldown)
    → "✅ Riesgo mitigado: probabilidad de helada bajó del 85% al 60%..."
    → Se crea Notification #N2 (previous_notification_id = N1)

  ── Ingesta actualiza prob a 0.95 (subió mucho) ──

  ── Evaluación 3 (10:30) ──
    Query: prob 0.95, última notificación = N2 (prob_at=0.60, type=risk_ended)
    determine_action(has_previous=True, was_above=False, is_above=True)
    → Caso D → RISK_INCREASED
    → "⚠️  Alerta: probabilidad de helada 95%..."
    → Se crea Notification #N3 (previous_notification_id = N2)

  ── Ingesta actualiza prob a 0.97 (subió poco, +2%) ──

  ── Evaluación 4 (10:45) ──
    Query: prob 0.97, última notificación = N3 (prob_at=0.95, triggered=10:30)
    determine_action(was_above=True, is_above=True, delta=0.02 < 0.10)
    → Caso C → None (anti-spam, cambio menor)
    → No se crea notificación
