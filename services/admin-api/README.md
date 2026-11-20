# Tenant Admin API

Multi-tenant account, product, and admin endpoints, built on the
Row-Level Security schema. The API serves machine integrations
(per-tenant API keys) and browser users (owner/agent accounts).

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

## Agency accounts

The browser account API uses Argon2 password hashes and opaque,
short-lived session tokens. Only SHA-256 token hashes are stored. New
owners must verify their email before login; password-reset tokens are
single-use and reset revokes existing sessions. Owners can invite and
deactivate agent accounts. Owner-only operations include team management,
webhooks, OAuth connect, agency settings, listing writes, and document
uploads. Agents can use tenant-scoped read routes and edit leads and
appointments. Machine API keys remain supported for service integrations.

```
POST /auth/signup
POST /auth/{tenant_id}/verify-email
POST /auth/{tenant_id}/verification/resend
POST /auth/login
POST /auth/password-reset/request
POST /auth/password-reset/confirm
POST /auth/{tenant_id}/logout
GET  /auth/{tenant_id}/me
GET  /admin/tenants/{tenant_id}/team              -- owner session
POST /admin/tenants/{tenant_id}/team/invitations  -- owner session
POST /auth/{tenant_id}/team/accept
DELETE /admin/tenants/{tenant_id}/team/{user_id}  -- owner session
```

Email verification, password reset, and invitations use the provider-
agnostic email adapter (`email_provider.py`), with SMTP as the default.
Set `SMTP_HOST` and `SMTP_FROM`; configure the remaining SMTP variables
for the provider. `DASHBOARD_BASE_URL` controls the links in account
emails. These flows are tested with outbound mail replaced at the
provider boundary; delivery through a real SMTP account has not been
verified.

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

## Platform tenant registry

These operator-only routes require
`Authorization: Bearer <PLATFORM_OPERATOR_TOKEN>`, not a tenant API key.
The backing `tenants` and `tenant_phone_numbers` tables have no direct
grants to `propview_app`; the API uses restricted registry functions from
`db/migrations/011_tenant_registry_settings_usage.sql`.

```
GET /admin/platform/tenants
POST /admin/platform/tenants
  {"slug": "austin-realty", "name": "Austin Realty", "status": "active", "plan": "starter"}
GET /admin/platform/phone-numbers
PUT /admin/platform/phone-numbers
  {"tenant_id": "austin-realty", "phone_number": "+15125550123"}
DELETE /admin/platform/phone-numbers
  {"phone_number": "+15125550123"}
```

Tenant provisioning also ensures a registry row exists. A production
worker resolves inbound calls by the dialed E.164 number; no mapping,
missing number, or inactive tenant ends the call instead of using a
default tenant. The registry lookup uses the LiveKit
`sip.trunkPhoneNumber` attribute; real SIP-call verification is still
pending.

## Product write APIs

These tenant-scoped routes use `tenant_connection()` and Postgres RLS.
Owner sessions or machine API keys may manage listings, settings, and
documents; owner and agent sessions may update leads and appointments.

```
POST /admin/tenants/{tenant_id}/listings/upload-csv
  multipart/form-data: file=<CSV with the ListingUpload core fields>
  -> {"inserted": 1, "ids": [42], "errors": []}

PATCH /admin/tenants/{tenant_id}/leads/{lead_id}
  {"status": "qualified", "notes": "Requested a showing"}

PATCH /admin/tenants/{tenant_id}/appointments/{appointment_id}
  {"scheduled_at": "2026-11-15T17:00:00+00:00"}
  -- or {"status": "cancelled"}

PATCH /admin/tenants/{tenant_id}/properties/{property_id}
DELETE /admin/tenants/{tenant_id}/properties/{property_id}
POST /admin/tenants/{tenant_id}/knowledge-base/documents
  multipart/form-data: file=<.pdf, .txt, or .md>, source_type=<type>
  -- wraps db/ingestion helpers and Gemini embeddings. A real Gemini
     embedding request through this route has not been verified.
```

## Calendar OAuth

```
GET /admin/tenants/{tenant_id}/calendar/google/status
GET /admin/tenants/{tenant_id}/calendar/google/connect  -- owner session
GET /auth/calendar/google/callback
```

The flow signs tenant-bound, expiring state, consumes it once, exchanges
the authorization code, and stores credentials encrypted at rest. The
callback's provider exchange is tested with a fake HTTP client. A real
Google account authorization has not been verified.

## Webhooks and notifications

```
GET    /admin/tenants/{tenant_id}/webhooks
POST   /admin/tenants/{tenant_id}/webhooks
PATCH  /admin/tenants/{tenant_id}/webhooks/{webhook_id}
DELETE /admin/tenants/{tenant_id}/webhooks/{webhook_id}
POST   /admin/tenants/{tenant_id}/webhooks/{webhook_id}/rotate-secret
GET    /admin/tenants/{tenant_id}/webhooks/{webhook_id}/deliveries
```

Only owners manage webhooks. Signing secrets are encrypted and returned
only on creation or rotation. HTTPS targets are checked against private
and reserved addresses. Events are `lead.created`, `lead.qualified`,
`appointment.booked`, and `call.completed`; delivery is at-least-once.
Hot-lead and appointment emails are queued in a tenant-scoped outbox.

Run `python event_dispatcher.py` from this service to drain webhook and
email outboxes. It is a one-shot entrypoint intended for periodic
scheduler invocation; no production scheduler or real webhook receiver
is configured in this repository.

FastAPI publishes interactive API documentation at `/docs` and the
OpenAPI schema at `/openapi.json`.

## Billing (Phase 5)

```
GET  /admin/tenants/{tenant_id}/billing
POST /admin/tenants/{tenant_id}/billing/subscription
  {"plan_slug": "agency"}
POST /webhooks/razorpay
  X-Razorpay-Signature: <HMAC-SHA256 of the exact raw body>
  X-Razorpay-Event-Id: <provider event ID, when supplied>
```

The global `billing_plans` catalog is read-only to `propview_app`;
platform operators configure its prices, monthly quotas, and Razorpay
test-plan IDs during deployment. The tenant subscription and webhook
idempotency ledger use forced RLS. Checkout refuses to run unless
`RAZORPAY_KEY_ID` has the `rzp_test_` prefix, the key secret exists, and
the selected catalog plan has a price and test-plan ID. Subscription
creation is through a provider interface and makes a call only to
Razorpay's documented `/v1/subscriptions` API.

The webhook endpoint validates `X-Razorpay-Signature` against the exact
unmodified request bytes with HMAC-SHA256 before reading event data.
Repeated event IDs are accepted idempotently; status updates are tenant
scoped. Webhook processing also requires configured Razorpay test-mode
credentials and rejects live-mode keys. No live credentials, Razorpay
account, payment, or real provider webhook has been verified.

Current-month `usage_events` are compared with the current plan's call,
SMS, and WhatsApp quotas. The API returns advisory warnings at 80% and at
the limit; there is deliberately no blocking path into call handling or
message delivery. No production prices or quotas are seeded. A test-mode
checkout remains unavailable until the operator configures catalog rows
and Razorpay test plan IDs. See the [Razorpay subscription API](https://razorpay.com/docs/api/payments/subscriptions/create-subscription/)
and [subscription webhook events](https://razorpay.com/docs/webhooks/subscriptions/)
plus the [webhook signature validation guide](https://razorpay.com/docs/webhooks/validate-test/).

## Tenant API

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
  -- retained for machine integrations; browser users connect through the
     Calendar OAuth flow above.

GET /admin/tenants/{tenant_id}/calendar-credentials
  -> {"provider": "google_calendar", "credentials": {...}}
  -- machine API key only; never expose this response to a browser client.

PUT /admin/tenants/{tenant_id}/branding
  {"agency_name": "Austin Realty"}
  -> {"status": "ok"}
  -- docs/AGENCY_ONBOARDING.md Stage 2b. Looked up per call by
  -- services/orchestrator/tenant_branding.py, replacing the old
  -- process-level AGENCY_NAME env var for any tenant that's set this.

GET /admin/tenants/{tenant_id}/branding
  -> {"agency_name": "Austin Realty"}

PUT /admin/tenants/{tenant_id}/settings
  {"broker_transfer_number": "+15125550124", "sms_sender_number": "+15125550125",
   "whatsapp_sender_number": "+15125550126", "time_zone": "America/Chicago",
   "business_hours_start_hour": 9, "business_hours_end_hour": 17,
   "voice_name": "Kore", "greeting": "Thanks for calling Austin Realty."}
GET /admin/tenants/{tenant_id}/settings
  -> the configured operational settings; unset values are null.
  -- Business hours must be set or cleared as a valid start/end pair.

GET /admin/tenants/{tenant_id}/usage/monthly
  -> {"items": [{"month": "...", "event_type": "call", "event_count": 1, "units": 1}]}
  -- tenant-scoped monthly aggregation from the RLS-protected usage ledger.

GET /admin/tenants/{tenant_id}/properties
GET /admin/tenants/{tenant_id}/leads
GET /admin/tenants/{tenant_id}/appointments
GET /admin/tenants/{tenant_id}/calls
GET /admin/tenants/{tenant_id}/calls/{call_id}
GET /admin/tenants/{tenant_id}/stats
  -- dashboard read endpoints; all data access uses tenant_connection()
     and is isolated by Postgres RLS.

GET /health
  -- checks the Admin API process, a real Postgres query, and Redis PING;
     dependency failures are reported in the JSON response.
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

**Verified 2026-11-15**: all 40 Admin API tests passed against real
Postgres and Redis. The account/product integration coverage includes
signup/verification/login/reset, sessions and owner/agent permissions,
CSV and CRM writes, OAuth state/replay and encrypted credential storage,
webhook event generation/signatures/retry, email outbox creation, and the
live Postgres/Redis health checks. SMTP and Google's token endpoint are
stubbed only at their outbound API boundaries; no external account is
claimed as live-verified.

## Definition of Done (from Sprint Plan)

- [x] Tenant Admin API endpoints for uploading listings and calendar keys.
- [x] Calendar credentials encrypted at rest.
- [x] Authentication/authorization on the admin endpoints — per-tenant API
      keys, see "Auth" above. Closes the gap
      `infra/observability/SECURITY_AUDIT.md` flagged as the platform's
      single biggest security finding.
- [x] Tenant-scoped dashboard read endpoints and a separate read-rate
      budget. See the API and Testing sections above.
- [x] Platform tenant/phone-number registry routes, operational settings,
      and tenant-scoped monthly usage reporting.
- [x] Argon2 owner/agent accounts, email verification, password reset,
      short-lived sessions, team invitations, and tenant-scoped audit log.
- [x] Lead and appointment updates, listing update/delete and CSV upload,
      plus a tenant-scoped knowledge-document upload wrapper.
- [x] Google Calendar OAuth state flow and encrypted credential storage;
      real Google account authorization remains unverified.
- [x] Per-tenant webhook configuration, encrypted signing secrets,
      delivery log, retries, and email notification outbox.
- [x] SMTP-default email adapter and published OpenAPI documentation.
- [x] Browser dashboard uses the owner/agent session API; machine API
      keys are not stored in browser local storage.
- [ ] Configure and live-verify SMTP and Google Calendar with real
      provider accounts; run the dispatcher from a production scheduler.
- [x] Phase 5 billing foundation: test-mode subscription creation, signed
      idempotent webhooks, and non-enforcing monthly usage warnings.
      Real Razorpay payments and webhook delivery remain unverified.

**Verified 2026-11-15**: the focused Admin API regression set, including
billing, passed 31/31 against real Postgres and Redis using the
`propview_app` role (`NOSUPERUSER NOBYPASSRLS`). Razorpay API calls were
checked with a fake HTTP boundary; no external payment or webhook was
claimed as verified.
