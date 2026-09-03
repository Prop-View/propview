-- PROP-601: Row-Level Security for tenant_id isolation.
--
-- Fail-CLOSED by design: current_setting('app.tenant_id', true) returns
-- NULL if unset, and `tenant_id = NULL` is never true in SQL, so a
-- connection that forgets to set the tenant context sees zero rows,
-- not all rows. FORCE ROW LEVEL SECURITY so even the table owner
-- (which the app connects as, in this dev setup) is subject to it --
-- without FORCE, RLS silently does not apply to the owner.
--
-- Application code must call:
--   SELECT set_config('app.tenant_id', $1, true)   -- 'true' = transaction-local
-- inside a transaction before querying. See services/tool-router/db.py's
-- tenant_connection() for the pattern.

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'projects', 'properties', 'knowledge_base_chunks',
        'contacts', 'leads', 'appointments', 'interactions'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I
                USING (tenant_id = current_setting(''app.tenant_id'', true))
                WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
            tbl
        );
    END LOOP;
END $$;
