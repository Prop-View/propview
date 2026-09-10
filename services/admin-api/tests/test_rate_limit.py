"""
Closes infra/observability/SECURITY_AUDIT.md section 4's "no rate
limiting anywhere" finding for this service. Needs a real Redis instance
-- not mocked, same rationale as ../../tool-router/tests/test_rate_limit.py.

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

from rate_limit import rate_limited


@pytest_asyncio.fixture
async def redis_client(monkeypatch):
    client = Redis.from_url("redis://localhost:6379", decode_responses=True)
    # rate_limited()'s dependency reaches for the module-level singleton
    # in redis_client.py, not an injectable parameter (it has to work as
    # a plain FastAPI Depends() callable taking only `tenant_id`) -- point
    # that singleton at this test's own client instance.
    import redis_client as redis_client_module

    monkeypatch.setattr(redis_client_module, "_client", client)
    yield client
    await client.aclose()


def unique_tenant_id() -> str:
    return f"test-tenant-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_requests_under_the_limit_are_allowed(redis_client):
    dependency = rate_limited(limit=5, window_seconds=10)
    tenant_id = unique_tenant_id()
    for _ in range(5):
        await dependency(tenant_id)


@pytest.mark.asyncio
async def test_request_over_the_limit_is_rejected(redis_client):
    dependency = rate_limited(limit=3, window_seconds=10)
    tenant_id = unique_tenant_id()
    for _ in range(3):
        await dependency(tenant_id)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(tenant_id)
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_different_tenants_have_independent_budgets(redis_client):
    dependency = rate_limited(limit=3, window_seconds=10)
    tenant_a, tenant_b = unique_tenant_id(), unique_tenant_id()
    for _ in range(3):
        await dependency(tenant_a)

    with pytest.raises(HTTPException):
        await dependency(tenant_a)

    await dependency(tenant_b)  # untouched by tenant_a's flood


@pytest.mark.asyncio
async def test_different_limits_for_the_same_tenant_share_one_budget(redis_client):
    # rate_limited() keys purely by tenant_id (not tenant_id+route) --
    # deliberate, see rate_limit.py's module docstring. A route using a
    # *smaller* limit hits 429 sooner because it's counting the same
    # underlying Redis key as one already incremented by a more generous
    # route for that tenant.
    tenant_id = unique_tenant_id()
    generous = rate_limited(limit=10, window_seconds=10)
    strict = rate_limited(limit=2, window_seconds=10)

    await generous(tenant_id)
    await generous(tenant_id)

    with pytest.raises(HTTPException):
        await strict(tenant_id)  # same tenant, same window -- already at 2
