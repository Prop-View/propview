"""Shared Redis client for rate_limit.py. Lazy singleton, same pattern as
db.py's connection pool and ../tool-router/redis_client.py (duplicated,
not imported across the service boundary, same as db.py/auth.py -- each
service owns its own copy)."""

from __future__ import annotations

import os

import redis.asyncio as redis

_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
    return _client


async def close_redis_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
