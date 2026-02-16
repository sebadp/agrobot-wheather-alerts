import logging
import time
import uuid as uuid_mod
from contextlib import asynccontextmanager
from contextvars import ContextVar

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.database import async_session_factory, engine
from app.logging_config import setup_logging
from app.routers import alert_configs, jobs, notifications
from app.services.alert_evaluator import evaluate_alerts
from app.services.weather_seeder import seed_if_empty

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

setup_logging()
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def run_evaluation():
    request_id = str(uuid_mod.uuid4())[:8]
    correlation_id_var.set(request_id)
    logger.info("Scheduled evaluation starting", extra={"correlation_id": request_id})
    start = time.monotonic()
    try:
        async with async_session_factory() as session:
            result = await evaluate_alerts(session)
        elapsed = time.monotonic() - start
        logger.info(
            "Scheduled evaluation completed in %.2fs: %s",
            elapsed,
            result,
            extra={"correlation_id": request_id, "elapsed_s": elapsed, **result},
        )
        if elapsed > settings.EVAL_INTERVAL_MINUTES * 60 * 0.8:
            logger.warning(
                "Evaluation took %.1fs — approaching interval limit of %ds",
                elapsed,
                settings.EVAL_INTERVAL_MINUTES * 60,
                extra={"correlation_id": request_id},
            )
    except Exception:
        elapsed = time.monotonic() - start
        logger.exception(
            "Evaluation job failed after %.2fs",
            elapsed,
            extra={"correlation_id": request_id, "elapsed_s": elapsed},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-seed on startup
    try:
        async with async_session_factory() as session:
            seeded = await seed_if_empty(session)
            if seeded:
                logger.info("Database seeded with initial data")
    except Exception:
        logger.exception("Failed to seed database on startup")

    # Start scheduler
    scheduler.add_job(
        run_evaluation,
        trigger=IntervalTrigger(minutes=settings.EVAL_INTERVAL_MINUTES),
        id="evaluate_alerts",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (interval=%dm)", settings.EVAL_INTERVAL_MINUTES)

    yield

    scheduler.shutdown()
    await engine.dispose()


app = FastAPI(title="Agrobot - Sistema de Alertas Climáticas", lifespan=lifespan)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid_mod.uuid4())[:8])
    correlation_id_var.set(request_id)
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s %d %.3fs",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
        extra={"correlation_id": request_id, "elapsed_s": elapsed},
    )
    return response


@app.get("/health")
async def health():
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception:
        logger.exception("Health check failed — database unreachable")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "disconnected"},
        )


app.include_router(alert_configs.router)
app.include_router(notifications.router)
app.include_router(jobs.router)
