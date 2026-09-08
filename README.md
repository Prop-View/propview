# Propview — AI Real-Estate Voice Agent

Enterprise-grade, low-latency, full-duplex Voice AI agent for inbound real
estate calls: qualifies leads, queries live MLS/property data, books site
visits, and escalates to a human broker when needed.

- **Plan**: `Sprint Plan.md` — 6 sprints, 49 engineering tasks (PROP-101–608)
- **Architecture**: `docs/architecture.md` — supersedes the plan text where they differ
- **Tracking**: Jira project `PROP` (dspacejira) — task mapping in project memory
- **Team**: Aahil (Dev A — Backend/Telephony/Infra), Deepak (Dev B — AI/Data/Tools)

## Layout

```
infra/          Provisioning & deployment: telephony, LiveKit, GCP, observability
services/       Runtime services: audio, orchestrator, tool router, lead engine, ...
db/             Schema migrations and knowledge-base ingestion
tests/          Integration, E2E voice-scenario, and load test suites
docs/           Architecture reference and sprint documentation
```

Each subdirectory's README maps its contents back to specific PROP ticket
IDs from `Sprint Plan.md`. New tenant? Start at `docs/AGENCY_ONBOARDING.md`.

## Status

As of 2026-09-08, all 6 sprints have working code for every ticket except
the ones that need real cloud accounts this environment doesn't have
(Twilio/GCP/Google Calendar/Deepgram/OpenAI/Cartesia credentials) —
those are built and tested against mocks or the real API's auth layer
(a fake key reaching a real 401, not a local failure), with the gap
documented in the relevant README rather than silently assumed complete.

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
- **Sprint 6** (hardening & multi-tenancy) — RLS, Tenant Admin API,
  Grafana dashboards, and security audit done. PROP-604/605 (50-scenario
  E2E voice tests, load testing) and PROP-608 (pilot launch) remain —
  see `Sprint Plan.md` for what's left.

Per-service Definition of Done checklists (with dates and exact test
counts) live in each service's own README — this summary is the index,
not the source of truth.
