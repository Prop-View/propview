"""
Closes infra/observability/SECURITY_AUDIT.md section 4's "no rate
limiting anywhere" finding for this service. Needs a real Redis instance
-- not mocked, since the whole point is the real INCR/EXPIRE behavior.

Run: redis-server & (or brew services start redis)
     python -m pytest tests/test_rate_limit.py -v
"""

import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from redis.asyncio import Redis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rate_limit import enforce_rate_limit


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url("redis://localhost:6379", decode_responses=True)
    yield client
    await client.aclose()


def unique_key() -> str:
    return f"test-tenant-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_requests_under_the_limit_are_allowed(redis_client):
    key = unique_key()
    for _ in range(5):
        await enforce_rate_limit(redis_client, key=key, limit=5, window_seconds=10)
    # No exception raised -- all 5 allowed.


@pytest.mark.asyncio
async def test_request_over_the_limit_is_rejected(redis_client):
    key = unique_key()
    for _ in range(3):
        await enforce_rate_limit(redis_client, key=key, limit=3, window_seconds=10)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(redis_client, key=key, limit=3, window_seconds=10)
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_different_tenants_have_independent_budgets(redis_client):
    tenant_a, tenant_b = unique_key(), unique_key()
    for _ in range(3):
        await enforce_rate_limit(redis_client, key=tenant_a, limit=3, window_seconds=10)

    with pytest.raises(HTTPException):
        await enforce_rate_limit(redis_client, key=tenant_a, limit=3, window_seconds=10)

    # tenant_b's budget is untouched by tenant_a's flood.
    await enforce_rate_limit(redis_client, key=tenant_b, limit=3, window_seconds=10)


@pytest.mark.asyncio
async def test_budget_resets_in_a_new_window(redis_client):
    import asyncio

    key = unique_key()
    for _ in range(2):
        await enforce_rate_limit(redis_client, key=key, limit=2, window_seconds=1)
    with pytest.raises(HTTPException):
        await enforce_rate_limit(redis_client, key=key, limit=2, window_seconds=1)

    await asyncio.sleep(1.2)  # cross into the next 1s window

    await enforce_rate_limit(redis_client, key=key, limit=2, window_seconds=1)  # allowed again
