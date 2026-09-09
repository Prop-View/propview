# Integration Tests

FastAPI TestClient-style suites against staging Postgres/Redis.

- **PROP-306 / PROP-23** — Tool execution latency & context injection.
  The "context injection" half is covered by
  `../../services/tool-router/README.md`'s live-verified
  `search_properties` test (a real Gemini response correctly referenced
  returned listing data). The "latency" half is now measured, live, by
  `latency_benchmark.py`:

  ```bash
  # Tool Router running (see ../../services/tool-router/README.md), a
  # real GEMINI_API_KEY loaded, one property seeded for tenant
  # "test-latency-bench"
  python latency_benchmark.py
  ```

  **Run 2026-09-09** — two separate measurements, since the plan's
  targets apply to different layers:
  - **Tool Router round trip alone** (HTTP → real Postgres query →
    response), 20 calls to `search_properties`: p50=1.7ms, p95=45.0ms,
    min=1.1ms, max=45.0ms. Comfortably **OK** against the plan's
    "enforce strict 350ms DB timeout" mitigation.
  - **Full turn latency** ("user question → agent starts speaking"),
    via 5 real Gemini Live sessions, measuring `send_text()` to the
    first `AudioChunk` after the tool round trip completes: samples
    5363ms, 2101ms, 1489ms, 1343ms, 1553ms → p50=1553ms, p95=5363ms,
    min=1343ms, max=5363ms. This **EXCEEDS** the plan's <900ms target at
    p95 (and even at p50) — the gap is Gemini's own model latency for
    tool-calling turns, not the Tool Router (which the first measurement
    shows is not the bottleneck). The plan's own documented mitigation
    for this — filler speech within 300ms while the real answer is
    prepared (`../../services/orchestrator/vocal_filler.py`, PROP-305,
    already built) — is the intended way this gets masked from the
    caller's perspective; it is not itself a latency fix, so this
    remains a genuine, unresolved gap against the raw <900ms target and
    is recorded here rather than papered over.
- **PROP-406** — Appointment booking and lead capture end-to-end. Covered
  by `../../services/tool-router/tests/test_booking.py` (real Postgres +
  real Redis, Google Calendar/Twilio mocked — full round trip: check
  availability → book → appointment row created → SMS dispatched → the
  double-booking-gets-rejected race) and
  `../../services/tool-router/tests/test_tool_router.py`'s
  `update_lead_qualification` cases (real contact/lead upsert, re-scoring,
  partial-update semantics). No separate suite lives in this directory —
  those tests already exercise the full API surface this ticket calls
  for; a second, duplicate suite here would just re-test the same
  endpoints against the same database.
