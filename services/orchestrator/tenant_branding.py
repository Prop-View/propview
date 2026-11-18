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

from tenant_settings import get_tenant_call_settings


async def get_agency_name(database_url: str, tenant_id: str, default: str) -> str:
    """Compatibility helper for callers that only need the agency name."""
    settings = await get_tenant_call_settings(tenant_id, database_url, default_agency_name=default)
    return settings.agency_name or default
