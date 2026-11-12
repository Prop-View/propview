"""
Tests for conversation_store.py -- structured conversation persistence
for ML training data.

Needs real Postgres and Redis instances with migrations applied
(including 009_conversation_store.sql). Same pattern as test_transcript_store.py.

Run: python -m pytest tests/test_conversation_store.py -v
"""

import os
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conversation_context import ContextLine, ConversationContextStore
from conversation_store import ToolInvocationRecord, save_conversation_data
from db import tenant_connection
from mask_existing_conversation_pii import mask_existing_conversation_data

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://propview_app:devpassword@localhost/propview_dev"
)
TENANT_ID = "default"


def unique_call_id() -> str:
    return f"test-conv-{uuid.uuid4().hex[:8]}"


async def _fetch_turns(call_id: str):
    async with tenant_connection(TENANT_ID, DATABASE_URL) as conn:
        return await conn.fetch(
            "SELECT * FROM conversation_turns WHERE call_id = $1 ORDER BY turn_index",
            call_id,
        )


async def _fetch_tool_invocations(call_id: str):
    async with tenant_connection(TENANT_ID, DATABASE_URL) as conn:
        return await conn.fetch(
            "SELECT * FROM tool_invocations WHERE call_id = $1 ORDER BY created_at",
            call_id,
        )


async def _fetch_analytics(call_id: str):
    async with tenant_connection(TENANT_ID, DATABASE_URL) as conn:
        return await conn.fetchrow(
            "SELECT * FROM call_analytics WHERE call_id = $1", call_id
        )


@pytest_asyncio.fixture
async def context_store():
    store = ConversationContextStore(
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    yield store
    await store.aclose()


async def _append_sample_lines(store: ConversationContextStore, call_id: str) -> None:
    lines = [
        ContextLine(speaker="caller", text="I want a 3BHK", interrupted=False, timestamp=1000.0),
        ContextLine(speaker="agent", text="Let me search for that", interrupted=False, timestamp=1001.5),
        ContextLine(speaker="caller", text="In Whitefield", interrupted=False, timestamp=1003.0),
        ContextLine(speaker="agent", text="I found several", interrupted=True, timestamp=1004.0),
    ]
    for line in lines:
        await store.append_line(
            call_id,
            line.speaker,
            line.text,
            interrupted=line.interrupted,
            timestamp=line.timestamp,
        )


@pytest.fixture
def sample_tool_invocations():
    return [
        ToolInvocationRecord(
            tool_name="search_properties",
            input_params={"bedrooms": 3, "location": "Whitefield"},
            output_result={"properties": [{"id": 1, "name": "Test Property"}]},
            error=None,
            latency_ms=120.5,
            success=True,
        ),
        ToolInvocationRecord(
            tool_name="update_lead_qualification",
            input_params={"intent": "buy", "budget_min": 5000000},
            output_result={"lead_id": 42},
            error=None,
            latency_ms=45.2,
            success=True,
        ),
    ]


@pytest.mark.asyncio
async def test_saves_conversation_turns(context_store):
    call_id = unique_call_id()
    await _append_sample_lines(context_store, call_id)

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=context_store,
        tool_invocations=[],
        duration_seconds=30,
        barge_in_count=1,
        outcome="unknown",
    )

    rows = await _fetch_turns(call_id)
    assert len(rows) == 4
    assert rows[0]["speaker"] == "caller"
    assert rows[0]["text"] == "I want a 3BHK"
    assert rows[0]["turn_index"] == 0
    assert rows[0]["interrupted"] is False
    assert rows[3]["speaker"] == "agent"
    assert rows[3]["interrupted"] is True
    await context_store.clear(call_id)


@pytest.mark.asyncio
async def test_saves_every_turn_even_when_redis_window_is_truncated(context_store):
    call_id = unique_call_id()
    all_lines = [
        ContextLine(
            speaker="caller" if idx % 2 == 0 else "agent",
            text=f"turn {idx}",
            interrupted=False,
            timestamp=1000.0 + idx,
        )
        for idx in range(225)
    ]
    for line in all_lines:
        await context_store.append_line(
            call_id,
            line.speaker,
            line.text,
            interrupted=line.interrupted,
            timestamp=line.timestamp,
        )
    assert len(await context_store.get_lines(call_id)) == 200

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=context_store,
        tool_invocations=[],
        duration_seconds=300,
        barge_in_count=0,
        outcome="unknown",
        conversation_lines=all_lines,
    )

    rows = await _fetch_turns(call_id)
    assert len(rows) == len(all_lines)
    assert rows[0]["text"] == "turn 0"
    assert rows[-1]["text"] == "turn 224"
    await context_store.clear(call_id)


@pytest.mark.asyncio
async def test_saves_tool_invocations(sample_tool_invocations):
    call_id = unique_call_id()

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=None,
        tool_invocations=sample_tool_invocations,
        duration_seconds=60,
        barge_in_count=0,
        outcome="qualified",
    )

    rows = await _fetch_tool_invocations(call_id)
    assert len(rows) == 2
    assert rows[0]["tool_name"] == "search_properties"
    assert rows[0]["success"] is True
    assert rows[0]["latency_ms"] == pytest.approx(120.5, abs=0.1)
    assert rows[1]["tool_name"] == "update_lead_qualification"


@pytest.mark.asyncio
async def test_saves_call_analytics(context_store, sample_tool_invocations):
    call_id = unique_call_id()
    await _append_sample_lines(context_store, call_id)

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=context_store,
        tool_invocations=sample_tool_invocations,
        duration_seconds=90,
        barge_in_count=2,
        outcome="booked",
        lead_id=None,
    )

    row = await _fetch_analytics(call_id)
    assert row is not None
    assert row["total_turns"] == 4
    assert row["caller_turns"] == 2
    assert row["agent_turns"] == 2
    assert row["duration_seconds"] == 90
    assert row["barge_in_count"] == 2
    assert row["outcome"] == "booked"
    await context_store.clear(call_id)


@pytest.mark.asyncio
async def test_skips_when_no_data():
    call_id = unique_call_id()

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=None,
        tool_invocations=[],
        duration_seconds=5,
        barge_in_count=0,
        outcome="dropped",
    )

    rows = await _fetch_turns(call_id)
    assert len(rows) == 0
    row = await _fetch_analytics(call_id)
    assert row is None


@pytest.mark.asyncio
async def test_records_failed_tool_invocation():
    call_id = unique_call_id()

    failed_inv = ToolInvocationRecord(
        tool_name="book_site_visit",
        input_params={"property_id": 99},
        output_result=None,
        error="Calendar API unavailable",
        latency_ms=5000.0,
        success=False,
    )

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=None,
        tool_invocations=[failed_inv],
        duration_seconds=15,
        barge_in_count=0,
        outcome="unknown",
    )

    rows = await _fetch_tool_invocations(call_id)
    assert len(rows) == 1
    assert rows[0]["success"] is False
    assert rows[0]["error"] == "Calendar API unavailable"
    assert rows[0]["output_result"] is None


@pytest.mark.asyncio
async def test_masks_pii_in_turns_and_nested_tool_data():
    call_id = unique_call_id()
    line = ContextLine(
        speaker="caller",
        text="My name is John Smith and my number is 555-123-4567.",
        interrupted=False,
        timestamp=1000.0,
    )
    invocation = ToolInvocationRecord(
        tool_name="save_contact",
        input_params={"contact": {"email": "jane.doe@example.com"}},
        output_result={"message": "Call Sarah Johnson at 555-123-4567."},
        error=None,
        latency_ms=1,
        success=True,
    )

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=None,
        tool_invocations=[invocation],
        duration_seconds=5,
        barge_in_count=0,
        outcome="unknown",
        conversation_lines=[line],
    )

    turns = await _fetch_turns(call_id)
    tool_rows = await _fetch_tool_invocations(call_id)
    assert "John Smith" not in turns[0]["text"]
    assert "555-123-4567" not in turns[0]["text"]
    assert "jane.doe@example.com" not in str(tool_rows[0]["input_params"])
    assert "Sarah Johnson" not in str(tool_rows[0]["output_result"])
    assert "555-123-4567" not in str(tool_rows[0]["output_result"])


@pytest.mark.asyncio
async def test_backfill_masks_existing_rows_for_the_selected_tenant():
    call_id = unique_call_id()
    async with tenant_connection(TENANT_ID, DATABASE_URL) as conn:
        await conn.execute(
            """
            INSERT INTO conversation_turns
                (tenant_id, call_id, turn_index, speaker, text, timestamp_ms)
            VALUES ($1, $2, 0, 'caller', 'My name is John Smith, 555-123-4567', 1000)
            """,
            TENANT_ID,
            call_id,
        )
        await conn.execute(
            """
            INSERT INTO tool_invocations
                (tenant_id, call_id, tool_name, input_params, output_result, error)
            VALUES ($1, $2, 'save_contact',
                    '{"email":"jane.doe@example.com"}',
                    '{"message":"Call Sarah Johnson"}',
                    'Phone 555-123-4567')
            """,
            TENANT_ID,
            call_id,
        )

    counts = await mask_existing_conversation_data(DATABASE_URL, TENANT_ID)

    turns = await _fetch_turns(call_id)
    tools = await _fetch_tool_invocations(call_id)
    assert counts["turns"] >= 1
    assert counts["tool_invocations"] >= 1
    assert "John Smith" not in turns[0]["text"]
    assert "555-123-4567" not in turns[0]["text"]
    assert "jane.doe@example.com" not in str(tools[0]["input_params"])
    assert "Sarah Johnson" not in str(tools[0]["output_result"])
    assert "555-123-4567" not in tools[0]["error"]
