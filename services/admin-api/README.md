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

## Definition of Done (from Sprint Plan)

- [x] Tenant Admin API endpoints for uploading listings and calendar keys.
- [x] Calendar credentials encrypted at rest.
- [x] Authentication/authorization on the admin endpoints — per-tenant API
      keys, see "Auth" above. Closes the gap
      `infra/observability/SECURITY_AUDIT.md` flagged as the platform's
      single biggest security finding.
