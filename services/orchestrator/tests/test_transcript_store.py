"""
PROP-506 follow-up: tests for the interactions write path (transcript_store.py).
Needs a real Postgres instance with migrations applied -- not mocked, since
the whole point is to verify PII masking + RLS tenant scoping on the actual
INSERT.

Run: python -m pytest tests/test_transcript_store.py -v
"""

import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transcript_store import save_interaction

DATABASE_URL = "postgresql://propview_app:devpassword@localhost/propview_dev"
TENANT_ID = "default"


def unique_call_id() -> str:
    return f"test-call-{uuid.uuid4().hex[:8]}"


async def _fetch_row(call_id: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", TENANT_ID)
            return await conn.fetchrow("SELECT * FROM interactions WHERE call_id = $1", call_id)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_save_interaction_masks_pii_and_persists():
    call_id = unique_call_id()
    transcript = "Caller: My name is John Smith, call me at 512-555-0199.\nAgent: Sure thing."

    await save_interaction(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        transcript=transcript,
        duration_seconds=42,
    )

    row = await _fetch_row(call_id)
    assert row is not None
    assert row["tenant_id"] == TENANT_ID
    assert row["duration_seconds"] == 42
    assert row["channel"] == "voice"
    assert "John Smith" not in row["transcript"]
    assert "512-555-0199" not in row["transcript"]
    assert "<PERSON>" in row["transcript"]


@pytest.mark.asyncio
async def test_save_interaction_skips_blank_transcript():
    call_id = unique_call_id()

    await save_interaction(
        database_url=DATABASE_URL,
        tenant_id=TENANT_ID,
        call_id=call_id,
        transcript="   ",
        duration_seconds=5,
    )

    row = await _fetch_row(call_id)
    assert row is None
