"""
PROP-603: Tests for the Prometheus metrics -- verifies real counters
actually increment on the real global registry (not mocked -- the point
is to confirm the metric names/labels Grafana would query actually exist
and move), and that start_metrics_server() serves real Prometheus
exposition format over a real HTTP request.

Run: python -m pytest tests/test_metrics.py -v
"""

import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prometheus_client import REGISTRY

import metrics
import call_lifecycle
from metrics import CALLS_STARTED, RESPONSE_LATENCY_SECONDS, TOOL_CALLS, start_metrics_server


def _sample_value(metric_name: str, labels: dict) -> float | None:
    for family in REGISTRY.collect():
        for sample in family.samples:
            if sample.name == metric_name and sample.labels == labels:
                return sample.value
    return None


def test_calls_started_counter_increments():
    before = _sample_value("propview_calls_started_total", {"tenant_id": "test-metrics-tenant"}) or 0
    CALLS_STARTED.labels(tenant_id="test-metrics-tenant").inc()
    after = _sample_value("propview_calls_started_total", {"tenant_id": "test-metrics-tenant"})
    assert after == before + 1


def test_response_latency_histogram_records_observation():
    RESPONSE_LATENCY_SECONDS.labels(tenant_id="test-metrics-tenant-2").observe(0.45)
    count = _sample_value("propview_response_latency_seconds_count", {"tenant_id": "test-metrics-tenant-2"})
    assert count is not None
    assert count >= 1


def test_tool_calls_counter_has_outcome_label():
    TOOL_CALLS.labels(tenant_id="test-metrics-tenant-3", tool_name="search_properties", outcome="success").inc()
    value = _sample_value(
        "propview_tool_calls_total",
        {"tenant_id": "test-metrics-tenant-3", "tool_name": "search_properties", "outcome": "success"},
    )
    assert value == 1


def test_start_metrics_server_serves_real_prometheus_exposition_format():
    start_metrics_server(port=9099)
    CALLS_STARTED.labels(tenant_id="test-metrics-scrape").inc()

    with urllib.request.urlopen("http://localhost:9099/metrics", timeout=5) as resp:
        body = resp.read().decode()

    assert 'propview_calls_started_total{tenant_id="test-metrics-scrape"} 1.0' in body
    # Standard Prometheus exposition format markers -- confirms this is a
    # real Prometheus-compatible endpoint, not just some HTTP 200.
    assert "# HELP propview_calls_started_total" in body
    assert "# TYPE propview_calls_started_total counter" in body


def test_start_metrics_server_is_idempotent():
    start_metrics_server(port=9099)
    start_metrics_server(port=9099)  # must not raise (e.g. "address already in use")
    assert metrics._metrics_server_started is True


def test_worker_health_readiness_and_drain_endpoints(monkeypatch):
    monkeypatch.setattr(call_lifecycle, "_active_calls", 0)
    monkeypatch.setattr(call_lifecycle, "_draining", False)
    monkeypatch.setattr(
        metrics.WorkerMetricsHandler,
        "_dependencies_ready",
        staticmethod(lambda: (True, {"postgres": "connected", "redis": "connected"})),
    )
    start_metrics_server(port=9099)

    with urllib.request.urlopen("http://localhost:9099/healthz", timeout=5) as response:
        assert response.status == 200
        assert response.read() == b'{"status": "ok"}'

    with urllib.request.urlopen("http://localhost:9099/readyz", timeout=5) as response:
        assert response.status == 200
        assert b'"status": "ready"' in response.read()

    assert call_lifecycle.register_active_call()
    drain_request = urllib.request.Request("http://localhost:9099/drain", method="POST")
    with urllib.request.urlopen(drain_request, timeout=5) as response:
        assert response.status == 202
        assert b'"active_calls": 1' in response.read()

    with pytest.raises(urllib.error.HTTPError) as not_ready:
        urllib.request.urlopen("http://localhost:9099/readyz", timeout=5)
    assert not_ready.value.code == 503

    call_lifecycle.unregister_active_call()
    with urllib.request.urlopen("http://localhost:9099/drained", timeout=5) as response:
        assert b'"drained": true' in response.read()
    assert not call_lifecycle.register_active_call()
