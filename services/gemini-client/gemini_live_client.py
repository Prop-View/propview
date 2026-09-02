"""
PROP-104: WebSocket client for the Gemini Live API bidirectional audio stream.

Wraps google-genai's `client.aio.live` session with the shapes this project
needs: push 16kHz mono PCM16 frames in, get 24kHz mono PCM16 frames plus
turn/interruption events out, across the whole call (not just one turn).

Verified against google-genai==1.75.0's actual Live API surface
(`google.genai.live.AsyncSession`) — not just the public docs — since this
SDK's live API has changed shape across versions. If a newer/older
google-genai version behaves differently, check `AsyncSession.receive`,
`send_realtime_input`, and `types.LiveServerContent` directly.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

from google import genai
from google.genai import types

INPUT_SAMPLE_RATE_HZ = 16000
OUTPUT_SAMPLE_RATE_HZ = 24000
DEFAULT_MODEL = "gemini-live-2.5-flash-preview"


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


LiveEvent = AudioChunk | TurnComplete | Interrupted


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
    ):
        self._client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self._model = model or os.environ.get("GEMINI_LIVE_MODEL", DEFAULT_MODEL)
        self._config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system_instruction,
        )
        self._connect_cm = None
        self._session = None

    async def __aenter__(self) -> "GeminiLiveSession":
        self._connect_cm = self._client.aio.live.connect(model=self._model, config=self._config)
        self._session = await self._connect_cm.__aenter__()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._connect_cm is not None:
            await self._connect_cm.__aexit__(*exc_info)

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        """Send a chunk of 16kHz mono PCM16 audio (e.g. one 20ms frame)."""
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm16_bytes, mime_type=f"audio/pcm;rate={INPUT_SAMPLE_RATE_HZ}")
        )

    async def send_end_of_audio(self) -> None:
        """Signal the caller stopped speaking (e.g. call ended)."""
        await self._session.send_realtime_input(audio_stream_end=True)

    async def receive_events(self) -> AsyncIterator[LiveEvent]:
        """Yields events for the whole session (all turns, not just one).

        `session.receive()` only covers a single turn and returns when
        that turn completes, so this re-enters it in a loop to keep
        surfacing events for the life of the call.
        """
        while True:
            async for message in self._session.receive():
                content = message.server_content
                if content is None:
                    continue

                if content.interrupted:
                    yield Interrupted()

                if content.model_turn:
                    for part in content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            yield AudioChunk(data=part.inline_data.data)

                if content.turn_complete:
                    yield TurnComplete()
