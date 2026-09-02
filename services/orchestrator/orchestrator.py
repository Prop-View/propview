"""
PROP-105: Orchestrator event loop connecting LiveKit audio frames to Gemini.

Verified against the installed livekit==1.1.17 (rtc) SDK's actual API
surface, same approach as services/gemini-client/.

Key finding from that inspection: `rtc.AudioStream.from_track(...,
sample_rate=16000)` and `rtc.AudioSource(sample_rate=24000, ...)` do real
resampling inside LiveKit's own media engine -- so this orchestrator talks
to Gemini's native 16kHz-in/24kHz-out directly and never touches raw
G.711 bytes itself. The custom codec in services/audio-pipeline/ is a
correct, tested building block, but it isn't wired in here: LiveKit's SIP
bridge + this SDK's rate-converting AudioStream/AudioSource already cover
that conversion end to end, and routing through a second (lower-quality)
resampler on top would only hurt audio quality. audio_resampler.py stays
available for anything that ever needs to touch raw G.711 directly
(e.g. a non-LiveKit fallback path in Sprint 5).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from livekit import rtc

from gemini_live_client import AudioChunk, Interrupted, TurnComplete

logger = logging.getLogger("orchestrator")

GEMINI_INPUT_RATE_HZ = 16000
GEMINI_OUTPUT_RATE_HZ = 24000
AGENT_TRACK_NAME = "agent-voice"


class AudioChunkLike(Protocol):
    data: bytes


class GeminiSessionLike(Protocol):
    """Structural type for GeminiLiveSession -- lets tests substitute a fake."""

    async def send_audio(self, pcm16_bytes: bytes) -> None: ...
    async def send_end_of_audio(self) -> None: ...
    def receive_events(self): ...  # AsyncIterator[AudioChunk | TurnComplete | Interrupted]


class CallOrchestrator:
    """Bridges one LiveKit room's caller audio to a Gemini Live session."""

    def __init__(self, room: rtc.Room, gemini_session: GeminiSessionLike):
        self._room = room
        self._gemini = gemini_session
        self._publish_source: rtc.AudioSource | None = None
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._publish_source = rtc.AudioSource(sample_rate=GEMINI_OUTPUT_RATE_HZ, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track(AGENT_TRACK_NAME, self._publish_source)
        await self._room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

        self._room.on("track_subscribed", self._on_track_subscribed)
        self._tasks.append(asyncio.create_task(self._forward_gemini_audio_to_room()))

    def _on_track_subscribed(self, track: rtc.Track, publication, participant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        logger.info("Subscribed to caller audio track from %s", participant.identity)
        self._tasks.append(asyncio.create_task(self._forward_caller_audio_to_gemini(track)))

    async def _forward_caller_audio_to_gemini(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream.from_track(track=track, sample_rate=GEMINI_INPUT_RATE_HZ, num_channels=1)
        try:
            async for event in stream:
                await self._gemini.send_audio(bytes(event.frame.data))
        finally:
            await stream.aclose()

    async def _forward_gemini_audio_to_room(self) -> None:
        async for event in self._gemini.receive_events():
            if isinstance(event, AudioChunk):
                frame = rtc.AudioFrame(
                    data=event.data,
                    sample_rate=GEMINI_OUTPUT_RATE_HZ,
                    num_channels=1,
                    samples_per_channel=len(event.data) // 2,
                )
                await self._publish_source.capture_frame(frame)
            elif isinstance(event, TurnComplete):
                logger.debug("Gemini turn complete")
            elif isinstance(event, Interrupted):
                logger.info("Gemini turn interrupted (barge-in) -- clearing playout queue")
                self._publish_source.clear_queue()

    async def aclose(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
