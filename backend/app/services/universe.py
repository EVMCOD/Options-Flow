"""Universe management service."""

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_setup import get_logger
from app.models.models import ScannerUniverse

log = get_logger(__name__)


async def get_universe(
    db: AsyncSession, tenant_id: Optional[uuid.UUID] = None
) -> List[ScannerUniverse]:
    q = select(ScannerUniverse).order_by(
        ScannerUniverse.priority.desc(), ScannerUniverse.symbol
    )
    if tenant_id is not None:
        q = q.where(ScannerUniverse.tenant_id == tenant_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_enabled_symbols(
    db: AsyncSession, tenant_id: Optional[uuid.UUID] = None
) -> List[str]:
    q = (
        select(ScannerUniverse.symbol)
        .where(ScannerUniverse.enabled == True)
        .order_by(ScannerUniverse.priority.desc(), ScannerUniverse.symbol)
    )
    if tenant_id is not None:
        q = q.where(ScannerUniverse.tenant_id == tenant_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, entry_id: uuid.UUID) -> Optional[ScannerUniverse]:
    result = await db.execute(select(ScannerUniverse).where(ScannerUniverse.id == entry_id))
    return result.scalar_one_or_none()


async def create_entry(
    db: AsyncSession,
    symbol: str,
    tenant_id: Optional[uuid.UUID] = None,
    enabled: bool = True,
    priority: int = 0,
) -> ScannerUniverse:
    entry = ScannerUniverse(
        symbol=symbol.upper(),
        tenant_id=tenant_id,
        enabled=enabled,
        priority=priority,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    log.info("universe.created", symbol=symbol, tenant_id=str(tenant_id))
    return entry


async def patch_entry(
    db: AsyncSession,
    entry: ScannerUniverse,
    enabled: Optional[bool],
    priority: Optional[int],
) -> ScannerUniverse:
    if enabled is not None:
        entry.enabled = enabled
    if priority is not None:
        entry.priority = priority
    await db.commit()
    await db.refresh(entry)
    return entry


async def delete_entry(db: AsyncSession, entry: ScannerUniverse) -> None:
    await db.delete(entry)
    await db.commit()
    log.info("universe.deleted", symbol=entry.symbol)


async def seed_universe_if_empty(
    db: AsyncSession, tenant_id: uuid.UUID
) -> None:
    """Seed the universe table with default symbols for this tenant if empty."""
    result = await db.execute(
        select(ScannerUniverse).where(ScannerUniverse.tenant_id == tenant_id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return

    log.info("universe.seeding", tenant_id=str(tenant_id), count=len(settings.SCANNER_UNIVERSE))
    for i, symbol in enumerate(settings.SCANNER_UNIVERSE):
        entry = ScannerUniverse(
            symbol=symbol,
            tenant_id=tenant_id,
            enabled=True,
            priority=len(settings.SCANNER_UNIVERSE) - i,
        )
        db.add(entry)
    await db.commit()
    log.info("universe.seeded", tenant_id=str(tenant_id), symbols=settings.SCANNER_UNIVERSE)
