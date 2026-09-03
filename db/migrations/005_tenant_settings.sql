-- PROP-602: Tenant settings -- calendar integration credentials per tenant.
-- Credentials are stored encrypted (see services/admin-api/crypto.py);
-- this column only ever holds ciphertext.

CREATE TABLE IF NOT EXISTS tenant_settings (
    tenant_id                       TEXT PRIMARY KEY,
    calendar_provider               TEXT,
    encrypted_calendar_credentials  BYTEA,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE tenant_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_settings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tenant_settings;
CREATE POLICY tenant_isolation ON tenant_settings
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
