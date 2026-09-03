# Observability

Owner: Aahil (Dev A)

Deployment-side observability: an OTel collector config and Grafana
dashboards, once there's real infra to point them at. Per the architecture
reference, LangSmith also traces LLM-specific spans alongside OTel, and
structured logs/audit trails go to OpenSearch/Loki separately — see
`../../docs/architecture.md`.

- **PROP-206** — the actual tracing/logging middleware code lives in
  `../../services/orchestrator/telemetry.py` (built & live-verified) —
  it's application logic the orchestrator calls directly, not a deployment
  concern. This directory would hold an OTel collector config once one is
  needed (currently exports straight to console for local dev).
- **PROP-603** — Grafana dashboards (TTFA, call volume, CSAT, tool errors)
- **PROP-606** — Security audit & secret rotation (Vault/AWS Secrets Manager)
