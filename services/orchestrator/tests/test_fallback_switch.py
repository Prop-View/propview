"""
PROP-502: Unit tests for the orchestrator-side fallback switch mechanism
-- _switch_to_fallback and the health-monitor-triggered paths in
_run_forward_gemini_audio_to_room / _send_audio_with_fallback. Uses fakes
for the fallback session (no real Deepgram/OpenAI/Cartesia needed here --
that's covered by ../../fallback-pipeline/tests/test_cascaded_session.py)
and HealthMonitor's real implementation (it's cheap, pure logic).

Run: python -m pytest tests/test_fallback_switch.py -v
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "fallback-pipeline"))

from gemini_live_client import AudioChunk, TurnComplete
from health_monitor import HealthMonitor
from orchestrator import CallOrchestrator


class FakeRoom:
    name = "test-room"


class FakeFallbackSession:
    """Stands in for CascadedFallbackSession -- just enough to satisfy
    GeminiSessionLike and be distinguishable from the primary session."""

    def __init__(self):
        self.aexit_called = False

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        pass

    async def send_end_of_audio(self) -> None:
        pass

    async def send_tool_response(self, call_id, name, response) -> None:
        pass

    def receive_events(self):
        async def gen():
            return
            yield  # pragma: no cover -- makes this an async generator that yields nothing

        return gen()

    async def __aexit__(self, *exc_info) -> None:
        self.aexit_called = True


@pytest.fixture
def orchestrator_with_monitor():
    health_monitor = HealthMonitor(latency_threshold_ms=1200, consecutive_errors_threshold=2)
    fallback_session = FakeFallbackSession()
    factory = AsyncMock(return_value=fallback_session)
    orch = CallOrchestrator(
        room=FakeRoom(), gemini_session=MagicMock(), health_monitor=health_monitor, fallback_session_factory=factory
    )
    return orch, health_monitor, fallback_session, factory


@pytest.mark.asyncio
async def test_switch_to_fallback_swaps_active_session(orchestrator_with_monitor):
    orch, health_monitor, fallback_session, factory = orchestrator_with_monitor
    health_monitor.record_response_latency(1500)  # trips the threshold
    original_session = orch._gemini

    switched = await orch._switch_to_fallback()

    assert switched is True
    assert orch._gemini is fallback_session
    assert orch._gemini is not original_session
    factory.assert_called_once()


@pytest.mark.asyncio
async def test_switch_to_fallback_resets_the_monitor(orchestrator_with_monitor):
    orch, health_monitor, _, _ = orchestrator_with_monitor
    health_monitor.record_response_latency(1500)

    await orch._switch_to_fallback()

    assert health_monitor.should_fallback is False


@pytest.mark.asyncio
async def test_switch_to_fallback_is_idempotent(orchestrator_with_monitor):
    """Both forwarding tasks (caller-audio-in, gemini-audio-out) can hit
    errors around the same time -- the second call must not build a
    second fallback session."""
    orch, health_monitor, _, factory = orchestrator_with_monitor
    health_monitor.record_response_latency(1500)

    first = await orch._switch_to_fallback()
    second = await orch._switch_to_fallback()

    assert first is True
    assert second is True
    factory.assert_called_once()  # not called twice


@pytest.mark.asyncio
async def test_no_factory_configured_declines_to_switch():
    health_monitor = HealthMonitor(latency_threshold_ms=1200)
    orch = CallOrchestrator(room=FakeRoom(), gemini_session=MagicMock(), health_monitor=health_monitor)
    health_monitor.record_response_latency(1500)

    switched = await orch._switch_to_fallback()

    assert switched is False
    assert orch._gemini is not None  # unchanged, still whatever was passed to __init__


@pytest.mark.asyncio
async def test_factory_failure_declines_to_switch_and_stays_on_primary():
    health_monitor = HealthMonitor(latency_threshold_ms=1200)
    failing_factory = AsyncMock(side_effect=RuntimeError("no API key"))
    original_session = MagicMock()
    orch = CallOrchestrator(
        room=FakeRoom(), gemini_session=original_session, health_monitor=health_monitor, fallback_session_factory=failing_factory
    )
    health_monitor.record_response_latency(1500)

    switched = await orch._switch_to_fallback()

    assert switched is False
    assert orch._gemini is original_session


@pytest.mark.asyncio
async def test_send_audio_with_fallback_switches_on_send_failure(orchestrator_with_monitor):
    orch, health_monitor, fallback_session, factory = orchestrator_with_monitor
    orch._gemini.send_audio = AsyncMock(side_effect=[RuntimeError("connection dropped"), RuntimeError("again")])

    # First failure: only 1 consecutive error, threshold is 2 -- recorded, but
    # must NOT re-raise (a real bug PROP-40's live stress test caught: doing
    # so used to kill the entire caller-audio-forwarding task on the very
    # first sub-threshold error, permanently silencing the caller before a
    # second error ever got the chance to accumulate and trigger the switch
    # it was configured for). The chunk is just dropped and the loop
    # (represented here by the caller trying again below) keeps going.
    await orch._send_audio_with_fallback(b"\x00\x01")
    factory.assert_not_called()
    assert orch._gemini is not fallback_session

    # Second failure: hits the threshold -- must switch and swallow the error.
    await orch._send_audio_with_fallback(b"\x00\x01")
    assert orch._gemini is fallback_session


@pytest.mark.asyncio
async def test_send_audio_with_fallback_reraises_when_no_health_monitor_configured():
    room = FakeRoom()
    gemini = MagicMock()
    gemini.send_audio = AsyncMock(side_effect=RuntimeError("connection dropped"))
    orch = CallOrchestrator(room=room, gemini_session=gemini, health_monitor=None, fallback_session_factory=None)

    # No fallback configured at all -- preserve the original crash-loud
    # behavior (nothing to degrade to, so surfacing the error is correct).
    with pytest.raises(RuntimeError):
        await orch._send_audio_with_fallback(b"\x00\x01")


@pytest.mark.asyncio
async def test_aclose_exits_the_fallback_session_if_one_was_created(orchestrator_with_monitor):
    orch, health_monitor, fallback_session, _ = orchestrator_with_monitor
    health_monitor.record_response_latency(1500)
    await orch._switch_to_fallback()

    await orch.aclose()

    assert fallback_session.aexit_called is True
