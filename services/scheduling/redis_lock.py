"""
Distributed lock on a calendar slot key during booking (the plan's Sprint
4 risk register: "Property Double Booking... Implement Redis distributed
locking (Redlock) on calendar slot keys during booking execution.").

This is a single-Redis-instance lock (SET NX PX + a token-checked Lua
release), not textbook Redlock (which coordinates a quorum across N
independent Redis instances/nodes). That's a deliberate simplification,
not a missed requirement: this codebase runs one Redis instance
(../orchestrator/session_store.py connects to the same one), and
Redlock's whole point -- tolerating one node's clock/failure without
losing the lock -- only matters once there's more than one node to be
inconsistent with. If/when Redis is ever clustered for real HA, swap this
for the `redis` package's `Redlock` class (same acquire/release shape)
without touching callers.
"""

from __future__ import annotations

import uuid

import redis.asyncio as redis

# Only deletes the key if it still holds *our* token -- without this, a
# lock held past its TTL and already reassigned to a different booking
# attempt could be released out from under that other attempt.
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

DEFAULT_TTL_MS = 10_000  # long enough to cover one Google Calendar API round trip


def slot_lock_key(tenant_id: str, calendar_id: str, slot_start_iso: str) -> str:
    return f"slot_lock:{tenant_id}:{calendar_id}:{slot_start_iso}"


class SlotLock:
    """`async with SlotLock(redis_client, key):` -- raises SlotAlreadyLockedError
    on __aenter__ if another booking attempt already holds it."""

    def __init__(self, redis_client: redis.Redis, key: str, ttl_ms: int = DEFAULT_TTL_MS):
        self._redis = redis_client
        self._key = key
        self._ttl_ms = ttl_ms
        self._token = uuid.uuid4().hex

    async def acquire(self) -> bool:
        return bool(await self._redis.set(self._key, self._token, nx=True, px=self._ttl_ms))

    async def release(self) -> None:
        await self._redis.eval(_RELEASE_SCRIPT, 1, self._key, self._token)

    async def __aenter__(self) -> "SlotLock":
        if not await self.acquire():
            raise SlotAlreadyLockedError(self._key)
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.release()


class SlotAlreadyLockedError(RuntimeError):
    def __init__(self, key: str):
        super().__init__(f"Slot {key!r} is already being booked by another call")
        self.key = key
