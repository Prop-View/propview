# Sprint 1 Setup & Deployment (PROP-109)

Status as of 2026-09-03: all Sprint 1 code is built and tested. PROP-101
(Twilio) and PROP-102 (LiveKit VM) are the only pieces still waiting on
real account credentials (Twilio Account SID/Auth Token, GCP project) —
everything else has been verified against real local instances of the
services involved (see each component's own README for exact test
evidence and dates).

## What Sprint 1 actually is

Per `Sprint Plan.md`: a caller dials a phone number, the call reaches a
LiveKit room over SIP, the orchestrator streams that audio to Gemini Live,
and Gemini's spoken response streams back to the caller — the "Hello
World" voice loop.

## Component map

| Component | Directory | Status | Depends on |
|---|---|---|---|
| PROP-101 SIP trunk + DID | `infra/telephony/provisioning/` | Code ready, not yet run (needs Twilio creds) | — |
| PROP-102 LiveKit server + SIP gateway | `infra/livekit/`, `infra/gcp/` | Code ready, not yet deployed (needs GCP project) | PROP-101 |
| PROP-103 Audio resampler | `services/audio-pipeline/` | Built & tested — not on the hot path (see below) | — |
| PROP-104 Gemini Live client | `services/gemini-client/` | Built & live-tested with a real API key | — |
| PROP-105 Orchestrator | `services/orchestrator/orchestrator.py` | Built & live-tested against a real LiveKit server | PROP-103, PROP-104 |
| PROP-106 Redis session store | `services/orchestrator/session_store.py` | Built & live-tested against real Redis | — |
| PROP-107 Frame-chunking unit tests | `services/audio-pipeline/tests/` | 13/13 passing | PROP-103 |

**Why PROP-103 isn't wired into PROP-105**: building the orchestrator
revealed that LiveKit's own SDK (`AudioStream`/`AudioSource`) resamples
audio internally, so the orchestrator talks to Gemini's 16kHz/24kHz PCM
directly and never touches raw G.711. Full explanation in
`../../services/orchestrator/README.md`.

## Standing up the full loop yourself

1. **PROP-101** — `infra/telephony/provisioning/README.md`. Needs a
   Twilio account (Account SID, Auth Token) and a chosen area code.
2. **PROP-102** — `infra/gcp/README.md` then `infra/livekit/README.md`.
   Needs a GCP project with billing + Compute Engine API enabled. Once
   deployed, feed its static IP back into PROP-101's
   `LIVEKIT_SIP_ORIGINATION_URI`.
3. **Redis** — `infra/redis/README.md`. For Sprint 1 scale, colocating
   `redis-server` on the same VM as LiveKit is enough.
4. **Gemini API key** — free, from https://aistudio.google.com/apikey.
   See `services/gemini-client/README.md`.
5. **Run the orchestrator**: `python services/orchestrator/main.py <room-name>`
   — connects to that room, bridges it to Gemini, runs until the caller
   hangs up. Verified live end-to-end (real LiveKit, real Redis, real
   Gemini) with a synthetic caller standing in for the phone leg.

## Testing without any of the above

Every component that doesn't strictly need a paid account has a
**local-only test path with no cloud dependency**:

- `infra/livekit/LOCAL_TESTING.md` — SIP → LiveKit room, via a free
  softphone on your LAN instead of Twilio.
- `services/gemini-client/test_mic_call.py` — talk to Gemini through your
  own mic/speakers, just needs a free API key.
- `services/orchestrator/tests/test_orchestrator_live.py` — the full
  LiveKit audio-plumbing path, using `livekit-server --dev` (installed
  locally via Homebrew) and a fake Gemini session, no API cost.
- `services/audio-pipeline/tests/`, `services/orchestrator/tests/test_session_store.py`
  — plain `pytest`, no external services beyond a local Redis for the
  latter.

## Known gaps going into PROP-108 / Sprint 2

- `main.py` takes an explicit room name — it doesn't yet auto-dispatch
  onto every new inbound SIP call (needs LiveKit's Agent Worker /
  job-dispatch system once PROP-102 is deployed and real calls exist).
- TLS (PROP-108) is blocked on PROP-102's VM existing.
- Barge-in (`Interrupted` events) only fires from Gemini's own
  server-side detection for now — real VAD-driven buffer clearing is
  PROP-203/204 (Sprint 2).
