"""
PROP-501: Unit tests for CascadedFallbackSession's event sequencing and
conversation-history bookkeeping -- Deepgram/OpenAI/Cartesia all mocked
(no real credentials for any of the three available in this environment,
see the module docstring). Verifies the STT-transcript -> LLM-reply ->
TTS-audio -> TurnComplete chain and its failure modes, not that any real
API behaves as expected.

Run: python -m pytest tests/test_cascaded_session.py -v
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))

from gemini_live_client import AudioChunk, TranscriptChunk, TurnComplete

from cascaded_session import CascadedFallbackSession
from deepgram_client import TranscriptResult


class FakeSTT:
    """Stands in for DeepgramStreamingSTT -- yields a scripted sequence of
    TranscriptResults from receive_transcripts()."""

    def __init__(self, results: list[TranscriptResult]):
        self._results = results
        self.sent_audio: list[bytes] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        pass

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        self.sent_audio.append(pcm16_bytes)

    async def receive_transcripts(self):
        for result in self._results:
            yield result
        await asyncio.sleep(3600)  # stay "connected" -- a real socket doesn't end on its own


async def _collect_events(session: CascadedFallbackSession, count: int) -> list:
    events = []
    gen = session.receive_events()
    for _ in range(count):
        events.append(await asyncio.wait_for(gen.__anext__(), timeout=2))
    return events


@pytest.fixture
def patched_session(monkeypatch):
    """Builds a CascadedFallbackSession with all three externals mocked.
    Returns (session, fake_stt, mock_llm, mock_tts) so each test can
    script its own STT results / LLM reply / TTS chunks."""

    def make(stt_results: list[TranscriptResult], llm_reply: str, tts_chunks: list[bytes]):
        fake_stt = FakeSTT(stt_results)
        mock_llm = AsyncMock()
        mock_llm.generate_reply = AsyncMock(return_value=llm_reply)
        mock_tts = AsyncMock()

        async def fake_synthesize(text):
            for chunk in tts_chunks:
                yield chunk

        mock_tts.synthesize = fake_synthesize

        with (
            patch("cascaded_session.DeepgramStreamingSTT", return_value=fake_stt),
            patch("cascaded_session.FallbackLLM", return_value=mock_llm),
            patch("cascaded_session.CartesiaTTS", return_value=mock_tts),
        ):
            session = CascadedFallbackSession("dg-key", "oai-key", "cartesia-key", "voice-1", "system prompt")
        return session, fake_stt, mock_llm, mock_tts

    return make


@pytest.mark.asyncio
async def test_full_utterance_triggers_llm_and_tts_and_turn_complete(patched_session):
    session, fake_stt, mock_llm, _ = patched_session(
        stt_results=[TranscriptResult(text="I want to buy a house", is_final=True)],
        llm_reply="Great, what's your budget?",
        tts_chunks=[b"\x01\x02", b"\x03\x04"],
    )

    async with session:
        events = await _collect_events(session, 4)

    assert isinstance(events[0], TranscriptChunk)
    assert events[0].speaker == "caller"
    assert events[0].finished is True

    assert isinstance(events[1], TranscriptChunk)
    assert events[1].speaker == "agent"
    assert events[1].text == "Great, what's your budget?"

    assert isinstance(events[2], AudioChunk)
    assert events[2].data == b"\x01\x02"
    assert isinstance(events[3], AudioChunk)
    assert events[3].data == b"\x03\x04"

    mock_llm.generate_reply.assert_called_once()
    # generate_reply was called with the SAME list object session._conversation_history
    # mutates in place -- by the time we inspect call_args here, the reply has
    # already been appended too, so check the final state, not "as called."
    assert session._conversation_history == [
        {"role": "user", "content": "I want to buy a house"},
        {"role": "assistant", "content": "Great, what's your budget?"},
    ]


@pytest.mark.asyncio
async def test_interim_result_does_not_trigger_llm(patched_session):
    session, _, mock_llm, _ = patched_session(
        stt_results=[TranscriptResult(text="I want to", is_final=False)],
        llm_reply="unused",
        tts_chunks=[],
    )

    async with session:
        events = await _collect_events(session, 1)

    assert events[0].finished is False
    mock_llm.generate_reply.assert_not_called()


@pytest.mark.asyncio
async def test_empty_llm_reply_skips_tts_but_still_completes_turn(patched_session):
    session, _, mock_llm, mock_tts = patched_session(
        stt_results=[TranscriptResult(text="hello", is_final=True)],
        llm_reply="",
        tts_chunks=[b"should-not-be-used"],
    )

    async with session:
        events = await _collect_events(session, 2)

    assert isinstance(events[0], TranscriptChunk)  # the caller transcript
    assert isinstance(events[1], TurnComplete)  # straight to TurnComplete, no agent TranscriptChunk/AudioChunk


@pytest.mark.asyncio
async def test_llm_failure_still_completes_turn(patched_session):
    session, _, mock_llm, _ = patched_session(
        stt_results=[TranscriptResult(text="hello", is_final=True)], llm_reply="unused", tts_chunks=[]
    )
    mock_llm.generate_reply.side_effect = RuntimeError("API down")

    async with session:
        events = await _collect_events(session, 2)

    assert isinstance(events[1], TurnComplete)


@pytest.mark.asyncio
async def test_send_audio_forwards_to_stt(patched_session):
    session, fake_stt, _, _ = patched_session(stt_results=[], llm_reply="", tts_chunks=[])

    async with session:
        await session.send_audio(b"\x00\x01")

    assert fake_stt.sent_audio == [b"\x00\x01"]


@pytest.mark.asyncio
async def test_send_tool_response_is_a_safe_no_op(patched_session):
    session, _, _, _ = patched_session(stt_results=[], llm_reply="", tts_chunks=[])

    async with session:
        await session.send_tool_response(call_id="1", name="search_properties", response={})  # must not raise
