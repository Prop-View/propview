# Sprint 2 Turn-Taking State Machine & Buffer Clearing (PROP-208)

Status as of 2026-09-09: predictive barge-in (PROP-202/203) is built,
unit-tested, and live-verified against a real LiveKit server with real
Silero ONNX inference on real recorded speech (see below). Transcript
truncation on barge-in (PROP-204) is now built and live-verified too —
see below, this section previously described it as only partially built.
AEC3 (PROP-201) is deliberately not implemented — see below. Text-driven
E2E interruption/conversation scenario testing (PROP-207) shipped later
in Sprint 6 alongside PROP-604 (`tests/e2e-voice/`, 12/12 scenarios
live-verified against real Gemini) — see that directory's README; this
doc's earlier "not done" note was written before that work existed. Full
audio-injection E2E testing against a real *phone call* still needs
PROP-101/102 deployed, same gap Sprint 1's `PROP-109` doc flags.

## Component map

| Component | Directory | Status | Depends on |
|---|---|---|---|
| PROP-201 AEC3 | — | **Not applicable** to this architecture, see below | PROP-102 |
| PROP-202 VAD/VAP sidecar | `services/vap-sidecar/` | Built & tested against real speech audio | PROP-105 |
| PROP-203 CLEAR_BUFFER signal | `services/orchestrator/orchestrator.py` | Built & live-verified against a real LiveKit call | PROP-201*, PROP-202 |
| PROP-204 Transcript truncation on barge-in | `services/orchestrator/orchestrator.py`, `conversation_context.py`, `transcript_store.py` | Built & live-verified — chunk-granularity, not word-exact (see below) | PROP-106, PROP-203 |
| PROP-205 Persona prompt | `services/prompts/` | Built (earlier commit) | — |
| PROP-206 OTel logging | `services/orchestrator/telemetry.py` | Built & live-verified (earlier commit) | PROP-105 |
| PROP-207 E2E interruption testing | `tests/e2e-voice/` | Built & live-verified (PROP-604, Sprint 6) — text-driven, not audio-injection; see that directory | PROP-203 |

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

## PROP-204: Redis context window + barge-in truncation

Built as `services/orchestrator/conversation_context.py`'s
`ConversationContextStore` — a live, Redis-backed, per-call ordered list
of finalized utterances, distinct from `session_store.py` (PROP-106,
just call_id→room lookup) and `transcript_store.py` (PROP-506, the full
transcript persisted to Postgres once, at call end). Every utterance is
pushed as it's finalized, not just accumulated in the orchestrator
process's own memory.

`orchestrator.py`'s `_flush_transcript_buffer` is called from both
interruption paths (VAP predictive and Gemini reactive) with
`interrupted=True`: it flushes whatever text has streamed into the
interrupted speaker's chunk buffer up to that instant as one labeled
line (tagged `(interrupted)` / `interrupted=True` in Redis), then
**resets** the buffer. The reset matters, not just the flush — without
it, later chunks for the abandoned turn (Gemini's transcription stream
runs "independent to the model turn," so these can still arrive) would
silently bleed onto whatever the agent says next. This was a real gap
found by re-reading the code, not a hypothetical: the original
`_record_transcript_chunk` had no interaction with either interrupt path
at all, despite an earlier version of this doc claiming truncation was
already implemented.

**Known limitation, not silently approximated:** the plan's Definition
of Done says *"accurately truncates text to match the word spoken at
the exact millisecond of interruption."* Gemini's Live API exposes
`output_transcription` as streamed text chunks, not per-word
timestamps (same honest-scope note `telemetry.py` already makes about
TTFA), so word-exact, millisecond-precise truncation isn't achievable
from this SDK's surface. What's implemented and verified is
chunk-granularity truncation: accurate up to "what had streamed in by
the last chunk boundary before the interruption was detected."

**Live-verified** 2026-09-09
(`services/orchestrator/tests/test_transcript_truncation_live.py`)
against a real LiveKit call and real Redis: a fake Gemini session
streamed real `TranscriptChunk` deltas word-by-word while "speaking," a
real recorded caller-speech clip triggered a predictive barge-in
partway through, and the truncated, reset, correctly-tagged line landed
in both the orchestrator's in-memory transcript and the real Redis
context window — `RESULT: PASS`.

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
- `services/orchestrator/tests/test_conversation_context.py` — 6/6, real
  Redis (ordering, the `interrupted` flag, TTL expiry, list trimming at
  `MAX_LINES`).
- `services/orchestrator/tests/test_orchestrator_barge_in.py` — extended
  with PROP-204 cases: barge-in flushes the agent buffer as an
  `(interrupted)` line, an empty buffer is a no-op, later chunks after a
  barge-in don't bleed onto the interrupted line, and the Redis push is
  correctly skipped when no `conversation_context` is configured.
- `services/orchestrator/tests/test_transcript_truncation_live.py` — see
  "PROP-204" section above. **Verified passing** 2026-09-09.
- Text-driven E2E scenario testing (PROP-207/PROP-604) shipped in Sprint
  6 — see `tests/e2e-voice/README.md` for the 12/12 live-verified
  scenarios and the deliberate text-vs-audio-injection scope decision.
  The plan's full 15-scenario literal *audio*-injection framework
  (`Sprint Plan.md` section 3) is still not built.
