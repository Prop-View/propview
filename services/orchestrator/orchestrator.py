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
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from google.genai import types as genai_types
from livekit import api, rtc

from gemini_live_client import AudioChunk, Interrupted, ToolCallRequest, TranscriptChunk, TurnComplete
from human_transfer import transfer_to_broker
from metrics import FALLBACK_SWITCHES, HUMAN_TRANSFERS, TOOL_CALLS, TOOL_LATENCY_SECONDS
from pre_transfer_summary import build_pre_transfer_summary
from session_store import SessionStore
from telemetry import CallTelemetry, log_event
from tool_client import ToolRouterClient
from transcript_store import save_interaction
from vocal_filler import VocalFillerPlayer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vap-sidecar"))
from vap_processor import SpeechActivityDetector  # noqa: E402

sys.path.append(str(Path(__file__).resolve().parent.parent / "scheduling"))  # append, not insert(0) -- see tool-router/tools/_calendar_context.py
from sms_dispatch import SmsDispatchError, send_sms  # noqa: E402

sys.path.append(str(Path(__file__).resolve().parent.parent / "fallback-pipeline"))
from health_monitor import HealthMonitor  # noqa: E402

logger = logging.getLogger("orchestrator")

GEMINI_INPUT_RATE_HZ = 16000
GEMINI_OUTPUT_RATE_HZ = 24000
AGENT_TRACK_NAME = "agent-voice"

# PROP-503: a local tool -- not fetched from the Tool Router's /tools/schema
# like the others, since executing it needs direct LiveKit room/SIP admin
# access the Tool Router doesn't have. Dispatched locally in
# _handle_tool_call rather than forwarded over HTTP.
TRANSFER_TO_HUMAN_TOOL = genai_types.FunctionDeclaration(
    name="transfer_to_human_agent",
    description=(
        "Transfers the call to a human broker immediately. Call this the moment the caller "
        "explicitly asks for a person, a manager, or a human -- don't ask clarifying questions first."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Brief reason, e.g. 'caller asked for a human'"}
        },
    },
)
DEFAULT_FILLER_DELAY_SECONDS = 0.5  # plan's threshold for "tool calls expected to exceed 500ms"


def build_gemini_tools(remote_tools: list[genai_types.Tool]) -> list[genai_types.Tool]:
    """Merges the Tool Router's remote tool schemas with locally-dispatched
    ones (just transfer_to_human_agent today) into the single list
    GeminiLiveSession(tools=...) expects."""
    return [*remote_tools, genai_types.Tool(function_declarations=[TRANSFER_TO_HUMAN_TOOL])]


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
        vad_detector: SpeechActivityDetector | None = None,
        filler_delay_seconds: float = DEFAULT_FILLER_DELAY_SECONDS,
        lk_api: api.LiveKitAPI | None = None,
        broker_phone_number: str | None = None,
        health_monitor: HealthMonitor | None = None,
        fallback_session_factory: Callable[[], Awaitable[GeminiSessionLike]] | None = None,
    ):
        self._room = room
        self._gemini = gemini_session
        self._session_store = session_store
        self._tool_client = tool_client
        self._database_url = database_url
        self._tenant_id = tenant_id
        self._filler_delay_seconds = filler_delay_seconds
        # PROP-503/504: both None disables transfer entirely -- transfer_to_human_agent
        # replies with an error to Gemini rather than raising, so a call
        # without transfer configured still degrades gracefully.
        self._lk_api = lk_api
        self._broker_phone_number = broker_phone_number
        self._caller_identity: str | None = None
        self._last_lead_snapshot: dict | None = None
        # PROP-501/502: both None disables the cascaded fallback entirely --
        # a session error/latency spike just logs and (for errors) re-raises
        # as before. fallback_session_factory is a zero-arg async callable
        # (main.py builds one closing over the real API keys) returning an
        # already-entered CascadedFallbackSession-like object.
        self._health_monitor = health_monitor
        self._fallback_session_factory = fallback_session_factory
        self._fallback_session: object | None = None  # tracked separately so aclose() knows to __aexit__ it
        # None disables predictive barge-in entirely (e.g. lightweight unit
        # tests) -- Gemini's own reactive Interrupted signal still works
        # either way, this only adds the faster local path on top of it.
        self._vad = vad_detector
        self._telemetry = CallTelemetry(call_id=room.name, room_name=room.name, tenant_id=tenant_id)
        self._publish_source: rtc.AudioSource | None = None
        self._tasks: list[asyncio.Task] = []
        self._forwarded_track_sids: set[str] = set()
        self._transcript_lines: list[str] = []
        self._transcript_buffer: dict[str, str] = {"caller": "", "agent": ""}
        self._call_started_at = time.monotonic()
        # Tracks whether the agent's audio is currently playing out, so a VAD
        # speech_started event only triggers a CLEAR_BUFFER when it's an
        # actual interruption (PROP-203) rather than every time the caller
        # speaks during their own turn.
        self._agent_speaking = False
        # Set only while a PROP-305 filler clip is playing during a slow
        # tool call, so a barge-in mid-filler can actually cancel it (see
        # _handle_predictive_speech_start) -- clear_queue() alone only
        # drops already-captured frames, it doesn't stop the filler's
        # capture loop from refilling the queue with the rest of the clip.
        self._active_filler: VocalFillerPlayer | None = None
        # PROP-402: who's calling, and which lead row this call has already
        # created (so repeated update_lead_qualification calls within one
        # call update the same row instead of creating a new one per
        # field learned). Both threaded through to the Tool Router as
        # call-scoped context in _handle_tool_call, never exposed to
        # Gemini's function schema.
        self._caller_phone_number: str | None = None
        self._lead_id: int | None = None

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
        self._caller_identity = participant.identity  # needed for PROP-503's transfer_sip_participant call
        self._capture_caller_phone_number(participant)
        self._tasks.append(asyncio.create_task(self._forward_caller_audio_to_gemini(track)))

    def _capture_caller_phone_number(self, participant) -> None:
        # LiveKit's SIP bridge sets "sip.phoneNumber" on the SIP
        # participant's attributes (PROP-101/102, not yet deployed here --
        # so this is exercised so far only by tests that set it manually).
        # Falls back to a synthetic per-call id so update_lead_qualification
        # (PROP-402) always has *something* to key a contact record on --
        # not a reusable real phone number, a known limitation until real
        # telephony is wired up.
        if self._caller_phone_number is not None:
            return
        phone_number = getattr(participant, "attributes", {}).get("sip.phoneNumber")
        self._caller_phone_number = phone_number or f"unknown-{self._room.name}"

    async def _forward_caller_audio_to_gemini(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream.from_track(track=track, sample_rate=GEMINI_INPUT_RATE_HZ, num_channels=1)
        try:
            async for event in stream:
                pcm16_bytes = bytes(event.frame.data)
                if self._vad is not None:
                    for speech_event in self._vad.process(pcm16_bytes):
                        if speech_event.kind == "speech_started":
                            self._handle_predictive_speech_start()
                await self._send_audio_with_fallback(pcm16_bytes)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Caller audio forwarding to Gemini stopped unexpectedly")
            self._telemetry.record_error("caller_audio_forwarding", exc)
            raise
        finally:
            await stream.aclose()

    async def _send_audio_with_fallback(self, pcm16_bytes: bytes) -> None:
        """PROP-502: a send_audio failure (the primary engine's connection
        dropped) is exactly the kind of error the health monitor should
        see. If it decides to trigger the cascaded fallback and the switch
        succeeds, this one chunk is simply dropped -- the next chunk goes
        to the new self._gemini automatically (looked up fresh each call,
        not captured in a local variable). If fallback isn't
        configured/available, re-raises so the caller's broader handler
        still logs and records it the same way it always has (crash-loud,
        matching pre-PROP-502 behavior with nothing to fall back to).

        A real bug PROP-40's live stress test caught: this used to
        re-raise whenever the switch didn't happen yet (below the health
        monitor's consecutive-errors threshold) too. That exception
        propagates out of _forward_caller_audio_to_gemini's `async for`
        loop entirely, killing that task for the rest of the call -- so a
        single transient failure, below the threshold, permanently
        silenced the caller before a second error ever had the chance to
        accumulate and actually trigger the fallback it was configured
        for. Now: when a health monitor IS configured, a sub-threshold
        error just drops this one chunk and lets the loop keep running --
        a genuinely dead connection keeps failing on the next chunks too
        and reaches the threshold; a transient blip loses one 20ms frame
        instead of the rest of the call."""
        try:
            await self._gemini.send_audio(pcm16_bytes)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._health_monitor is None:
                raise
            logger.exception("send_audio failed")
            self._telemetry.record_error("caller_audio_forwarding", exc)
            self._health_monitor.record_error()
            if self._health_monitor.should_fallback:
                await self._switch_to_fallback()

    async def _forward_gemini_audio_to_room(self) -> None:
        # A supervisor loop, not a single try/except: PROP-502's health
        # monitor can decide mid-call to switch self._gemini to the
        # cascaded fallback (_switch_to_fallback), but the `async for` in
        # _run_forward_gemini_audio_to_room below is bound to whichever
        # session's receive_events() generator was active when it started
        # -- reassigning self._gemini doesn't redirect an already-running
        # iterator. So on a session error that trips the fallback
        # threshold, this restarts the inner loop fresh against the (by
        # then already swapped-in) self._gemini instead of just dying.
        while True:
            try:
                await self._run_forward_gemini_audio_to_room()
                return  # the generator ended on its own -- nothing to restart
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Gemini audio forwarding to room stopped unexpectedly")
                self._telemetry.record_error("gemini_audio_forwarding", exc)
                if self._health_monitor is not None:
                    self._health_monitor.record_error()
                    if self._health_monitor.should_fallback and await self._switch_to_fallback():
                        continue
                raise

    async def _run_forward_gemini_audio_to_room(self) -> None:
        async for event in self._gemini.receive_events():
            if isinstance(event, AudioChunk):
                latency_ms = self._telemetry.record_response_audio()
                if self._health_monitor is not None:
                    self._health_monitor.record_response_latency(latency_ms)
                    if self._health_monitor.should_fallback and await self._switch_to_fallback():
                        return  # this generator is bound to the OLD session -- the supervisor loop restarts against the new one
                self._agent_speaking = True
                frame = rtc.AudioFrame(
                    data=event.data,
                    sample_rate=GEMINI_OUTPUT_RATE_HZ,
                    num_channels=1,
                    samples_per_channel=len(event.data) // 2,
                )
                await self._publish_source.capture_frame(frame)
            elif isinstance(event, TurnComplete):
                logger.debug("Gemini turn complete")
                self._agent_speaking = False
                self._telemetry.record_turn_complete()
            elif isinstance(event, Interrupted):
                # Gemini's own (reactive) barge-in signal -- arrives after a
                # server round trip. If the VAP sidecar already predictively
                # cleared the queue for this same interruption (see
                # _handle_predictive_speech_start), _agent_speaking is
                # already False here; clear_queue() is still safe to call
                # again (no-op on an already-empty queue).
                logger.info("Gemini turn interrupted (barge-in) -- clearing playout queue")
                self._telemetry.record_interrupted(source="gemini")
                self._agent_speaking = False
                self._publish_source.clear_queue()
                if self._active_filler is not None:
                    self._tasks.append(asyncio.create_task(self._active_filler.stop()))
            elif isinstance(event, ToolCallRequest):
                await self._handle_tool_call(event)
            elif isinstance(event, TranscriptChunk):
                self._record_transcript_chunk(event)

    def _handle_predictive_speech_start(self) -> None:
        """PROP-203: the VAP sidecar detected caller speech onset locally --
        no round trip to Gemini needed. If the agent is mid-utterance, clear
        its playout buffer immediately rather than waiting for Gemini's own
        (reactive) Interrupted event, which only arrives after Gemini has
        itself processed enough caller audio to recognize the interruption.
        This is what gets barge-in under the plan's 80ms target."""
        if not self._agent_speaking:
            return  # caller speaking during their own turn, not an interruption
        logger.info("VAP predicted caller speech onset during agent playback -- clearing playout queue")
        self._telemetry.record_interrupted(source="vap_predictive")
        self._agent_speaking = False
        self._publish_source.clear_queue()
        if self._active_filler is not None:
            # A barge-in during PROP-305 filler audio: clear_queue() alone
            # only drops frames already handed to LiveKit -- the filler's
            # own capture loop would otherwise keep refilling the queue
            # with the rest of the clip. Cancel it too; _handle_tool_call's
            # `finally` clause still runs its own stop()/clear_queue() once
            # the tool call itself resolves, so this is safe to call twice.
            self._tasks.append(asyncio.create_task(self._active_filler.stop()))

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
        if call.name == "transfer_to_human_agent":
            # Dispatched locally, not through self._tool_client -- see
            # TRANSFER_TO_HUMAN_TOOL's comment, the Tool Router has no
            # LiveKit room/SIP admin access to act on this itself.
            await self._handle_transfer_to_human(call)
            return

        if self._tool_client is None:
            logger.warning("Tool call %r received but no tool_client configured -- ignoring", call.name)
            return

        logger.info("Tool call: %s(%r)", call.name, call.args)
        started_at = time.monotonic()

        # PROP-305: mask latency on slow tool calls (DB queries, calendar
        # lookups, ...) with filler speech, since Gemini itself is
        # synchronously blocked awaiting this response and can't generate
        # anything else in the meantime. Filler audio counts as the agent
        # "speaking" for barge-in purposes -- a caller talking over a
        # filler clip should interrupt it exactly like any other agent
        # speech (handled by the shared _agent_speaking flag).
        filler = VocalFillerPlayer(self._publish_source, delay_seconds=self._filler_delay_seconds)
        filler.start()
        self._active_filler = filler
        self._agent_speaking = True
        try:
            result = await self._tool_client.call_tool(
                call.name, call.args, caller_phone_number=self._caller_phone_number, lead_id=self._lead_id
            )
            error = None
            if call.name == "update_lead_qualification" and "lead_id" in result:
                self._lead_id = result["lead_id"]  # subsequent calls this turn update the same row
                self._last_lead_snapshot = result.get("captured")  # PROP-504's pre-transfer summary uses this
        except Exception as exc:  # noqa: BLE001 -- always report back to Gemini, even on failure
            logger.exception("Tool call %s failed", call.name)
            result = None
            error = str(exc)
        finally:
            self._active_filler = None
            await filler.stop()
            # Cut off any filler audio still queued/playing so it can't
            # overlap Gemini's real response, which starts as soon as
            # send_tool_response() below returns.
            self._publish_source.clear_queue()
            self._agent_speaking = False

        execution_time_ms = (time.monotonic() - started_at) * 1000
        log_event(
            "tool_execution_completed",
            self._room.name,
            metrics={"execution_time_ms": round(execution_time_ms, 1), "filler_played": filler.played},
            payload={"tool_name": call.name, "args": call.args, "error": error},
            level="ERROR" if error else "INFO",
        )
        TOOL_CALLS.labels(tenant_id=self._tenant_id, tool_name=call.name, outcome="error" if error else "success").inc()
        TOOL_LATENCY_SECONDS.labels(tenant_id=self._tenant_id, tool_name=call.name).observe(execution_time_ms / 1000)

        response = {"error": error} if error else {"result": result}
        await self._gemini.send_tool_response(call_id=call.id, name=call.name, response=response)

    async def _handle_transfer_to_human(self, call: ToolCallRequest) -> None:
        """PROP-503/504: dispatches the pre-transfer SMS to the broker
        (best-effort -- a failed SMS doesn't block the transfer itself,
        same reasoning as book_site_visit's confirmation SMS), then hands
        the caller's SIP leg off to the broker's phone via LiveKit's
        TransferSIPParticipant API. Degrades to a spoken-by-Gemini "not
        available" response rather than raising if transfer isn't
        configured for this call (lk_api/broker_phone_number/caller_identity
        all need to be set -- see __init__)."""
        reason = call.args.get("reason", "")
        logger.info("Transfer to human agent requested: %r", reason)

        if self._lk_api is None or self._broker_phone_number is None or self._caller_identity is None:
            logger.warning("Transfer requested but not configured for this call -- lk_api/broker_phone_number/caller_identity missing")
            await self._gemini.send_tool_response(
                call_id=call.id,
                name=call.name,
                response={"error": "Human transfer is not available for this call"},
            )
            return

        try:
            await send_sms(
                self._broker_phone_number,
                build_pre_transfer_summary(
                    self._caller_phone_number, reason, self._last_lead_snapshot, self._transcript_lines
                ),
            )
        except SmsDispatchError:
            logger.exception("Pre-transfer SMS to broker failed -- proceeding with transfer anyway")

        try:
            await transfer_to_broker(self._lk_api, self._room.name, self._caller_identity, self._broker_phone_number)
            response = {"status": "transferred"}
        except Exception as exc:  # noqa: BLE001 -- always report back to Gemini, even on failure
            logger.exception("SIP transfer to human broker failed")
            response = {"error": str(exc)}

        log_event(
            "call_transferred_to_human",
            self._room.name,
            payload={"reason": reason, "error": response.get("error")},
            level="ERROR" if "error" in response else "INFO",
        )
        HUMAN_TRANSFERS.labels(tenant_id=self._tenant_id, outcome="error" if "error" in response else "success").inc()
        await self._gemini.send_tool_response(call_id=call.id, name=call.name, response=response)

    async def _switch_to_fallback(self) -> bool:
        """PROP-501/502: builds a fresh cascaded fallback session (via the
        factory main.py supplied) and makes it the active engine. Returns
        whether the switch actually happened -- callers use this to decide
        whether to retry/continue or give up and re-raise the original
        error, so a broken factory (or none configured) degrades to "the
        call just drops," never to a silent hang."""
        if self._fallback_session_factory is None:
            return False
        if self._fallback_session is not None:
            return True  # already switched (e.g. both forwarding tasks hit errors around the same time)

        logger.warning("Switching to cascaded fallback session (reason: %s)", self._health_monitor.trigger_reason)
        try:
            new_session = await self._fallback_session_factory()
        except Exception:
            logger.exception("Failed to build fallback session -- staying on the primary engine")
            return False

        self._fallback_session = new_session
        self._gemini = new_session
        self._health_monitor.reset()
        log_event(
            "switched_to_cascaded_fallback",
            self._room.name,
            payload={"reason": self._health_monitor.trigger_reason},
            level="ERROR",
        )
        FALLBACK_SWITCHES.labels(tenant_id=self._tenant_id).inc()
        return True

    async def aclose(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._session_store is not None:
            await self._session_store.end_session(call_id=self._room.name)
        if self._tool_client is not None:
            await self._tool_client.aclose()
        if self._fallback_session is not None:
            await self._fallback_session.__aexit__(None, None, None)

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
