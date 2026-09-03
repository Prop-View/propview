# PROP-202/203/204: VAD / Predictive Barge-In

Silero VAD (ONNX) speech-activity detector for predictive turn-taking.
Detects the caller starting to speak *before* Gemini's own server-side
interruption signal round-trips back, so the orchestrator can clear the
agent's playout buffer sooner — the plan's <80ms barge-in target (PROP-204's
Definition of Done).

## Why this runs in-process, not as a deployed sidecar process

The plan describes this as a "lightweight...sidecar service." At an 80ms
total budget, an HTTP/gRPC hop on every 32ms audio window would burn a
real fraction of that budget for no benefit — the orchestrator already
receives raw caller PCM frame-by-frame in
`../orchestrator/orchestrator.py`'s `_forward_caller_audio_to_gemini`, so
running Silero directly in that loop is strictly faster than proxying the
same bytes to a second process and back. "Sidecar" here means a
logically separate, independently-testable module (`vap_processor.py`,
its own `requirements.txt` and tests) — not a separate OS process. If
this ever needs to scale off the orchestrator's own CPU, `vap_processor.py`
is exactly where a gRPC/HTTP wrapper would go without touching callers.

This is the same tradeoff `../orchestrator/README.md` already documents
for the resampler and TLS: prefer the library already in the hot path
over a literal reading of "separate service" when a network hop would
cost more than it buys.

## What's implemented

`vap_processor.py`'s `SpeechActivityDetector`:
- Wraps `silero-vad`'s `VADIterator` (the PyPI package bundles the ONNX
  model directly — no runtime download, matches the plan's "quantized
  ONNX...on CPU workers" cost mitigation for PROP-202's GPU-overhead risk).
- `.process(pcm16_bytes)` accepts caller audio in whatever chunk size
  LiveKit delivers (20ms frames don't line up with Silero's fixed
  512-sample/32ms window) — buffers internally, returns a list of
  `SpeechEvent(kind="speech_started"|"speech_ended", sample_offset=...)`
  for each transition detected.
- One instance per call (`VADIterator` carries hysteresis state across
  windows) — `../orchestrator/main.py` constructs a fresh one per
  `CallOrchestrator`.

Wired into `../orchestrator/orchestrator.py`: a `speech_started` event
during agent playback (`_agent_speaking == True`) immediately calls
`clear_queue()` — this is PROP-203's "CLEAR_BUFFER signal." Gemini's own
`Interrupted` event still fires independently afterward and is safe to
also call `clear_queue()` on (no-op on an already-cleared queue); which
one "wins" for a given interruption is recorded via
`telemetry.record_interrupted(source="vap_predictive"|"gemini")` so the
two paths' relative latency is observable once there's real traffic.

**Not implemented as a separate Kafka/RabbitMQ event bus message** — the
architecture reference's "event bus" for call/tool/lead/notification
events doesn't exist anywhere in this codebase yet (no Kafka/RabbitMQ
wiring at all); `CLEAR_BUFFER` here is a direct in-process method call
for the same latency reason as above. Revisit if/when a real event bus is
provisioned for other reasons (e.g. cross-service lead/notification
fan-out) and this signal is cheap to also publish there.

## What's explicitly out of scope here (see `../orchestrator/README.md`)

- **AEC3 (PROP-201)**: doesn't apply to this architecture. The caller is
  a SIP/PSTN LiveKit participant and the agent is a separate participant
  publishing its own track — there's no local speaker-into-mic loop for
  echo cancellation to remove (that's a browser/softphone concern).
- **Millisecond-exact transcript truncation (PROP-204's literal wording)**:
  Gemini's `output_transcription` streams text in chunks, not per-word
  timestamps, so truncation happens at chunk granularity. Documented gap,
  not silently approximated.

## Testing

```bash
cd services/vap-sidecar
pip install -r requirements.txt
python -m pytest tests/ -v
```

`tests/test_vap_processor.py` runs the **real ONNX model** against
`tests/fixtures/sample_speech.wav` — an 8s clip trimmed from
[silero-vad's own MIT-licensed test fixture](https://github.com/snakers4/silero-vad/blob/master/tests/data/test.wav),
not synthetic tones (a neural VAD model doesn't respond meaningfully to a
sine wave — the point is to verify real speech/silence transitions).

**Verified passing** 2026-09-04: detects real speech-start/end
transitions in the fixture, zero false positives on 2s of digital
silence, and — since LiveKit's 20ms frames (640 bytes) don't align with
Silero's 512-sample window — confirmed chunked delivery produces
identical events to feeding the whole buffer at once.

`../orchestrator/tests/test_orchestrator_barge_in.py` covers the
"only clear the queue if the agent was actually speaking" trigger logic
with fakes (no LiveKit/model dependency needed there).

## Definition of Done (from Sprint Plan)

- [x] Silero VAD sidecar deployed (in-process, see above) — ONNX backend
      per the plan's CPU-cost mitigation.
- [x] CLEAR_BUFFER signal wired from VAP to the LiveKit audio queue
      (PROP-203).
- [x] Verified against real speech audio (not yet a real phone call).
- [x] Live-verified end-to-end against a real LiveKit call with real
      recorded speech triggering the predictive CLEAR_BUFFER signal —
      `../orchestrator/tests/test_predictive_barge_in_live.py`, 2026-09-04.
      Still not verified against an actual PSTN phone call — needs
      PROP-101/102 deployed; `../orchestrator/README.md` tracks that.
- [ ] False-positive rate on real ambient noise (coughing, car noise —
      the plan's <10% target) — untested without real call audio.
- [ ] AEC3, millisecond-exact truncation: not applicable / not
      implemented, see above.
