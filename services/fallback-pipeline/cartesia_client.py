"""
PROP-501: Cartesia TTS -- the final stage of the cascaded fallback (STT ->
LLM -> TTS). Synthesizes the LLM's text reply to speech, streamed back as
raw PCM16 at 24kHz -- matching orchestrator.py's GEMINI_OUTPUT_RATE_HZ
exactly, so audio from either engine (Gemini or this fallback) can be
captured onto the same LiveKit AudioSource with no resampling.

Uses the one-shot `tts.bytes()` call (whole utterance in, an async byte
stream out) rather than Cartesia's WebSocket streaming API: the LLM stage
already produces a complete reply text before this runs, so there's no
partial-sentence text to stream in incrementally.

**Partially live-verified**: no real Cartesia API key available in this
environment, but `synthesize()` was run for real against Cartesia's API
with a fake key (`api_key="fake"`) -- it reached a real 401
`AuthenticationError` from Cartesia's own auth layer. This is actually
how a real bug got caught: an earlier version called the more
obvious-looking (but deprecated) `tts.bytes()` directly as an async
iterator, which raised `TypeError: 'async for' requires an object with
__aiter__ method, got coroutine` -- `tts.bytes()` returns a coroutine
that must be awaited first, and the non-deprecated replacement
(`tts.generate()` + `.iter_bytes()`) has the same two-step shape. Fixed
and reconfirmed reaching the real 401 after the fix. What's NOT verified:
real audio output, since that needs a real key.
"""

from __future__ import annotations

from typing import AsyncIterator

from cartesia import AsyncCartesia

SAMPLE_RATE_HZ = 24000  # matches orchestrator.py's GEMINI_OUTPUT_RATE_HZ
DEFAULT_MODEL_ID = "sonic-2"


class CartesiaTTS:
    def __init__(self, api_key: str, voice_id: str, model_id: str = DEFAULT_MODEL_ID):
        self._client = AsyncCartesia(api_key=api_key)
        self._voice_id = voice_id
        self._model_id = model_id

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yields raw PCM16LE chunks at 24kHz as Cartesia produces them.

        `tts.generate()` returns a response object, not the byte stream
        directly -- `.iter_bytes()` on it is the actual streaming
        iterator. (`tts.bytes()`, the more obvious-looking method, is
        deprecated in favor of this. Verified against the real Cartesia
        API with a fake key: this shape reaches a real 401
        AuthenticationError; an earlier version of this method that
        awaited `tts.bytes()` directly as an async iterator raised
        `TypeError: 'async for' requires an object with __aiter__`, since
        it returns a coroutine, not an async generator.)"""
        response = await self._client.tts.generate(
            model_id=self._model_id,
            transcript=text,
            voice=self._voice_id,
            output_format={"container": "raw", "encoding": "pcm_s16le", "sample_rate": SAMPLE_RATE_HZ},
        )
        async for chunk in response.iter_bytes():
            yield chunk

    async def aclose(self) -> None:
        await self._client.close()
