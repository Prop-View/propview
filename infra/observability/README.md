# Observability

Owner: Aahil (Dev A)

Grafana dashboards and the OpenTelemetry tracing middleware. Per the
architecture reference, LangSmith also traces LLM-specific spans alongside
OTel, and structured logs/audit trails go to OpenSearch/Loki separately —
see `../../docs/architecture.md`.

- **PROP-206** — OpenTelemetry logging middleware (call ID + latency)
- **PROP-603** — Grafana dashboards (TTFA, call volume, CSAT, tool errors)
- **PROP-606** — Security audit & secret rotation (Vault/AWS Secrets Manager)
