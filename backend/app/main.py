from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging_setup import configure_logging, get_logger
from app.routers import alerts, diagnostics, events, health, intelligence, jobs, metrics, runs, snapshots, universe
from app.signals.router import router as signal_settings_router
from app.tenants.router import router as tenants_router
from app.scheduler import start_scheduler, stop_scheduler
from app.tenants.service import seed_default_tenant
from app.services.universe import seed_universe_if_empty

# Ensure ProviderRegistry is populated before the scheduler fires.
import app.providers.registry  # noqa: F401

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- startup ----
    log.info("app.startup", env=settings.ENV, provider=settings.DATA_PROVIDER)

    async with AsyncSessionLocal() as db:
        tenant = await seed_default_tenant(db)
        await seed_universe_if_empty(db, tenant.id)

    start_scheduler()

    yield

    # ---- shutdown ----
    stop_scheduler()
    log.info("app.shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.2.0",
    description="Real-time options flow scanner and alert engine — multi-provider",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Exception handlers ----

@app.exception_handler(422)
async def validation_exception_handler(request: Request, exc: Exception):
    log.warning("validation_error", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"success": False, "data": None, "error": str(exc)},
    )


@app.exception_handler(500)
async def internal_server_error_handler(request: Request, exc: Exception):
    log.exception("internal_error", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "data": None, "error": "Internal server error"},
    )


# ---- Routers ----
PREFIX = "/api/v1"

app.include_router(health.router, prefix=PREFIX)
app.include_router(universe.router, prefix=PREFIX)
app.include_router(alerts.router, prefix=PREFIX)
app.include_router(snapshots.router, prefix=PREFIX)
app.include_router(metrics.router, prefix=PREFIX)
app.include_router(jobs.router, prefix=PREFIX)
app.include_router(runs.router, prefix=PREFIX)
app.include_router(diagnostics.router, prefix=PREFIX)
app.include_router(intelligence.router, prefix=PREFIX)
app.include_router(tenants_router, prefix=PREFIX)
app.include_router(signal_settings_router, prefix=PREFIX)
app.include_router(events.router, prefix=PREFIX)
