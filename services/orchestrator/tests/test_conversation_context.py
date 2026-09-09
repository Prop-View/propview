"""
PROP-204: Tests for the Redis-backed live conversation context window.
Needs a real Redis instance -- not mocked, same rationale as
test_session_store.py (the whole point is to verify real Redis list
behavior: ordering, trimming, TTL).

Run: redis-server & (or brew services start redis)
     python -m pytest tests/test_conversation_context.py -v
"""

import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conversation_context import ConversationContextStore


@pytest_asyncio.fixture
async def store():
    s = ConversationContextStore(redis_url="redis://localhost:6379", ttl_seconds=2)
    yield s
    await s.aclose()


def unique_call_id() -> str:
    return f"test-context-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_append_and_get_lines_preserves_order(store):
    call_id = unique_call_id()
    await store.append_line(call_id, "caller", "Hi, I'm looking for a house")
    await store.append_line(call_id, "agent", "Great, what area are you interested in")
    await store.append_line(call_id, "caller", "North Austin")

    lines = await store.get_lines(call_id)
    assert [line.speaker for line in lines] == ["caller", "agent", "caller"]
    assert [line.text for line in lines] == [
        "Hi, I'm looking for a house",
        "Great, what area are you interested in",
        "North Austin",
    ]
    assert all(line.interrupted is False for line in lines)

    await store.clear(call_id)


@pytest.mark.asyncio
async def test_interrupted_flag_is_stored(store):
    call_id = unique_call_id()
    await store.append_line(call_id, "agent", "This house has four bed", interrupted=True)

    lines = await store.get_lines(call_id)
    assert len(lines) == 1
    assert lines[0].interrupted is True

    await store.clear(call_id)


@pytest.mark.asyncio
async def test_get_lines_for_unknown_call_returns_empty(store):
    assert await store.get_lines(unique_call_id()) == []


@pytest.mark.asyncio
async def test_clear_removes_all_lines(store):
    call_id = unique_call_id()
    await store.append_line(call_id, "caller", "hello")
    assert await store.get_lines(call_id) != []

    await store.clear(call_id)
    assert await store.get_lines(call_id) == []


@pytest.mark.asyncio
async def test_lines_expire_via_ttl(store):
    import asyncio

    call_id = unique_call_id()
    await store.append_line(call_id, "caller", "hello")
    assert await store.get_lines(call_id) != []

    await asyncio.sleep(2.5)
    assert await store.get_lines(call_id) == [], "context should have expired via Redis TTL"


@pytest.mark.asyncio
async def test_list_is_trimmed_to_max_lines(store):
    from conversation_context import MAX_LINES

    call_id = unique_call_id()
    for i in range(MAX_LINES + 20):
        await store.append_line(call_id, "caller", f"line {i}")

    lines = await store.get_lines(call_id)
    assert len(lines) == MAX_LINES
    # The trim keeps the most recent MAX_LINES, not the oldest.
    assert lines[-1].text == f"line {MAX_LINES + 19}"

    await store.clear(call_id)
