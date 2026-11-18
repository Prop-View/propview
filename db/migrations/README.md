# Database Migrations

Owner: Aahil (Dev A)

PostgreSQL + pgvector schema for listings, projects, and the knowledge
base. `apply_migrations.py` runs every `*.sql` file here in order,
tracking what's applied in a `schema_migrations` table so re-running is
safe.

## Local setup

```bash
brew install postgresql@17 pgvector   # pgvector's bottle targets 17/18, not 16
brew services start postgresql@17
createdb propview_dev

pip install -r requirements.txt
DATABASE_URL=postgresql://localhost/propview_dev python apply_migrations.py
# or: cp .env.example .env (edit DATABASE_URL if the default's wrong), then just:
python apply_migrations.py
```

(`../../scripts/setup_dev_env.sh` does the venv + `.env` setup for the
whole repo in one step, if you haven't already.)

Run `apply_migrations.py` as the cluster superuser (default local setup) —
`000_create_app_role.sql` needs superuser privileges to create the
`propview_app` role. **Application code must connect as `propview_app`,
not the superuser** — see the RLS section below for why.

**Verified** 2026-09-03 against a real local instance: schema applies
cleanly, `CREATE EXTENSION vector` succeeds (v0.8.6), a `search_properties`-
style filtered query returns correct results, and a real cosine-distance
nearest-neighbor query against `knowledge_base_chunks` correctly finds the
closest embedding.

## Schema

- **`projects`** — a development/building a property may belong to.
- **`properties`** — the actual listings: address, type, beds/baths/sqft,
  price, status, amenities (JSONB), all indexed for the filter patterns
  `search_properties` (PROP-304) will use.
- **`knowledge_base_chunks`** — pgvector-backed RAG source (brochures,
  FAQs, policies, transcripts). `embedding` is `vector(768)`, matching
  Gemini's `text-embedding-004`; the Admin API now wraps the shared
  ingestion helpers for document uploads. A live Gemini embedding
  request through that endpoint remains unverified.
- **`contacts` / `leads` / `appointments` / `interactions`** (PROP-401) —
  the CRM tables. `leads`' BANT fields (intent, budget, timeline,
  decision_maker) follow `services/prompts/bant_conversation_design.md`
  and are nullable throughout — the plan targets >80% of *fields*
  captured, not full qualification on every call. `interactions.call_id`
  ties a durable record back to `services/orchestrator/session_store.py`'s
  ephemeral Redis session.
- **`follow_ups`** (`008_follow_ups.sql`, a post-plan addition — see
  `services/follow-up-manager/README.md`) — the dedup ledger for
  `followup_scan.py`'s no-show/nurture SMS passes. One partial unique
  index per `kind` (`appointment_id` for `'no_show'`, `lead_id` for
  `'nurture'`) makes re-running that script safe.
- **Structured conversation data** (`009_conversation_store.sql`) stores
  per-turn transcripts, tool invocations, and call analytics, each
  protected by RLS. `010_conversation_outcome_values.sql` keeps only
  outcomes the orchestrator can resolve (`booked`, `qualified`,
  `transferred`, `unknown`); any legacy `dropped`/`nurture` values are
  normalized to `unknown`.
- **Phase 2 tenant operations** (`011_tenant_registry_settings_usage.sql`)
  adds platform-level `tenants` and `tenant_phone_numbers` registries,
  tenant operational settings, and the RLS-protected `usage_events`
  ledger with the `monthly_usage` view. Registry tables intentionally do
  not use tenant RLS; `propview_app` has no direct table grants and can
  access them only through narrowly scoped `SECURITY DEFINER` functions
  owned by `propview_registry_owner`, which has no tenant-data privileges.
  `usage_events`, like other tenant-owned data, has `tenant_id`, forced
  RLS, and must be accessed through `tenant_connection()`.
- **Phase 3 account and product API** (`012_accounts_product_api.sql`)
  adds RLS-protected account users/sessions/tokens, tenant audit records,
  webhook configuration and delivery log, and email outbox tables.
  Registry signup/activation uses restricted `SECURITY DEFINER`
  functions; application code receives no direct registry-table access.
  Database triggers enqueue the supported webhook events and hot-lead /
  appointment emails.
- **Email trigger correction** (`013_product_email_trigger_fix.sql`)
  keeps table-specific `NEW` record fields inside their matching trigger
  branches. The original shared trigger referenced `NEW.priority` while
  processing appointment rows, causing real inserts to fail; this
  append-only migration replaces the function without rewriting the
  already-applied `012` migration.
- **Phase 5 billing** (`014_billing.sql`) adds the platform-managed
  `billing_plans` catalog (read-only to `propview_app`) and tenant-RLS
  `billing_subscriptions` and `billing_webhook_events` tables. Plan prices,
  quotas, and Razorpay test plan IDs are intentionally not invented or
  seeded; the platform operator configures them in the catalog before
  checkout can be offered.

- **Row-Level Security** (PROP-601, `004_row_level_security.sql`) enforces
  `tenant_id` isolation on every table above, fail-closed (a connection
  that never sets `app.tenant_id` sees zero rows, not all rows).

  **Critical, only found by testing this for real**: Postgres always
  bypasses RLS for superuser roles, `FORCE ROW LEVEL SECURITY`
  notwithstanding. The initial local dev role is a superuser by default —
  RLS silently did nothing under it (all tenants saw all rows) until
  switching to `propview_app` (`000_create_app_role.sql`, `NOSUPERUSER
  NOBYPASSRLS`), after which isolation was verified correct. **Any code
  connecting to this database that needs RLS enforced must use
  `propview_app`, never a superuser.**

  Application code must call
  `SELECT set_config('app.tenant_id', $1, true)` (transaction-local)
  before querying — see `services/tool-router/db.py`'s
  `tenant_connection()` for the pattern.

Migrations are append-only (the current sequence follows `014`); do not
edit an already-applied migration. On a database where a migration has
already been marked applied, do not rerun it manually. As with other new
`BIGSERIAL` tables, the app-role sequence grant is explicitly included in
`011`; a long-lived local database may still need the one-time
`GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO propview_app;`
repair documented above if it predates the default-privilege fix.

## Definition of Done (from Sprint Plan)

- [x] Schema designed and applied against a real PostgreSQL + pgvector instance.
- [x] Verified: property filter query and vector similarity search both correct.
- [x] PROP-401 CRM schema: contacts/leads/appointments/interactions, verified
      against real Postgres (insert flow, CHECK constraint rejection,
      cascade deletes, unique-phone-per-tenant), 4/4 pytest passing.
- [x] PROP-601 Row-Level Security: verified against real Postgres using the
      correct non-superuser role — fail-closed with no tenant set, and
      genuine cross-tenant isolation confirmed (see the critical finding
      above). Tool Router updated to set tenant context per request;
      its full test suite (12 cases) still passes with RLS enforced.
