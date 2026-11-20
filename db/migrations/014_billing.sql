-- Phase 5: provider-neutral billing catalog, tenant subscriptions, and
-- idempotent payment-provider webhook events. Razorpay identifiers are
-- configured per catalog plan and must refer to test-mode plans.

CREATE TABLE billing_plans (
    slug                 TEXT PRIMARY KEY
                         CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    display_name         TEXT NOT NULL CHECK (length(btrim(display_name)) > 0),
    description          TEXT,
    price_minor          BIGINT CHECK (price_minor IS NULL OR price_minor >= 0),
    currency             TEXT CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    calls_limit          INTEGER CHECK (calls_limit IS NULL OR calls_limit >= 0),
    sms_limit            INTEGER CHECK (sms_limit IS NULL OR sms_limit >= 0),
    whatsapp_limit       INTEGER CHECK (whatsapp_limit IS NULL OR whatsapp_limit >= 0),
    razorpay_plan_id     TEXT UNIQUE,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((price_minor IS NULL) = (currency IS NULL))
);

-- Catalog writes are deployment/operator-managed; tenant application
-- credentials may only read it and cannot alter prices or plan limits.
REVOKE INSERT, UPDATE, DELETE ON billing_plans FROM propview_app;
GRANT SELECT ON billing_plans TO propview_app;

CREATE TABLE billing_subscriptions (
    id                          BIGSERIAL PRIMARY KEY,
    tenant_id                   TEXT NOT NULL,
    plan_slug                   TEXT NOT NULL,
    plan_name                   TEXT NOT NULL,
    provider                    TEXT NOT NULL CHECK (provider = 'razorpay'),
    provider_subscription_id    TEXT NOT NULL UNIQUE,
    status                      TEXT NOT NULL CHECK (status IN (
                                    'created', 'authenticated', 'active', 'pending',
                                    'halted', 'paused', 'cancelled', 'completed',
                                    'expired', 'failed'
                                )),
    checkout_url                TEXT,
    current_period_start         TIMESTAMPTZ,
    current_period_end           TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX billing_subscriptions_tenant_created_idx
    ON billing_subscriptions (tenant_id, created_at DESC);
CREATE UNIQUE INDEX billing_subscriptions_one_open_per_tenant_idx
    ON billing_subscriptions (tenant_id)
    WHERE status IN ('created', 'authenticated', 'active', 'pending', 'halted', 'paused');

CREATE TABLE billing_webhook_events (
    id                          BIGSERIAL PRIMARY KEY,
    tenant_id                   TEXT NOT NULL,
    provider_event_id           TEXT NOT NULL,
    event_name                  TEXT NOT NULL,
    provider_subscription_id    TEXT NOT NULL,
    received_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at                TIMESTAMPTZ,
    UNIQUE (tenant_id, provider_event_id)
);

CREATE INDEX billing_webhook_events_subscription_idx
    ON billing_webhook_events (tenant_id, provider_subscription_id, received_at DESC);

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['billing_subscriptions', 'billing_webhook_events']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I
            USING (tenant_id = current_setting(''app.tenant_id'', true))
            WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', tbl);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO propview_app', tbl);
    END LOOP;
END $$;

GRANT USAGE, SELECT ON SEQUENCE
    billing_subscriptions_id_seq, billing_webhook_events_id_seq
    TO propview_app;
