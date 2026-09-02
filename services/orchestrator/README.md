# PROP-105: Orchestrator Event Loop

Bridges a LiveKit room's caller audio to a Gemini Live session
(`../gemini-client/`): subscribes to the caller's track, forwards audio
to Gemini, publishes Gemini's spoken response back into the room.

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
# gemini_live_client must be importable -- either install ../gemini-client
# as a package, or run with both dirs on PYTHONPATH (see the test for the pattern)
```

## Testing

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

## Definition of Done (from Sprint Plan)

- [x] Orchestrator event loop connects LiveKit audio frames to Gemini.
- [x] Verified live against a real LiveKit server (fake Gemini session).
- [ ] Verified with a real phone call once PROP-101/102 are deployed.
- [ ] Barge-in buffer clearing wired to real VAD signal (PROP-203/204, Sprint 2) —
      `Interrupted` events already call `clear_queue()`, but that event only
      fires from Gemini's own server-side interruption detection for now.
