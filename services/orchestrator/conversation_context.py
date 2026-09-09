"""
PROP-204: Redis-backed live conversation context window for the call
currently in progress -- distinct from session_store.py's SessionStore
(PROP-106, just call_id -> room name lookup) and transcript_store.py
(PROP-506, the full transcript persisted to Postgres once, at call end).
This is the mid-call, externally-readable state the plan's DoD names
explicitly ("Redis context window"): each finalized utterance is pushed
here as it happens, not just accumulated in the orchestrator process's
own memory.

Barge-in truncation: the plan's literal DoD wording is "accurately
truncates text to match the word spoken at the exact millisecond of
interruption." Gemini Live's `output_transcription` stream exposes text
in chunks, not per-word timestamps (same honest-scope note telemetry.py
already makes about TTFA) -- word-exact truncation isn't achievable from
this SDK's surface. What IS achievable and what orchestrator.py actually
does: on interruption, whatever text has streamed into the agent's
in-progress chunk buffer up to that instant is flushed here as the
truncated utterance (tagged interrupted=True), and the buffer is reset
so later, unrelated chunks don't bleed onto it. See
CallOrchestrator._flush_transcript_buffer.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

import redis.asyncio as redis

DEFAULT_TTL_SECONDS = 4 * 60 * 60  # matches SessionStore's safety-net expiry
KEY_PREFIX = "call_context:"
MAX_LINES = 200  # bounded so one very long call can't grow this key unboundedly


@dataclass
class ContextLine:
    speaker: str  # "caller" | "agent"
    text: str
    interrupted: bool
    timestamp: float

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "ContextLine":
        return cls(**json.loads(data))


class ConversationContextStore:
    """Ephemeral call_id -> ordered list of ContextLine, in Redis."""

    def __init__(self, redis_url: str = "redis://localhost:6379", ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._ttl = ttl_seconds

    async def append_line(self, call_id: str, speaker: str, text: str, interrupted: bool = False) -> None:
        key = KEY_PREFIX + call_id
        line = ContextLine(speaker=speaker, text=text, interrupted=interrupted, timestamp=time.time())
        await self._redis.rpush(key, line.to_json())
        await self._redis.ltrim(key, -MAX_LINES, -1)
        await self._redis.expire(key, self._ttl)

    async def get_lines(self, call_id: str) -> list[ContextLine]:
        raw_lines = await self._redis.lrange(KEY_PREFIX + call_id, 0, -1)
        return [ContextLine.from_json(raw) for raw in raw_lines]

    async def clear(self, call_id: str) -> None:
        await self._redis.delete(KEY_PREFIX + call_id)

    async def aclose(self) -> None:
        await self._redis.aclose()
