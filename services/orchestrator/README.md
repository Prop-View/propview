# PROP-105 / PROP-106: Orchestrator Event Loop + Session Store

Bridges a LiveKit room's caller audio to a Gemini Live session
(`../gemini-client/`): subscribes to the caller's track, forwards audio
to Gemini, publishes Gemini's spoken response back into the room.
`session_store.py` (PROP-106) gives it a place to look up which room a
`call_id` belongs to, in Redis, with automatic expiry.

PROP-106 didn't have a directory assigned in the original project scaffold
— it's here rather than under `infra/` because it's runtime call-session
lookup logic the orchestrator itself owns, not a deployment/provisioning
concern.

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
python -m pytest tests/test_session_store.py -v
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

## Definition of Done (from Sprint Plan)

- [x] Orchestrator event loop connects LiveKit audio frames to Gemini.
- [x] Verified live against a real LiveKit server (fake Gemini session).
- [x] Redis session store: create/get/end/touch, verified against real
      Redis including actual TTL expiry timing (PROP-106).
- [x] `main.py` composes GeminiLiveSession + SessionStore + CallOrchestrator
      into one runnable process, verified live end-to-end (see above).
- [ ] Verified with a real phone call once PROP-101/102 are deployed.
- [ ] Auto-dispatch on new inbound calls (currently takes an explicit room name).
- [ ] Barge-in buffer clearing wired to real VAD signal (PROP-203/204, Sprint 2) —
      `Interrupted` events already call `clear_queue()`, but that event only
      fires from Gemini's own server-side interruption detection for now.
