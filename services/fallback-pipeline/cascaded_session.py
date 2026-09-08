"""
PROP-501: Cascaded Fallback -- chains Deepgram STT -> GPT-4o-mini ->
Cartesia TTS behind the exact same interface `orchestrator.py` already
expects from `GeminiLiveSession` (`GeminiSessionLike`: `send_audio`,
`send_end_of_audio`, `send_tool_response`, `receive_events` yielding
`AudioChunk`/`TurnComplete`/`Interrupted`/`ToolCallRequest`/`TranscriptChunk`).
That's deliberate, not incidental: PROP-502's health monitor swaps
`CallOrchestrator._gemini` from a `GeminiLiveSession` to a
`CascadedFallbackSession` mid-call, and every downstream consumer
(barge-in via `_publish_source.clear_queue()`, transcript capture, PII
masking, telemetry) is engine-agnostic as long as both sides speak the
same event vocabulary -- no orchestrator-side special-casing needed for
"which engine is active."

**Scope decision: no tool calling in the fallback path.** This maps
directly onto the architecture reference's fallback layer D ("AI
degradation modes: disable non-critical tools") -- during a Gemini
outage, the fallback offers a real (if reduced) voice conversation
rather than none, but doesn't re-implement live listing search / BANT
capture / booking against GPT-4o-mini. `send_tool_response` exists only
to satisfy the shared protocol; this session never emits
`ToolCallRequest`, so it's never actually called in practice.

**No self-emitted barge-in.** Unlike Gemini, this cascade doesn't detect
its own interruptions -- but it doesn't need to: PROP-203's VAP sidecar
already clears the orchestrator's `AudioSource` directly on caller speech
onset, independent of which engine is feeding it. Barge-in against
fallback-generated speech works for free from the existing predictive
path.

**Not live-verified**: no real Deepgram/OpenAI/Cartesia credentials
available in this environment (same gap as every other third-party
integration in this codebase without a real account). Unit-tested with
all three externals mocked (tests/test_cascaded_session.py) -- verifies
the event sequencing and conversation-history bookkeeping, not that any
of the three real APIs behave as expected.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "gemini-client"))
from gemini_live_client import AudioChunk, TranscriptChunk, TurnComplete  # noqa: E402

from cartesia_client import CartesiaTTS
from deepgram_client import DeepgramStreamingSTT
from llm_fallback import FallbackLLM

logger = logging.getLogger("fallback_pipeline.cascaded_session")


class CascadedFallbackSession:
    """One instance per call, used as `async with CascadedFallbackSession(...) as session:`.
    `system_prompt` should be the same persona prompt Gemini was using
    (`services/prompts/system_prompt.py`) so the fallback doesn't sound
    like a different assistant mid-call."""

    def __init__(
        self,
        deepgram_api_key: str,
        openai_api_key: str,
        cartesia_api_key: str,
        cartesia_voice_id: str,
        system_prompt: str,
    ):
        self._stt = DeepgramStreamingSTT(deepgram_api_key)
        self._llm = FallbackLLM(openai_api_key)
        self._tts = CartesiaTTS(cartesia_api_key, cartesia_voice_id)
        self._system_prompt = system_prompt
        self._conversation_history: list[dict[str, str]] = []
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._stt_consumer_task: asyncio.Task | None = None

    async def __aenter__(self) -> "CascadedFallbackSession":
        await self._stt.__aenter__()
        self._stt_consumer_task = asyncio.create_task(self._consume_transcripts())
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._stt_consumer_task is not None:
            self._stt_consumer_task.cancel()
            try:
                await self._stt_consumer_task
            except asyncio.CancelledError:
                pass
        await self._stt.__aexit__(*exc_info)
        await self._tts.aclose()

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        await self._stt.send_audio(pcm16_bytes)

    async def send_end_of_audio(self) -> None:
        pass  # Deepgram detects utterance boundaries itself (endpointing/is_final) -- nothing to flush here

    async def send_tool_response(self, call_id: str, name: str, response: dict) -> None:
        # Never actually called -- this session never emits ToolCallRequest.
        # Exists only to satisfy GeminiSessionLike. See module docstring.
        logger.warning("send_tool_response(%r) called on CascadedFallbackSession -- tools are disabled during fallback", name)

    def receive_events(self):
        return self._event_generator()

    async def _event_generator(self):
        while True:
            yield await self._event_queue.get()

    async def _consume_transcripts(self) -> None:
        async for result in self._stt.receive_transcripts():
            self._event_queue.put_nowait(TranscriptChunk(speaker="caller", text=result.text, finished=result.is_final))
            if result.is_final and result.text.strip():
                await self._handle_caller_utterance(result.text)

    async def _handle_caller_utterance(self, text: str) -> None:
        self._conversation_history.append({"role": "user", "content": text})
        try:
            reply = await self._llm.generate_reply(self._system_prompt, self._conversation_history)
        except Exception:
            logger.exception("Fallback LLM call failed")
            self._event_queue.put_nowait(TurnComplete())
            return

        if not reply:
            self._event_queue.put_nowait(TurnComplete())
            return

        self._conversation_history.append({"role": "assistant", "content": reply})
        self._event_queue.put_nowait(TranscriptChunk(speaker="agent", text=reply, finished=True))

        try:
            async for chunk in self._tts.synthesize(reply):
                self._event_queue.put_nowait(AudioChunk(data=chunk))
        except Exception:
            logger.exception("Fallback TTS call failed")
        finally:
            self._event_queue.put_nowait(TurnComplete())
