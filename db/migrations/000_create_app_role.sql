-- Creates the application's Postgres role. MUST run before enabling RLS
-- (004): Postgres always bypasses row-level security for superusers,
-- FORCE ROW LEVEL SECURITY notwithstanding, so the app must connect as a
-- plain NOSUPERUSER/NOBYPASSRLS role or RLS silently does nothing --
-- discovered by testing this directly, not from reading the RLS docs
-- alone (see db/migrations/README.md).
--
-- Change the password before using this anywhere but local dev.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'propview_app') THEN
        CREATE ROLE propview_app LOGIN PASSWORD 'devpassword' NOSUPERUSER NOBYPASSRLS;
    END IF;
END $$;

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO propview_app', current_database());
END $$;

GRANT USAGE ON SCHEMA public TO propview_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO propview_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO propview_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO propview_app;
