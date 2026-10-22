# Follow-up Manager

A post-plan addition — no Sprint Plan ticket, same category as
`PROP-50/51/52` (see `CLAUDE.md` section 1). Closes a real gap found
while auditing this repo's tools/business-logic coverage against the
product's full tool list: nothing anywhere re-contacted a caller after
the call ended. Two independent passes, both in `followup_scan.py`:

- **No-show re-contact**: an `appointments` row past its `scheduled_at`
  that's still `status = 'scheduled'` gets flipped to `'no_show'` and
  triggers one re-contact SMS.
- **Didn't-book nurture**: a `leads` row with at least one completed call
  (`interactions`, written by `../orchestrator/transcript_store.py`) but
  no appointment ever booked, where the most recent call is stale enough,
  gets one nurture SMS.

Neither is a Gemini-facing tool — both are deliberately asynchronous,
post-call decisions with no in-call moment to hook into, unlike every
other tool in `../tool-router/tools/`.

## Why a one-shot script, not a service

This repo has no deployed scheduler/cron anywhere yet — wiring one is a
separate, later infra decision. `followup_scan.py` is a plain script:

```bash
cd services/follow-up-manager
cp .env.example .env   # fill in DATABASE_URL, Twilio creds
python followup_scan.py
```

Run it by hand for now, or from any external scheduler (cron / Windows
Task Scheduler / a cloud scheduler) later without changing the script
itself.

## Retry safety (the part that matters right now)

The Twilio account for this project exists but **isn't funded yet** —
every real SMS send in this environment currently fails. `follow_ups`
(`db/migrations/008_follow_ups.sql`) is only written *after* a send
actually succeeds, so a failed send leaves no ledger row and the next
run retries it automatically. The no-show status flip itself is
idempotent and intentionally **not** the dedup signal (see
`_scan_no_shows`'s own comment in `followup_scan.py`) — if it were, a
failed send on one run would permanently exclude that appointment from
ever being retried, since the row would no longer match
`status = 'scheduled'` on the next pass.

## Known simplification: `FOLLOWUP_TENANT_IDS`

There's no way to list every tenant_id without a raw connection
bypassing RLS (`CLAUDE.md` section 2), and nothing else in this repo has
solved that either — `TENANT_ID` is a single env var everywhere else
too. `FOLLOWUP_TENANT_IDS` (comma-separated, default `"default"`) is the
same category of simplification, not a real tenant registry. Revisit
when real multi-tenant production exists.

## Testing

```bash
cd services/follow-up-manager
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # .venv/bin/python on Linux/macOS
DATABASE_URL=postgresql://propview_app:devpassword@localhost:5433/propview_dev \
.venv/Scripts/python -m pytest tests/ -v
```

Real Postgres (RLS-enforced), Twilio mocked — same convention as
`../scheduling/tests/test_sms_dispatch.py` and
`../tool-router/tests/test_booking.py`. Covers: the status flip, the
dedup ledger preventing a resend, the retry-after-failed-send case (the
scenario this environment is actually in right now), and both scan
queries' edge cases (not yet overdue, lead already has an appointment, no
interaction ever recorded, lead already past the qualification stages
nurture applies to).

**Verified 2026-10-18**: all tests passing against real Postgres with
Twilio mocked (no real Twilio credentials available — the account exists
but isn't funded; see `CLAUDE.md`'s Phase 3 notes).

## Definition of Done

- [x] No-show detection and re-contact SMS.
- [x] Didn't-book nurture SMS, gated on at least one real completed call
      ever having been recorded for the lead.
- [x] Dedup ledger (`follow_ups`) preventing double-sends, with a
      retry-safe design verified against the Twilio-not-funded case this
      environment is actually in today.
- [ ] Real scheduler/cron wiring — this is a one-shot script by design
      for now (see above); deploying it on a recurring trigger is a later
      infra step, not part of this work.
- [ ] Live-verified against a real, funded Twilio account — blocked on
      the same account-funding step as the rest of Phase 3's telephony
      work.
- [ ] Real multi-tenant tenant enumeration — `FOLLOWUP_TENANT_IDS` is a
      documented simplification, not a registry (see above).
