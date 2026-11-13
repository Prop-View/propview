# PROP-602: Tenant Admin API

Multi-tenant admin endpoints for uploading listings and calendar
credentials, built on PROP-601's Row-Level Security.

## Setup

```bash
cd services/admin-api
pip install -r requirements.txt
cp .env.example .env
# generate ENCRYPTION_KEY: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
uvicorn main:app --reload --port 8001
```

The local dashboard runs at `http://localhost:5173` and the Admin API at
`http://localhost:8001`. `CORS_ORIGINS` in `.env.example` matches the
Vite default; update it if the dashboard is served from another origin.

## Auth

Closes `infra/observability/SECURITY_AUDIT.md` section 3's "no
service-to-service authentication" finding for this service. Per-tenant
API keys (`auth.py`), not a shared secret -- admin-api is tenant-facing
(one real caller per tenant), so a shared secret would let any tenant's
caller act as any other tenant.

```
POST /admin/tenants/{tenant_id}/provision
  Authorization: Bearer <PLATFORM_OPERATOR_TOKEN>
  -> {"tenant_id": "...", "admin_api_key": "<plaintext, shown once>"}
  -- Stage 1 of docs/AGENCY_ONBOARDING.md's onboarding flow. Every other
  -- route below requires the tenant's own key from this response, not
  -- the platform token.
```

Only the key's SHA-256 hash is ever stored
(`tenant_settings.admin_api_key_hash`) -- a fast hash is correct here
since these are high-entropy random tokens, not low-entropy human
passwords (no bcrypt/scrypt/argon2 needed). Re-provisioning a tenant
invalidates its previous key immediately.

## Rate limiting

Closes `infra/observability/SECURITY_AUDIT.md` section 4's "no rate
limiting anywhere" finding for this service. `rate_limit.py`: 30
requests / 60s per `tenant_id` for normal tenant-scoped operations, plus a
separate dashboard-read bucket defaulting to 300 requests / 60s per
tenant, and a 5 requests / 60s limit for `/provision`
(mints/rotates a tenant's credential — a materially more sensitive
action than a listing upload). Dashboard reads do not consume the normal
write/API budget. Limits are configurable via
`RATE_LIMIT_ADMIN_REQUESTS_PER_WINDOW`,
`RATE_LIMIT_DASHBOARD_REQUESTS_PER_WINDOW`,
`RATE_LIMIT_PROVISION_REQUESTS_PER_WINDOW`, and
`RATE_LIMIT_WINDOW_SECONDS`.

## API

All routes below require `Authorization: Bearer <tenant's admin_api_key>`
(from `/provision` above) except `/health`.

```
POST /admin/tenants/{tenant_id}/listings
  {"listings": [{"address": "...", "city": "...", "state": "...", "property_type": "house", "price": 500000, "amenities": ["pool"]}]}
  -> {"inserted": 1, "ids": [42]}

PUT /admin/tenants/{tenant_id}/calendar-credentials
  {"provider": "google_calendar", "credentials": {"access_token": "...", "refresh_token": "..."}}
  -> {"status": "ok"}
  -- encrypted at rest (Fernet, services/admin-api/crypto.py) before storage.
  -- Anticipates PROP-407 ("API key encryption for third-party calendar
  -- integrations") ahead of PROP-403 (the actual Calendar API integration)
  -- existing -- no reason to ever store a real credential in plaintext.

GET /admin/tenants/{tenant_id}/calendar-credentials
  -> {"provider": "google_calendar", "credentials": {...}}

PUT /admin/tenants/{tenant_id}/branding
  {"agency_name": "Austin Realty"}
  -> {"status": "ok"}
  -- docs/AGENCY_ONBOARDING.md Stage 2b. Looked up per call by
  -- services/orchestrator/tenant_branding.py, replacing the old
  -- process-level AGENCY_NAME env var for any tenant that's set this.

GET /admin/tenants/{tenant_id}/branding
  -> {"agency_name": "Austin Realty"}

GET /admin/tenants/{tenant_id}/properties
GET /admin/tenants/{tenant_id}/leads
GET /admin/tenants/{tenant_id}/appointments
GET /admin/tenants/{tenant_id}/calls
GET /admin/tenants/{tenant_id}/calls/{call_id}
GET /admin/tenants/{tenant_id}/stats
  -- dashboard read endpoints; all data access uses tenant_connection()
     and is isolated by Postgres RLS.

GET /health
```

## Testing

```bash
DATABASE_URL=postgresql://propview_app:devpassword@localhost/propview_dev \
ENCRYPTION_KEY=<a fernet key> python -m pytest tests/ -v
```

**Verified passing** 2026-09-03: 9/9 against real Postgres — listing
upload with correct row counts, invalid enum rejected with 422, tenant
isolation confirmed by directly querying as a different tenant context
(not just trusting the app-level filter), and the calendar-credentials
roundtrip confirmed genuinely encrypted at rest (asserted the plaintext
token literally does not appear in the stored bytes, not just that the
API "works"). **Extended 2026-09-10**, now 17/17: 6 auth cases (provisioning,
wrong/missing platform token rejected, a tenant route rejected without a
token, one tenant's own valid key confirmed rejected against a
*different* tenant's routes -- the actual point of per-tenant keys, not
just "auth exists" -- and re-provisioning confirmed to invalidate the old
key) plus 3 for the new branding endpoint (roundtrip, upsert overwrites,
missing returns null). Also live-verified end to end outside pytest:
`curl` through provision → upload a listing and set branding with the
returned key → query both back, plus confirming `search_properties`
reaches the same data via a real running Tool Router using its own
shared secret, and that a wrong/missing credential gets a real 401 from
each service, not a local mock.

**Verified passing** 2026-09-10: 5 more cases (`test_rate_limit.py`) for
the new per-tenant rate limiting — under-limit allowed, over-limit
rejected with 429, independent tenants have independent budgets, and a
lower-limit route sharing a budget with an already-incremented
higher-limit route correctly rejects sooner. Also live-verified against
real running instances: 35 real calls in a tight loop against the
then-configured shared 30/60s limit returned exactly 29×200 then 6×429 —
the limit fired at precisely the configured threshold. Full suite at that
time was 21/21.

The dashboard read routes have focused integration coverage in
`tests/test_dashboard_reads.py`, using the real Postgres and Redis
services. It exercises all six routes and verifies a call belonging to
another tenant is not readable. The independent dashboard bucket has a
separate Redis-backed limit test in `tests/test_rate_limit.py`.
**Verified passing 2026-11-13**: the focused dashboard-read, rate-limit,
and Admin API regression selection passed 27/27 tests against real
Postgres and Redis.

## Definition of Done (from Sprint Plan)

- [x] Tenant Admin API endpoints for uploading listings and calendar keys.
- [x] Calendar credentials encrypted at rest.
- [x] Authentication/authorization on the admin endpoints — per-tenant API
      keys, see "Auth" above. Closes the gap
      `infra/observability/SECURITY_AUDIT.md` flagged as the platform's
      single biggest security finding.
- [x] Tenant-scoped dashboard read endpoints and a separate read-rate
      budget. See the API and Testing sections above.
