# Propview — AI Real-Estate Voice Agent

Enterprise-grade, low-latency, full-duplex Voice AI agent for inbound real
estate calls: qualifies leads, queries live MLS/property data, books site
visits, and escalates to a human broker when needed.

- **Plan**: `Sprint Plan.md` — 6 sprints, 49 engineering tasks (PROP-101–608)
- **Architecture**: `docs/architecture.md` — supersedes the plan text where they differ
- **Tracking**: Jira project `PROP` (dspacejira) — task mapping in project memory
- **Team**: Aahil (Dev A — Backend/Telephony/Infra), Deepak (Dev B — AI/Data/Tools)

## Quickstart

```bash
./scripts/setup_dev_env.sh   # one shared venv + wired-up .env files -- see scripts/README.md
source .venv/bin/activate
cd services/orchestrator && python tests/test_orchestrator_live.py   # proves the core loop works, no API keys/mic/phone needed
```

Then `docs/AGENCY_ONBOARDING.md` for onboarding a tenant, or any
service's own README for what it does.

## Layout

```
scripts/        Dev environment setup (venv + .env wiring)
infra/          Provisioning & deployment: telephony, LiveKit, GCP, observability
services/       Runtime services: audio, orchestrator, tool router, lead engine, ...
db/             Schema migrations and knowledge-base ingestion
tests/          Integration, E2E voice-scenario, and load test suites
docs/           Architecture reference and sprint documentation
```

Each subdirectory's README maps its contents back to specific PROP ticket
IDs from `Sprint Plan.md`. New tenant? Start at `docs/AGENCY_ONBOARDING.md`.

## Status

As of 2026-09-09: **43 of 49 tickets Done** (tracked in Jira project
`PROP`). The 6 remaining are each genuinely blocked, not just
unstarted — see the exact list below. Everything else is built and
tested, either live-verified against the real API/service or (where a
real third-party account isn't available in this environment — Twilio,
Google Calendar OAuth, Deepgram, OpenAI, Cartesia) verified as far as
possible: a fake key reaching that provider's real 401, not a local
failure, with the remaining gap documented in the relevant README rather
than silently assumed complete.

- **Sprint 1** (voice loop) — done, live-verified end to end except
  PROP-101/102/108 (real telephony/TLS deployment).
- **Sprint 2** (turn-taking) — done: predictive barge-in live-verified
  against a real LiveKit call. PROP-201 (AEC3) doesn't apply to this
  architecture (documented in `docs/sprint-notes/sprint-2-turn-taking.md`);
  PROP-204's literal "exact millisecond" wording isn't achievable with
  Gemini's current transcription API.
- **Sprint 3** (property RAG & tools) — done, live-verified.
- **Sprint 4** (lead qualification & booking) — done: BANT extraction
  live-verified against a real Gemini call; calendar/SMS built against
  mocked-then-real-API-boundary-tested Google/Twilio clients.
- **Sprint 5** (fallback & compliance) — done except PROP-507 (stress
  testing, blocked on a real call to stress). Fair Housing filter is
  built and tested but not live-wired (documented open design problem,
  see `services/compliance/README.md`).
- **Sprint 6** (hardening & multi-tenancy) — done except PROP-608 (pilot
  launch, needs a real agency partner). RLS, Tenant Admin API, Grafana
  dashboards, security audit, the 12-scenario E2E voice test suite
  (live-verified against real Gemini), and a Locust load test
  (live-verified against a real local LiveKit server) are all built.

**The 6 remaining tickets**: PROP-8 (TLS — needs real deployment),
PROP-10 (AEC3 — doesn't apply to this architecture), PROP-13
(millisecond-exact transcript truncation — not achievable with Gemini's
current transcription API), PROP-23 (tool latency benchmarking at load),
PROP-40 (fallback stress testing — needs a real call to stress), PROP-49
(pilot launch — needs a real agency partner).

Per-service Definition of Done checklists (with dates and exact test
counts) live in each service's own README — this summary is the index,
not the source of truth.
