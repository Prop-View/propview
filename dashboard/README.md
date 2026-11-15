# Propview Agency Dashboard

The React + Vite dashboard is the browser interface for the Tenant Admin
API. It supports self-service agency accounts, agency operations, and
tenant-scoped call, lead, property, appointment, and usage views.

## Local setup

```bash
cd dashboard
npm install
cp .env.example .env
npm run dev
```

By default Vite serves the dashboard at `http://localhost:5173` and the
Admin API at `http://localhost:8001`. The Admin API's local CORS default
allows the Vite origin. If the API is hosted elsewhere, set `VITE_API_URL`
in `dashboard/.env` to its base URL (without a trailing slash).

Start the Admin API and its required Postgres and Redis services first;
see [the Admin API README](../services/admin-api/README.md) and
[the developer guide](../docs/GUIDE.md). Signup, email verification, and
password reset also require the Admin API's SMTP settings.

## Account and session behavior

- Owners can sign up with an agency name/slug, owner name, email, and
  password. Signup remains pending until the email verification link is
  used.
- Login uses the agency slug, email, and password and receives the
  Admin API's expiring bearer session.
- The browser stores that short-lived session in `sessionStorage` so it
  survives page reloads in the current tab. The machine API key is never
  stored or sent by the dashboard; legacy local-storage keys are removed
  at startup.
- Password reset and team-invitation acceptance are available from the
  emailed links. Signing out revokes the active session through the API.

## Dashboard pages

- **Overview, calls, and analytics** show the existing tenant-scoped
  Admin API read models.
- **Leads** allows staff to update lead status and notes.
- **Appointments** allows staff to reschedule or cancel eligible visits.
- **Properties** supports owner CSV upload, listing edits, and deletion.
  Download the CSV template from the page.
- **Settings** wires agency branding, voice/greeting, time zone, business
  hours, broker/SMS/WhatsApp numbers, Google Calendar OAuth, webhook
  management, team invitations/deactivation, and knowledge-document
  upload to the Admin API.
- **Usage & Billing** shows monthly metered usage. Subscription, invoice,
  and payment management are not available yet; those belong to Phase 5.

Inbound phone-number routing is intentionally platform-operator managed:
carrier and LiveKit provisioning must be coordinated, and the dashboard
does not receive platform operator credentials. The status view reports
live Admin API, Postgres, and Redis reachability; it does not claim that
the Tool Router, LiveKit, or external provider accounts are healthy.

Google Calendar OAuth, SMTP delivery, webhook delivery, and document
embedding still require configured external services and are not claimed
as live-verified by dashboard tests.

## Development checks

```bash
npm run lint
npm run test
npm run build
npm run test:e2e
```

The component tests exercise account form behavior with mocked HTTP
responses. The Playwright smoke test runs the real Vite dashboard and
stubs only the Admin API boundary; it verifies the password login flow and
that neither tenant API keys nor tenant identifiers are persisted in
`localStorage`.
