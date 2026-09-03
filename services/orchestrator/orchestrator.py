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
import time
from typing import Protocol

from livekit import rtc

from gemini_live_client import AudioChunk, Interrupted, ToolCallRequest, TranscriptChunk, TurnComplete
from session_store import SessionStore
from telemetry import CallTelemetry, log_event
from tool_client import ToolRouterClient
from transcript_store import save_interaction

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
    async def send_tool_response(self, call_id: str, name: str, response: dict) -> None: ...
    def receive_events(self): ...  # AsyncIterator[AudioChunk | TurnComplete | Interrupted | ToolCallRequest]


class CallOrchestrator:
    """Bridges one LiveKit room's caller audio to a Gemini Live session."""

    def __init__(
        self,
        room: rtc.Room,
        gemini_session: GeminiSessionLike,
        session_store: SessionStore | None = None,
        tool_client: ToolRouterClient | None = None,
        database_url: str | None = None,
        tenant_id: str = "default",
    ):
        self._room = room
        self._gemini = gemini_session
        self._session_store = session_store
        self._tool_client = tool_client
        self._database_url = database_url
        self._tenant_id = tenant_id
        self._telemetry = CallTelemetry(call_id=room.name, room_name=room.name)
        self._publish_source: rtc.AudioSource | None = None
        self._tasks: list[asyncio.Task] = []
        self._forwarded_track_sids: set[str] = set()
        self._transcript_lines: list[str] = []
        self._transcript_buffer: dict[str, str] = {"caller": "", "agent": ""}
        self._call_started_at = time.monotonic()

    async def start(self) -> None:
        self._telemetry.start()
        if self._session_store is not None:
            await self._session_store.create_session(call_id=self._room.name, room_name=self._room.name)

        self._publish_source = rtc.AudioSource(sample_rate=GEMINI_OUTPUT_RATE_HZ, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track(AGENT_TRACK_NAME, self._publish_source)
        await self._room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

        # Register the listener *before* scanning for already-subscribed
        # tracks: the caller (e.g. a SIP participant) is typically already
        # in the room -- and may already have a subscribed audio track --
        # by the time this orchestrator joins and calls start(), since the
        # room is created by the inbound call itself. If we only listened
        # for future "track_subscribed" events, that already-subscribed
        # caller track would never fire one and we'd never forward their
        # audio to Gemini (one-way call: agent talks, never hears back).
        self._room.on("track_subscribed", self._on_track_subscribed)
        for participant in self._room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.kind == rtc.TrackKind.KIND_AUDIO and publication.track is not None:
                    self._start_forwarding_caller_audio(publication.track, participant)

        self._tasks.append(asyncio.create_task(self._forward_gemini_audio_to_room()))

    def _on_track_subscribed(self, track: rtc.Track, publication, participant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        self._start_forwarding_caller_audio(track, participant)

    def _start_forwarding_caller_audio(self, track: rtc.Track, participant) -> None:
        # Guard against forwarding the same track twice -- it could show up
        # both in the start-up scan and in a near-simultaneous
        # "track_subscribed" event for the same track.
        if track.sid in self._forwarded_track_sids:
            return
        self._forwarded_track_sids.add(track.sid)
        logger.info("Subscribed to caller audio track from %s", participant.identity)
        self._telemetry.record_track_subscribed(participant.identity)
        self._tasks.append(asyncio.create_task(self._forward_caller_audio_to_gemini(track)))

    async def _forward_caller_audio_to_gemini(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream.from_track(track=track, sample_rate=GEMINI_INPUT_RATE_HZ, num_channels=1)
        try:
            async for event in stream:
                await self._gemini.send_audio(bytes(event.frame.data))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Caller audio forwarding to Gemini stopped unexpectedly")
            self._telemetry.record_error("caller_audio_forwarding", exc)
            raise
        finally:
            await stream.aclose()

    async def _forward_gemini_audio_to_room(self) -> None:
        try:
            await self._run_forward_gemini_audio_to_room()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Gemini audio forwarding to room stopped unexpectedly")
            self._telemetry.record_error("gemini_audio_forwarding", exc)
            raise

    async def _run_forward_gemini_audio_to_room(self) -> None:
        async for event in self._gemini.receive_events():
            if isinstance(event, AudioChunk):
                self._telemetry.record_response_audio()
                frame = rtc.AudioFrame(
                    data=event.data,
                    sample_rate=GEMINI_OUTPUT_RATE_HZ,
                    num_channels=1,
                    samples_per_channel=len(event.data) // 2,
                )
                await self._publish_source.capture_frame(frame)
            elif isinstance(event, TurnComplete):
                logger.debug("Gemini turn complete")
                self._telemetry.record_turn_complete()
            elif isinstance(event, Interrupted):
                logger.info("Gemini turn interrupted (barge-in) -- clearing playout queue")
                self._telemetry.record_interrupted()
                self._publish_source.clear_queue()
            elif isinstance(event, ToolCallRequest):
                await self._handle_tool_call(event)
            elif isinstance(event, TranscriptChunk):
                self._record_transcript_chunk(event)

    def _record_transcript_chunk(self, chunk: TranscriptChunk) -> None:
        # Transcription streams incrementally and "is independent to the
        # model turn" (Gemini's own docs) -- keep appending to a per-speaker
        # buffer, and flush it as one labeled line once `finished` marks
        # that utterance complete.
        self._transcript_buffer[chunk.speaker] += chunk.text
        if chunk.finished:
            label = "Caller" if chunk.speaker == "caller" else "Agent"
            self._transcript_lines.append(f"{label}: {self._transcript_buffer[chunk.speaker]}")
            self._transcript_buffer[chunk.speaker] = ""

    async def _handle_tool_call(self, call: ToolCallRequest) -> None:
        if self._tool_client is None:
            logger.warning("Tool call %r received but no tool_client configured -- ignoring", call.name)
            return

        logger.info("Tool call: %s(%r)", call.name, call.args)
        started_at = time.monotonic()
        try:
            result = await self._tool_client.call_tool(call.name, call.args)
            error = None
        except Exception as exc:  # noqa: BLE001 -- always report back to Gemini, even on failure
            logger.exception("Tool call %s failed", call.name)
            result = None
            error = str(exc)

        execution_time_ms = (time.monotonic() - started_at) * 1000
        log_event(
            "tool_execution_completed",
            self._room.name,
            metrics={"execution_time_ms": round(execution_time_ms, 1)},
            payload={"tool_name": call.name, "args": call.args, "error": error},
            level="ERROR" if error else "INFO",
        )

        response = {"error": error} if error else {"result": result}
        await self._gemini.send_tool_response(call_id=call.id, name=call.name, response=response)

    async def aclose(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._session_store is not None:
            await self._session_store.end_session(call_id=self._room.name)
        if self._tool_client is not None:
            await self._tool_client.aclose()

        # Flush any incomplete utterance still sitting in the per-speaker
        # buffers (e.g. the call ended mid-sentence) so it isn't lost.
        for speaker, text in self._transcript_buffer.items():
            if text:
                label = "Caller" if speaker == "caller" else "Agent"
                self._transcript_lines.append(f"{label}: {text}")

        if self._database_url is not None and self._transcript_lines:
            duration_seconds = int(time.monotonic() - self._call_started_at)
            try:
                await save_interaction(
                    database_url=self._database_url,
                    tenant_id=self._tenant_id,
                    call_id=self._room.name,
                    transcript="\n".join(self._transcript_lines),
                    duration_seconds=duration_seconds,
                )
            except Exception:
                logger.exception("Failed to save interaction transcript")

        self._telemetry.end()
