"""
Closes docs/AGENCY_ONBOARDING.md's Stage 2b gap: AGENCY_NAME used to be a
process-level env var (main.py), meaning a real multi-tenant deployment
running one shared orchestrator process pool couldn't vary it per call by
tenant_id -- every call got the same agency name regardless of which
tenant it belonged to. Looked up from `tenant_settings.agency_name`
(db/migrations/007_tenant_branding.sql) instead, alongside calendar
credentials -- same table, same per-tenant-row shape.
"""

from __future__ import annotations

import asyncpg


async def get_agency_name(database_url: str, tenant_id: str, default: str) -> str:
    """`default` (main.py's AGENCY_NAME env var) covers both real gaps
    this can't distinguish between: DATABASE_URL unset entirely (local
    dev without Postgres, same degrade-gracefully pattern
    transcript_store.py uses), and a tenant that exists but was
    onboarded before this existed / never set branding via
    PUT /admin/tenants/{tenant_id}/branding."""
    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            row = await conn.fetchrow(
                "SELECT agency_name FROM tenant_settings WHERE tenant_id = $1", tenant_id
            )
    finally:
        await conn.close()
    if row is None or not row["agency_name"]:
        return default
    return row["agency_name"]
