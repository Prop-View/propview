"""
docs/AGENCY_ONBOARDING.md Stage 2b: tests for tenant_branding.py against
real Postgres -- the same real-Postgres-not-mocked rationale as
test_transcript_store.py, since the whole point is to verify the RLS
tenant-scoped lookup on the actual SELECT, not just the fallback logic.

Run: python -m pytest tests/test_tenant_branding.py -v
"""

import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tenant_branding import get_agency_name

DATABASE_URL = "postgresql://propview_app:devpassword@localhost/propview_dev"


def unique_tenant_id() -> str:
    return f"test-branding-{uuid.uuid4().hex[:8]}"


async def _set_agency_name(tenant_id: str, agency_name: str) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            await conn.execute(
                """
                INSERT INTO tenant_settings (tenant_id, agency_name, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (tenant_id) DO UPDATE SET agency_name = EXCLUDED.agency_name
                """,
                tenant_id,
                agency_name,
            )
    finally:
        await conn.close()


async def _cleanup(tenant_id: str) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            await conn.execute("DELETE FROM tenant_settings WHERE tenant_id = $1", tenant_id)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_returns_configured_agency_name():
    tenant_id = unique_tenant_id()
    await _set_agency_name(tenant_id, "Austin Realty")
    try:
        name = await get_agency_name(DATABASE_URL, tenant_id, default="fallback name")
        assert name == "Austin Realty"
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_falls_back_when_tenant_has_no_row_at_all():
    tenant_id = unique_tenant_id()  # never inserted anywhere
    name = await get_agency_name(DATABASE_URL, tenant_id, default="fallback name")
    assert name == "fallback name"


@pytest.mark.asyncio
async def test_falls_back_when_tenant_row_exists_but_branding_unset():
    tenant_id = unique_tenant_id()
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            # A row from calendar-credentials setup, say -- agency_name never touched.
            await conn.execute("INSERT INTO tenant_settings (tenant_id) VALUES ($1)", tenant_id)
    finally:
        await conn.close()

    try:
        name = await get_agency_name(DATABASE_URL, tenant_id, default="fallback name")
        assert name == "fallback name"
    finally:
        await _cleanup(tenant_id)


@pytest.mark.asyncio
async def test_scoped_by_rls_not_just_the_query_filter():
    tenant_a, tenant_b = unique_tenant_id(), unique_tenant_id()
    await _set_agency_name(tenant_a, "Tenant A Realty")
    try:
        # tenant_b has no row -- must NOT see tenant_a's, RLS-enforced.
        name = await get_agency_name(DATABASE_URL, tenant_b, default="fallback name")
        assert name == "fallback name"
    finally:
        await _cleanup(tenant_a)
