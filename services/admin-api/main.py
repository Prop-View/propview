"""
PROP-602: Tenant Admin API -- upload listings and calendar credentials
per tenant. Builds on PROP-601's RLS: every write goes through
tenant_connection() so a tenant can only ever write its own rows.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv

load_dotenv()  # real gap found 2026-09-09: this was never called here --
# see services/tool-router/main.py's identical fix for the full story.

from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from auth import generate_api_key, hash_key, require_platform_token, require_tenant_auth  # noqa: E402
from crypto import decrypt, encrypt  # noqa: E402
from db import close_pool, get_pool, tenant_connection  # noqa: E402
from rate_limit import PROVISION_LIMIT, rate_limited  # noqa: E402
from redis_client import close_redis_client  # noqa: E402


class ListingUpload(BaseModel):
    address: str
    city: str
    state: str
    property_type: Literal["house", "condo", "townhouse", "land"]
    status: Literal["active", "pending", "sold", "off_market"] = "active"
    beds: int | None = None
    baths: float | None = None
    sqft: int | None = None
    price: float
    hoa_fee: float | None = None
    listing_agent: str | None = None
    amenities: list[str] = Field(default_factory=list)
    project_id: int | None = None


class ListingsUploadRequest(BaseModel):
    listings: list[ListingUpload]


class CalendarCredentialsRequest(BaseModel):
    provider: str
    credentials: dict


class BrandingRequest(BaseModel):
    agency_name: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()
    await close_redis_client()


app = FastAPI(title="Propview Tenant Admin API", lifespan=lifespan)


@app.post(
    "/admin/tenants/{tenant_id}/provision",
    dependencies=[Depends(require_platform_token), Depends(rate_limited(PROVISION_LIMIT))],
)
async def provision_tenant(tenant_id: str):
    """Stage 1 of docs/AGENCY_ONBOARDING.md's onboarding flow -- the very
    first call for a brand-new tenant. Generates a fresh admin API key,
    stores only its hash, and returns the plaintext key exactly once (the
    caller -- platform ops onboarding the agency -- must save it now;
    there is no recovery endpoint, only re-provisioning, which invalidates
    the old key). Gated by the platform operator token, not a tenant key,
    since no tenant key exists yet for a brand-new tenant."""
    api_key = generate_api_key()
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            """
            INSERT INTO tenant_settings (tenant_id, admin_api_key_hash, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                admin_api_key_hash = EXCLUDED.admin_api_key_hash,
                updated_at = now()
            """,
            tenant_id,
            hash_key(api_key),
        )
    return {"tenant_id": tenant_id, "admin_api_key": api_key}


@app.post(
    "/admin/tenants/{tenant_id}/listings",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
)
async def upload_listings(tenant_id: str, request: ListingsUploadRequest):
    if not request.listings:
        raise HTTPException(status_code=400, detail="listings must not be empty")

    inserted_ids = []
    async with tenant_connection(tenant_id) as conn:
        for listing in request.listings:
            row_id = await conn.fetchval(
                """
                INSERT INTO properties
                    (tenant_id, project_id, address, city, state, property_type, status,
                     beds, baths, sqft, price, hoa_fee, listing_agent, amenities)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb)
                RETURNING id
                """,
                tenant_id,
                listing.project_id,
                listing.address,
                listing.city,
                listing.state,
                listing.property_type,
                listing.status,
                listing.beds,
                listing.baths,
                listing.sqft,
                listing.price,
                listing.hoa_fee,
                listing.listing_agent,
                json.dumps(listing.amenities),
            )
            inserted_ids.append(row_id)

    return {"inserted": len(inserted_ids), "ids": inserted_ids}


@app.put(
    "/admin/tenants/{tenant_id}/branding",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
)
async def set_branding(tenant_id: str, request: BrandingRequest):
    """docs/AGENCY_ONBOARDING.md Stage 2b -- per-tenant agency name,
    looked up by services/orchestrator/tenant_branding.py at call start.
    Same upsert shape as set_calendar_credentials below, same table."""
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            """
            INSERT INTO tenant_settings (tenant_id, agency_name, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                agency_name = EXCLUDED.agency_name,
                updated_at = now()
            """,
            tenant_id,
            request.agency_name,
        )
    return {"status": "ok"}


@app.get(
    "/admin/tenants/{tenant_id}/branding",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
)
async def get_branding(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow("SELECT agency_name FROM tenant_settings WHERE tenant_id = $1", tenant_id)
    return {"agency_name": row["agency_name"] if row else None}


@app.put(
    "/admin/tenants/{tenant_id}/calendar-credentials",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
)
async def set_calendar_credentials(tenant_id: str, request: CalendarCredentialsRequest):
    encrypted = encrypt(json.dumps(request.credentials))
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            """
            INSERT INTO tenant_settings (tenant_id, calendar_provider, encrypted_calendar_credentials, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                calendar_provider = EXCLUDED.calendar_provider,
                encrypted_calendar_credentials = EXCLUDED.encrypted_calendar_credentials,
                updated_at = now()
            """,
            tenant_id,
            request.provider,
            encrypted,
        )
    return {"status": "ok"}


@app.get(
    "/admin/tenants/{tenant_id}/calendar-credentials",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
)
async def get_calendar_credentials(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            "SELECT calendar_provider, encrypted_calendar_credentials FROM tenant_settings WHERE tenant_id = $1",
            tenant_id,
        )
    if row is None or row["encrypted_calendar_credentials"] is None:
        return {"provider": None, "credentials": None}
    return {
        "provider": row["calendar_provider"],
        "credentials": json.loads(decrypt(row["encrypted_calendar_credentials"])),
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
