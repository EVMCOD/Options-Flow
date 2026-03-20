"""Signal job — can be triggered independently of ingestion."""

import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.database import AsyncSessionLocal
from app.core.logging_setup import get_logger
from app.services.signal import run_signal_engine

log = get_logger(__name__)


async def run_signal_job(tenant_id: Optional[uuid.UUID] = None) -> None:
    """
    Standalone signal job.
    Runs signal engine on the most recent successful run for the given tenant.
    If tenant_id is None, operates on the globally latest run.
    """
    start = time.monotonic()
    log.info(
        "signal_job.started",
        at=datetime.now(tz=timezone.utc).isoformat(),
        tenant_id=str(tenant_id) if tenant_id else "all",
    )

    async with AsyncSessionLocal() as db:
        try:
            summary = await run_signal_engine(db, run_id=None, tenant_id=tenant_id)
            elapsed = time.monotonic() - start
            log.info(
                "signal_job.finished",
                tenant_id=str(tenant_id) if tenant_id else "all",
                features=summary.features_created,
                alerts=summary.alerts_created,
                snapshots_failed=summary.snapshots_failed,
                elapsed_s=round(elapsed, 2),
            )
        except Exception as exc:
            log.exception(
                "signal_job.failed",
                tenant_id=str(tenant_id) if tenant_id else "all",
                error=str(exc),
            )
