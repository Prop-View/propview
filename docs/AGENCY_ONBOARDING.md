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
```

## Stage 1: Partner Onboarding

### 1a. Pick a `tenant_id`

Every table in `db/migrations/003_crm_schema.sql`/`001_projects_and_properties.sql`
is scoped by a plain `tenant_id` text column, enforced by RLS
(`004_row_level_security.sql`). There's no tenant-registration endpoint —
a tenant "exists" the moment any row references its `tenant_id` for the
first time. Pick a short, stable slug (e.g. `austin-realty`); it's used
in every API call below.

### 1b. Import listings

```bash
curl -X POST localhost:8001/admin/tenants/austin-realty/listings \
  -H 'Content-Type: application/json' \
  -d '{"listings": [{"address": "123 Oak St", "city": "Austin", "state": "TX",
       "property_type": "house", "beds": 3, "baths": 2.0, "price": 520000}]}'
```

Full field reference: `services/admin-api/main.py`'s `ListingUpload`
model, or `services/tool-router/README.md`'s tool-schema section for how
these fields surface back through `search_properties`/`get_property_details`.

For unstructured docs (brochures, FAQs, policies) that should be
answerable via `search_knowledge_base`, see `db/ingestion/README.md`
(PROP-302) — a separate ingestion script, not an admin-api endpoint.

## Stage 2: Portal Configuration

### 2a. Calendar credentials (PROP-403/407)

```bash
curl -X PUT localhost:8001/admin/tenants/austin-realty/calendar-credentials \
  -H 'Content-Type: application/json' \
  -d '{"provider": "google", "credentials": {"refresh_token": "...", "client_id": "...", "client_secret": "..."}}'
```

Stored Fernet-encrypted (`services/admin-api/crypto.py`) — see
`services/scheduling/README.md` for how to actually obtain a Google
Calendar OAuth refresh token, and the current gap (never tested against
a real Google account in this codebase's development so far).

### 2b. Agency branding

`AGENCY_NAME` is currently a **process-level env var**
(`services/orchestrator/.env.example`), not a per-tenant database value —
a real multi-tenant deployment running one shared orchestrator process
pool would need this promoted into `tenant_settings` (alongside
calendar credentials) so it varies per call by `tenant_id` rather than
per deployment. Not built; today, one orchestrator deployment serves
callers under one agency name.

### 2c. Assign a phone number (PROP-101)

Provisioning a DID and routing it to this tenant needs PROP-101/102
actually deployed (Twilio SIP trunk + LiveKit SIP gateway) — see
`infra/telephony/provisioning/README.md`. No code here currently maps
"which DID rang" to "which tenant_id" — that mapping would need to come
from the SIP trunk's routing config or a lookup table keyed by the
inbound DID, neither of which exists yet since no number has actually
been provisioned end to end.

### 2d. Twilio SMS/WhatsApp sender

Shared across all tenants today (`TWILIO_SMS_FROM_NUMBER`,
`services/orchestrator/.env.example`) — not per-tenant. See
`services/scheduling/README.md`.

## Running a call for this tenant

```bash
cd services/orchestrator
TENANT_ID=austin-realty AGENCY_NAME="Austin Realty" python main.py <room-name>
```

`TENANT_ID` flows through to every tool call
(`services/tool-router/README.md`'s API reference), lead capture
(`services/lead-engine/README.md`), and the RLS-enforced database layer.

## Full API / schema reference index

Rather than duplicated here, each of these is the authoritative doc for
its piece:

| Area | Reference |
|---|---|
| Tool Router (`search_properties`, `book_site_visit`, etc.) | `services/tool-router/README.md` |
| Admin API (listings, calendar credentials) | `services/admin-api/main.py` (docstrings) |
| Database schema (all tables/fields) | `db/migrations/*.sql`, `db/migrations/README.md` |
| Lead scoring rules | `services/lead-engine/README.md` |
| Human transfer / escalation | `services/orchestrator/README.md` §"Human transfer" |
| Cascaded fallback config | `services/fallback-pipeline/README.md` |
| Compliance rules | `services/compliance/COMPLIANCE_AND_ESCALATION.md` |
| Metrics / dashboards | `infra/observability/README.md` |
| Security posture | `infra/observability/SECURITY_AUDIT.md` |

## What Stage 1–2 does NOT cover yet (honest gaps)

- No tenant "registration" endpoint or admin UI — onboarding today is
  direct API calls, documented above.
- No per-tenant agency branding storage (§2b).
- No DID-to-tenant routing (§2c) — needs PROP-101/102 deployed first.
- No auth on any admin-api/tool-router endpoint — see
  `infra/observability/SECURITY_AUDIT.md` §3. Anyone who can reach these
  services can onboard/modify any tenant. Must be fixed before real
  agency data goes through this.

## Definition of Done (from Sprint Plan)

- [x] Onboarding guide covering listing import, calendar setup, and
      per-tenant call configuration.
- [x] API reference index pointing to each service's authoritative doc.
- [ ] Stages 3–8 of the plan's rollout (dry-run testing, soft launch,
      monitoring, scaling, iteration, full rollout) — operational
      process, not automated by this codebase.
- [ ] Per-tenant branding, DID routing, and admin auth — documented
      above as real gaps, not built.
