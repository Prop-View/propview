"""
Closes infra/observability/SECURITY_AUDIT.md section 4's "no rate
limiting anywhere" finding for this service. Now that auth (auth.py) is
required, the threat this defends against isn't an unauthenticated flood
(that's rejected before touching Redis/Postgres at all) -- it's a single
tenant's calls (legitimately authenticated via the orchestrator, but
buggy or abusive) monopolizing shared infrastructure that every other
tenant's calls also depend on. Rate limited per tenant_id, not per
caller, since the caller is always the same orchestrator.

Fixed-window counter via Redis INCR/EXPIRE -- not a sliding window or
token bucket. Simpler and sufficient here: the failure mode of a fixed
window (a caller can burst up to ~2x the limit right at a window
boundary) is a real but minor gap against the actual threat model (a
sustained flood, not a single well-timed burst), and this needs no
extra Redis data structure beyond what redis_client.py already provides.
"""

from __future__ import annotations

import os
import time

from fastapi import HTTPException
from redis.asyncio import Redis

DEFAULT_LIMIT = int(os.environ.get("RATE_LIMIT_TOOL_CALLS_PER_WINDOW", "120"))
DEFAULT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "10"))


async def enforce_rate_limit(
    redis_client: Redis,
    key: str,
    limit: int = DEFAULT_LIMIT,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> None:
    """Raises HTTPException(429) if `key` has exceeded `limit` requests in
    the current `window_seconds`-wide window. Call this explicitly inside
    a route (not via Depends()) when the rate-limit key comes from the
    request body -- FastAPI dependencies and route handlers each parsing
    the same Pydantic body model isn't guaranteed to share a single parse,
    and this needs exactly one canonical `request.tenant_id`, not a
    second independently-parsed copy."""
    bucket = int(time.time()) // window_seconds
    redis_key = f"ratelimit:tool-router:{key}:{bucket}"
    count = await redis_client.incr(redis_key)
    if count == 1:
        await redis_client.expire(redis_key, window_seconds)
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per {window_seconds}s for {key!r}",
        )
