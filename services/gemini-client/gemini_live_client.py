"""
PROP-104: WebSocket client for the Gemini Live API bidirectional audio stream.

Wraps google-genai's `client.aio.live` session with the shapes this project
needs: push 16kHz mono PCM16 frames in, get 24kHz mono PCM16 frames plus
turn/interruption events out, across the whole call (not just one turn).

Verified against the installed Google Gen AI SDK's actual Live API
surface (`google.genai.live.AsyncSession`) — not just the public docs —
since this SDK's live API has changed shape across versions. The
`google-genai>=1.75.0` minimum is also checked for the session-resumption,
GoAway, and context-compression types used here. If another SDK version
behaves differently, check `AsyncSession.receive`,
`send_realtime_input`, and the matching `google.genai.types` models.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

from google import genai
from google.genai import types

INPUT_SAMPLE_RATE_HZ = 16000
OUTPUT_SAMPLE_RATE_HZ = 24000
DEFAULT_MODEL = "gemini-3.8-live"
logger = logging.getLogger(__name__)

# All 30 prebuilt voices Gemini Live/TTS currently share, with Google's own
# one-word character descriptor -- https://ai.google.dev/gemini-api/docs/speech-generation.
# Not enforced client-side (the SDK's PrebuiltVoiceConfig.voice_name is a
# plain Optional[str], validated server-side, not a client-side enum) --
# kept here so GEMINI_VOICE_NAME has a documented, spellable set of options
# rather than sending an unverified guess.
PREBUILT_VOICES = {
    "Zephyr": "Bright", "Puck": "Upbeat", "Charon": "Informative", "Kore": "Firm",
    "Fenrir": "Excitable", "Leda": "Youthful", "Orus": "Firm", "Aoede": "Breezy",
    "Callirrhoe": "Easy-going", "Autonoe": "Bright", "Enceladus": "Breathy", "Iapetus": "Clear",
    "Umbriel": "Easy-going", "Algieba": "Smooth", "Despina": "Smooth", "Erinome": "Clear",
    "Algenib": "Gravelly", "Rasalgethi": "Informative", "Laomedeia": "Upbeat", "Achernar": "Soft",
    "Alnilam": "Firm", "Schedar": "Even", "Gacrux": "Mature", "Pulcherrima": "Forward",
    "Achird": "Friendly", "Zubenelgenubi": "Casual", "Vindemiatrix": "Gentle", "Sadachbia": "Lively",
    "Sadaltager": "Knowledgeable", "Sulafat": "Warm",
}


@dataclass
class AudioChunk:
    """A chunk of 24kHz mono PCM16 audio spoken by the model."""

    data: bytes


@dataclass
class TurnComplete:
    """The model has finished speaking its turn."""


@dataclass
class Interrupted:
    """The model's turn was cut off (barge-in) — see PROP-204."""


@dataclass
class ToolCallRequest:
    """The model wants to call a function. Reply with GeminiLiveSession.send_tool_response()."""

    id: str
    name: str
    args: dict


@dataclass
class TranscriptChunk:
    """Speech-to-text transcription of either side of the call.

    "The transcription is independent to the model turn which means it
    doesn't imply any ordering between transcription and model turn"
    (Gemini's own docs) -- so these can arrive interleaved with AudioChunk
    events in either order, not strictly before/after. Consumers should
    accumulate by `speaker` and use `finished` to know when one utterance
    is complete, not assume strict ordering against audio events.
    """

    speaker: str  # "caller" or "agent"
    text: str
    finished: bool


LiveEvent = AudioChunk | TurnComplete | Interrupted | ToolCallRequest | TranscriptChunk


class GeminiLiveSession:
    """One bidirectional voice session with the Gemini Live API.

    Usage:
        async with GeminiLiveSession(system_instruction=persona_prompt) as session:
            asyncio.create_task(feed_from_livekit(session))
            async for event in session.receive_events():
                handle(event)  # dispatch AudioChunk / TurnComplete / Interrupted
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        system_instruction: str | None = None,
        tools: list[types.Tool] | None = None,
        voice_name: str | None = None,
    ):
        self._client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self._model = model or os.environ.get("GEMINI_LIVE_MODEL", DEFAULT_MODEL)

        # GEMINI_VOICE_NAME (env, or the voice_name argument) selects one of
        # PREBUILT_VOICES. Unset/None = Gemini's own default voice -- this
        # was never explicitly chosen before this option existed. Not
        # validated client-side against PREBUILT_VOICES (the SDK doesn't
        # either): an unrecognized name is left for the Live API's own
        # connect-time error rather than guessed at here, in case Google
        # adds voices this list hasn't caught up to yet.
        resolved_voice_name = voice_name or os.environ.get("GEMINI_VOICE_NAME")
        speech_config = None
        if resolved_voice_name:
            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=resolved_voice_name)
                )
            )

        self._config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system_instruction,
            tools=tools,
            speech_config=speech_config,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
        )
        self._connect_cm = None
        self._session = None
        self._session_resumption_handle: str | None = None
        self._session_lock = asyncio.Lock()

    async def __aenter__(self) -> "GeminiLiveSession":
        await self._connect_session()
        return self

    async def __aexit__(self, *exc_info) -> None:
        async with self._session_lock:
            if self._connect_cm is not None:
                await self._connect_cm.__aexit__(*exc_info)
                self._connect_cm = None
                self._session = None

    async def _connect_session(self) -> None:
        config = self._config.model_copy(
            update={
                "session_resumption": types.SessionResumptionConfig(
                    handle=self._session_resumption_handle,
                )
            }
        )
        connect_cm = self._client.aio.live.connect(model=self._model, config=config)
        session = await connect_cm.__aenter__()
        self._connect_cm = connect_cm
        self._session = session

    async def _resume_session(self, time_left: str | None) -> None:
        if self._session_resumption_handle is None:
            raise RuntimeError(
                "Gemini Live requested connection shutdown but has not provided a resumable session handle"
            )
        async with self._session_lock:
            old_connect_cm = self._connect_cm
            config = self._config.model_copy(
                update={
                    "session_resumption": types.SessionResumptionConfig(
                        handle=self._session_resumption_handle,
                    )
                }
            )
            new_connect_cm = self._client.aio.live.connect(model=self._model, config=config)
            new_session = await new_connect_cm.__aenter__()

            self._connect_cm = new_connect_cm
            self._session = new_session
            if old_connect_cm is not None:
                await old_connect_cm.__aexit__(None, None, None)

        logger.info(
            "Resumed Gemini Live session before connection shutdown (time_left=%s)",
            time_left,
        )

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        """Send a chunk of 16kHz mono PCM16 audio (e.g. one 20ms frame)."""
        async with self._session_lock:
            session = self._session
            if session is None:
                raise RuntimeError("GeminiLiveSession must be entered before sending audio")
            await session.send_realtime_input(
                audio=types.Blob(data=pcm16_bytes, mime_type=f"audio/pcm;rate={INPUT_SAMPLE_RATE_HZ}")
            )

    async def send_end_of_audio(self) -> None:
        """Signal the caller stopped speaking (e.g. call ended)."""
        async with self._session_lock:
            session = self._session
            if session is None:
                raise RuntimeError("GeminiLiveSession must be entered before ending audio")
            await session.send_realtime_input(audio_stream_end=True)

    async def send_tool_response(self, call_id: str, name: str, response: dict) -> None:
        """Reply to a ToolCallRequest event with the tool's result."""
        async with self._session_lock:
            session = self._session
            if session is None:
                raise RuntimeError("GeminiLiveSession must be entered before sending tool responses")
            await session.send_tool_response(
                function_responses=types.FunctionResponse(id=call_id, name=name, response=response)
            )

    async def send_text(self, text: str, end_of_turn: bool = True) -> None:
        """Send text as a user turn. Mainly for testing without a mic/real call."""
        async with self._session_lock:
            session = self._session
            if session is None:
                raise RuntimeError("GeminiLiveSession must be entered before sending text")
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=end_of_turn
            )

    async def receive_events(self) -> AsyncIterator[LiveEvent]:
        """Yields events for the whole session (all turns, not just one).

        `session.receive()` only covers a single turn and returns when
        that turn completes, so this re-enters it in a loop to keep
        surfacing events for the life of the call.
        """
        while True:
            got_message = False
            reconnect = False
            async for message in self._session.receive():
                got_message = True

                resumption_update = message.session_resumption_update
                if (
                    resumption_update is not None
                    and resumption_update.resumable
                    and resumption_update.new_handle
                ):
                    self._session_resumption_handle = resumption_update.new_handle

                if message.tool_call:
                    for call in message.tool_call.function_calls:
                        yield ToolCallRequest(id=call.id, name=call.name, args=call.args or {})

                content = message.server_content
                if content is not None:
                    if content.interrupted:
                        yield Interrupted()

                    if content.input_transcription and content.input_transcription.text:
                        yield TranscriptChunk(
                            speaker="caller",
                            text=content.input_transcription.text,
                            finished=bool(content.input_transcription.finished),
                        )

                    if content.output_transcription and content.output_transcription.text:
                        yield TranscriptChunk(
                            speaker="agent",
                            text=content.output_transcription.text,
                            finished=bool(content.output_transcription.finished),
                        )

                    if content.model_turn:
                        for part in content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                yield AudioChunk(data=part.inline_data.data)

                    if content.turn_complete:
                        yield TurnComplete()

                if message.go_away is not None:
                    logger.info(
                        "Gemini Live connection is closing; reconnecting (time_left=%s)",
                        message.go_away.time_left,
                    )
                    await self._resume_session(message.go_away.time_left)
                    reconnect = True
                    break

            if reconnect:
                continue

            if not got_message:
                # `receive()` returned without yielding anything and without
                # raising -- treat that as the underlying connection having
                # closed rather than spin-looping calls to `receive()`
                # forever with no delay.
                return
