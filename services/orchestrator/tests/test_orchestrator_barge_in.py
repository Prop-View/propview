"""
PROP-203/PROP-207: Unit tests for predictive barge-in -- verifies the VAP
sidecar's speech_started signal only clears the agent's playout queue when
it's an actual interruption (agent mid-utterance), not every time the
caller speaks. Uses fakes for room/telemetry/publish_source (no real
LiveKit server or Postgres needed) -- test_orchestrator_live.py already
covers the real LiveKit plumbing end to end.

Run: python -m pytest tests/test_orchestrator_barge_in.py -v
"""

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
