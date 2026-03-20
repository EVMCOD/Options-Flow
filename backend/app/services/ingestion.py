"""
Ingestion service: fetch → raw storage → normalize → persist.
Called by the ingestion job. Owns the full ingest pipeline for one run.
"""

import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_setup import get_logger
from app.models.models import IngestionRun, NormalizedOptionSnapshot, RawOptionSnapshot, ScannerUniverse
from app.providers.base import BaseOptionsDataProvider, OptionContract

log = get_logger(__name__)


async def _get_enabled_symbols(
    db: AsyncSession, tenant_id: Optional[uuid.UUID]
) -> List[str]:
    q = select(ScannerUniverse.symbol).where(ScannerUniverse.enabled == True)
    if tenant_id is not None:
        q = q.where(ScannerUniverse.tenant_id == tenant_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def _store_raw(
    db: AsyncSession, run_id: uuid.UUID, contract: OptionContract, source: str
) -> RawOptionSnapshot:
    raw = RawOptionSnapshot(
        run_id=run_id,
        source=source,
        raw_payload_json={
            "as_of_ts": contract.as_of_ts.isoformat(),
            "underlying_symbol": contract.underlying_symbol,
            "expiry": contract.expiry.isoformat(),
            "strike": contract.strike,
            "option_type": contract.option_type,
            "spot_price": contract.spot_price,
            "bid": contract.bid,
            "ask": contract.ask,
            "last": contract.last,
            "volume": contract.volume,
            "open_interest": contract.open_interest,
            "implied_vol": contract.implied_vol,
        },
    )
    db.add(raw)
    return raw


def _normalize(
    contract: OptionContract, run_id: uuid.UUID
) -> NormalizedOptionSnapshot:
    return NormalizedOptionSnapshot(
        as_of_ts=(
            contract.as_of_ts.replace(tzinfo=timezone.utc)
            if contract.as_of_ts.tzinfo is None
            else contract.as_of_ts
        ),
        underlying_symbol=contract.underlying_symbol,
        expiry=contract.expiry,
        strike=contract.strike,
        option_type=contract.option_type,
        spot_price=contract.spot_price,
        bid=contract.bid,
        ask=contract.ask,
        last=contract.last,
        volume=contract.volume,
        open_interest=contract.open_interest,
        implied_vol=contract.implied_vol,
        source=contract.source,
        run_id=run_id,
    )


async def run_ingestion(
    db: AsyncSession,
    provider: BaseOptionsDataProvider,
    tenant_id: Optional[uuid.UUID] = None,
    provider_config_id: Optional[uuid.UUID] = None,
    market_data_mode: Optional[str] = None,
) -> IngestionRun:
    """
    Execute a full ingestion run for the given tenant.

    1. Create IngestionRun record (status=running)
    2. For each enabled symbol in tenant's universe: fetch, store raw, normalize
    3. Update run to success or failed
    """
    now = datetime.now(tz=timezone.utc)
    run = IngestionRun(
        tenant_id=tenant_id,
        provider_config_id=provider_config_id,
        provider_type=provider.provider_name(),
        market_data_mode=market_data_mode,
        started_at=now,
        status="running",
        records_ingested=0,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    run_id = run.id
    log.info("ingestion.started", run_id=str(run_id), tenant_id=str(tenant_id))

    symbols = await _get_enabled_symbols(db, tenant_id)
    if not symbols:
        log.warning("ingestion.no_symbols", tenant_id=str(tenant_id))
        run.status = "failed"
        run.error_message = "No enabled symbols in universe"
        run.finished_at = datetime.now(tz=timezone.utc)
        await db.commit()
        return run

    total_records = 0
    errors: List[str] = []

    for symbol in symbols:
        try:
            symbol_start = time.monotonic()
            contracts = await provider.fetch_chain(symbol)
            elapsed_fetch = round(time.monotonic() - symbol_start, 2)

            if not contracts:
                log.info(
                    "ingestion.symbol_empty",
                    symbol=symbol,
                    elapsed_s=elapsed_fetch,
                    note="provider returned 0 contracts — market may be closed or no delayed data",
                )
                continue

            normalized_batch: List[NormalizedOptionSnapshot] = []
            quality_skipped = 0

            for contract in contracts:
                # Quality gate: skip contracts with no usable price data.
                # ib_insync fills missing prices with 0.01 proxies — if both
                # bid and ask are at or below the proxy floor, the record has
                # no real market data and would pollute the signal baseline.
                mid = (contract.bid + contract.ask) / 2.0
                if mid < 0.02 and contract.last < 0.02:
                    quality_skipped += 1
                    continue

                await _store_raw(db, run_id, contract, provider.provider_name())
                normalized = _normalize(contract, run_id)
                normalized_batch.append(normalized)

            db.add_all(normalized_batch)
            await db.flush()  # assign IDs without committing

            total_records += len(normalized_batch)

            log.info(
                "ingestion.symbol_done",
                symbol=symbol,
                fetched=len(contracts),
                stored=len(normalized_batch),
                quality_skipped=quality_skipped,
                elapsed_s=elapsed_fetch,
            )

        except Exception as exc:
            log.exception("ingestion.symbol_failed", symbol=symbol, error=str(exc))
            errors.append(f"{symbol}: {exc}")

    # Final commit
    try:
        run.records_ingested = total_records
        run.finished_at = datetime.now(tz=timezone.utc)

        symbols_attempted = len(symbols)
        if errors and total_records == 0:
            run.status = "failed"
            run.error_message = "; ".join(errors)
        elif total_records == 0 and not errors:
            # Explicit note for empty-but-not-errored runs: provider returned []
            # for all symbols. Normal outside market hours with delayed data.
            run.status = "success"
            run.error_message = (
                f"0 records from {symbols_attempted} symbol(s). "
                f"Provider returned no contracts — market may be closed "
                f"or delayed data unavailable."
            )
        else:
            run.status = "success"
            if errors:
                run.error_message = f"Partial failures: {'; '.join(errors)}"

        await db.commit()
        await db.refresh(run)
        log.info(
            "ingestion.finished",
            run_id=str(run_id),
            tenant_id=str(tenant_id),
            provider_type=provider.provider_name(),
            market_data_mode=market_data_mode,
            status=run.status,
            records=total_records,
            symbols_attempted=symbols_attempted,
        )
    except Exception as exc:
        log.exception("ingestion.commit_failed", run_id=str(run_id), error=str(exc))
        run.status = "failed"
        run.error_message = str(exc)
        try:
            await db.rollback()
            await db.commit()
        except Exception:
            pass

    return run
