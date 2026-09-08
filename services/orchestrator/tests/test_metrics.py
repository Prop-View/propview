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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prometheus_client import REGISTRY

import metrics
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
