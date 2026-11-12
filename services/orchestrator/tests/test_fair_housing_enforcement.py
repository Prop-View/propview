import asyncio
import sys
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))

from gemini_live_client import AudioChunk, Interrupted, TranscriptChunk, TurnComplete
from orchestrator import CallOrchestrator


class FakeRoom:
    name = "fair-housing-test-room"


def _write_response_clip(path: Path) -> None:
    with wave.open(str(path), "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(24000)
        clip.writeframes(b"\0" * 960 * 2)


@pytest.fixture
def orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CallOrchestrator:
    clip_path = tmp_path / "redirect.wav"
    _write_response_clip(clip_path)
    monkeypatch.setattr("orchestrator.FAIR_HOUSING_AUDIO_PATH", clip_path)

    orch = CallOrchestrator(room=FakeRoom(), gemini_session=MagicMock())
    source = MagicMock()
    source.capture_frame = AsyncMock()
    orch._publish_source = source
    return orch


@pytest.mark.asyncio
async def test_only_finished_caller_transcript_can_trigger_redirect(orchestrator: CallOrchestrator) -> None:
    orchestrator._record_transcript_chunk(TranscriptChunk(speaker="caller", text="Are the local residents ", finished=False))
    orchestrator._record_transcript_chunk(TranscriptChunk(speaker="agent", text="Hello.", finished=True))

    orchestrator._publish_source.clear_queue.assert_not_called()
    assert orchestrator._fair_housing_response_task is None

    orchestrator._record_transcript_chunk(TranscriptChunk(speaker="caller", text="mostly white?", finished=True))

    orchestrator._publish_source.clear_queue.assert_called_once()
    assert orchestrator._suppress_gemini_audio is True
    assert orchestrator._fair_housing_response_task is not None
    await asyncio.gather(*orchestrator._tasks)


def test_non_steering_caller_question_does_not_trigger_redirect(orchestrator: CallOrchestrator) -> None:
    orchestrator._record_transcript_chunk(
        TranscriptChunk(speaker="caller", text="Is there a church nearby?", finished=True)
    )

    orchestrator._publish_source.clear_queue.assert_not_called()
    assert orchestrator._fair_housing_response_task is None


@pytest.mark.asyncio
async def test_redirect_plays_recorded_audio_and_is_persisted(orchestrator: CallOrchestrator) -> None:
    orchestrator._record_transcript_chunk(
        TranscriptChunk(speaker="caller", text="Are the local residents mostly white?", finished=True)
    )

    await asyncio.gather(*orchestrator._tasks)

    orchestrator._publish_source.capture_frame.assert_awaited()
    assert orchestrator._publish_source.capture_frame.await_count == 2
    first_frame = orchestrator._publish_source.capture_frame.await_args_list[0].args[0]
    assert first_frame.sample_rate == 24000
    assert first_frame.num_channels == 1
    assert first_frame.samples_per_channel == 480
    assert any(line.startswith("Agent: I'm not able to speak to that") for line in orchestrator._transcript_lines)
    assert orchestrator._fair_housing_response_task is None
    assert orchestrator._agent_speaking is False


@pytest.mark.asyncio
async def test_redirect_audio_is_cancelled_on_barge_in(orchestrator: CallOrchestrator) -> None:
    started = asyncio.Event()

    async def hold_audio_frame(_frame) -> None:
        started.set()
        await asyncio.Future()

    orchestrator._publish_source.capture_frame = AsyncMock(side_effect=hold_audio_frame)
    orchestrator._record_transcript_chunk(
        TranscriptChunk(speaker="caller", text="Are the local residents mostly white?", finished=True)
    )
    await started.wait()

    orchestrator._handle_predictive_speech_start()
    await asyncio.gather(*orchestrator._tasks, return_exceptions=True)

    orchestrator._publish_source.clear_queue.assert_called()
    assert orchestrator._fair_housing_response_task is None
    assert orchestrator._agent_speaking is False


@pytest.mark.asyncio
async def test_gemini_audio_is_discarded_until_redirect_turn_completes(orchestrator: CallOrchestrator) -> None:
    class FakeSession:
        async def receive_events(self):
            yield AudioChunk(data=b"\0" * 960)
            yield TurnComplete()

    orchestrator._gemini = FakeSession()
    orchestrator._suppress_gemini_audio = True

    await orchestrator._run_forward_gemini_audio_to_room()

    orchestrator._publish_source.capture_frame.assert_not_awaited()
    assert orchestrator._suppress_gemini_audio is False


@pytest.mark.asyncio
async def test_gemini_interruption_releases_audio_suppression(orchestrator: CallOrchestrator) -> None:
    class FakeSession:
        async def receive_events(self):
            yield Interrupted()

    orchestrator._gemini = FakeSession()
    orchestrator._suppress_gemini_audio = True

    await orchestrator._run_forward_gemini_audio_to_room()

    assert orchestrator._suppress_gemini_audio is False
