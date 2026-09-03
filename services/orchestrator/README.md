# PROP-105 / PROP-106 / PROP-206: Orchestrator, Session Store & Telemetry

Bridges a LiveKit room's caller audio to a Gemini Live session
(`../gemini-client/`): subscribes to the caller's track, forwards audio
to Gemini, publishes Gemini's spoken response back into the room.
`session_store.py` (PROP-106) gives it a place to look up which room a
`call_id` belongs to, in Redis, with automatic expiry. `telemetry.py`
(PROP-206) emits OpenTelemetry spans and structured JSON logs for the
call's lifecycle.

Neither PROP-106 nor PROP-206 had a directory assigned in the original
project scaffold — both are here rather than under `infra/` because
they're runtime logic the orchestrator itself owns and calls directly,
not a deployment/provisioning concern. (`infra/observability/` still
covers the *deployment* side — Grafana dashboards, an OTel collector — once
there's real infra to point at.)

## Telemetry (PROP-206)

`CallTelemetry` wraps one OTel span per call plus structured JSON logs
matching the Sprint Plan's exact schema (section 5): `correlation_id`
(call_id/session_id/tenant_id), `service`, `event`, `metrics`, `payload`.
Emits on: `call_started`, `caller_audio_subscribed`, `first_response_audio`
(with `response_latency_ms`), `turn_complete`, `interrupted`, `error`,
`call_ended` (with `call_duration_ms`).

**Honest scope note**: `response_latency_ms` measures time from the
agent's last `TurnComplete` to its next `AudioChunk` — an approximation of
per-turn response latency, not the plan's precisely-defined TTFA
(`Timestamp(First Audio Byte Sent) - Timestamp(User Finished Speaking)`).
Gemini's Live API doesn't surface an explicit "user finished speaking"
timestamp to the client in the current integration. Refining this with
Gemini's `input_transcription`/`waiting_for_input` signals is a documented
future improvement, not implemented here.

Defaults to a console span exporter for local dev; set
`OTEL_EXPORTER_OTLP_ENDPOINT` to ship to a real collector once one exists
(Sprint 6 / PROP-603).

**Verified live** 2026-09-03 as part of the full orchestrator test: real
spans exported with correct `call_id`/`room_name` attributes and
`response_latency_ms` values, structured JSON logs matching the schema
exactly, `call_started`/`call_ended` both firing.

## Important finding from building this

Inspecting the installed `livekit` (rtc) SDK directly (same approach as
`../gemini-client/`) turned up something that changes how PROP-103 gets
used: `rtc.AudioStream.from_track(..., sample_rate=16000)` and
`rtc.AudioSource(sample_rate=24000, ...)` do **real resampling inside
LiveKit's own media engine** — confirmed live, not just from docs (see
Testing below). So this orchestrator talks to Gemini's native
16kHz-in/24kHz-out directly and never touches raw G.711 bytes.

**`../audio-pipeline/`'s custom G.711/resampler is correct and tested, but
isn't wired in here** — LiveKit's SIP bridge plus this SDK's rate-converting
AudioStream/AudioSource already cover 8kHz↔16kHz end to end, and stacking a
second (lower-quality, linear-interpolation) resampler on top would only
hurt audio quality for no benefit. It stays available for any future path
that touches raw G.711 outside LiveKit (e.g. a non-LiveKit fallback stack).

## Setup

```bash
cd services/orchestrator
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY; LiveKit/Redis defaults match local dev
```

`main.py` adds `../gemini-client/` to `sys.path` itself at startup, so
`gemini_live_client` doesn't need to be separately installed or put on
`PYTHONPATH` by hand.

## Running a call

```bash
python main.py <room-name>
```

Connects to `<room-name>` as the agent, bridges it to Gemini, and runs
until the caller disconnects (or Ctrl+C). This is the actual process a
deployed VM would run — not yet wired to auto-dispatch on every new
inbound SIP call (that needs LiveKit's Agent Worker / job-dispatch system,
a separate step once PROP-102 is deployed and real calls exist to
dispatch against); for now it's invoked with an explicit room name.

**Verified live end-to-end** 2026-09-03 with real LiveKit, real Redis, and
a real Gemini API key (no telephony — a synthetic caller participant
stood in for the phone leg): the process joined the room, created its
Redis session, subscribed to the caller's audio track, and — when the
caller disconnected — cleanly cancelled its forwarding tasks, closed the
Gemini session, deleted the Redis session, disconnected from the room, and
exited.

For local Redis: `brew install redis && brew services start redis` (or
`redis-server` directly). See `../../infra/redis/README.md` for cloud
deployment options.

## Testing

`tests/test_session_store.py` runs against a **real Redis instance** (not
mocked — the point is to verify actual TTL/expiry timing):

```bash
redis-server &   # or: brew services start redis
python -m pytest tests/test_session_store.py tests/test_transcript_store.py tests/test_orchestrator_barge_in.py -v
```

**Verified passing** 2026-09-03: all 7 cases, including a real 2.5s wait
to confirm TTL-based expiry and a touch()-refreshes-TTL check.


`tests/test_orchestrator_live.py` is a **live integration test**, not a
pytest unit test — it needs a real LiveKit server:

```bash
livekit-server --dev &
python tests/test_orchestrator_live.py
```

It uses a fake Gemini session (echoes audio back, no API key/cost needed)
to isolate and verify the LiveKit plumbing itself. **Verified passing**
2026-09-03 against `livekit-server --dev` (v1.13.6): two real participants
join a room, the caller publishes synthetic 8kHz audio, the orchestrator
correctly receives it resampled to 16kHz (confirmed via received chunk
sizes), and the caller correctly receives the echoed audio back at 24kHz
on the agent's published track. Real speech + real Gemini wasn't tested
together here since PROP-104's separate live test already validated the
Gemini side — the two aren't yet exercised in the same run.

`tests/test_predictive_barge_in_live.py` is the same kind of live test,
focused on PROP-202/203: real LiveKit server, real Silero ONNX VAD, a
real recorded-speech WAV as the "caller," and a fake Gemini that never
stops talking on its own (isolates the predictive path). **Verified
passing** 2026-09-04 — see the barge-in section above for the exact
result.

## Definition of Done (from Sprint Plan)

- [x] Orchestrator event loop connects LiveKit audio frames to Gemini.
- [x] Verified live against a real LiveKit server (fake Gemini session).
- [x] Redis session store: create/get/end/touch, verified against real
      Redis including actual TTL expiry timing (PROP-106).
- [x] `main.py` composes GeminiLiveSession + SessionStore + CallOrchestrator
      into one runnable process, verified live end-to-end (see above).
- [x] OpenTelemetry spans + structured JSON logs tracking call_id and
      per-turn response latency, verified live (PROP-206).
- [x] `tool_client.py` registers `../tool-router/`'s tools with Gemini and
      dispatches `ToolCallRequest` events to it, logging a
      `tool_execution_completed` structured event (plan section 5's exact
      schema) per call. **Live-verified** 2026-09-03: real text query →
      real `search_properties` call → real Postgres data → real spoken
      response, wired through `main.py`. Closes the "not yet registered
      as a Gemini tool" gap noted in the Tool Router's own README.
- [x] Speech transcription captured both directions (`TranscriptChunk`,
      `../gemini-client/`) and, on call end, PII-masked
      (`../compliance/pii_masking.py`, PROP-506) and persisted to
      `interactions.transcript` via `transcript_store.py` — the write path
      PROP-506's own README had flagged as missing. `DATABASE_URL` unset
      skips it entirely (safe no-op for local dev without Postgres).
- [x] Predictive barge-in (PROP-202/203/204): `../vap-sidecar/`'s Silero
      VAD runs in-process on every caller audio frame; a detected speech
      onset during agent playback clears the playout queue immediately,
      without waiting on Gemini's own server round-trip `Interrupted`
      signal. `_agent_speaking` tracks which source (VAP or Gemini) is
      "first" for a given interruption so both can coexist safely —
      `telemetry.record_interrupted(source=...)` tags which one fired.
      Set `ENABLE_PREDICTIVE_BARGE_IN=false` to disable and fall back to
      Gemini's reactive signal only. **Verified live** 2026-09-04
      (`tests/test_predictive_barge_in_live.py`) against a real LiveKit
      server: a real caller track publishing real recorded speech, real
      Silero ONNX inference, and a fake continuously-talking Gemini
      (isolates the predictive path from Gemini's own reactive signal) —
      `clear_queue()` fired within one 20ms audio frame of speech onset,
      and the `interrupted` OTel span event recorded
      `source="vap_predictive"`.
- [ ] OTLP export to a real collector/Grafana once one exists (PROP-603).
- [ ] Verified with a real phone call once PROP-101/102 are deployed.
- [ ] Auto-dispatch on new inbound calls (currently takes an explicit room name).
- [ ] Word-level transcript truncation at the exact millisecond of
      interruption (the plan's literal PROP-204 wording) — Gemini's
      `output_transcription` streams in text chunks, not per-word
      timestamps, so the current implementation truncates at
      utterance/chunk granularity instead. Noted as a known gap, not
      silently approximated.
- [ ] AEC3 (PROP-201): not implemented. This architecture never actually
      needs it — the caller is a SIP/PSTN participant and the agent is a
      separate LiveKit participant publishing its own track, so there's no
      local mic-hears-its-own-speaker loop for AEC to cancel (that's a
      browser-softphone problem). Real PSTN-side echo, if any, is the
      telco/SIP trunk's concern, not this service's. See
      `../vap-sidecar/README.md`.
