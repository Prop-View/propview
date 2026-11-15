"""
PROP-602: Tenant Admin API -- upload listings and calendar credentials
per tenant. Builds on PROP-601's RLS: every write goes through
tenant_connection() so a tenant can only ever write its own rows.

Dashboard read endpoints (properties, leads, calls, appointments,
analytics) added to serve the React frontend -- same tenant auth,
same RLS isolation, read-only queries.
"""

from __future__ import annotations

import json
import os
import csv
import io
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg
from dotenv import load_dotenv

load_dotenv()  # real gap found 2026-09-09: this was never called here --
# see services/tool-router/main.py's identical fix for the full story.

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field, ValidationError  # noqa: E402
from redis.exceptions import RedisError  # noqa: E402

from accounts import router as accounts_router  # noqa: E402
from audit import write_audit  # noqa: E402
from billing import router as billing_router  # noqa: E402
from auth import (  # noqa: E402
    AuthPrincipal,
    generate_api_key,
    hash_key,
    require_machine_api_key,
    require_owner,
    require_owner_or_machine,
    require_platform_token,
    require_tenant_auth,
)
from calendar_oauth import router as calendar_oauth_router  # noqa: E402
from crypto import decrypt, encrypt  # noqa: E402
from db import close_pool, get_pool, tenant_connection  # noqa: E402
from knowledge_upload import ingest_document  # noqa: E402
from rate_limit import (  # noqa: E402
    DASHBOARD_LIMIT,
    DEFAULT_LIMIT,
    PROVISION_LIMIT,
    platform_rate_limited,
    rate_limited,
)
from redis_client import close_redis_client, get_redis_client  # noqa: E402
from webhooks import router as webhooks_router  # noqa: E402


def _row_to_dict(row) -> dict:
    out = dict(row)
    for key, value in out.items():
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif key == "amenities" and isinstance(value, str):
            out[key] = json.loads(value)
    return out


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


class TenantRegistryRequest(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    name: str = Field(min_length=1, max_length=200)
    status: Literal["pending", "active", "suspended"] = "active"
    plan: str = Field(default="starter", min_length=1, max_length=80)


class TenantPhoneNumberRequest(BaseModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    phone_number: str = Field(pattern=r"^\+[1-9][0-9]{1,14}$")


class TenantPhoneNumberRemovalRequest(BaseModel):
    phone_number: str = Field(pattern=r"^\+[1-9][0-9]{1,14}$")


class TenantOperationalSettingsRequest(BaseModel):
    broker_transfer_number: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{1,14}$")
    sms_sender_number: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{1,14}$")
    whatsapp_sender_number: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{1,14}$")
    time_zone: str | None = Field(default=None, min_length=1, max_length=100)
    business_hours_start_hour: int | None = Field(default=None, ge=0, le=23)
    business_hours_end_hour: int | None = Field(default=None, ge=1, le=24)
    voice_name: str | None = Field(default=None, min_length=1, max_length=80)
    greeting: str | None = Field(default=None, min_length=1, max_length=500)


class LeadUpdateRequest(BaseModel):
    status: Literal["new", "qualified", "appointment_set", "closed_won", "closed_lost"] | None = None
    notes: str | None = Field(default=None, max_length=10000)


class AppointmentUpdateRequest(BaseModel):
    scheduled_at: datetime | None = None
    status: Literal["cancelled"] | None = None


class ListingUpdateRequest(BaseModel):
    address: str | None = Field(default=None, min_length=1, max_length=500)
    city: str | None = Field(default=None, min_length=1, max_length=200)
    state: str | None = Field(default=None, min_length=1, max_length=100)
    property_type: Literal["house", "condo", "townhouse", "land"] | None = None
    status: Literal["active", "pending", "sold", "off_market"] | None = None
    beds: int | None = None
    baths: float | None = None
    sqft: int | None = None
    price: float | None = None
    hoa_fee: float | None = None
    listing_agent: str | None = None
    amenities: list[str] | None = None
    project_id: int | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()
    await close_redis_client()


app = FastAPI(title="Propview Tenant Admin API", lifespan=lifespan)
app.include_router(accounts_router)
app.include_router(billing_router)
app.include_router(calendar_oauth_router)
app.include_router(webhooks_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post(
    "/admin/tenants/{tenant_id}/provision",
    dependencies=[
        Depends(require_platform_token),
        Depends(rate_limited(PROVISION_LIMIT, budget="provision")),
    ],
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
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SELECT public.platform_ensure_tenant($1)", tenant_id)

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


@app.get(
    "/admin/platform/tenants",
    dependencies=[
        Depends(require_platform_token),
        Depends(platform_rate_limited(DEFAULT_LIMIT, budget="platform-read")),
    ],
)
async def list_platform_tenants():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT slug, name, status, plan, created_at
            FROM public.platform_list_tenants()
            """
        )
    return {"items": [dict(row) for row in rows]}


@app.post(
    "/admin/platform/tenants",
    dependencies=[
        Depends(require_platform_token),
        Depends(platform_rate_limited(PROVISION_LIMIT, budget="platform-write")),
    ],
)
async def upsert_platform_tenant(request: TenantRegistryRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "SELECT public.platform_upsert_tenant($1, $2, $3, $4)",
            request.slug,
            request.name,
            request.status,
            request.plan,
        )
    return {"slug": request.slug, "name": request.name, "status": request.status, "plan": request.plan}


@app.get(
    "/admin/platform/phone-numbers",
    dependencies=[
        Depends(require_platform_token),
        Depends(platform_rate_limited(DEFAULT_LIMIT, budget="platform-read")),
    ],
)
async def list_platform_phone_numbers():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT phone_number, tenant_id, created_at
            FROM public.platform_list_tenant_phone_numbers()
            """
        )
    return {"items": [dict(row) for row in rows]}


@app.put(
    "/admin/platform/phone-numbers",
    dependencies=[
        Depends(require_platform_token),
        Depends(platform_rate_limited(PROVISION_LIMIT, budget="platform-write")),
    ],
)
async def set_platform_phone_number(request: TenantPhoneNumberRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "SELECT public.platform_set_tenant_phone_number($1, $2)",
                request.phone_number,
                request.tenant_id,
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise HTTPException(status_code=404, detail="Tenant not found") from exc
    return {"phone_number": request.phone_number, "tenant_id": request.tenant_id}


@app.delete(
    "/admin/platform/phone-numbers",
    dependencies=[
        Depends(require_platform_token),
        Depends(platform_rate_limited(PROVISION_LIMIT, budget="platform-write")),
    ],
)
async def remove_platform_phone_number(request: TenantPhoneNumberRemovalRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        removed = await conn.fetchval(
            "SELECT public.platform_remove_tenant_phone_number($1)",
            request.phone_number,
        )
    if not removed:
        raise HTTPException(status_code=404, detail="Phone number mapping not found")
    return {"phone_number": request.phone_number, "removed": True}


@app.post(
    "/admin/tenants/{tenant_id}/listings",
    dependencies=[Depends(require_owner_or_machine), Depends(rate_limited())],
)
async def upload_listings(
    tenant_id: str,
    request: ListingsUploadRequest,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    if not request.listings:
        raise HTTPException(status_code=400, detail="listings must not be empty")

    inserted_ids = []
    async with tenant_connection(tenant_id) as conn:
        for listing in request.listings:
            if listing.project_id is not None:
                project_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM projects WHERE tenant_id = $1 AND id = $2)",
                    tenant_id,
                    listing.project_id,
                )
                if not project_exists:
                    raise HTTPException(status_code=404, detail="Project not found")
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
        await write_audit(
            conn, tenant_id, "listing.bulk_uploaded", principal.user_id,
            "property", metadata={"count": len(inserted_ids)},
        )

    return {"inserted": len(inserted_ids), "ids": inserted_ids}


@app.post(
    "/admin/tenants/{tenant_id}/listings/upload-csv",
    dependencies=[Depends(require_owner_or_machine), Depends(rate_limited())],
)
async def upload_listings_csv(
    tenant_id: str,
    file: UploadFile = File(...),
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    contents = await file.read(5 * 1024 * 1024 + 1)
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV exceeds the 5 MiB limit")
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    required = {"address", "city", "state", "property_type", "price"}
    allowed = set(ListingUpload.model_fields)
    headers = set(reader.fieldnames or [])
    if (
        not required.issubset(headers)
        or not headers.issubset(allowed)
        or len(headers) != len(reader.fieldnames or [])
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "CSV headers are missing required fields or contain unsupported fields",
                "required": sorted(required),
                "supported": sorted(allowed),
            },
        )
    listings = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise HTTPException(status_code=422, detail=f"CSV row {row_number} has extra values")
        normalized = {
            key: (value.strip() if value is not None else None)
            for key, value in row.items()
        }
        if normalized.get("amenities") is not None:
            normalized["amenities"] = [
                amenity.strip()
                for amenity in normalized["amenities"].split("|")
                if amenity.strip()
            ]
        for key in ("beds", "baths", "sqft", "hoa_fee", "listing_agent", "project_id"):
            if normalized.get(key) == "":
                normalized[key] = None
        try:
            listings.append(ListingUpload.model_validate(normalized))
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"row": row_number, "errors": exc.errors()},
            ) from exc
        if len(listings) > 500:
            raise HTTPException(status_code=413, detail="CSV may contain at most 500 listings")
    if not listings:
        raise HTTPException(status_code=400, detail="CSV contains no listings")

    inserted_ids = []
    async with tenant_connection(tenant_id) as conn:
        for listing in listings:
            if listing.project_id is not None:
                project_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM projects WHERE tenant_id = $1 AND id = $2)",
                    tenant_id,
                    listing.project_id,
                )
                if not project_exists:
                    raise HTTPException(status_code=404, detail="Project not found")
            row_id = await conn.fetchval(
                """
                INSERT INTO properties
                    (tenant_id, project_id, address, city, state, property_type, status,
                     beds, baths, sqft, price, hoa_fee, listing_agent, amenities)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb)
                RETURNING id
                """,
                tenant_id, listing.project_id, listing.address, listing.city,
                listing.state, listing.property_type, listing.status,
                listing.beds, listing.baths, listing.sqft, listing.price,
                listing.hoa_fee, listing.listing_agent, json.dumps(listing.amenities),
            )
            inserted_ids.append(row_id)
        await write_audit(
            conn, tenant_id, "listing.csv_uploaded", principal.user_id, "property",
            metadata={"count": len(inserted_ids), "filename": file.filename},
        )
    return {"inserted": len(inserted_ids), "ids": inserted_ids}


@app.patch(
    "/admin/tenants/{tenant_id}/leads/{lead_id}",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
)
async def update_lead(
    tenant_id: str,
    lead_id: int,
    request: LeadUpdateRequest,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="At least one lead field must be provided")
    columns = list(updates)
    assignments = ", ".join(f"{column} = ${index + 3}" for index, column in enumerate(columns))
    values = [tenant_id, lead_id, *(updates[column] for column in columns)]
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE leads SET {assignments}, updated_at = now()
            WHERE tenant_id = $1 AND id = $2
            RETURNING id, status, notes, updated_at
            """,
            *values,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        await write_audit(
            conn, tenant_id, "lead.updated", principal.user_id, "lead", lead_id,
            {"fields": columns},
        )
    return dict(row)


@app.patch(
    "/admin/tenants/{tenant_id}/appointments/{appointment_id}",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
)
async def update_appointment(
    tenant_id: str,
    appointment_id: int,
    request: AppointmentUpdateRequest,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Provide scheduled_at to reschedule or status=cancelled to cancel",
        )
    scheduled_at = updates.get("scheduled_at")
    if scheduled_at is not None:
        if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
            raise HTTPException(status_code=422, detail="scheduled_at must include a timezone")
        if scheduled_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="scheduled_at must be in the future")
    columns = list(updates)
    assignments = ", ".join(f"{column} = ${index + 3}" for index, column in enumerate(columns))
    values = [tenant_id, appointment_id, *(updates[column] for column in columns)]
    async with tenant_connection(tenant_id) as conn:
        current = await conn.fetchrow(
            "SELECT status FROM appointments WHERE tenant_id = $1 AND id = $2",
            tenant_id,
            appointment_id,
        )
        if current is None:
            raise HTTPException(status_code=404, detail="Appointment not found")
        if current["status"] in {"cancelled", "completed"}:
            raise HTTPException(status_code=409, detail="Appointment can no longer be changed")
        row = await conn.fetchrow(
            f"""
            UPDATE appointments SET {assignments}
            WHERE tenant_id = $1 AND id = $2
            RETURNING id, status, scheduled_at
            """,
            *values,
        )
        await write_audit(
            conn, tenant_id, "appointment.updated", principal.user_id, "appointment",
            appointment_id, {"fields": columns},
        )
    return dict(row)


@app.patch(
    "/admin/tenants/{tenant_id}/properties/{property_id}",
    dependencies=[Depends(require_owner_or_machine), Depends(rate_limited())],
)
async def update_listing(
    tenant_id: str,
    property_id: int,
    request: ListingUpdateRequest,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="At least one listing field must be provided")
    non_nullable = {"address", "city", "state", "property_type", "status", "price", "amenities"}
    if any(field in updates and updates[field] is None for field in non_nullable):
        raise HTTPException(status_code=422, detail="Required listing fields cannot be cleared")
    if "project_id" in updates and updates["project_id"] is not None:
        async with tenant_connection(tenant_id) as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM projects WHERE tenant_id = $1 AND id = $2)",
                tenant_id,
                updates["project_id"],
            )
        if not exists:
            raise HTTPException(status_code=404, detail="Project not found")
    if "amenities" in updates and updates["amenities"] is not None:
        updates["amenities"] = json.dumps(updates["amenities"])
    columns = list(updates)
    assignments = ", ".join(
        f"{column} = ${index + 3}" + ("::jsonb" if column == "amenities" else "")
        for index, column in enumerate(columns)
    )
    values = [tenant_id, property_id, *(updates[column] for column in columns)]
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE properties SET {assignments}, updated_at = now()
            WHERE tenant_id = $1 AND id = $2
            RETURNING id, address, city, state, property_type, status, beds, baths,
                      sqft, price, hoa_fee, listing_agent, amenities, updated_at
            """,
            *values,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Listing not found")
        await write_audit(
            conn, tenant_id, "listing.updated", principal.user_id, "property",
            property_id, {"fields": columns},
        )
    return _row_to_dict(row)


@app.delete(
    "/admin/tenants/{tenant_id}/properties/{property_id}",
    dependencies=[Depends(require_owner_or_machine), Depends(rate_limited())],
)
async def delete_listing(
    tenant_id: str,
    property_id: int,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    async with tenant_connection(tenant_id) as conn:
        deleted = await conn.fetchval(
            "DELETE FROM properties WHERE tenant_id = $1 AND id = $2 RETURNING id",
            tenant_id,
            property_id,
        )
        if deleted is None:
            raise HTTPException(status_code=404, detail="Listing not found")
        await write_audit(
            conn, tenant_id, "listing.deleted", principal.user_id, "property", property_id
        )
    return {"id": deleted, "deleted": True}


@app.post(
    "/admin/tenants/{tenant_id}/knowledge-base/documents",
    dependencies=[Depends(require_owner_or_machine), Depends(rate_limited())],
)
async def upload_knowledge_document(
    tenant_id: str,
    file: UploadFile = File(...),
    source_type: Literal["faq", "policy", "brochure", "transcript", "other"] = Form("other"),
    project_id: int | None = Form(default=None),
    property_id: int | None = Form(default=None),
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    chunks = await ingest_document(
        tenant_id, file, source_type, project_id, property_id
    )
    async with tenant_connection(tenant_id) as conn:
        await write_audit(
            conn, tenant_id, "knowledge_base.document_uploaded", principal.user_id,
            "knowledge_base_document", file.filename,
            {"source_type": source_type, "chunk_count": chunks},
        )
    return {"filename": file.filename, "chunks_created": chunks}


@app.put(
    "/admin/tenants/{tenant_id}/branding",
    dependencies=[Depends(require_owner_or_machine), Depends(rate_limited())],
)
async def set_branding(
    tenant_id: str,
    request: BrandingRequest,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
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
        await write_audit(
            conn, tenant_id, "branding.updated", principal.user_id,
            "tenant_settings", tenant_id,
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


OPERATIONAL_SETTING_COLUMNS = (
    "broker_transfer_number",
    "sms_sender_number",
    "whatsapp_sender_number",
    "time_zone",
    "business_hours_start_hour",
    "business_hours_end_hour",
    "voice_name",
    "greeting",
)


@app.get(
    "/admin/tenants/{tenant_id}/settings",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
)
async def get_tenant_operational_settings(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            f"SELECT {', '.join(OPERATIONAL_SETTING_COLUMNS)} FROM tenant_settings WHERE tenant_id = $1",
            tenant_id,
        )
    return {
        column: row[column] if row else None
        for column in OPERATIONAL_SETTING_COLUMNS
    }


@app.put(
    "/admin/tenants/{tenant_id}/settings",
    dependencies=[Depends(require_owner_or_machine), Depends(rate_limited())],
)
async def set_tenant_operational_settings(
    tenant_id: str,
    request: TenantOperationalSettingsRequest,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="At least one setting must be provided")
    if any(column not in OPERATIONAL_SETTING_COLUMNS for column in updates):
        raise HTTPException(status_code=400, detail="Unsupported setting")

    time_zone = updates.get("time_zone")
    if time_zone is not None:
        try:
            ZoneInfo(time_zone)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(status_code=422, detail="time_zone must be a valid IANA time zone") from exc

    async with tenant_connection(tenant_id) as conn:
        current_hours = await conn.fetchrow(
            """
            SELECT business_hours_start_hour, business_hours_end_hour
            FROM tenant_settings
            WHERE tenant_id = $1
            """,
            tenant_id,
        )
        start_hour = updates.get(
            "business_hours_start_hour",
            current_hours["business_hours_start_hour"] if current_hours else None,
        )
        end_hour = updates.get(
            "business_hours_end_hour",
            current_hours["business_hours_end_hour"] if current_hours else None,
        )
        if (start_hour is None) != (end_hour is None) or (
            start_hour is not None and end_hour is not None and start_hour >= end_hour
        ):
            raise HTTPException(
                status_code=422,
                detail="Business hours must be set or cleared as a valid start/end pair",
            )

        columns = list(updates)
        values = [tenant_id, *(updates[column] for column in columns)]
        insert_columns = ", ".join(("tenant_id", *columns))
        placeholders = ", ".join(f"${index}" for index in range(1, len(values) + 1))
        assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns)
        await conn.execute(
            f"""
            INSERT INTO tenant_settings ({insert_columns}, updated_at)
            VALUES ({placeholders}, now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                {assignments},
                updated_at = now()
            """,
            *values,
        )
        await write_audit(
            conn, tenant_id, "tenant_settings.updated", principal.user_id,
            "tenant_settings", tenant_id, {"fields": columns},
        )
    return {"status": "ok"}


@app.get(
    "/admin/tenants/{tenant_id}/usage/monthly",
    dependencies=[
        Depends(require_tenant_auth),
        Depends(rate_limited(DASHBOARD_LIMIT, budget="dashboard")),
    ],
)
async def get_monthly_usage(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT month, event_type, event_count, units
            FROM monthly_usage
            WHERE tenant_id = $1
            ORDER BY month, event_type
            """,
            tenant_id,
        )
    return {"items": [dict(row) for row in rows]}


@app.put(
    "/admin/tenants/{tenant_id}/calendar-credentials",
    dependencies=[Depends(require_owner_or_machine), Depends(rate_limited())],
)
async def set_calendar_credentials(
    tenant_id: str,
    request: CalendarCredentialsRequest,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
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
        await write_audit(
            conn, tenant_id, "calendar.credentials_updated", principal.user_id,
            "tenant_settings", tenant_id, {"provider": request.provider},
        )
    return {"status": "ok"}


@app.get(
    "/admin/tenants/{tenant_id}/calendar-credentials",
    dependencies=[Depends(require_machine_api_key), Depends(rate_limited())],
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


@app.get(
    "/admin/tenants/{tenant_id}/properties",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited(DASHBOARD_LIMIT, budget="dashboard"))],
)
async def list_properties(
    tenant_id: str,
    status: str | None = None,
    property_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conditions = ["tenant_id = $1"]
    params: list = [tenant_id]
    if status:
        params.append(status)
        conditions.append(f"status = ${len(params)}")
    if property_type:
        params.append(property_type)
        conditions.append(f"property_type = ${len(params)}")
    params.extend([limit, offset])
    query = f"""
        SELECT id, address, city, state, property_type, status, beds, baths,
               sqft, price, hoa_fee, listing_agent, amenities, created_at
        FROM properties
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """
    async with tenant_connection(tenant_id) as conn:
        rows = await conn.fetch(query, *params)
        count = await conn.fetchval(
            f"SELECT count(*) FROM properties WHERE {' AND '.join(conditions)}",
            *params[:-2],
        )
    return {"items": [_row_to_dict(r) for r in rows], "total": count}


@app.get(
    "/admin/tenants/{tenant_id}/leads",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited(DASHBOARD_LIMIT, budget="dashboard"))],
)
async def list_leads(
    tenant_id: str,
    priority: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conditions = ["l.tenant_id = $1"]
    params: list = [tenant_id]
    if priority:
        params.append(priority)
        conditions.append(f"l.priority = ${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"l.status = ${len(params)}")
    params.extend([limit, offset])
    query = f"""
        SELECT l.id, l.contact_id, c.full_name, c.phone_number, c.email, l.notes,
               l.intent, l.budget_min, l.budget_max, l.timeline,
               l.decision_maker, l.priority, l.status, l.property_id,
               l.created_at, l.updated_at
        FROM leads l
        JOIN contacts c ON c.id = l.contact_id AND c.tenant_id = l.tenant_id
        WHERE {' AND '.join(conditions)}
        ORDER BY l.updated_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """
    async with tenant_connection(tenant_id) as conn:
        rows = await conn.fetch(query, *params)
        count = await conn.fetchval(
            f"SELECT count(*) FROM leads l WHERE {' AND '.join(conditions[:1] + conditions[1:])}",
            *params[:-2],
        )
    return {"items": [_row_to_dict(r) for r in rows], "total": count}


@app.get(
    "/admin/tenants/{tenant_id}/appointments",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited(DASHBOARD_LIMIT, budget="dashboard"))],
)
async def list_appointments(
    tenant_id: str,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conditions = ["a.tenant_id = $1"]
    params: list = [tenant_id]
    if status:
        params.append(status)
        conditions.append(f"a.status = ${len(params)}")
    params.extend([limit, offset])
    query = f"""
        SELECT a.id, a.lead_id, a.property_id, a.scheduled_at, a.status,
               a.agent_name, a.confirmation_sms_sent_at, a.created_at,
               c.full_name AS lead_name,
               p.address AS property_address
        FROM appointments a
        JOIN leads l ON l.id = a.lead_id AND l.tenant_id = a.tenant_id
        JOIN contacts c ON c.id = l.contact_id AND c.tenant_id = a.tenant_id
        LEFT JOIN properties p ON p.id = a.property_id AND p.tenant_id = a.tenant_id
        WHERE {' AND '.join(conditions)}
        ORDER BY a.scheduled_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """
    async with tenant_connection(tenant_id) as conn:
        rows = await conn.fetch(query, *params)
        count = await conn.fetchval(
            f"SELECT count(*) FROM appointments a WHERE {' AND '.join(conditions)}",
            *params[:-2],
        )
    return {"items": [_row_to_dict(r) for r in rows], "total": count}


@app.get(
    "/admin/tenants/{tenant_id}/calls",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited(DASHBOARD_LIMIT, budget="dashboard"))],
)
async def list_calls(
    tenant_id: str,
    outcome: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conditions = ["i.tenant_id = $1"]
    params: list = [tenant_id]
    if outcome:
        params.append(outcome)
        conditions.append(f"ca.outcome = ${len(params)}")
    params.extend([limit, offset])
    query = f"""
        SELECT i.id, i.call_id, i.channel, i.duration_seconds, i.outcome,
               i.created_at,
               c.full_name AS caller_name, c.phone_number AS caller_phone,
               ca.total_turns, ca.tools_used, ca.outcome AS analytics_outcome,
               ca.barge_in_count
        FROM interactions i
        LEFT JOIN contacts c ON c.id = i.contact_id AND c.tenant_id = i.tenant_id
        LEFT JOIN call_analytics ca ON ca.call_id = i.call_id AND ca.tenant_id = i.tenant_id
        WHERE {' AND '.join(conditions)}
        ORDER BY i.created_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """
    async with tenant_connection(tenant_id) as conn:
        rows = await conn.fetch(query, *params)
        count = await conn.fetchval(
            f"""SELECT count(*) FROM interactions i
                LEFT JOIN call_analytics ca ON ca.call_id = i.call_id AND ca.tenant_id = i.tenant_id
                WHERE {' AND '.join(conditions)}""",
            *params[:-2],
        )
    return {"items": [_row_to_dict(r) for r in rows], "total": count}


@app.get(
    "/admin/tenants/{tenant_id}/calls/{call_id}",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited(DASHBOARD_LIMIT, budget="dashboard"))],
)
async def get_call_detail(tenant_id: str, call_id: str):
    async with tenant_connection(tenant_id) as conn:
        interaction = await conn.fetchrow(
            """SELECT i.*, c.full_name AS caller_name, c.phone_number AS caller_phone
               FROM interactions i
               LEFT JOIN contacts c ON c.id = i.contact_id AND c.tenant_id = i.tenant_id
               WHERE i.call_id = $1""",
            call_id,
        )
        if not interaction:
            raise HTTPException(status_code=404, detail="Call not found")

        turns = await conn.fetch(
            "SELECT * FROM conversation_turns WHERE call_id = $1 ORDER BY turn_index",
            call_id,
        )
        tools = await conn.fetch(
            "SELECT * FROM tool_invocations WHERE call_id = $1 ORDER BY created_at",
            call_id,
        )
        analytics = await conn.fetchrow(
            "SELECT * FROM call_analytics WHERE call_id = $1", call_id,
        )
    return {
        "interaction": _row_to_dict(interaction),
        "turns": [_row_to_dict(t) for t in turns],
        "tool_invocations": [_row_to_dict(t) for t in tools],
        "analytics": _row_to_dict(analytics) if analytics else None,
    }


@app.get(
    "/admin/tenants/{tenant_id}/stats",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited(DASHBOARD_LIMIT, budget="dashboard"))],
)
async def get_dashboard_stats(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        total_calls = await conn.fetchval(
            "SELECT count(*) FROM interactions WHERE tenant_id = $1", tenant_id
        )
        calls_today = await conn.fetchval(
            "SELECT count(*) FROM interactions WHERE tenant_id = $1 AND created_at >= CURRENT_DATE",
            tenant_id,
        )
        avg_duration = await conn.fetchval(
            "SELECT coalesce(avg(duration_seconds), 0) FROM interactions WHERE tenant_id = $1",
            tenant_id,
        )
        total_properties = await conn.fetchval(
            "SELECT count(*) FROM properties WHERE tenant_id = $1", tenant_id
        )
        active_leads = await conn.fetchval(
            "SELECT count(*) FROM leads WHERE tenant_id = $1 AND status NOT IN ('closed_won', 'closed_lost')",
            tenant_id,
        )
        hot_leads = await conn.fetchval(
            "SELECT count(*) FROM leads WHERE tenant_id = $1 AND priority = 'high' AND status NOT IN ('closed_won', 'closed_lost')",
            tenant_id,
        )
        appointments_this_week = await conn.fetchval(
            """SELECT count(*) FROM appointments
               WHERE tenant_id = $1 AND scheduled_at >= date_trunc('week', CURRENT_DATE)
               AND scheduled_at < date_trunc('week', CURRENT_DATE) + interval '7 days'""",
            tenant_id,
        )
        lead_priority_counts = await conn.fetch(
            """SELECT priority, count(*)::int AS count FROM leads
               WHERE tenant_id = $1 AND status NOT IN ('closed_won', 'closed_lost')
               GROUP BY priority""",
            tenant_id,
        )
        outcome_counts = await conn.fetch(
            """SELECT outcome, count(*)::int AS count FROM call_analytics
               WHERE tenant_id = $1 GROUP BY outcome""",
            tenant_id,
        )
        daily_calls = await conn.fetch(
            """SELECT created_at::date AS date, count(*)::int AS calls
               FROM interactions WHERE tenant_id = $1
               AND created_at >= CURRENT_DATE - interval '7 days'
               GROUP BY created_at::date ORDER BY date""",
            tenant_id,
        )
        daily_bookings = await conn.fetch(
            """SELECT scheduled_at::date AS date, count(*)::int AS booked
               FROM appointments WHERE tenant_id = $1
               AND scheduled_at >= CURRENT_DATE - interval '7 days'
               GROUP BY scheduled_at::date ORDER BY date""",
            tenant_id,
        )
        tool_usage = await conn.fetch(
            """SELECT tool_name, count(*)::int AS count
               FROM tool_invocations WHERE tenant_id = $1
               GROUP BY tool_name ORDER BY count DESC""",
            tenant_id,
        )
        booked_count = await conn.fetchval(
            "SELECT count(*) FROM call_analytics WHERE tenant_id = $1 AND outcome = 'booked'",
            tenant_id,
        )
    conversion_rate = round((booked_count / total_calls * 100), 1) if total_calls > 0 else 0
    return {
        "total_calls": total_calls,
        "calls_today": calls_today,
        "avg_duration_seconds": float(avg_duration),
        "conversion_rate": conversion_rate,
        "total_properties": total_properties,
        "active_leads": active_leads,
        "hot_leads": hot_leads,
        "appointments_this_week": appointments_this_week,
        "lead_priority_counts": {r["priority"]: r["count"] for r in lead_priority_counts if r["priority"]},
        "outcome_counts": {r["outcome"]: r["count"] for r in outcome_counts if r["outcome"]},
        "daily_calls": [{"date": str(r["date"]), "calls": r["calls"]} for r in daily_calls],
        "daily_bookings": [{"date": str(r["date"]), "booked": r["booked"]} for r in daily_bookings],
        "tool_usage": [{"tool_name": r["tool_name"], "count": r["count"]} for r in tool_usage],
    }


@app.get("/health")
async def health():
    dependencies = {"postgres": "connected", "redis": "connected"}
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError):
        dependencies["postgres"] = "offline"
    try:
        await get_redis_client().ping()
    except (RedisError, OSError, TimeoutError):
        dependencies["redis"] = "offline"
    status = "ok" if all(value == "connected" for value in dependencies.values()) else "degraded"
    return {"status": status, "service": "admin-api", "dependencies": dependencies}
