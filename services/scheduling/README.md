# PROP-403 / PROP-404: Calendar Booking & SMS Confirmations

Google Calendar availability/booking (`calendar_client.py`), a Redis
slot lock preventing double-booking (`redis_lock.py`), and Twilio SMS/
WhatsApp dispatch (`sms_dispatch.py`). The Gemini-facing tools that use
these live in `../tool-router/tools/check_calendar_slots.py` and
`book_site_visit.py` — this directory holds the underlying clients, not
the tool schemas themselves (same split as `../lead-engine/`).

PROP-503 (SIP call transfer) and PROP-504 (pre-transfer webhook) were
listed in this directory's original scope but ended up living in
`../orchestrator/` instead (`human_transfer.py`, `pre_transfer_summary.py`)
— executing a transfer needs direct LiveKit room/SIP admin access, which
only the orchestrator has; see `../orchestrator/README.md`'s "Human
transfer" section. This directory's `sms_dispatch.py` is still what sends
the pre-transfer SMS itself, just called from there instead of a tool
router tool.

## Credentials

Calendar credentials come from `tenant_settings.encrypted_calendar_credentials`
(`../admin-api/main.py`'s `PUT /admin/tenants/{id}/calendar-credentials`,
PROP-407 — encrypted via `../admin-api/crypto.py`, a Fernet key from
`ENCRYPTION_KEY`). This module only ever *reads* that credential; it's
never stored a second time here.

```bash
# Set once per tenant, via the admin API:
curl -X PUT localhost:8001/admin/tenants/default/calendar-credentials \
  -d '{"provider": "google", "credentials": {"refresh_token": "...", "client_id": "...", "client_secret": "..."}}'
```

SMS/WhatsApp use plain env vars (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_SMS_FROM_NUMBER`, `TWILIO_WHATSAPP_FROM_NUMBER`) — not
per-tenant encrypted storage like calendar credentials, since this MVP
runs one Twilio account for all tenants (see `infra/telephony/`).

## Double-booking prevention (Sprint 4 risk register)

`redis_lock.py`'s `SlotLock` holds a per-slot Redis key
(`slot_lock:<tenant>:<calendar>:<start-iso>`) for the duration of a
booking attempt — `book_site_visit` re-checks the slot is still actually
open *after* acquiring the lock (a concurrent booking could have taken it
between the caller's `check_calendar_slots` call and this one), then
books it, then releases. This is a single-Redis-instance lock (SET NX PX
+ a token-checked release), not textbook multi-node Redlock — see the
module docstring for why that's a deliberate simplification, not a missed
requirement, given this MVP runs one Redis instance.

## Not live-verified

Neither Google Calendar nor Twilio has real credentials available in
this environment — same category of gap as PROP-101/102 (Twilio
SIP/GCP). Tested against mocks instead:
- `tests/test_calendar_client.py` — mocks `googleapiclient`, verifies
  the business-hours/overlap slot computation and the booking request
  shape. 4/4 passing.
- `tests/test_sms_dispatch.py` — mocks Twilio's `Client`, verifies
  routing (SMS vs WhatsApp number prefixing) and the confirmation
  message body. 6/6 passing.
- `tests/test_redis_lock.py` — **real** Redis (not mocked — the point is
  actual SET NX/TTL/token-release behavior). 5/5 passing, including a
  lock-expires-and-gets-reacquired-by-someone-else race.
- `../tool-router/tests/test_booking.py` — the full tool path (real
  Postgres + real Redis, mocked Google/Twilio): slot listing, booking
  creates both the calendar event and the `appointments` row, SMS
  confirmation dispatch, and — the actual double-booking scenario — a
  slot the mocked calendar reports as busy gets rejected by the
  re-check-under-lock. 5/5 passing.

## Testing

```bash
cd services/scheduling
pip install -r requirements.txt
redis-server &   # or: brew services start redis
python -m pytest tests/ -v
```

**Verified passing** 2026-09-04: 15/15 across all three modules (see above).

## Definition of Done (from Sprint Plan)

- [x] Google Calendar API integration for slot reading and booking (PROP-403).
- [x] SMS/WhatsApp dispatch service via Twilio messaging API (PROP-404).
- [x] Redis distributed locking on calendar slot keys during booking
      (Sprint 4 risk mitigation) — simplified to a single-instance lock,
      see above.
- [ ] Live-verified against a real Google Calendar / Twilio account — no
      real credentials available in this environment.
- [ ] E2E API testing for appointment booking and lead capture (PROP-406)
      — tracked in `../../tests/integration/`.
- [ ] PROP-503 (SIP call transfer) / PROP-504 (pre-transfer webhook) —
      not built yet.
