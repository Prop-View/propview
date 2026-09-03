"""
PROP-106: Redis-backed ephemeral call session mapping.

Minimal by design (plan scope: S / 0.5 days) -- just enough for the
orchestrator to look up which LiveKit room a call_id belongs to, and to
clean itself up automatically if a call ends uncleanly. Conversation
transcript storage is a separate, later concern (PROP-204, Sprint 2).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

import redis.asyncio as redis

DEFAULT_TTL_SECONDS = 4 * 60 * 60  # safety-net expiry; end_session() is the normal cleanup path
KEY_PREFIX = "call_session:"


@dataclass
class CallSession:
    call_id: str
    room_name: str
    caller_number: str | None = None
    started_at: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "CallSession":
        return cls(**json.loads(data))


class SessionStore:
    """Ephemeral call_id -> CallSession mapping in Redis."""

    def __init__(self, redis_url: str = "redis://localhost:6379", ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._ttl = ttl_seconds

    async def create_session(
        self, call_id: str, room_name: str, caller_number: str | None = None
    ) -> CallSession:
        session = CallSession(
            call_id=call_id, room_name=room_name, caller_number=caller_number, started_at=time.time()
        )
        await self._redis.set(KEY_PREFIX + call_id, session.to_json(), ex=self._ttl)
        return session

    async def get_session(self, call_id: str) -> CallSession | None:
        raw = await self._redis.get(KEY_PREFIX + call_id)
        return CallSession.from_json(raw) if raw else None

    async def end_session(self, call_id: str) -> None:
        await self._redis.delete(KEY_PREFIX + call_id)

    async def touch(self, call_id: str) -> bool:
        """Refresh the TTL -- call periodically for long-running calls."""
        return bool(await self._redis.expire(KEY_PREFIX + call_id, self._ttl))

    async def aclose(self) -> None:
        await self._redis.aclose()
