"""
PROP-305: Unit tests for the vocal filler player -- verifies it only
plays when the tool call actually runs past the delay threshold, and that
stop() cancels cleanly mid-clip. Uses a fake AudioSource and a short
synthetic clip (not the real ~2-4s recordings) to keep this fast.

Run: python -m pytest tests/test_vocal_filler.py -v
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vocal_filler
from vocal_filler import BYTES_PER_FRAME, VocalFillerPlayer

# 5 frames of fake "audio" -- big enough to take a few event-loop ticks to
# play out, small enough to keep tests fast.
FAKE_CLIP = b"\x01\x02" * (BYTES_PER_FRAME // 2) * 5


@pytest.fixture(autouse=True)
def fake_clips(monkeypatch):
    monkeypatch.setattr(vocal_filler, "_get_filler_clips", lambda: [FAKE_CLIP])


@pytest.mark.asyncio
async def test_fast_tool_call_never_triggers_filler():
    publish_source = AsyncMock()
    filler = VocalFillerPlayer(publish_source, delay_seconds=1.0)

    filler.start()
    await filler.stop()  # simulates a tool call resolving well before the delay

    assert filler.played is False
    publish_source.capture_frame.assert_not_called()


@pytest.mark.asyncio
async def test_slow_tool_call_triggers_filler_playback():
    publish_source = AsyncMock()
    filler = VocalFillerPlayer(publish_source, delay_seconds=0.01)

    filler.start()
    await filler._task  # let it finish playing the whole (short, fake) clip

    assert filler.played is True
    assert publish_source.capture_frame.call_count == 5


@pytest.mark.asyncio
async def test_stop_mid_playback_cancels_immediately():
    publish_source = AsyncMock()

    # capture_frame "takes time" so stop() has something to interrupt --
    # side_effect must itself be a coroutine function for AsyncMock to
    # actually await it (a plain lambda returning a coroutine is just
    # used as the call's return value, never awaited).
    async def slow_capture_frame(*_args):
        await asyncio.sleep(0.05)

    publish_source.capture_frame.side_effect = slow_capture_frame
    filler = VocalFillerPlayer(publish_source, delay_seconds=0.01)

    filler.start()
    await asyncio.sleep(0.05)  # let one or two frames play
    await filler.stop()

    assert filler.played is True
    assert publish_source.capture_frame.call_count < 5  # cut off before the clip finished
