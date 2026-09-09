"""
PROP-203/PROP-207: Unit tests for predictive barge-in -- verifies the VAP
sidecar's speech_started signal only clears the agent's playout queue when
it's an actual interruption (agent mid-utterance), not every time the
caller speaks. Uses fakes for room/telemetry/publish_source (no real
LiveKit server or Postgres needed) -- test_orchestrator_live.py already
covers the real LiveKit plumbing end to end.

Run: python -m pytest tests/test_orchestrator_barge_in.py -v
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))

from orchestrator import CallOrchestrator


class FakeRoom:
    name = "test-room"


@pytest.fixture
def orchestrator():
    orch = CallOrchestrator(room=FakeRoom(), gemini_session=MagicMock())
    orch._publish_source = MagicMock()
    return orch


def test_speech_start_during_agent_playback_clears_queue(orchestrator):
    orchestrator._agent_speaking = True

    orchestrator._handle_predictive_speech_start()

    orchestrator._publish_source.clear_queue.assert_called_once()
    assert orchestrator._agent_speaking is False


def test_speech_start_while_agent_silent_does_not_clear_queue(orchestrator):
    orchestrator._agent_speaking = False

    orchestrator._handle_predictive_speech_start()

    orchestrator._publish_source.clear_queue.assert_not_called()


def test_only_first_speech_start_in_a_burst_clears_queue(orchestrator):
    # A real caller utterance can span many 32ms VAD windows; only the
    # first should register as the interruption trigger.
    orchestrator._agent_speaking = True

    orchestrator._handle_predictive_speech_start()
    orchestrator._handle_predictive_speech_start()
    orchestrator._handle_predictive_speech_start()

    orchestrator._publish_source.clear_queue.assert_called_once()


# PROP-204: barge-in must truncate the agent's in-progress transcript
# buffer (chunk-granularity -- see conversation_context.py's docstring
# for why not word-exact) rather than silently letting it keep
# accumulating, or lose it entirely.


def test_barge_in_flushes_agent_buffer_as_interrupted(orchestrator):
    orchestrator._agent_speaking = True
    orchestrator._transcript_buffer["agent"] = "This house has four bed"

    orchestrator._handle_predictive_speech_start()

    assert orchestrator._transcript_lines == ["Agent: This house has four bed (interrupted)"]
    assert orchestrator._transcript_buffer["agent"] == ""


def test_barge_in_with_empty_buffer_is_a_noop(orchestrator):
    orchestrator._agent_speaking = True
    assert orchestrator._transcript_buffer["agent"] == ""

    orchestrator._handle_predictive_speech_start()

    assert orchestrator._transcript_lines == []


def test_later_chunks_after_barge_in_do_not_bleed_into_the_interrupted_line(orchestrator):
    from gemini_live_client import TranscriptChunk

    orchestrator._agent_speaking = True
    orchestrator._transcript_buffer["agent"] = "This house has four bed"
    orchestrator._handle_predictive_speech_start()

    # Gemini's transcription stream is "independent to the model turn" --
    # simulate a late chunk for what's now a new turn arriving afterward.
    orchestrator._record_transcript_chunk(TranscriptChunk(speaker="agent", text="rooms.", finished=True))

    assert orchestrator._transcript_lines == [
        "Agent: This house has four bed (interrupted)",
        "Agent: rooms.",
    ]


@pytest.mark.asyncio
async def test_barge_in_pushes_to_conversation_context_when_configured():
    from unittest.mock import AsyncMock

    context_store = MagicMock()
    context_store.append_line = AsyncMock()
    orch = CallOrchestrator(room=FakeRoom(), gemini_session=MagicMock(), conversation_context=context_store)
    orch._publish_source = MagicMock()
    orch._agent_speaking = True
    orch._transcript_buffer["agent"] = "This house has four bed"

    orch._handle_predictive_speech_start()
    await asyncio.gather(*orch._tasks)

    context_store.append_line.assert_awaited_once_with(
        "test-room", "agent", "This house has four bed", interrupted=True
    )


def test_no_conversation_context_configured_does_not_error(orchestrator):
    # Default fixture has conversation_context=None -- must not try to push.
    orchestrator._agent_speaking = True
    orchestrator._transcript_buffer["agent"] = "no crash please"

    orchestrator._handle_predictive_speech_start()

    assert orchestrator._tasks == []
