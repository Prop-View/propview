"""
Closes infra/observability/SECURITY_AUDIT.md section 4's "no rate
limiting anywhere" finding for this service. Rate limited per tenant_id
(from the URL path -- trivially available to a FastAPI dependency here,
unlike ../tool-router/rate_limit.py where tenant_id lives in the request
body instead), so one tenant's traffic -- or a single leaked/misused
tenant API key -- can't monopolize shared Postgres that every other
tenant's calls also depend on.

Same fixed-window-via-Redis-INCR/EXPIRE design and tradeoff as
../tool-router/rate_limit.py -- see that module's docstring. Duplicated
rather than imported across the service boundary, same as db.py/auth.py.

The budget is per-tenant across *all* routes sharing a given `limit`
(the key is just `tenant_id`, not `tenant_id + route`) -- deliberate:
what this protects against is one tenant's overall traffic monopolizing
shared Postgres, not any single endpoint in isolation. Provisioning gets
its own, much tighter, separate budget (`PROVISION_LIMIT`) since it's a
materially different, more sensitive action (mints/rotates a tenant's
credential) from the day-to-day listings/branding/calendar routes.
"""

from __future__ import annotations

import os
import time

from fastapi import HTTPException
from redis.asyncio import Redis

from redis_client import get_redis_client

DEFAULT_LIMIT = int(os.environ.get("RATE_LIMIT_ADMIN_REQUESTS_PER_WINDOW", "30"))
# Provisioning mints/rotates a tenant's admin API key -- far rarer and
# more sensitive than a listing upload, so a much tighter ceiling.
PROVISION_LIMIT = int(os.environ.get("RATE_LIMIT_PROVISION_REQUESTS_PER_WINDOW", "5"))
DEFAULT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))


async def _enforce(redis_client: Redis, key: str, limit: int, window_seconds: int) -> None:
    bucket = int(time.time()) // window_seconds
    redis_key = f"ratelimit:admin-api:{key}:{bucket}"
    count = await redis_client.incr(redis_key)
    if count == 1:
        await redis_client.expire(redis_key, window_seconds)
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per {window_seconds}s for tenant {key!r}",
        )


def rate_limited(limit: int = DEFAULT_LIMIT, window_seconds: int = DEFAULT_WINDOW_SECONDS):
    """Returns a FastAPI dependency that rate-limits by the route's own
    `tenant_id` path parameter -- use as
    `dependencies=[Depends(rate_limited())]` (or `rate_limited(PROVISION_LIMIT)`
    for a stricter route)."""

    async def dependency(tenant_id: str) -> None:
        await _enforce(get_redis_client(), key=tenant_id, limit=limit, window_seconds=window_seconds)

    return dependency
