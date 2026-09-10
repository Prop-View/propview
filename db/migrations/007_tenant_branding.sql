-- Closes docs/AGENCY_ONBOARDING.md's Stage 2b gap: agency branding
-- (currently just a name) was a process-level env var on the
-- orchestrator, not a per-tenant value -- meaning a shared orchestrator
-- process pool serving multiple tenants couldn't vary it per call.

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS agency_name TEXT;
