# PROP-501 / PROP-502: Cascaded Fallback Pipeline & Health Monitor

Deepgram STT → GPT-4o-mini → Cartesia TTS cascade that takes over when
Gemini Live degrades or drops, plus the health monitor that decides when
to trigger it. This is Fallback-layer **A** in the architecture reference
(`../../docs/architecture.md`) — telephony-provider failover (layer B)
is `../../infra/telephony/`, AI degradation modes (layer D, "disable
non-critical tools") is this pipeline's own scope decision (see below),
human escalation (layer E) is `../orchestrator/human_transfer.py`.

## Design: same interface as GeminiLiveSession, on purpose

`cascaded_session.py`'s `CascadedFallbackSession` implements the exact
same `GeminiSessionLike` protocol `../orchestrator/orchestrator.py`
already defines for `GeminiLiveSession` (`send_audio`,
`send_end_of_audio`, `send_tool_response`, `receive_events` yielding
`AudioChunk`/`TurnComplete`/`TranscriptChunk`). That's what makes
PROP-502's "auto-switch" possible without special-casing: the
orchestrator's `_switch_to_fallback()` just reassigns `self._gemini` to a
new `CascadedFallbackSession` and restarts the receive loop against it —
barge-in (`_publish_source.clear_queue()`), transcript capture, PII
masking, and telemetry are all engine-agnostic already.

## Scope decision: no tool calling during fallback

Maps directly onto the architecture reference's fallback layer D ("AI
degradation modes: disable non-critical tools"). During a Gemini outage,
the fallback offers a real (if reduced) voice conversation — it can still
talk, just not search live listings, capture BANT, or book appointments.
`send_tool_response` exists only to satisfy the shared protocol; this
session never emits `ToolCallRequest`, so it's never actually called.
Re-implementing the full Tool Router integration against GPT-4o-mini
would double this pipeline's scope for a path that's explicitly the
degraded/backup one, not the primary experience.

## Health monitor (PROP-502)

`health_monitor.py`'s `HealthMonitor` is a plain state machine, no I/O —
the orchestrator feeds it two signals it already has:
- `record_response_latency(latency_ms)` on every Gemini response (via
  `telemetry.py`'s `record_response_audio()`, which now returns the
  measured latency instead of keeping it purely internal). Triggers past
  the plan's exact **1200ms** threshold.
- `record_error()` on a caught exception from either audio-forwarding
  direction. Triggers after **2 consecutive** errors (one could be a
  transient blip; a successful response in between resets the streak).

Kept separate from `CallOrchestrator` so the triggering *policy*
(thresholds) is independently testable from the *mechanism* (actually
swapping sessions).

## Configuration

All optional — unset, the fallback is disabled entirely and a session
error/latency spike just ends the call, exactly as it did before this
existed:

```bash
# services/orchestrator/.env
DEEPGRAM_API_KEY=
OPENAI_API_KEY=
CARTESIA_API_KEY=
CARTESIA_VOICE_ID=
FALLBACK_LATENCY_THRESHOLD_MS=1200   # optional, defaults to the plan's threshold
```

`main.py`'s `_build_fallback_session_factory()` imports
`CascadedFallbackSession` lazily (inside the factory closure, not at
module load) — a deployment that never sets these env vars doesn't need
`deepgram-sdk`/`openai`/`cartesia` installed at all.

## Verification

No real Deepgram/OpenAI/Cartesia account is available in this
environment, but each client was run for real against its actual API
with an intentionally fake key, confirming the request construction
itself (not just plausible-looking mock behavior):

- **Deepgram**: `wss://api.deepgram.com` connection attempt reached a
  real `ApiError` from Deepgram's own auth layer.
- **OpenAI**: `chat.completions.create()` reached a real 401
  `AuthenticationError`.
- **Cartesia**: reached a real 401 `AuthenticationError` — and this is
  how a real bug got caught. The first version called the more
  obvious-looking (but deprecated) `tts.bytes()` directly as an async
  iterator, which raised `TypeError: 'async for' requires an object with
  __aiter__ method, got coroutine` (it returns a coroutine that must be
  awaited first). Fixed to use `tts.generate()` + `.iter_bytes()`
  instead, reconfirmed reaching the real 401 after the fix.

What's **not** verified: real transcription/completion/audio quality
with a working key, and the cascade has never been exercised against a
real live call (needs PROP-101/102 deployed, same gap as everything else
gated on real telephony).

```bash
cd services/fallback-pipeline
pip install -r requirements.txt
python -m pytest tests/ -v
```

**Verified passing** 2026-09-08: 19/19 —
`test_health_monitor.py` (8, pure logic), `test_deepgram_client.py` (5,
transcript-extraction against typed stand-ins for the SDK's result
variants), `test_cascaded_session.py` (6, full STT→LLM→TTS→TurnComplete
event sequencing with all three externals mocked).
`../orchestrator/tests/test_fallback_switch.py` (7 more) covers the
orchestrator-side swap mechanism: the switch is idempotent (both
forwarding tasks can hit errors around the same time), a failed factory
declines and stays on the primary engine, and `aclose()` correctly exits
the fallback session if one was created.

## Definition of Done (from Sprint Plan)

- [x] Cascaded fallback pipeline (Deepgram + GPT-4o-mini + Cartesia),
      swappable in as a drop-in replacement for the Gemini session.
- [x] Health monitor auto-switching on latency >1200ms or session drops.
- [x] AI degradation mode (tools disabled during fallback) — architecture
      reference's layer D.
- [ ] Live-verified against a real call with real API keys — see above.
- [ ] PROP-507 (stress testing fallback switches during active calls) —
      not built; needs the above live verification first.
