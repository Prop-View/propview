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
```

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
  Gemini's `text-embedding-004` — **must match whatever model PROP-302's
  ingestion script (not yet built) actually uses**, or inserts will fail
  loudly (pgvector enforces the column's fixed dimension).
- **`contacts` / `leads` / `appointments` / `interactions`** (PROP-401) —
  the CRM tables. `leads`' BANT fields (intent, budget, timeline,
  decision_maker) follow `services/prompts/bant_conversation_design.md`
  and are nullable throughout — the plan targets >80% of *fields*
  captured, not full qualification on every call. `interactions.call_id`
  ties a durable record back to `services/orchestrator/session_store.py`'s
  ephemeral Redis session.

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
