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

## API

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
  -- ⚠️ NO AUTH on this endpoint. Fine for local dev; MUST be locked down
  -- (internal-only network, real auth middleware) before any real
  -- deployment. Not addressed by this ticket -- flagged, not silently shipped.

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
API "works").

## Definition of Done (from Sprint Plan)

- [x] Tenant Admin API endpoints for uploading listings and calendar keys.
- [x] Calendar credentials encrypted at rest.
- [ ] Authentication/authorization on the admin endpoints themselves —
      out of scope for this ticket, but a real gap before deployment.
