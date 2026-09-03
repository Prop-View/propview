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

`tenant_id` (default `'default'`) is on every table now, with no RLS
policies yet — PROP-601 (Sprint 6) only needs to add policies on top of
this rather than restructure the schema later.

## Definition of Done (from Sprint Plan)

- [x] Schema designed and applied against a real PostgreSQL + pgvector instance.
- [x] Verified: property filter query and vector similarity search both correct.
- [x] PROP-401 CRM schema: contacts/leads/appointments/interactions, verified
      against real Postgres (insert flow, CHECK constraint rejection,
      cascade deletes, unique-phone-per-tenant), 4/4 pytest passing.
