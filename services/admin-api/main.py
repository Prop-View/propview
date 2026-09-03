"""
PROP-602: Tenant Admin API -- upload listings and calendar credentials
per tenant. Builds on PROP-601's RLS: every write goes through
tenant_connection() so a tenant can only ever write its own rows.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from crypto import decrypt, encrypt
from db import close_pool, get_pool, tenant_connection


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()


app = FastAPI(title="Propview Tenant Admin API", lifespan=lifespan)


@app.post("/admin/tenants/{tenant_id}/listings")
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


@app.put("/admin/tenants/{tenant_id}/calendar-credentials")
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


@app.get("/admin/tenants/{tenant_id}/calendar-credentials")
async def get_calendar_credentials(tenant_id: str):
    """NOTE: no authentication/authorization on this endpoint -- fine for
    local dev, but this MUST be locked down (internal-only network, auth
    middleware) before any real deployment. Not addressed by this ticket."""
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
