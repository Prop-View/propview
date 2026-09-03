"""
Tests for the slot lock against a real Redis instance (not mocked -- the
point is to verify actual SET NX / TTL / token-checked release behavior,
same rationale as ../../orchestrator/tests/test_session_store.py).

Run: redis-server &   (or: brew services start redis)
     python -m pytest tests/test_redis_lock.py -v
"""

import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
import redis.asyncio as redis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redis_lock import SlotAlreadyLockedError, SlotLock, slot_lock_key


@pytest_asyncio.fixture
async def redis_client():
    client = redis.from_url("redis://localhost:6379", decode_responses=True)
    yield client
    await client.aclose()


def unique_key() -> str:
    return f"test-slot-lock:{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_acquire_and_release(redis_client):
    key = unique_key()
    lock = SlotLock(redis_client, key)

    assert await lock.acquire() is True
    assert await redis_client.get(key) is not None

    await lock.release()
    assert await redis_client.get(key) is None


@pytest.mark.asyncio
async def test_second_acquire_fails_while_held(redis_client):
    key = unique_key()
    first = SlotLock(redis_client, key)
    second = SlotLock(redis_client, key)

    assert await first.acquire() is True
    assert await second.acquire() is False  # different token, key already set

    await first.release()


@pytest.mark.asyncio
async def test_context_manager_raises_when_already_locked(redis_client):
    key = unique_key()
    async with SlotLock(redis_client, key):
        with pytest.raises(SlotAlreadyLockedError):
            async with SlotLock(redis_client, key):
                pass

    # released cleanly after the outer context exits
    assert await redis_client.get(key) is None


@pytest.mark.asyncio
async def test_release_does_not_delete_a_different_holders_lock(redis_client):
    """A lock past its TTL and re-acquired by someone else must not be
    deleted by the original holder's (late) release() call."""
    key = unique_key()
    first = SlotLock(redis_client, key, ttl_ms=50)
    await first.acquire()

    import asyncio

    await asyncio.sleep(0.1)  # let it expire
    second = SlotLock(redis_client, key)
    assert await second.acquire() is True  # re-acquired by someone else

    await first.release()  # first's token no longer matches -- must be a no-op
    assert await redis_client.get(key) is not None  # second's lock survives

    await second.release()


@pytest.mark.asyncio
async def test_slot_lock_key_is_stable_and_distinguishes_slots():
    k1 = slot_lock_key("tenant-a", "primary", "2026-09-10T14:00:00-05:00")
    k2 = slot_lock_key("tenant-a", "primary", "2026-09-10T14:00:00-05:00")
    k3 = slot_lock_key("tenant-a", "primary", "2026-09-10T15:00:00-05:00")
    assert k1 == k2
    assert k1 != k3
