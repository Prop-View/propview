# Sprint 2 Turn-Taking State Machine & Buffer Clearing (PROP-208)

Status as of 2026-09-04: predictive barge-in (PROP-202/203) is built,
unit-tested, and live-verified against a real LiveKit server with real
Silero ONNX inference on real recorded speech (see below). Speech
transcription capture (feeds PROP-204) is built and unit-tested. AEC3
(PROP-201) is deliberately not implemented — see below. Full 15-scenario
E2E interruption testing against a real *phone call* (PROP-207) is not
done — needs PROP-101/102 deployed, same gap Sprint 1's `PROP-109` doc
flags.

## Component map

| Component | Directory | Status | Depends on |
|---|---|---|---|
| PROP-201 AEC3 | — | **Not applicable** to this architecture, see below | PROP-102 |
| PROP-202 VAD/VAP sidecar | `services/vap-sidecar/` | Built & tested against real speech audio | PROP-105 |
| PROP-203 CLEAR_BUFFER signal | `services/orchestrator/orchestrator.py` | Built & live-verified against a real LiveKit call | PROP-201*, PROP-202 |
| PROP-204 Transcript truncation on barge-in | `services/orchestrator/orchestrator.py`, `transcript_store.py` | Partially built — chunk-granularity, not word-exact (see below) | PROP-106, PROP-203 |
| PROP-205 Persona prompt | `services/prompts/` | Built (earlier commit) | — |
| PROP-206 OTel logging | `services/orchestrator/telemetry.py` | Built & live-verified (earlier commit) | PROP-105 |
| PROP-207 E2E interruption testing | — | **Not done** — needs real caller/mic audio | PROP-203 |

\* PROP-201 was a listed dependency of PROP-203 in the plan; it turned out
not to be needed for this signal to work (see below), so PROP-203 shipped
without it.

## Two interruption signals, one queue

The agent's playout buffer can be cleared by either of two independent
signals, and both are kept rather than picking one:

1. **VAP predictive** (`services/vap-sidecar/vap_processor.py`): Silero
   VAD runs on every caller audio frame as it arrives in the
   orchestrator's own forwarding loop. A `speech_started` transition
   while the agent is mid-utterance clears the queue immediately — no
   network round trip.
2. **Gemini reactive** (`services/gemini-client/gemini_live_client.py`'s
   `Interrupted` event): Gemini's own server-side turn-detection, which
   necessarily arrives after a WebSocket round trip to Google's servers.

Whichever fires first actually clears the queue; the other is a safe
no-op (`AudioSource.clear_queue()` on an already-empty queue does
nothing). `CallOrchestrator._agent_speaking` is the shared guard that
prevents either signal from "interrupting" a turn that already ended, and
`telemetry.record_interrupted(source=...)` tags which one won for a given
call — once there's real call traffic, that tag is how to measure whether
the predictive path is actually beating Gemini's reactive one in practice
(the whole reason it was built).

## Why AEC3 isn't implemented

The plan's PROP-201 (WebRTC AEC3 into the LiveKit pipeline) targets a
scenario this architecture doesn't have: a participant whose own
microphone picks up its own speaker output (a browser softphone on
speakers, or a physical handset with poor isolation). Here, the caller is
a SIP/PSTN participant (audio arrives as RTP from the phone network, not
from a local mic listening to a local speaker) and the AI agent is a
*separate* LiveKit participant publishing its own track — there is no
shared mic/speaker loop for AEC to cancel. Any echo on a real PSTN call
would originate on the telephony carrier's side of the SIP trunk, which
is that provider's concern, not this media pipeline's.

This was reconfirmed, not just assumed, when building PROP-203: if AEC3
were actually a hard dependency of the CLEAR_BUFFER signal (as the plan's
dependency column implies), PROP-203 would have needed it to work
end-to-end. It doesn't — the VAD sidecar and Gemini's own interrupt
signal both operate correctly without any echo-cancellation stage in
front of them, because there's no echo to cancel in the first place.

## Known gap: PROP-204's literal wording

The plan's Definition of Done: *"Redis context window accurately
truncates text to match the word spoken at the exact millisecond of
interruption."* What's actually implemented
(`orchestrator._record_transcript_chunk`) truncates at Gemini
`output_transcription` chunk boundaries, not individual words with
millisecond timestamps — Gemini's Live API doesn't expose word-level
timing on its transcription stream in the current integration (same
honest-scope note `telemetry.py` already makes about TTFA). The
transcript stored is accurate up to "what had been said by the last
completed chunk before interruption," which is what actually reaches
Postgres via `transcript_store.py` (PROP-506's persistence path) — not
literally the exact word.

## Testing

- `services/vap-sidecar/tests/test_vap_processor.py` — real Silero ONNX
  model against a real 8s speech/silence recording. 4/4 passing.
- `services/orchestrator/tests/test_orchestrator_barge_in.py` — the
  "only clear the queue if the agent was actually speaking" trigger logic,
  with fakes. 3/3 passing.
- `services/orchestrator/tests/test_predictive_barge_in_live.py` — real
  LiveKit server, real Silero ONNX VAD, a real recorded-speech WAV
  published as the caller's track, a fake continuously-talking Gemini
  session (isolates the predictive path from Gemini's own reactive
  signal). **Verified passing** 2026-09-04: `clear_queue()` fired via the
  VAP path, tagged `source="vap_predictive"` in the OTel span, within one
  20ms audio frame of the caller's simulated speech onset.
- Not built: the plan's full 15-scenario audio-injection framework
  (PROP-207/`tests/e2e-voice/`) covering all the interruption edge cases
  in `Sprint Plan.md` section 3 (false positives on coughing/car noise,
  mid-sentence topic changes, etc.) — what's verified above is the
  CLEAR_BUFFER mechanism itself working end-to-end, not the full
  scenario matrix.
