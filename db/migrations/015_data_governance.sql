-- Phase 6: per-tenant retention policy and auditable consent records.

CREATE UNIQUE INDEX contacts_tenant_id_id_unique ON contacts (tenant_id, id);

CREATE TABLE tenant_data_retention (
    tenant_id       TEXT PRIMARY KEY,
    retention_days  INTEGER NOT NULL CHECK (retention_days > 0),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE consent_records (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    contact_id      BIGINT,
    call_id         TEXT,
    purpose         TEXT NOT NULL CHECK (
        purpose IN ('recording', 'data_processing', 'marketing', 'other')
    ),
    granted         BOOLEAN NOT NULL,
    capture_method  TEXT NOT NULL CHECK (
        capture_method IN ('verbal', 'web', 'written', 'other')
    ),
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, contact_id)
        REFERENCES contacts (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX consent_records_tenant_captured_idx
    ON consent_records (tenant_id, captured_at DESC);
CREATE INDEX consent_records_contact_idx
    ON consent_records (tenant_id, contact_id);
CREATE INDEX consent_records_call_idx
    ON consent_records (tenant_id, call_id)
    WHERE call_id IS NOT NULL;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['tenant_data_retention', 'consent_records']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I
                USING (tenant_id = current_setting(''app.tenant_id'', true))
                WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
            tbl
        );
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO propview_app',
            tbl
        );
    END LOOP;
END $$;

GRANT USAGE, SELECT ON SEQUENCE consent_records_id_seq TO propview_app;
