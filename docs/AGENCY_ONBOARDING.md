# PROP-607: Agency Onboarding Guide & API Documentation

How to bring a new tenant (real estate agency) onto the platform, and
where the full API reference for each piece lives. Consolidates what's
scattered across every service's own README into one walkthrough — this
document doesn't duplicate those references in full, it links to them at
the point they're needed.

Maps onto `Sprint Plan.md` section 9's Eight-Stage Pilot Rollout Plan,
Stages 1–2 (Partner Onboarding, Portal Configuration) specifically —
Stages 3–8 (dry-run testing, soft launch, monitoring, scaling, iteration,
full rollout) are operational/business process, not something this
codebase automates.

## Prerequisites

Every step below assumes the shared infrastructure is already running:
Postgres with migrations applied (`db/migrations/README.md`), Redis,
the Tool Router (`services/tool-router/`), and the Admin API
(`services/admin-api/`). None of this is per-tenant — it's shared
infrastructure every tenant's calls route through, isolated from each
other by PROP-601's Row-Level Security.

```bash
# Once, for the whole platform:
cd db/migrations && python apply_migrations.py
cd ../../services/tool-router && uvicorn main:app --port 8000 &
cd ../admin-api && uvicorn main:app --port 8001 &
# Dashboard: cd dashboard && npm run dev (http://localhost:5173)
```

## Stage 1: Partner Onboarding

### 1a. Pick a `tenant_id`

Every table in `db/migrations/003_crm_schema.sql`/`001_projects_and_properties.sql`
is scoped by a plain `tenant_id` text column, enforced by RLS
(`004_row_level_security.sql`). Pick a short, stable slug (e.g.
`austin-realty`); it's used in every API call below. Phase 2 also records
the tenant in the platform-level `tenants` registry. The registry tables
are not directly readable by `propview_app`; restricted
`SECURITY DEFINER` functions provide only the operations needed by the
platform API, inbound-call lookup, and scheduled follow-up scan.

### 1b. Self-service owner account

For agency signup, use the account API. Configure SMTP first, since the
owner must verify their email before the tenant becomes active:

```bash
curl -X POST localhost:8001/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{
    "tenant_slug": "austin-realty",
    "tenant_name": "Austin Realty",
    "owner_name": "Agency Owner",
    "email": "owner@example.com",
    "password": "<at least 12 characters>"
  }'
# -> {"tenant_slug": "austin-realty", "status": "verification_required"}
```

The verification link is emailed to the owner. Successful verification
activates the tenant. Then sign in with `POST /auth/login` using
`tenant_slug`, `email`, and `password`; the short-lived bearer session
replaces browser use of the machine key. Password reset and team
invitation routes are documented in the Admin API README.

### 1c. Provision a machine API key (integrations only)

```bash
curl -X POST localhost:8001/admin/tenants/austin-realty/provision \
  -H "Authorization: Bearer $PLATFORM_OPERATOR_TOKEN"
# -> {"tenant_id": "austin-realty", "admin_api_key": "<save this now>"}
```

`$PLATFORM_OPERATOR_TOKEN` is `services/admin-api/.env`'s value — held
only by whoever operates this platform, not given to the agency. The
returned `admin_api_key` is shown exactly once (only its hash is stored);
every other admin-api call for this tenant needs it as
`Authorization: Bearer <admin_api_key>`. Losing it means re-provisioning
(which invalidates the old one), not recovering it — see
`services/admin-api/README.md`'s "Auth" section for the full design and
why this is per-tenant rather than one shared secret.

### 1d. Import listings

```bash
curl -X POST localhost:8001/admin/tenants/austin-realty/listings \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"listings": [{"address": "123 Oak St", "city": "Austin", "state": "TX",
       "property_type": "house", "beds": 3, "baths": 2.0, "price": 520000}]}'
```

Full field reference: `services/admin-api/main.py`'s `ListingUpload`
model, or `services/tool-router/README.md`'s tool-schema section for how
these fields surface back through `search_properties`/`get_property_details`.

For unstructured docs (brochures, FAQs, policies) that should be
answerable via `search_knowledge_base`, upload the PDF/TXT/Markdown
document through the Admin API knowledge-base route. It reuses the
existing ingestion helpers and requires a configured Gemini API key.
The standalone script remains documented in `db/ingestion/README.md`.

## Stage 2: Portal Configuration

### 2a. Google Calendar connect

```bash
curl -X PUT localhost:8001/admin/tenants/austin-realty/calendar-credentials \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"provider": "google", "credentials": {"refresh_token": "...", "client_id": "...", "client_secret": "..."}}'
```

For browser accounts, open the owner-only OAuth authorization URL from
`GET /admin/tenants/{tenant_id}/calendar/google/connect`, approve the
requested calendar scope, and let Google redirect to the configured
callback. Credentials are stored Fernet-encrypted. A real Google account
exchange remains unverified. Machine integrations can still set
credentials through the machine-key-only `/calendar-credentials` route.

### 2b. Agency branding

```bash
curl -X PUT localhost:8001/admin/tenants/austin-realty/branding \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"agency_name": "Austin Realty"}'
```

Stored in `tenant_settings.agency_name` — `services/orchestrator/main.py`
looks this up per call (`tenant_branding.get_agency_name`) before
building the system prompt, falling back to the `AGENCY_NAME` env var
(`services/orchestrator/.env.example`) only if `DATABASE_URL` is unset or
this hasn't been set for the tenant yet. This is what actually lets one
shared orchestrator process pool serve multiple tenants under their own
agency names, rather than one name fixed per deployment.

### 2c. Assign a phone number (PROP-101)

After provisioning a real DID and configuring the Twilio SIP trunk /
LiveKit SIP gateway (see `infra/telephony/provisioning/README.md`), map
the E.164 number to this tenant using the platform operator credential:

```bash
curl -X PUT localhost:8001/admin/platform/phone-numbers \
  -H "Authorization: Bearer $PLATFORM_OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id": "austin-realty", "phone_number": "+15125550123"}'
```

The worker resolves the caller's dialed number from LiveKit's
`sip.trunkPhoneNumber` attribute through the restricted registry
function. Missing, inactive, or unmapped numbers end the call; the worker
does not fall back to a default tenant. The registry and routing code are
implemented, but a real SIP-originated call still needs live verification.

### 2d. Twilio SMS/WhatsApp sender

Tenant-specific `sms_sender_number` and `whatsapp_sender_number` are
stored in `tenant_settings`. Set operational call settings with the
tenant's API key:

```bash
curl -X PUT localhost:8001/admin/tenants/austin-realty/settings \
  -H "Authorization: Bearer $AUSTIN_REALTY_ADMIN_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "broker_transfer_number": "+15125550124",
    "sms_sender_number": "+15125550125",
    "whatsapp_sender_number": "+15125550126",
    "time_zone": "America/Chicago",
    "business_hours_start_hour": 9,
    "business_hours_end_hour": 17,
    "voice_name": "Kore",
    "greeting": "Thanks for calling Austin Realty. How can I help?"
  }'
```

The same settings endpoint accepts a subset of fields. Calendar booking,
the orchestrator, and follow-up scans read tenant settings; the matching
environment values in each service's `.env.example` are local-development
fallbacks only. Secrets such as Twilio account credentials remain service
configuration.

## Running a call for this tenant

```bash
cd services/orchestrator
TENANT_ID=austin-realty AGENCY_NAME="Austin Realty" python main.py <room-name>
```

For manual local calls, `TENANT_ID` flows through to every tool call
(`services/tool-router/README.md`'s API reference), lead capture
(`services/lead-engine/README.md`), and the RLS-enforced database layer.
Production inbound calls use `worker.py`, which resolves each tenant from
the dialed phone number and fails closed if it cannot resolve the mapping.

The existing React dashboard connects to the Admin API at
`http://localhost:8001` by default (`dashboard/.env.example`) and runs
locally at `http://localhost:5173`. Owners can sign up from the dashboard,
verify their email, and sign in with their agency slug, email, and
password. Browser sessions replace machine API keys; the dashboard does
not persist tenant API keys in local storage. Product edits, CSV and
knowledge uploads, settings, team access, webhooks, calendar connect, and
monthly usage are available through the existing dashboard. See
`dashboard/README.md` for current behavior and remaining live-provider
gaps.

## Full API / schema reference index

Rather than duplicated here, each of these is the authoritative doc for
its piece:

| Area | Reference |
|---|---|
| Tool Router (`search_properties`, `book_site_visit`, etc.) | `services/tool-router/README.md` |
| Admin API (accounts, CRM writes, settings, OAuth, webhooks) | `services/admin-api/README.md`, `/docs`, `/openapi.json` |
| Database schema (all tables/fields) | `db/migrations/*.sql`, `db/migrations/README.md` |
| Lead scoring rules | `services/lead-engine/README.md` |
| Human transfer / escalation | `services/orchestrator/README.md` §"Human transfer" |
| Cascaded fallback config | `services/fallback-pipeline/README.md` |
| Compliance rules | `services/compliance/COMPLIANCE_AND_ESCALATION.md` |
| Metrics / dashboards | `infra/observability/README.md` |
| Security posture | `infra/observability/SECURITY_AUDIT.md` |

## What Stage 1–2 does NOT cover yet (honest gaps)

- Inbound number assignment remains a platform-operator action: carrier
  and LiveKit provisioning must be coordinated and is not exposed to
  agency accounts in the dashboard.
- The Phase 5 billing foundation now displays monthly usage, subscription
  state, and advisory quota warnings. Razorpay checkout is test-mode only
  and unavailable until an operator configures catalog prices and matching
  Razorpay test plan IDs. No production billing credentials or plans are
  configured, and payment/webhook delivery still needs live verification.
- Real DID provisioning and live SIP-call routing (§2c) still need
  telephony credentials and end-to-end verification.
- No production scheduler is deployed for follow-up scans, webhook
  deliveries, or email notifications. SMTP delivery, Google Calendar
  OAuth, webhook delivery, and Gemini-backed document ingestion need real
  provider credentials and live verification.

**Fixed 2026-09-10:** admin-api/tool-router auth (see
`infra/observability/SECURITY_AUDIT.md` §3, `services/admin-api/README.md`
and `services/tool-router/README.md`'s "Auth" sections) and per-tenant
agency branding (§2b above, now stored in `tenant_settings` instead of a
process-level env var).

**Added in Phase 2:** protected tenant and phone-number registries,
fail-closed DID-to-tenant resolution, tenant operational settings,
tenant-scoped monthly call/SMS usage, and registry-driven follow-up scans.
See `db/migrations/README.md` and the relevant service READMEs for
implementation and verification status.

## Definition of Done (from Sprint Plan)

- [x] Onboarding guide covering listing import, calendar setup, and
      per-tenant call configuration.
- [x] API reference index pointing to each service's authoritative doc.
- [x] Per-tenant branding and admin-api/tool-router auth — see Stage 1b
      and 2b above, and `infra/observability/SECURITY_AUDIT.md` §3.
- [ ] Stages 3–8 of the plan's rollout (dry-run testing, soft launch,
      monitoring, scaling, iteration, full rollout) — operational
      process, not automated by this codebase.
- [x] DID-to-tenant registry lookup and fail-closed worker behavior are
      implemented; real SIP-call verification remains pending.
