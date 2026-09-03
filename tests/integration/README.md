# Integration Tests

FastAPI TestClient-style suites against staging Postgres/Redis.

- **PROP-306** — Tool execution latency & context injection. The
  "context injection" half is covered by
  `../../services/tool-router/README.md`'s live-verified
  `search_properties` test (a real Gemini response correctly referenced
  returned listing data). The "latency" half (plan target: <900ms
  including DB query, or filler speech within 300ms) is not yet measured
  under load — see that README's Definition of Done.
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
