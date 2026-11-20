-- Phase 2: platform tenant registry, per-tenant operational settings,
-- and tenant-scoped usage metering.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'propview_registry_owner') THEN
        CREATE ROLE propview_registry_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
END $$;

CREATE TABLE tenants (
    slug        TEXT PRIMARY KEY CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('pending', 'active', 'suspended')),
    plan        TEXT NOT NULL DEFAULT 'starter',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tenant_phone_numbers (
    phone_number  TEXT PRIMARY KEY CHECK (phone_number ~ '^\+[1-9][0-9]{1,14}$'),
    tenant_id     TEXT NOT NULL REFERENCES tenants(slug) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tenant_phone_numbers_tenant_id ON tenant_phone_numbers (tenant_id);

-- These platform-level tables are deliberately not tenant-RLS tables.
-- The application role can reach them only through the restricted
-- SECURITY DEFINER functions below; the function owner has no privileges
-- on tenant data.
REVOKE ALL ON tenants, tenant_phone_numbers FROM PUBLIC, propview_app;
GRANT USAGE ON SCHEMA public TO propview_registry_owner;
GRANT SELECT, INSERT, UPDATE, DELETE ON tenants, tenant_phone_numbers TO propview_registry_owner;

CREATE OR REPLACE FUNCTION public.platform_ensure_tenant(p_slug TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_slug !~ '^[a-z0-9][a-z0-9-]{0,62}$' THEN
        RAISE EXCEPTION 'invalid tenant slug' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.tenants (slug, name)
    VALUES (p_slug, p_slug)
    ON CONFLICT (slug) DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_upsert_tenant(
    p_slug TEXT,
    p_name TEXT,
    p_status TEXT,
    p_plan TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_slug !~ '^[a-z0-9][a-z0-9-]{0,62}$' OR NULLIF(btrim(p_name), '') IS NULL THEN
        RAISE EXCEPTION 'invalid tenant identity' USING ERRCODE = '22023';
    END IF;
    IF p_status NOT IN ('pending', 'active', 'suspended') OR NULLIF(btrim(p_plan), '') IS NULL THEN
        RAISE EXCEPTION 'invalid tenant status or plan' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.tenants (slug, name, status, plan)
    VALUES (p_slug, btrim(p_name), p_status, btrim(p_plan))
    ON CONFLICT (slug) DO UPDATE SET
        name = EXCLUDED.name,
        status = EXCLUDED.status,
        plan = EXCLUDED.plan,
        updated_at = now();
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_set_tenant_phone_number(
    p_phone_number TEXT,
    p_tenant_id TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_phone_number !~ '^\+[1-9][0-9]{1,14}$' THEN
        RAISE EXCEPTION 'phone number must be E.164' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.tenant_phone_numbers (phone_number, tenant_id)
    VALUES (p_phone_number, p_tenant_id)
    ON CONFLICT (phone_number) DO UPDATE SET tenant_id = EXCLUDED.tenant_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_remove_tenant_phone_number(p_phone_number TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM public.tenant_phone_numbers WHERE phone_number = p_phone_number;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count > 0;
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_resolve_tenant_by_phone(p_phone_number TEXT)
RETURNS TEXT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT t.slug
    FROM public.tenant_phone_numbers AS p
    JOIN public.tenants AS t ON t.slug = p.tenant_id
    WHERE p.phone_number = p_phone_number
      AND t.status = 'active'
$$;

CREATE OR REPLACE FUNCTION public.platform_list_active_tenants()
RETURNS SETOF TEXT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT slug FROM public.tenants WHERE status = 'active' ORDER BY slug
$$;

CREATE OR REPLACE FUNCTION public.platform_list_tenants()
RETURNS TABLE (slug TEXT, name TEXT, status TEXT, plan TEXT, created_at TIMESTAMPTZ)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT t.slug, t.name, t.status, t.plan, t.created_at
    FROM public.tenants AS t
    ORDER BY t.slug
$$;

CREATE OR REPLACE FUNCTION public.platform_list_tenant_phone_numbers()
RETURNS TABLE (phone_number TEXT, tenant_id TEXT, created_at TIMESTAMPTZ)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT p.phone_number, p.tenant_id, p.created_at
    FROM public.tenant_phone_numbers AS p
    ORDER BY p.phone_number
$$;

ALTER FUNCTION public.platform_ensure_tenant(TEXT) OWNER TO propview_registry_owner;
ALTER FUNCTION public.platform_upsert_tenant(TEXT, TEXT, TEXT, TEXT) OWNER TO propview_registry_owner;
ALTER FUNCTION public.platform_set_tenant_phone_number(TEXT, TEXT) OWNER TO propview_registry_owner;
ALTER FUNCTION public.platform_remove_tenant_phone_number(TEXT) OWNER TO propview_registry_owner;
ALTER FUNCTION public.platform_resolve_tenant_by_phone(TEXT) OWNER TO propview_registry_owner;
ALTER FUNCTION public.platform_list_active_tenants() OWNER TO propview_registry_owner;
ALTER FUNCTION public.platform_list_tenants() OWNER TO propview_registry_owner;
ALTER FUNCTION public.platform_list_tenant_phone_numbers() OWNER TO propview_registry_owner;

REVOKE ALL ON FUNCTION public.platform_ensure_tenant(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_upsert_tenant(TEXT, TEXT, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_set_tenant_phone_number(TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_remove_tenant_phone_number(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_resolve_tenant_by_phone(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_list_active_tenants() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_list_tenants() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_list_tenant_phone_numbers() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.platform_ensure_tenant(TEXT) TO propview_app;
GRANT EXECUTE ON FUNCTION public.platform_upsert_tenant(TEXT, TEXT, TEXT, TEXT) TO propview_app;
GRANT EXECUTE ON FUNCTION public.platform_set_tenant_phone_number(TEXT, TEXT) TO propview_app;
GRANT EXECUTE ON FUNCTION public.platform_remove_tenant_phone_number(TEXT) TO propview_app;
GRANT EXECUTE ON FUNCTION public.platform_resolve_tenant_by_phone(TEXT) TO propview_app;
GRANT EXECUTE ON FUNCTION public.platform_list_active_tenants() TO propview_app;
GRANT EXECUTE ON FUNCTION public.platform_list_tenants() TO propview_app;
GRANT EXECUTE ON FUNCTION public.platform_list_tenant_phone_numbers() TO propview_app;

ALTER TABLE tenant_settings
    ADD COLUMN IF NOT EXISTS broker_transfer_number TEXT,
    ADD COLUMN IF NOT EXISTS sms_sender_number TEXT,
    ADD COLUMN IF NOT EXISTS whatsapp_sender_number TEXT,
    ADD COLUMN IF NOT EXISTS time_zone TEXT,
    ADD COLUMN IF NOT EXISTS business_hours_start_hour SMALLINT,
    ADD COLUMN IF NOT EXISTS business_hours_end_hour SMALLINT,
    ADD COLUMN IF NOT EXISTS voice_name TEXT,
    ADD COLUMN IF NOT EXISTS greeting TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tenant_settings_business_hours_start_check'
    ) THEN
        ALTER TABLE tenant_settings
            ADD CONSTRAINT tenant_settings_business_hours_start_check
            CHECK (business_hours_start_hour IS NULL OR business_hours_start_hour BETWEEN 0 AND 23);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tenant_settings_business_hours_end_check'
    ) THEN
        ALTER TABLE tenant_settings
            ADD CONSTRAINT tenant_settings_business_hours_end_check
            CHECK (business_hours_end_hour IS NULL OR business_hours_end_hour BETWEEN 1 AND 24);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tenant_settings_business_hours_pair_check'
    ) THEN
        ALTER TABLE tenant_settings
            ADD CONSTRAINT tenant_settings_business_hours_pair_check
            CHECK (
                (business_hours_start_hour IS NULL AND business_hours_end_hour IS NULL)
                OR (
                    business_hours_start_hour IS NOT NULL
                    AND business_hours_end_hour IS NOT NULL
                    AND business_hours_start_hour < business_hours_end_hour
                )
            );
    END IF;
END $$;

CREATE TABLE usage_events (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    event_type    TEXT NOT NULL CHECK (event_type IN ('call', 'sms', 'whatsapp')),
    source_id     TEXT NOT NULL,
    quantity      INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    metadata      JSONB NOT NULL DEFAULT '{}',
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, event_type, source_id)
);

CREATE INDEX idx_usage_events_tenant_occurred
    ON usage_events (tenant_id, occurred_at);

ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON usage_events
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

GRANT SELECT, INSERT ON usage_events TO propview_app;
GRANT USAGE, SELECT ON SEQUENCE usage_events_id_seq TO propview_app;

CREATE OR REPLACE VIEW monthly_usage
WITH (security_invoker = true)
AS
SELECT
    tenant_id,
    date_trunc('month', occurred_at) AS month,
    event_type,
    COUNT(*)::BIGINT AS event_count,
    SUM(quantity)::BIGINT AS units
FROM usage_events
GROUP BY tenant_id, date_trunc('month', occurred_at), event_type;

GRANT SELECT ON monthly_usage TO propview_app;
