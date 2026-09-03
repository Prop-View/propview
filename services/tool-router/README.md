# PROP-303 / PROP-304 / PROP-307: Tool Router

FastAPI service dispatching S2S function-call payloads (tool name + args,
matching Gemini's tool-calling protocol) to real database-backed handlers.

## Setup

```bash
cd services/tool-router
pip install -r requirements.txt
cp .env.example .env   # DATABASE_URL -- must be the propview_app role, NOT the superuser (see below)
uvicorn main:app --reload
```

Requires `db/migrations/` applied first (see its README).

## Row-Level Security (PROP-601)

Every query runs inside `db.tenant_connection()`, which sets
`app.tenant_id` for the transaction before the handler touches the
database — required because `db/migrations/004_row_level_security.sql`'s
RLS policies are fail-closed. **`DATABASE_URL` must point at the
`propview_app` role** (`db/migrations/000_create_app_role.sql`), not a
superuser — Postgres always bypasses RLS for superusers, so connecting as
one would make this isolation silently do nothing (found by testing it,
not assumed — see `db/migrations/README.md`).

## API

```
POST /tools/call
  {"name": "search_properties", "args": {"city": "Austin", "min_beds": 3, "max_price": 550000}, "tenant_id": "default"}
  -> {"name": "search_properties", "result": [...]}

POST /tools/call
  {"name": "get_property_details", "args": {"property_id": 42}}
  -> {"name": "get_property_details", "result": {...} | null}

GET /tools/schema   -- JSON schema per tool, source for the Gemini
                        FunctionDeclaration configs the orchestrator will
                        register (Sprint 3/4 wiring, not built yet)
GET /health
```

## SQL injection prevention (PROP-307)

Every user-supplied value goes through asyncpg's `$n` positional
parameters — true wire-protocol parameterization, not string escaping or
sanitization. Column names and query structure are fixed strings this
code controls and are never derived from request input. Enum-like fields
(`property_type`, `status`) are additionally constrained by Pydantic
`Literal` types, rejecting invalid values with a 422 before a query is
ever built.

**Verified** with a real attempted injection payload
(`city: "Austin'; DROP TABLE properties; --"`) — see
`tests/test_tool_router.py::test_search_properties_sql_injection_attempt_is_inert`.
It's treated as a literal (non-matching) string; the table survives.

## Testing

```bash
DATABASE_URL=postgresql://propview_app:devpassword@localhost/propview_dev python -m pytest tests/ -v
```

**Verified passing** 2026-09-03: all 12 cases against a real local
Postgres, connected as `propview_app` (not the superuser, so RLS is
genuinely enforced, not silently bypassed) — correct filtering, tenant
isolation at both the app-query and RLS layers, JSONB/Decimal correctly
normalized to JSON-safe types (`amenities` as a list, `price` as a
number), invalid enum rejected with 422, and the SQL injection attempt.

## Definition of Done (from Sprint Plan)

- [x] FastAPI Tool Router service handling function-call payloads (PROP-303).
- [x] `search_properties` tool schema & SQL execution logic (PROP-304).
- [x] SQL injection prevention & schema parameter validation (PROP-307).
- [x] Tenant isolation enforced by Postgres RLS, not just app-level
      filtering, verified with a real cross-tenant test (PROP-601).
- [x] Registered as an actual Gemini tool in the orchestrator —
      `services/orchestrator/tool_client.py` builds `FunctionDeclaration`s
      straight from `/tools/schema` (single source of truth) and dispatches
      calls to `/tools/call`. **Live-verified** 2026-09-03: a real Gemini
      session correctly called `search_properties` from a natural-language
      query and spoke a response using the real result.
- [x] PROP-306's "context injection" half is now verifiable and passing —
      the live test above confirms tool results actually land in Gemini's
      conversation context (the spoken response correctly referenced the
      returned listings' price and address). The "latency" half of
      PROP-306 is still open (see below).
- [ ] Latency budget (plan: <900ms including DB query, or filler speech
      within 300ms) not yet measured under load.
