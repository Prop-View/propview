# PROP-104: Gemini Live API Client

WebSocket client for Gemini's native Speech-to-Speech (S2S) Live API —
the bidirectional audio stream the orchestrator (PROP-105) feeds LiveKit
frames into and reads spoken responses from.

Built on the official `google-genai` SDK rather than a hand-rolled WebSocket
protocol implementation, and verified directly against the installed
`google-genai==1.75.0` package's actual `AsyncSession` API (not just the
public docs, which lag SDK changes). If you're on a different version and
something breaks, check `google.genai.live.AsyncSession.receive` /
`send_realtime_input` and `google.genai.types.LiveServerContent` first —
this has moved between versions before.

**Live-tested 2026-09-02** against a real API key: `models.list()` auth
check, a full text-in/audio-out handshake on `gemini-3.1-flash-live-preview`
(received real audio bytes back), and `GeminiLiveSession.send_audio()` /
`send_end_of_audio()` exercised over the network with no errors. Not yet
tested with real speech + playback — that needs an actual mic/speaker, see
`test_mic_call.py`. Note: the model name in `google-genai`'s own docstring
examples (`gemini-live-2.5-flash-preview`) was **not** available to this
key; `gemini-3.1-flash-live-preview` was — check what's available with
`client.models.list()` if this key changes or the model gets deprecated.

## Setup

```bash
cd services/gemini-client
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# get a free key at https://aistudio.google.com/apikey, put it in .env
```

## Try it — no Twilio/LiveKit needed

```bash
python test_mic_call.py
```

Speak into your mic; you should hear Gemini reply through your speakers.
This is the fastest way to confirm the client actually works end to end
before wiring it into the orchestrator.

## API

```python
from gemini_live_client import GeminiLiveSession, AudioChunk, TurnComplete, Interrupted

async with GeminiLiveSession(system_instruction=persona_prompt) as session:
    await session.send_audio(pcm16_16khz_bytes)   # one 20ms frame at a time

    async for event in session.receive_events():
        match event:
            case AudioChunk(data=pcm16_24khz_bytes): ...  # play it out
            case TurnComplete(): ...                       # model finished speaking
            case Interrupted(): ...                        # barge-in, see PROP-204
```

- Input: 16kHz mono PCM16 (matches PROP-103's resampler output).
- Output: 24kHz mono PCM16 — the orchestrator will need to resample this
  back down to 8kHz G.711 for the SIP leg.

## Definition of Done (from Sprint Plan)

- [ ] `test_mic_call.py` round-trips real speech through Gemini.
- [ ] `GeminiLiveSession` importable and usable from `services/orchestrator/`.
