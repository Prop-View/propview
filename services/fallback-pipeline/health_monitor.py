"""
PROP-502: Health Monitor -- watches the active S2S engine's response
latency and error signals, and decides when to trigger PROP-501's
cascaded fallback. Per the plan: auto-switch if latency exceeds 1200ms or
the session drops.

Deliberately a plain state machine with no I/O of its own -- the
orchestrator feeds it signals it already has (telemetry's measured
response latency, caught exceptions), and reads `should_fallback` back
out. Kept separate from CallOrchestrator so the triggering *policy*
(thresholds, what counts as "enough" errors) is independently testable
from the *mechanism* (actually swapping sessions, in orchestrator.py).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("fallback_pipeline.health_monitor")

DEFAULT_LATENCY_THRESHOLD_MS = 1200  # plan's exact threshold
DEFAULT_CONSECUTIVE_ERRORS_THRESHOLD = 2  # one error could be a transient blip; two in a row is a real problem


class HealthMonitor:
    def __init__(
        self,
        latency_threshold_ms: float = DEFAULT_LATENCY_THRESHOLD_MS,
        consecutive_errors_threshold: int = DEFAULT_CONSECUTIVE_ERRORS_THRESHOLD,
    ):
        self._latency_threshold_ms = latency_threshold_ms
        self._consecutive_errors_threshold = consecutive_errors_threshold
        self._consecutive_errors = 0
        self._triggered = False
        self._trigger_reason: str | None = None

    def record_response_latency(self, latency_ms: float | None) -> None:
        """A response arriving at all resets the error streak (the session
        is clearly still alive), even if this particular latency also
        happens to trip the threshold."""
        if latency_ms is None:
            return
        self._consecutive_errors = 0
        if latency_ms > self._latency_threshold_ms:
            self._trigger(f"response latency {latency_ms:.0f}ms exceeded {self._latency_threshold_ms:.0f}ms threshold")

    def record_error(self) -> None:
        self._consecutive_errors += 1
        if self._consecutive_errors >= self._consecutive_errors_threshold:
            self._trigger(f"{self._consecutive_errors} consecutive session errors")

    def _trigger(self, reason: str) -> None:
        if self._triggered:
            return  # already triggered -- don't spam the log or overwrite the original reason
        self._triggered = True
        self._trigger_reason = reason
        logger.warning("Health monitor triggered fallback: %s", reason)

    @property
    def should_fallback(self) -> bool:
        return self._triggered

    @property
    def trigger_reason(self) -> str | None:
        return self._trigger_reason

    def reset(self) -> None:
        """Call once the orchestrator has actually switched to the fallback
        session, so the monitor doesn't immediately re-trigger on stale state."""
        self._triggered = False
        self._trigger_reason = None
        self._consecutive_errors = 0
