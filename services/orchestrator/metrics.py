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

import json
import asyncio
import os
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from prometheus_client import Counter, Gauge, Histogram
from prometheus_client.exposition import MetricsHandler

from call_lifecycle import active_call_count, is_draining, request_drain

_metrics_server_started = False
_metrics_server: ThreadingHTTPServer | None = None


class WorkerMetricsHandler(MetricsHandler):
    @staticmethod
    def _dependencies_ready() -> tuple[bool, dict[str, str]]:
        """Check the worker's required stores without blocking its event loop."""
        async def check() -> dict[str, str]:
            status = {"postgres": "connected", "redis": "connected"}
            database_url = os.environ.get("DATABASE_URL")
            redis_url = os.environ.get("REDIS_URL")
            if not database_url:
                status["postgres"] = "offline"
            else:
                try:
                    import asyncpg

                    connection = await asyncio.wait_for(asyncpg.connect(database_url), timeout=2)
                    try:
                        await connection.fetchval("SELECT 1")
                    finally:
                        await connection.close()
                except Exception:
                    status["postgres"] = "offline"
            if not redis_url:
                status["redis"] = "offline"
            else:
                try:
                    from redis.asyncio import Redis

                    client = Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
                    try:
                        await asyncio.wait_for(client.ping(), timeout=2)
                    finally:
                        await client.aclose()
                except Exception:
                    status["redis"] = "offline"
            return status

        dependencies = asyncio.run(check())
        return all(value == "connected" for value in dependencies.values()), dependencies

    def _json_response(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._json_response(200, {"status": "ok"})
            return
        if path == "/readyz":
            dependencies_ready, dependencies = self._dependencies_ready()
            ready = not is_draining() and dependencies_ready
            self._json_response(
                200 if ready else 503,
                {
                    "status": "ready" if ready else ("draining" if is_draining() else "not_ready"),
                    "active_calls": active_call_count(),
                    "dependencies": dependencies,
                },
            )
            return
        if path == "/drained":
            active_calls = active_call_count()
            draining = is_draining()
            self._json_response(
                200,
                {"draining": draining, "active_calls": active_calls, "drained": draining and active_calls == 0},
            )
            return
        super().do_GET()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/drain":
            self.send_error(404)
            return
        active_calls = request_drain()
        self._json_response(202, {"status": "draining", "active_calls": active_calls})


def _serve_metrics(server: ThreadingHTTPServer) -> None:
    server.serve_forever()


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
    global _metrics_server_started, _metrics_server
    if _metrics_server_started:
        return
    _metrics_server = ThreadingHTTPServer(("", port), WorkerMetricsHandler)
    thread = threading.Thread(target=_serve_metrics, args=(_metrics_server,), daemon=True)
    thread.start()
    _metrics_server_started = True


CALLS_STARTED = Counter("propview_calls_started_total", "Calls started", ["tenant_id"])
CALLS_ENDED = Counter("propview_calls_ended_total", "Calls ended", ["tenant_id"])
CALL_FAILURES = Counter("propview_call_failures_total", "Calls with a failed audio-forwarding task", ["tenant_id"])
ACTIVE_CALLS = Gauge("propview_active_calls", "Active call sessions", ["tenant_id"])
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
