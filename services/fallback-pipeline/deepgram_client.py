"""
PROP-501: Deepgram streaming STT -- the first stage of the cascaded
fallback (STT -> LLM -> TTS) that takes over when Gemini Live degrades
(PROP-502's health monitor decides when, cascaded_session.py wires this
into the orchestrator).

**Partially live-verified**: no real Deepgram API key available in this
environment, but the connection setup was run for real against
`wss://api.deepgram.com` with a fake key (`api_key="x"`) -- it reached a
real `ApiError` from Deepgram's own auth layer rather than failing
locally, confirming the request construction (model/sample_rate/encoding
params, the `async with connect(...)` shape) is actually correct, not
just plausible-looking. What's NOT verified: real transcription quality/
behavior with real audio, since that needs a real key.
`tests/test_deepgram_client.py` mocks the socket to verify the
transcript-extraction logic in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

from deepgram import AsyncDeepgramClient

SAMPLE_RATE_HZ = 16000  # matches orchestrator.py's GEMINI_INPUT_RATE_HZ -- no resampling needed on fallback switch
DEFAULT_MODEL = "nova-2"


@dataclass
class TranscriptResult:
    text: str
    is_final: bool


def extract_transcript(result) -> tuple[str, bool]:
    """Deepgram's socket.recv() returns several typed result variants
    (Results, Metadata, UtteranceEnd, SpeechStarted) over the same
    connection -- only Results carries a transcript. Pulled out as a
    standalone function so it's testable against plain mock objects
    without a real socket."""
    channel = getattr(result, "channel", None)
    if channel is None:
        return "", False
    alternatives = getattr(channel, "alternatives", None) or []
    if not alternatives or not alternatives[0].transcript:
        return "", False
    return alternatives[0].transcript, bool(getattr(result, "is_final", False))


class DeepgramStreamingSTT:
    """One instance per call. `async with` it, then `send_audio()` raw
    16kHz PCM16 caller frames into it as they arrive (same frames the
    orchestrator would otherwise send to Gemini); `receive_transcripts()`
    yields a TranscriptResult per Deepgram result that actually carries
    transcript text."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._client = AsyncDeepgramClient(api_key=api_key)
        self._model = model
        self._socket_cm = None
        self._socket = None

    async def __aenter__(self) -> "DeepgramStreamingSTT":
        self._socket_cm = self._client.listen.v1.connect(
            model=self._model,
            sample_rate=SAMPLE_RATE_HZ,
            encoding="linear16",
            channels=1,
            interim_results=True,
            punctuate=True,
            smart_format=True,
        )
        self._socket = await self._socket_cm.__aenter__()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._socket_cm is not None:
            await self._socket_cm.__aexit__(*exc_info)

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        await self._socket.send_media(pcm16_bytes)

    async def receive_transcripts(self) -> AsyncIterator[TranscriptResult]:
        while True:
            result = await self._socket.recv()
            text, is_final = extract_transcript(result)
            if text:
                yield TranscriptResult(text=text, is_final=is_final)
