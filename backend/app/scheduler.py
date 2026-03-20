"""
APScheduler setup.

Schedules:
  - run_ingestion_job every SCAN_INTERVAL_SECONDS seconds
  - run_events_sync_job daily at 06:00 UTC
  - One-time startup run after a 5-second delay
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging_setup import get_logger
from app.jobs.events_job import run_events_sync_job
from app.jobs.ingestion_job import run_ingestion_job

log = get_logger(__name__)

scheduler = AsyncIOScheduler()


async def _delayed_startup_run() -> None:
    """Run ingestion once on startup after a short delay."""
    await asyncio.sleep(5)
    log.info("scheduler.startup_run")
    await run_ingestion_job()


def start_scheduler() -> None:
    """Register jobs and start the scheduler."""
    scheduler.add_job(
        run_ingestion_job,
        trigger=IntervalTrigger(seconds=settings.SCAN_INTERVAL_SECONDS),
        id="ingestion_job",
        name="Full Ingestion + Signal Run",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )

    # Daily event calendar sync — 06:00 UTC, before US pre-market
    scheduler.add_job(
        run_events_sync_job,
        trigger=CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="events_sync_daily",
        name="Daily Event Calendar Sync",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,   # 5 minutes — if server was down at :00
    )

    scheduler.start()
    log.info(
        "scheduler.started",
        interval_s=settings.SCAN_INTERVAL_SECONDS,
    )

    # Fire-and-forget the startup run
    asyncio.create_task(_delayed_startup_run())


def stop_scheduler() -> None:
    """Graceful shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
