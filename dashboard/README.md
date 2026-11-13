# Propview Agency Dashboard

The React + Vite dashboard gives agency staff a read-only view of their
properties, leads, appointments, calls, and call analytics. It uses the
existing Tenant Admin API; it is not a separate backend or a second
frontend.

## Local setup

```bash
cd dashboard
npm install
cp .env.example .env
npm run dev
```

By default Vite serves the dashboard at `http://localhost:5173` and the
Admin API at `http://localhost:8001`. The Admin API's local CORS default
allows the Vite origin. If the API is hosted elsewhere, set
`VITE_API_URL` in `dashboard/.env` to its base URL (without a trailing
slash).

Start the Admin API and its required Postgres and Redis services first;
see [the Admin API README](../services/admin-api/README.md) and
[the developer guide](../docs/GUIDE.md).

## Current dashboard pages

- Overview: call, lead, property, appointment, and conversion metrics.
- Calls: recent call history and per-call detail, including structured
  turns, tool invocations, and analytics.
- Leads and appointments: tenant-scoped read views.
- Properties: tenant-scoped listing inventory.
- Analytics: call trends and tool usage.
- Settings: current agency branding controls.

The current dashboard authenticates with a tenant Admin API key. The key
is stored in browser local storage by the existing login flow; replacing
this with password-based sessions and removing browser-persisted keys is
planned for Phase 4. Do not use this prototype as a public production
login surface.

## Development checks

```bash
npm run lint
npm run build
```

## Current gaps

- Signup, password login/reset, team management, and session-based browser
  authentication are not implemented.
- Settings controls beyond branding are not connected to tenant settings.
- Listing/document uploads, editing, usage, and billing views are not
  implemented.
- Component tests and a Playwright smoke test are not yet present.
