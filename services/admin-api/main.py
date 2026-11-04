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
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Literal

from dotenv import load_dotenv

load_dotenv()  # real gap found 2026-09-09: this was never called here --
# see services/tool-router/main.py's identical fix for the full story.

from fastapi import Depends, FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from auth import generate_api_key, hash_key, require_platform_token, require_tenant_auth  # noqa: E402
from crypto import decrypt, encrypt  # noqa: E402
from db import close_pool, get_pool, tenant_connection  # noqa: E402
from rate_limit import PROVISION_LIMIT, rate_limited  # noqa: E402
from redis_client import close_redis_client  # noqa: E402


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()
    await close_redis_client()


app = FastAPI(title="Propview Tenant Admin API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get(
    "/admin/tenants/{tenant_id}/properties",
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
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
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
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
        SELECT l.id, l.contact_id, c.full_name, c.phone_number, c.email,
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
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
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
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
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
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
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
    dependencies=[Depends(require_tenant_auth), Depends(rate_limited())],
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
    return {"status": "ok"}
