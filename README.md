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
IDs from `Sprint Plan.md`.

## Status

Sprint 1 in progress:

- [x] PROP-101 — Twilio SIP trunk provisioning script (`infra/telephony/provisioning/`)
- [x] PROP-102 — LiveKit media server + SIP gateway (`infra/livekit/`, `infra/gcp/`)
- [ ] PROP-103 onward — see `Sprint Plan.md`
