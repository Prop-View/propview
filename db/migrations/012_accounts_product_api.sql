-- Phase 3: agency accounts, account authentication, audit, webhooks, and
-- notification outboxes. Tenant-owned rows use the same fail-closed RLS
-- policy as the CRM tables and are accessed with tenant_connection().

ALTER TABLE leads ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE tenant_settings
    ADD COLUMN IF NOT EXISTS google_oauth_state_hash TEXT,
    ADD COLUMN IF NOT EXISTS google_oauth_state_expires_at TIMESTAMPTZ;

CREATE TABLE account_users (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           TEXT NOT NULL,
    email               TEXT NOT NULL CHECK (email = lower(btrim(email))),
    display_name        TEXT NOT NULL CHECK (length(btrim(display_name)) > 0),
    password_hash       TEXT NOT NULL,
    role                TEXT NOT NULL CHECK (role IN ('owner', 'agent')),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    email_verified_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);

CREATE INDEX account_users_tenant_role_idx ON account_users (tenant_id, role);

CREATE TABLE account_sessions (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    user_id     BIGINT NOT NULL REFERENCES account_users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX account_sessions_user_idx ON account_sessions (tenant_id, user_id);
CREATE INDEX account_sessions_expiry_idx ON account_sessions (expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE account_tokens (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    user_id     BIGINT NOT NULL REFERENCES account_users(id) ON DELETE CASCADE,
    purpose     TEXT NOT NULL CHECK (purpose IN ('email_verification', 'password_reset', 'team_invite')),
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX account_tokens_user_purpose_idx ON account_tokens (tenant_id, user_id, purpose);

CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    actor_user_id   BIGINT REFERENCES account_users(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX audit_log_tenant_created_idx ON audit_log (tenant_id, created_at DESC);

CREATE TABLE tenant_webhooks (
    id                      BIGSERIAL PRIMARY KEY,
    tenant_id               TEXT NOT NULL,
    target_url              TEXT NOT NULL CHECK (target_url ~ '^https://'),
    encrypted_signing_secret BYTEA NOT NULL,
    events                  TEXT[] NOT NULL DEFAULT ARRAY[
                                'lead.created', 'lead.qualified',
                                'appointment.booked', 'call.completed'
                            ],
    is_enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (events <@ ARRAY[
        'lead.created', 'lead.qualified', 'appointment.booked', 'call.completed'
    ]::TEXT[])
);

CREATE INDEX tenant_webhooks_enabled_idx ON tenant_webhooks (tenant_id, id)
    WHERE is_enabled;

CREATE TABLE webhook_deliveries (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           TEXT NOT NULL,
    webhook_id          BIGINT NOT NULL REFERENCES tenant_webhooks(id) ON DELETE CASCADE,
    event_name          TEXT NOT NULL CHECK (event_name IN (
                            'lead.created', 'lead.qualified',
                            'appointment.booked', 'call.completed'
                        )),
    payload             JSONB NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'delivered', 'failed')),
    attempts            INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_expires_at    TIMESTAMPTZ,
    last_status_code    INTEGER,
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at        TIMESTAMPTZ
);

CREATE INDEX webhook_deliveries_due_idx
    ON webhook_deliveries (tenant_id, next_attempt_at, id)
    WHERE status = 'pending';

CREATE TABLE email_outbox (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           TEXT NOT NULL,
    recipient           TEXT NOT NULL,
    subject             TEXT NOT NULL,
    body                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'sent', 'failed')),
    attempts            INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_expires_at    TIMESTAMPTZ,
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at             TIMESTAMPTZ
);

CREATE INDEX email_outbox_due_idx
    ON email_outbox (tenant_id, next_attempt_at, id)
    WHERE status = 'pending';

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'account_users', 'account_sessions', 'account_tokens', 'audit_log',
        'tenant_webhooks', 'webhook_deliveries', 'email_outbox'
    ]
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
    account_users_id_seq, account_sessions_id_seq, account_tokens_id_seq,
    audit_log_id_seq, tenant_webhooks_id_seq, webhook_deliveries_id_seq,
    email_outbox_id_seq TO propview_app;

GRANT SELECT, INSERT, UPDATE ON leads TO propview_app;
GRANT UPDATE, DELETE ON properties TO propview_app;
GRANT UPDATE ON appointments TO propview_app;
GRANT USAGE, SELECT ON SEQUENCE tenant_webhooks_id_seq TO propview_app;

-- Self-service signup may create a pending tenant, but cannot activate,
-- modify, or take ownership of an existing registry entry.
CREATE OR REPLACE FUNCTION public.platform_register_tenant(p_slug TEXT, p_name TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_slug !~ '^[a-z0-9][a-z0-9-]{0,62}$'
       OR NULLIF(btrim(p_name), '') IS NULL THEN
        RAISE EXCEPTION 'invalid tenant identity' USING ERRCODE = '22023';
    END IF;
    INSERT INTO public.tenants (slug, name, status, plan)
    VALUES (p_slug, btrim(p_name), 'pending', 'starter');
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_activate_tenant(p_slug TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    changed INTEGER;
BEGIN
    UPDATE public.tenants
    SET status = 'active', updated_at = now()
    WHERE slug = p_slug AND status = 'pending';
    GET DIAGNOSTICS changed = ROW_COUNT;
    RETURN changed > 0;
END;
$$;

ALTER FUNCTION public.platform_register_tenant(TEXT, TEXT) OWNER TO propview_registry_owner;
ALTER FUNCTION public.platform_activate_tenant(TEXT) OWNER TO propview_registry_owner;
REVOKE ALL ON FUNCTION public.platform_register_tenant(TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_activate_tenant(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.platform_register_tenant(TEXT, TEXT) TO propview_app;
GRANT EXECUTE ON FUNCTION public.platform_activate_tenant(TEXT) TO propview_app;

CREATE OR REPLACE FUNCTION public.enqueue_product_events()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    event_name TEXT;
    event_payload JSONB;
BEGIN
    IF TG_TABLE_NAME = 'leads' THEN
        IF TG_OP = 'INSERT' THEN
            event_name := 'lead.created';
        ELSIF OLD.status IS DISTINCT FROM NEW.status AND NEW.status = 'qualified' THEN
            event_name := 'lead.qualified';
        END IF;
        event_payload := jsonb_build_object(
            'lead_id', NEW.id,
            'status', NEW.status,
            'priority', NEW.priority,
            'created_at', NEW.created_at
        );
    ELSIF TG_TABLE_NAME = 'appointments' AND TG_OP = 'INSERT' THEN
        event_name := 'appointment.booked';
        event_payload := jsonb_build_object(
            'appointment_id', NEW.id,
            'lead_id', NEW.lead_id,
            'property_id', NEW.property_id,
            'scheduled_at', NEW.scheduled_at,
            'created_at', NEW.created_at
        );
    ELSIF TG_TABLE_NAME = 'interactions' AND TG_OP = 'INSERT' AND NEW.channel = 'voice' THEN
        event_name := 'call.completed';
        event_payload := jsonb_build_object(
            'call_id', NEW.call_id,
            'lead_id', NEW.lead_id,
            'duration_seconds', NEW.duration_seconds,
            'outcome', NEW.outcome,
            'created_at', NEW.created_at
        );
    END IF;

    IF event_name IS NOT NULL THEN
        INSERT INTO public.webhook_deliveries (tenant_id, webhook_id, event_name, payload)
        SELECT NEW.tenant_id, hook.id, event_name, event_payload
        FROM public.tenant_webhooks AS hook
        WHERE hook.tenant_id = NEW.tenant_id
          AND hook.is_enabled
          AND event_name = ANY(hook.events);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER leads_enqueue_product_events
AFTER INSERT OR UPDATE OF status ON leads
FOR EACH ROW EXECUTE FUNCTION public.enqueue_product_events();

CREATE TRIGGER appointments_enqueue_product_events
AFTER INSERT ON appointments
FOR EACH ROW EXECUTE FUNCTION public.enqueue_product_events();

CREATE TRIGGER interactions_enqueue_product_events
AFTER INSERT ON interactions
FOR EACH ROW EXECUTE FUNCTION public.enqueue_product_events();

CREATE OR REPLACE FUNCTION public.enqueue_product_emails()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    recipient_email TEXT;
    lead_label TEXT;
BEGIN
    IF TG_TABLE_NAME = 'leads' AND (
        (TG_OP = 'INSERT' AND NEW.priority = 'high')
        OR (TG_OP = 'UPDATE' AND OLD.priority IS DISTINCT FROM NEW.priority
            AND NEW.priority = 'high')
    ) THEN
        lead_label := format('Lead %s', NEW.id);
        FOR recipient_email IN
            SELECT email FROM public.account_users
            WHERE tenant_id = NEW.tenant_id AND is_active AND email_verified_at IS NOT NULL
              AND role = 'agent'
        LOOP
            INSERT INTO public.email_outbox (tenant_id, recipient, subject, body)
            VALUES (NEW.tenant_id, recipient_email, 'New high-priority Propview lead',
                    format('%s needs follow-up. Sign in to your agency dashboard to review the lead.', lead_label));
        END LOOP;
        IF NOT FOUND THEN
            FOR recipient_email IN
                SELECT email FROM public.account_users
                WHERE tenant_id = NEW.tenant_id AND is_active AND email_verified_at IS NOT NULL
                  AND role = 'owner'
            LOOP
                INSERT INTO public.email_outbox (tenant_id, recipient, subject, body)
                VALUES (NEW.tenant_id, recipient_email, 'New high-priority Propview lead',
                        format('%s needs follow-up. Sign in to your agency dashboard to review the lead.', lead_label));
            END LOOP;
        END IF;
    ELSIF TG_TABLE_NAME = 'appointments' AND TG_OP = 'INSERT'
          AND NEW.status IN ('scheduled', 'confirmed') THEN
        FOR recipient_email IN
            SELECT email FROM public.account_users
            WHERE tenant_id = NEW.tenant_id AND is_active AND email_verified_at IS NOT NULL
              AND role = 'agent' AND (NEW.agent_name IS NULL OR display_name = NEW.agent_name)
        LOOP
            INSERT INTO public.email_outbox (tenant_id, recipient, subject, body)
            VALUES (NEW.tenant_id, recipient_email, 'New Propview appointment',
                    format('Appointment %s is scheduled for %s. Sign in to your agency dashboard for details.',
                           NEW.id, NEW.scheduled_at));
        END LOOP;
        IF NOT FOUND THEN
            FOR recipient_email IN
                SELECT email FROM public.account_users
                WHERE tenant_id = NEW.tenant_id AND is_active AND email_verified_at IS NOT NULL
                  AND role = 'owner'
            LOOP
                INSERT INTO public.email_outbox (tenant_id, recipient, subject, body)
                VALUES (NEW.tenant_id, recipient_email, 'New Propview appointment',
                        format('Appointment %s is scheduled for %s. Sign in to your agency dashboard for details.',
                               NEW.id, NEW.scheduled_at));
            END LOOP;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER leads_enqueue_hot_lead_email
AFTER INSERT OR UPDATE OF priority ON leads
FOR EACH ROW EXECUTE FUNCTION public.enqueue_product_emails();

CREATE TRIGGER appointments_enqueue_notice_email
AFTER INSERT ON appointments
FOR EACH ROW EXECUTE FUNCTION public.enqueue_product_emails();
