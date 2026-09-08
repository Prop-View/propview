"""
PROP-502: Unit tests for the health monitor's triggering policy -- pure
state machine, no I/O.

Run: python -m pytest tests/test_health_monitor.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from health_monitor import HealthMonitor


def test_latency_under_threshold_does_not_trigger():
    monitor = HealthMonitor(latency_threshold_ms=1200)
    monitor.record_response_latency(800)
    assert monitor.should_fallback is False


def test_latency_over_threshold_triggers():
    monitor = HealthMonitor(latency_threshold_ms=1200)
    monitor.record_response_latency(1500)
    assert monitor.should_fallback is True
    assert "1500ms" in monitor.trigger_reason


def test_none_latency_is_ignored():
    monitor = HealthMonitor(latency_threshold_ms=1200)
    monitor.record_response_latency(None)
    assert monitor.should_fallback is False


def test_single_error_does_not_trigger_by_default():
    monitor = HealthMonitor(consecutive_errors_threshold=2)
    monitor.record_error()
    assert monitor.should_fallback is False


def test_consecutive_errors_reaching_threshold_triggers():
    monitor = HealthMonitor(consecutive_errors_threshold=2)
    monitor.record_error()
    monitor.record_error()
    assert monitor.should_fallback is True
    assert "2 consecutive" in monitor.trigger_reason


def test_successful_response_resets_error_streak():
    monitor = HealthMonitor(consecutive_errors_threshold=2)
    monitor.record_error()
    monitor.record_response_latency(500)  # a normal response in between
    monitor.record_error()
    assert monitor.should_fallback is False  # streak was reset, this is only error #1 again


def test_trigger_reason_is_not_overwritten_by_a_later_trigger():
    monitor = HealthMonitor(latency_threshold_ms=1200)
    monitor.record_response_latency(1500)
    first_reason = monitor.trigger_reason
    monitor.record_error()
    monitor.record_error()
    assert monitor.trigger_reason == first_reason


def test_reset_clears_triggered_state():
    monitor = HealthMonitor(latency_threshold_ms=1200, consecutive_errors_threshold=2)
    monitor.record_response_latency(1500)
    assert monitor.should_fallback is True

    monitor.reset()

    assert monitor.should_fallback is False
    assert monitor.trigger_reason is None
    monitor.record_error()
    assert monitor.should_fallback is False  # error streak also reset, not just the trigger flag
