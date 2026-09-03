"""
PROP-305: Interactive Vocal Filler generator.

Masks tool-call latency (DB queries, calendar lookups, etc.) with natural
filler speech, per the plan's threshold of calls expected to exceed 500ms.
Plays a pre-recorded clip directly onto the agent's LiveKit
`AudioSource` -- bypassing Gemini entirely, since Gemini itself is
synchronously blocked waiting for the function response for the duration
of the tool call and can't simultaneously generate other speech in that
same turn (there is no "say something while you wait" affordance in the
function-calling protocol `gemini_live_client.py` uses).

Clips are pre-recorded, not generated live via TTS: generating filler
audio on the fly would itself take real time, defeating the entire point
of a fast, guaranteed-available filler. They're bundled as 24kHz mono
PCM16 WAV (matching `orchestrator.py`'s `GEMINI_OUTPUT_RATE_HZ`) so they
capture directly onto the same `AudioSource` Gemini's own audio uses, no
resampling needed.

Known limitation: these fillers are a different (macOS `say`, en-US)
voice from Gemini's own TTS voice -- noticeably not the same speaker.
Acceptable for masking a ~1s DB query; a production system would instead
generate these once via the same TTS engine/voice Gemini uses, or ask
Gemini itself to pre-record a persona-matched set. Not done here since
that requires either a separate TTS API integration or reverse-engineering
Gemini Live's voice output outside the live session, both bigger scope
than this task.
"""

from __future__ import annotations

import asyncio
import logging
import random
import wave
from pathlib import Path

from livekit import rtc

logger = logging.getLogger("orchestrator.vocal_filler")

FILLER_DIR = Path(__file__).resolve().parent / "filler_audio"
SAMPLE_RATE_HZ = 24000
FRAME_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE_HZ * FRAME_MS // 1000
BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2  # 16-bit mono

_filler_clips_cache: list[bytes] | None = None


def _load_filler_clips() -> list[bytes]:
    clips = []
    for path in sorted(FILLER_DIR.glob("*.wav")):
        with wave.open(str(path), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SAMPLE_RATE_HZ, 1, 2):
                logger.warning("Skipping %s -- not 24kHz mono 16-bit PCM", path.name)
                continue
            clips.append(w.readframes(w.getnframes()))
    return clips


def _get_filler_clips() -> list[bytes]:
    global _filler_clips_cache
    if _filler_clips_cache is None:
        _filler_clips_cache = _load_filler_clips()
        if not _filler_clips_cache:
            logger.warning("No filler clips found in %s -- vocal filler disabled", FILLER_DIR)
    return _filler_clips_cache


class VocalFillerPlayer:
    """Starts a background task that plays one random filler clip onto
    `publish_source`, but only if it's still running after `delay_seconds`
    -- callers race this against the actual tool call and `stop()` it the
    moment a real result is ready, so a fast (<500ms) tool call never
    triggers filler speech at all."""

    def __init__(self, publish_source: rtc.AudioSource, delay_seconds: float = 0.5):
        self._publish_source = publish_source
        self._delay_seconds = delay_seconds
        self._task: asyncio.Task | None = None
        self.played = False  # set True once a clip actually starts playing -- observability/testing hook

    def start(self) -> None:
        self._task = asyncio.create_task(self._wait_then_play())

    async def _wait_then_play(self) -> None:
        await asyncio.sleep(self._delay_seconds)
        clips = _get_filler_clips()
        if not clips:
            return
        self.played = True
        clip = random.choice(clips)
        logger.info("Tool call exceeded %.1fs -- playing filler audio", self._delay_seconds)
        for i in range(0, len(clip), BYTES_PER_FRAME):
            chunk = clip[i : i + BYTES_PER_FRAME]
            if len(chunk) < BYTES_PER_FRAME:
                break  # drop a trailing partial frame rather than pad it
            frame = rtc.AudioFrame(
                data=chunk, sample_rate=SAMPLE_RATE_HZ, num_channels=1, samples_per_channel=SAMPLES_PER_FRAME
            )
            await self._publish_source.capture_frame(frame)

    async def stop(self) -> None:
        """Cancels playback immediately (mid-clip if needed) -- call once
        the real tool result is ready, before sending Gemini's response
        back into the room, so filler audio never overlaps the real
        answer."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
