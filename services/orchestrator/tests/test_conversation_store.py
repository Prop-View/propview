"""
Tests for conversation_store.py -- structured conversation persistence
for ML training data.

Needs a real Postgres instance with migrations applied (including
009_conversation_store.sql). Same pattern as test_transcript_store.py.

Run: python -m pytest tests/test_conversation_store.py -v
"""

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import asyncpg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conversation_context import ContextLine
from conversation_store import ToolInvocationRecord, save_conversation_data

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://propview_app:devpassword@localhost/propview_dev"
)
TENANT_ID = "default"


def unique_call_id() -> str:
    return f"test-conv-{uuid.uuid4().hex[:8]}"


async def _fetch_turns(call_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, true)", TENANT_ID
            )
            return await conn.fetch(
                "SELECT * FROM conversation_turns WHERE call_id = $1 ORDER BY turn_index",
                call_id,
            )
    finally:
        await conn.close()


async def _fetch_tool_invocations(call_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, true)", TENANT_ID
            )
            return await conn.fetch(
                "SELECT * FROM tool_invocations WHERE call_id = $1 ORDER BY created_at",
                call_id,
            )
    finally:
        await conn.close()


async def _fetch_analytics(call_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, true)", TENANT_ID
            )
            return await conn.fetchrow(
                "SELECT * FROM call_analytics WHERE call_id = $1", call_id
            )
    finally:
        await conn.close()


@pytest.fixture
def mock_context_store():
    store = AsyncMock()
    lines = [
        ContextLine(speaker="caller", text="I want a 3BHK", interrupted=False, timestamp=1000.0),
        ContextLine(speaker="agent", text="Let me search for that", interrupted=False, timestamp=1001.5),
        ContextLine(speaker="caller", text="In Whitefield", interrupted=False, timestamp=1003.0),
        ContextLine(speaker="agent", text="I found several", interrupted=True, timestamp=1004.0),
    ]
    store.get_lines = AsyncMock(return_value=lines)
    return store


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
async def test_saves_conversation_turns(mock_context_store):
    call_id = unique_call_id()

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=mock_context_store,
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


@pytest.mark.asyncio
async def test_saves_tool_invocations(sample_tool_invocations):
    call_id = unique_call_id()
    empty_context = AsyncMock()
    empty_context.get_lines = AsyncMock(return_value=[])

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=empty_context,
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
async def test_saves_call_analytics(mock_context_store, sample_tool_invocations):
    call_id = unique_call_id()

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=mock_context_store,
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


@pytest.mark.asyncio
async def test_skips_when_no_data():
    call_id = unique_call_id()
    empty_context = AsyncMock()
    empty_context.get_lines = AsyncMock(return_value=[])

    await save_conversation_data(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        conversation_context=empty_context,
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
    empty_context = AsyncMock()
    empty_context.get_lines = AsyncMock(return_value=[])

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
        conversation_context=empty_context,
        tool_invocations=[failed_inv],
        duration_seconds=15,
        barge_in_count=0,
        outcome="dropped",
    )

    rows = await _fetch_tool_invocations(call_id)
    assert len(rows) == 1
    assert rows[0]["success"] is False
    assert rows[0]["error"] == "Calendar API unavailable"
    assert rows[0]["output_result"] is None
