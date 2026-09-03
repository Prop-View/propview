"""
PROP-206: OpenTelemetry tracing + structured JSON event logging.

Two complementary outputs per the Sprint Plan's observability section:
- OTel spans (one per call, tagged with call_id) for trace visualization.
- Structured JSON log lines matching the plan's exact schema (section 5),
  for the OpenSearch/Loki log pipeline the architecture reference calls for.

Honest scope note on latency: `response_latency_ms` below measures time
from the agent's last TurnComplete (it stopped talking) to its next
AudioChunk (it starts responding again) -- an approximation of end-to-end
response latency per turn. It is NOT the plan's precisely-defined TTFA
metric (Timestamp(First Audio Byte Sent) - Timestamp(User Finished
Speaking)), since Gemini's Live API doesn't surface an explicit
"user finished speaking" timestamp to the client in the current
integration (see gemini_live_client.py's event model). Refining this with
Gemini's input_transcription/waiting_for_input signals is a future
improvement, not implemented here.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span

SERVICE_NAME = "core-orchestrator"

_tracer_configured = False


def _configure_tracing() -> None:
    global _tracer_configured
    if _tracer_configured:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    else:
        exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_configured = True


def _get_tracer():
    _configure_tracing()
    return trace.get_tracer(SERVICE_NAME)


_json_logger = logging.getLogger("structured_events")
_json_logger.setLevel(logging.INFO)
if not _json_logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _json_logger.addHandler(_handler)
    _json_logger.propagate = False


def log_event(
    event: str,
    call_id: str,
    session_id: str = "",
    tenant_id: str = "",
    metrics: dict | None = None,
    payload: dict | None = None,
    level: str = "INFO",
) -> None:
    """Emit one structured JSON log line matching the Sprint Plan's schema."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level,
        "correlation_id": {"call_id": call_id, "session_id": session_id, "tenant_id": tenant_id},
        "service": SERVICE_NAME,
        "event": event,
        "metrics": metrics or {},
        "payload": payload or {},
    }
    _json_logger.info(json.dumps(record))


class CallTelemetry:
    """Owns the one OTel span for a call's lifetime plus its structured logs.

    Usage:
        telemetry = CallTelemetry(call_id=room.name, room_name=room.name)
        telemetry.start()
        ...
        telemetry.record_turn_complete()
        telemetry.record_response_audio()   # call on the first AudioChunk of a turn
        telemetry.record_interrupted()
        ...
        telemetry.end()
    """

    def __init__(self, call_id: str, room_name: str, session_id: str = "", tenant_id: str = ""):
        self._call_id = call_id
        self._room_name = room_name
        self._session_id = session_id
        self._tenant_id = tenant_id
        self._span: Span | None = None
        self._call_started_at = 0.0
        self._awaiting_response_since: float | None = None
        self._response_in_progress = False

    def start(self) -> None:
        self._call_started_at = time.monotonic()
        self._span = _get_tracer().start_span("call_session")
        self._span.set_attribute("call_id", self._call_id)
        self._span.set_attribute("room_name", self._room_name)
        log_event("call_started", self._call_id, self._session_id, self._tenant_id)

    def record_track_subscribed(self, participant_identity: str) -> None:
        if self._span:
            self._span.add_event("caller_audio_subscribed", {"participant": participant_identity})
        log_event(
            "caller_audio_subscribed",
            self._call_id,
            self._session_id,
            self._tenant_id,
            payload={"participant": participant_identity},
        )

    def record_response_audio(self) -> None:
        """Call on the first AudioChunk of a new agent response."""
        if self._response_in_progress:
            return  # only the first chunk of a turn marks the response start
        self._response_in_progress = True

        metrics = {}
        if self._awaiting_response_since is not None:
            latency_ms = (time.monotonic() - self._awaiting_response_since) * 1000
            metrics["response_latency_ms"] = round(latency_ms, 1)
            if self._span:
                self._span.set_attribute("last_response_latency_ms", latency_ms)

        if self._span:
            self._span.add_event("first_response_audio", metrics)
        log_event("first_response_audio", self._call_id, self._session_id, self._tenant_id, metrics=metrics)

    def record_turn_complete(self) -> None:
        self._response_in_progress = False
        self._awaiting_response_since = time.monotonic()
        if self._span:
            self._span.add_event("turn_complete")
        log_event("turn_complete", self._call_id, self._session_id, self._tenant_id)

    def record_interrupted(self, source: str = "gemini") -> None:
        """`source` distinguishes Gemini's own (reactive, server-side) barge-in
        signal from the VAP sidecar's (predictive, fires on caller speech
        onset without waiting on a round trip) -- see PROP-203."""
        if self._span:
            self._span.add_event("interrupted", {"source": source})
        log_event("interrupted", self._call_id, self._session_id, self._tenant_id, payload={"source": source})

    def record_error(self, source: str, error: Exception) -> None:
        if self._span:
            self._span.record_exception(error)
        log_event(
            "error",
            self._call_id,
            self._session_id,
            self._tenant_id,
            payload={"source": source, "error": str(error)},
            level="ERROR",
        )

    def end(self) -> None:
        duration_ms = (time.monotonic() - self._call_started_at) * 1000
        if self._span:
            self._span.set_attribute("call_duration_ms", duration_ms)
            self._span.end()
        log_event(
            "call_ended", self._call_id, self._session_id, self._tenant_id, metrics={"call_duration_ms": round(duration_ms, 1)}
        )
