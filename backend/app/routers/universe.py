import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.schemas import (
    ApiResponse,
    ScannerUniverseCreate,
    ScannerUniverseOut,
    ScannerUniversePatch,
)
from app.services import universe as universe_svc

router = APIRouter(prefix="/universe", tags=["universe"])

_DEFAULT_TENANT = uuid.UUID(settings.DEFAULT_TENANT_ID)


def _tenant_id(tenant_id: Optional[uuid.UUID] = Query(None)) -> uuid.UUID:
    """Resolve tenant_id from query param, defaulting to the system default tenant."""
    return tenant_id or _DEFAULT_TENANT


@router.get("", response_model=ApiResponse[list[ScannerUniverseOut]])
async def list_universe(
    tenant_id: uuid.UUID = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    entries = await universe_svc.get_universe(db, tenant_id=tenant_id)
    return ApiResponse.ok([ScannerUniverseOut.model_validate(e) for e in entries])


@router.post("", response_model=ApiResponse[ScannerUniverseOut], status_code=status.HTTP_201_CREATED)
async def create_universe_entry(
    body: ScannerUniverseCreate,
    tenant_id: uuid.UUID = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    entry = await universe_svc.create_entry(
        db,
        symbol=body.symbol,
        tenant_id=tenant_id,
        enabled=body.enabled,
        priority=body.priority,
    )
    return ApiResponse.ok(ScannerUniverseOut.model_validate(entry))


@router.patch("/{entry_id}", response_model=ApiResponse[ScannerUniverseOut])
async def patch_universe_entry(
    entry_id: uuid.UUID,
    body: ScannerUniversePatch,
    db: AsyncSession = Depends(get_db),
):
    entry = await universe_svc.get_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Universe entry not found")
    updated = await universe_svc.patch_entry(db, entry, body.enabled, body.priority)
    return ApiResponse.ok(ScannerUniverseOut.model_validate(updated))


@router.delete("/{entry_id}", response_model=ApiResponse[None])
async def delete_universe_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    entry = await universe_svc.get_by_id(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Universe entry not found")
    await universe_svc.delete_entry(db, entry)
    return ApiResponse.ok(None)
