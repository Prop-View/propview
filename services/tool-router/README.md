# PROP-303 / PROP-304 / PROP-307: Tool Router

FastAPI service dispatching S2S function-call payloads (tool name + args,
matching Gemini's tool-calling protocol) to real database-backed handlers.

## Setup

```bash
cd services/tool-router
pip install -r requirements.txt
cp .env.example .env   # DATABASE_URL, defaults to local dev
uvicorn main:app --reload
```

Requires `db/migrations/` applied first (see its README).

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
DATABASE_URL=postgresql://localhost/propview_dev python -m pytest tests/ -v
```

**Verified passing** 2026-09-03: all 11 cases against a real local
Postgres — correct filtering, tenant isolation, JSONB/Decimal correctly
normalized to JSON-safe types (`amenities` as a list, `price` as a
number), invalid enum rejected with 422, and the SQL injection attempt.

## Definition of Done (from Sprint Plan)

- [x] FastAPI Tool Router service handling function-call payloads (PROP-303).
- [x] `search_properties` tool schema & SQL execution logic (PROP-304).
- [x] SQL injection prevention & schema parameter validation (PROP-307).
- [ ] Registered as an actual Gemini tool in the orchestrator (Sprint 3/4
      wiring — the schema endpoint exists for this, not yet consumed).
- [ ] PROP-306 (latency + **context injection** integration testing) is
      only partially covered: these tests exercise the real DB path
      end to end, but "context injection" specifically means verifying
      tool results actually land in Gemini's conversation context, which
      isn't possible to test until the orchestrator-to-Gemini tool wiring
      above exists. Not marked done.
- [ ] Latency budget (plan: <900ms including DB query, or filler speech
      within 300ms) not yet measured under load.
