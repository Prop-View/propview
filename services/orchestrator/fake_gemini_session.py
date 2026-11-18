"""Deterministic Gemini substitute for local end-to-end load tests only."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from gemini_live_client import AudioChunk, LiveEvent, ToolCallRequest, TranscriptChunk, TurnComplete


class FakeGeminiLiveSession:
    def __init__(self, **_kwargs) -> None:
        self._events: asyncio.Queue[LiveEvent] = asyncio.Queue()
        self._requested_tool = False

    async def __aenter__(self) -> FakeGeminiLiveSession:
        return self

    async def __aexit__(self, *_exc_info) -> None:
        return None

    async def send_audio(self, _pcm16_bytes: bytes) -> None:
        if self._requested_tool:
            return
        self._requested_tool = True
        await self._events.put(TranscriptChunk("caller", "Find properties in Austin", True))
        await self._events.put(
            ToolCallRequest(
                id=f"load-{uuid4().hex}",
                name="search_properties",
                args={"city": "Austin", "status": "active", "limit": 1},
            )
        )

    async def send_end_of_audio(self) -> None:
        return None

    async def send_tool_response(self, call_id: str, name: str, response: dict) -> None:
        await self._events.put(
            TranscriptChunk("agent", f"Load-test tool {name} completed", True)
        )
        await self._events.put(AudioChunk(data=b"\x00\x00" * 480))
        await self._events.put(TurnComplete())

    async def receive_events(self) -> AsyncIterator[LiveEvent]:
        while True:
            yield await self._events.get()
