"""Pydantic schemas for Tenant and TenantProviderConfig API."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------

class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")


class TenantPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# TenantProviderConfig
# ---------------------------------------------------------------------------

class TenantProviderConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    provider_type: str
    # Credentials are intentionally omitted from the GET response.
    # Return only config_json (non-sensitive operational settings).
    config_json: dict
    is_active: bool
    is_default: bool
    # Runtime health — managed by the ingestion job, not admins.
    status: str
    last_healthy_at: Optional[datetime]
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime


class TenantProviderConfigCreate(BaseModel):
    provider_type: str = Field(..., min_length=1, max_length=50)
    # Credentials accepted on write, never echoed back in responses.
    credentials_json: dict = Field(default_factory=dict)
    config_json: dict = Field(default_factory=dict)


class TenantProviderConfigPatch(BaseModel):
    is_active: Optional[bool] = None
    credentials_json: Optional[dict] = None
    config_json: Optional[dict] = None
