"""
PROP-603: Prometheus metrics -- the third leg of observability alongside
telemetry.py's OTel spans and structured JSON logs. `../../infra/observability/`'s
Grafana dashboards query these directly (TTFA, call volume, tool errors,
per the plan's dashboard requirements; CSAT is not implemented anywhere
in this codebase -- there's no post-call survey mechanism, see that
directory's dashboard README for the honest gap note).

Deliberately a thin translation layer over events CallTelemetry already
tracks, not a second instrumentation effort -- every metric here
corresponds 1:1 to an existing CallTelemetry method or orchestrator
log_event call site.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram, start_http_server

_metrics_server_started = False


def start_metrics_server(port: int = 9090) -> None:
    """Starts prometheus_client's built-in /metrics HTTP endpoint in a
    background thread. Call once per process; safe to call more than
    once (a no-op after the first call).

    Honest scope note: this orchestrator runs one process per call today
    (main.py's own docstring -- no LiveKit Agent Worker dispatch exists
    yet to run many calls in one persistent process). A /metrics endpoint
    on a short-lived, per-call process isn't yet useful for the kind of
    aggregate dashboards Grafana is meant to show -- each process would
    need its own scrape target, and most calls would end before
    Prometheus's next scrape interval even fires. Implemented correctly
    now (real counters, real HTTP endpoint, verified with a live scrape
    in tests) so the wiring is already in place once a persistent
    multi-call worker process exists to make it actually useful."""
    global _metrics_server_started
    if _metrics_server_started:
        return
    start_http_server(port)
    _metrics_server_started = True


CALLS_STARTED = Counter("propview_calls_started_total", "Calls started", ["tenant_id"])
CALLS_ENDED = Counter("propview_calls_ended_total", "Calls ended", ["tenant_id"])
CALL_DURATION_SECONDS = Histogram(
    "propview_call_duration_seconds",
    "Call duration",
    ["tenant_id"],
    buckets=(10, 30, 60, 120, 300, 600, 1800),
)

# "TTFA" per the plan's dashboard requirement -- see telemetry.py's own
# honest scope note: this measures last-TurnComplete-to-next-AudioChunk,
# an approximation of true TTFA, not Timestamp(first audio byte) -
# Timestamp(user finished speaking) exactly.
RESPONSE_LATENCY_SECONDS = Histogram(
    "propview_response_latency_seconds",
    "Agent per-turn response latency (TTFA approximation -- see telemetry.py)",
    ["tenant_id"],
    buckets=(0.1, 0.2, 0.3, 0.5, 0.6, 0.8, 1.0, 1.2, 2.0, 5.0),
)

INTERRUPTIONS = Counter("propview_interruptions_total", "Barge-in interruptions", ["tenant_id", "source"])

ERRORS = Counter("propview_errors_total", "Orchestrator-side errors", ["tenant_id", "source"])

TOOL_CALLS = Counter("propview_tool_calls_total", "Tool calls", ["tenant_id", "tool_name", "outcome"])
TOOL_LATENCY_SECONDS = Histogram(
    "propview_tool_latency_seconds",
    "Tool call latency",
    ["tenant_id", "tool_name"],
    buckets=(0.1, 0.2, 0.3, 0.5, 0.9, 1.5, 3.0),
)

FALLBACK_SWITCHES = Counter("propview_fallback_switches_total", "Cascaded fallback (PROP-501/502) switches", ["tenant_id"])
HUMAN_TRANSFERS = Counter("propview_human_transfers_total", "Human broker transfers (PROP-503)", ["tenant_id", "outcome"])
