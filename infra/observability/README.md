# PROP-603 / PROP-606: Observability & Security

- **PROP-206** — the actual tracing/logging middleware code lives in
  `../../services/orchestrator/telemetry.py` (built & live-verified) —
  it's application logic the orchestrator calls directly, not a deployment
  concern.
- **PROP-603** — Grafana dashboards (this directory).
- **PROP-606** — Security audit & secret rotation — see
  [`SECURITY_AUDIT.md`](SECURITY_AUDIT.md).

## Grafana dashboards (PROP-603)

`services/orchestrator/metrics.py` adds a real Prometheus `/metrics`
endpoint (via `prometheus_client`) alongside `telemetry.py`'s existing
OTel spans and structured JSON logs — the third observability leg the
plan's "OpenTelemetry + Prometheus" dashboard stack needs. Every metric
is a thin translation of an event `CallTelemetry` already tracks (call
start/end, response latency, interruptions by source, tool call
outcomes/latency, errors, fallback switches, human transfers) — see that
module's docstring for the full metric list.

```bash
cd services/orchestrator
python main.py <room-name>   # serves /metrics on :9090 by default (METRICS_PORT)
curl localhost:9090/metrics
```

**Verified** 2026-09-08: `services/orchestrator/tests/test_metrics.py`
does a real HTTP scrape against a real `start_http_server()` instance and
confirms genuine Prometheus exposition format (`# HELP`/`# TYPE` lines,
correctly-labeled sample values) — not just "the function didn't throw."

### Running the dashboard stack locally

```bash
cd infra/observability
docker compose up
# Prometheus: http://localhost:9091 (host 9090 is the orchestrator's own /metrics)
# Grafana:    http://localhost:3000 (anonymous viewer access enabled for local dev)
```

Grafana is pre-provisioned (`grafana/provisioning/`) with the Prometheus
datasource and the `Propview Operations` dashboard
(`grafana/dashboards/propview-operations.json`) — panels for call
volume, response latency (TTFA approximation, p50/p95), tool call error
rate, tool calls by name, interruptions by source (VAP predictive vs.
Gemini reactive — the actual signal PROP-202/203 was built to win),
orchestrator errors by source, fallback switches, human transfers, and
call duration.

**Honest scope notes**:
- **CSAT** is one of the plan's four named dashboard metrics
  (TTFA/Call-Volume/CSAT/Tool-Errors) and is **not implemented** — no
  post-call survey dispatch, response capture, or `csat_score` column
  exists anywhere in this codebase. The dashboard has a text panel
  saying so explicitly rather than a query against data that doesn't exist.
- The Prometheus scrape target is a single static `localhost:9090` —
  matches today's reality (one orchestrator process per call, run
  manually with an explicit room name, per `services/orchestrator/main.py`'s
  own docstring). Real service discovery (Kubernetes SD, DNS SRV) is a
  follow-up once a persistent multi-call worker process exists to
  discover.
- **Not live-verified against a running Grafana instance** — Docker
  wasn't available in this environment. `docker-compose.yml`,
  `prometheus.yml`, and both Grafana provisioning YAML files are
  confirmed to parse as valid YAML, and the dashboard JSON is confirmed
  valid JSON, but the actual "does Grafana render these panels
  correctly against real Prometheus data" round trip hasn't been run.

## Definition of Done (from Sprint Plan)

- [x] Grafana dashboards tracking TTFA, Call Volume, and Tool Errors.
- [ ] CSAT — not implemented anywhere in this codebase (documented gap,
      not a missing dashboard panel alone).
- [ ] Live-verified against a running Grafana/Prometheus stack — Docker
      unavailable in this environment.
