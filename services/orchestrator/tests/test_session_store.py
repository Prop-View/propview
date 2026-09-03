"""
PROP-106: Tests for the Redis session store. Needs a real Redis instance --
not mocked, since the whole point is to verify actual TTL/expiry behavior.

Run: redis-server & (or brew services start redis)
     python -m pytest tests/test_session_store.py -v
"""

import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_store import CallSession, SessionStore


@pytest_asyncio.fixture
async def store():
    s = SessionStore(redis_url="redis://localhost:6379", ttl_seconds=2)
    yield s
    await s.aclose()


def unique_call_id() -> str:
    return f"test-call-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_create_and_get_session(store):
    call_id = unique_call_id()
    created = await store.create_session(call_id, room_name="call-abc123", caller_number="+15125551234")

    fetched = await store.get_session(call_id)
    assert fetched is not None
    assert fetched.call_id == call_id
    assert fetched.room_name == "call-abc123"
    assert fetched.caller_number == "+15125551234"
    assert fetched.started_at == created.started_at

    await store.end_session(call_id)


@pytest.mark.asyncio
async def test_get_nonexistent_session_returns_none(store):
    assert await store.get_session(unique_call_id()) is None


@pytest.mark.asyncio
async def test_end_session_removes_it(store):
    call_id = unique_call_id()
    await store.create_session(call_id, room_name="call-xyz")
    assert await store.get_session(call_id) is not None

    await store.end_session(call_id)
    assert await store.get_session(call_id) is None


@pytest.mark.asyncio
async def test_session_expires_via_ttl(store):
    # store fixture uses ttl_seconds=2
    import asyncio

    call_id = unique_call_id()
    await store.create_session(call_id, room_name="call-ephemeral")
    assert await store.get_session(call_id) is not None

    await asyncio.sleep(2.5)
    assert await store.get_session(call_id) is None, "session should have expired via Redis TTL"


@pytest.mark.asyncio
async def test_touch_refreshes_ttl(store):
    import asyncio

    call_id = unique_call_id()
    await store.create_session(call_id, room_name="call-long")

    await asyncio.sleep(1.5)
    assert await store.touch(call_id) is True  # resets TTL back to 2s

    await asyncio.sleep(1.5)
    # 3s have elapsed since creation, but touch() reset the clock at 1.5s,
    # so the session should still be alive (only 1.5s since the touch).
    assert await store.get_session(call_id) is not None

    await store.end_session(call_id)


@pytest.mark.asyncio
async def test_touch_on_nonexistent_session_returns_false(store):
    assert await store.touch(unique_call_id()) is False


def test_call_session_json_roundtrip():
    session = CallSession(call_id="c1", room_name="call-1", caller_number="+1555", started_at=123.456)
    restored = CallSession.from_json(session.to_json())
    assert restored == session
