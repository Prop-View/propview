# Propview — AI Real-Estate Voice Agent

Enterprise-grade, low-latency, full-duplex Voice AI agent for inbound real
estate calls: qualifies leads, queries live MLS/property data, books site
visits, and escalates to a human broker when needed.

- **Guide**: `docs/GUIDE.md` — where every API key goes, how to use the
  product, and how the codebase is put together. Start here.
- **Plan**: `Sprint Plan.md` — 6 sprints, 49 engineering tasks (PROP-101–608)
- **Architecture**: `docs/architecture.md` — supersedes the plan text where they differ
- **Tracking**: Jira project `PROP` (dspacejira) — task mapping in project memory
- **Team**: Aahil (Dev A — Backend/Telephony/Infra), Deepak (Dev B — AI/Data/Tools)

## Quickstart

```bash
./scripts/setup_dev_env.sh   # one shared venv + wired-up .env files -- see scripts/README.md
source .venv/bin/activate    # Windows (Git Bash): source .venv/Scripts/activate
cd services/orchestrator && python tests/test_orchestrator_live.py   # proves the core loop works, no API keys/mic/phone needed
```

The setup script itself is cross-platform (macOS/Linux/Windows via Git
Bash) — it detects your Python version and venv layout automatically.

Then `docs/GUIDE.md` for API key placement, onboarding a tenant, and
running a real call, or any service's own README for what it does.

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

As of 2026-09-14: **51 of 52 tickets Done** (tracked in Jira project
`PROP`). Everything else is built and tested, either live-verified
against the real API/service or (where a real third-party account isn't
available in this environment — Twilio, Google Calendar OAuth, Deepgram,
OpenAI, Cartesia) verified as far as possible: a fake key reaching that
provider's real 401, not a local failure, with the remaining gap
documented in the relevant README rather than silently assumed complete.

Jira's ticket numbering (`PROP-1`–`PROP-52`) is a flat sequential list,
**not** the same as this plan's task IDs (`PROP-101`–`PROP-608`) — see
`CLAUDE.md` §1 for the exact mapping before quoting a ticket number from
either source.

- **Sprint 1** (voice loop) — done, live-verified end to end. PROP-101/102
  (real telephony/VM deployment) and PROP-108 (TLS) each have complete,
  runnable infra code; the one remaining step for all three is real cloud
  credentials/a real domain this environment doesn't have.
- **Sprint 2** (turn-taking) — done: predictive barge-in live-verified
  against a real LiveKit call, and transcript truncation on barge-in
  (PROP-204) live-verified against a real LiveKit call + real Redis
  context window. PROP-201 (AEC3) doesn't apply to this architecture
  (documented in `docs/sprint-notes/sprint-2-turn-taking.md`); PROP-204's
  literal "exact millisecond" wording isn't achievable with Gemini's
  current transcription API — chunk-granularity truncation is what's
  built and verified.
- **Sprint 3** (property RAG & tools) — done, live-verified, including a
  real latency benchmark (PROP-306/23): the Tool Router itself is well
  within budget, the full Gemini turn exceeds the plan's raw 900ms target
  at p95 — a real, documented finding, mitigated (not fixed) by the
  Interactive Vocal Filler.
- **Sprint 4** (lead qualification & booking) — done: BANT extraction
  live-verified against a real Gemini call; calendar/SMS built against
  mocked-then-real-API-boundary-tested Google/Twilio clients.
- **Sprint 5** (fallback & compliance) — done, including live fallback
  stress testing (PROP-507/40) that caught and fixed a real bug (a
  sub-threshold error was killing the caller-audio-forwarding task before
  the fallback could ever trigger). Fair Housing filter is built and
  tested but not live-wired (documented open design problem, see
  `services/compliance/README.md`).
- **Sprint 6** (hardening & multi-tenancy) — done except PROP-608 (pilot
  launch, needs a real agency partner — see below). RLS, Tenant Admin API,
  Grafana dashboards, the 12-scenario E2E voice test suite (live-verified
  against real Gemini), and a Locust load test (live-verified against a
  real local LiveKit server) are all built. The security audit's own
  biggest finding — no service-to-service authentication — is now fixed
  too: per-tenant API keys on admin-api, a shared internal secret on the
  Tool Router, both live-verified end to end (see
  `infra/observability/SECURITY_AUDIT.md` §3).

- **Post-plan additions** (Jira PROP-50/51/52, no Sprint Plan equivalent)
  — done: service-to-service authentication (per-tenant admin-api keys,
  a shared internal secret for the Tool Router), per-tenant agency
  branding (moved out of a process-level env var and into Postgres), and
  per-tenant rate limiting (Redis fixed-window counters on both admin-api
  and the Tool Router). All three came directly out of the security
  audit's own findings — see `infra/observability/SECURITY_AUDIT.md`.

**The 1 remaining ticket**: PROP-49 (plan `PROP-608`, soft launch pilot
deployment) — needs an actual real estate agency partner and live inbound
call traffic, which cannot be simulated or built in code.

Per-service Definition of Done checklists (with dates and exact test
counts) live in each service's own README — this summary is the index,
not the source of truth.

## License

Copyright (c) 2026 Aahil Shaik. All rights reserved. See `LICENSE`.
