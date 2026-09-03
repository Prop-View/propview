# PROP-303 / PROP-304 / PROP-307 / PROP-402: Tool Router

FastAPI service dispatching S2S function-call payloads (tool name + args,
matching Gemini's tool-calling protocol) to real database-backed handlers.

## Setup

```bash
cd services/tool-router
pip install -r requirements.txt
cp .env.example .env   # DATABASE_URL (propview_app role, not superuser) + GEMINI_API_KEY for search_knowledge_base
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

POST /tools/call
  {"name": "search_knowledge_base", "args": {"query": "how much are the HOA dues?"}}
  -> {"name": "search_knowledge_base", "result": [{"content": "...", "source_type": "faq", "source_name": "..."}]}
  -- semantic search over db/ingestion's (PROP-302) pgvector-embedded
  -- FAQs/brochures/policies. Embeds the query with the same model +
  -- dimensionality ingestion uses; a mismatch there would silently
  -- degrade to poor/random matches, not an error (see the module docstring).

POST /tools/call
  {"name": "update_lead_qualification", "args": {"intent": "buy", "budget_min": 500000, "timeline": "immediate"},
   "tenant_id": "default", "caller_phone_number": "+15125550100", "lead_id": null}
  -> {"name": "update_lead_qualification",
      "result": {"lead_id": 7, "contact_id": 3, "priority": "high", "captured": {...full leads row...}}}
  -- PROP-402/405: upserts the caller's contacts row (by phone number) and
  -- their leads row (by lead_id if given, else creates one -- see below),
  -- re-scoring priority (../../lead-engine/lead_scoring.py) every call.
  -- caller_phone_number/lead_id are call-scoped context the orchestrator
  -- supplies directly (like tenant_id) -- not part of Gemini's function
  -- schema, see tools/update_lead_qualification.py's docstring.

GET /tools/schema   -- JSON schema per tool, the source for the Gemini
                        FunctionDeclarations services/orchestrator/tool_client.py
                        builds (no hand-duplicated schemas)
GET /health
```

## BANT extraction (PROP-402) & lead scoring (PROP-405)

`update_lead_qualification` **is** PROP-402's "state extraction parser" —
not a separate NLP pass over the transcript. Gemini calls it directly as
it learns BANT facts during natural conversation (the same mechanism
`search_properties` already uses), per the field-by-field triggers in
`../prompts/bant_conversation_design.md` and the instructions in
`../prompts/system_prompt.py`. A standalone post-hoc parser would
duplicate extraction Gemini is already doing to decide what to say next.

Every call re-scores the lead via `../lead-engine/lead_scoring.py`
(PROP-405) — a small ordered rules table over `intent`/`budget`/`timeline`
(High: urgent timeline + budget + real intent; Low: browsing/exploring or
nothing captured yet; Medium in between) — so `leads.priority` always
reflects the fullest picture captured so far, not a one-time snapshot.

Repeated calls within the same phone call reuse the same `leads` row via
`lead_id` (threaded by the orchestrator, see its README) rather than
creating a new lead per field learned; calls without a `lead_id` (a fresh
call, or a repeat caller with no active `lead_id` yet) create a new lead
for that contact.

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

**Verified passing** 2026-09-03: all 13 cases against a real local
Postgres, connected as `propview_app` (not the superuser, so RLS is
genuinely enforced, not silently bypassed) — correct filtering, tenant
isolation at both the app-query and RLS layers, JSONB/Decimal correctly
normalized to JSON-safe types (`amenities` as a list, `price` as a
number), invalid enum rejected with 422, the SQL injection attempt, and
`search_knowledge_base` returning a real semantic match for a query with
no words in common with the source chunk.

**Verified passing** 2026-09-04: 5 more cases for `update_lead_qualification`
against the same real Postgres — missing `caller_phone_number` rejected
with 422, a fresh call creates both a `contacts` and `leads` row with the
correct rules-engine priority, a second call with the same phone number
reuses the `contacts` row, passing `lead_id` back updates the same `leads`
row instead of creating a new one (re-scoring as more fields arrive), and
omitted fields never overwrite already-captured ones (`COALESCE`, not a
blind overwrite).

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
- [x] BANT qualification state extraction (PROP-402) as a Gemini tool call
      — see dedicated section above. Verified against real Postgres; not
      yet live-verified against a real Gemini call (unlike
      `search_properties`) — `../orchestrator/README.md` tracks this.
- [x] Lead scoring rules engine, High/Medium/Low (PROP-405) — see
      `../lead-engine/lead_scoring.py`, 9/9 unit tests passing.
