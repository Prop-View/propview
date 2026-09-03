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
from gemini_live_client import GeminiLiveSession, AudioChunk, TurnComplete, Interrupted, ToolCallRequest

async with GeminiLiveSession(system_instruction=persona_prompt, tools=gemini_tools) as session:
    await session.send_audio(pcm16_16khz_bytes)   # one 20ms frame at a time

    async for event in session.receive_events():
        match event:
            case AudioChunk(data=pcm16_24khz_bytes): ...  # play it out
            case TurnComplete(): ...                       # model finished speaking
            case Interrupted(): ...                        # barge-in, see PROP-204
            case ToolCallRequest(id=call_id, name=name, args=args):
                result = await run_the_tool(name, args)
                await session.send_tool_response(call_id, name, {"result": result})
```

- Input: 16kHz mono PCM16 (matches PROP-103's resampler output).
- Output: 24kHz mono PCM16 — the orchestrator will need to resample this
  back down to 8kHz G.711 for the SIP leg.
- `tools`: a `list[types.Tool]` — see `services/orchestrator/tool_client.py`
  for building these from the Tool Router's `/tools/schema`.
- `send_text()` exists for testing tool-calling/text turns without a
  mic — not used in the real call path (that's always `send_audio`).

## Definition of Done (from Sprint Plan)

- [x] `GeminiLiveSession` importable and usable from `services/orchestrator/`.
- [x] Tool-calling wired: `ToolCallRequest` events + `send_tool_response()`,
      **live-verified** 2026-09-03 — a real text query ("Do you have any
      3 bedroom houses in Austin under 550 thousand dollars?") correctly
      triggered a `search_properties` call with properly-parsed structured
      args, executed against real Postgres data via the Tool Router, and
      Gemini spoke a real response incorporating the result (437KB of
      audio). This is the plan's Sprint 3 demo scenario, working end to end.
- [ ] `test_mic_call.py` round-trips real speech through Gemini (needs a
      real mic — the tool-calling path above was verified via text input
      instead, since this sandbox has no audio hardware).
