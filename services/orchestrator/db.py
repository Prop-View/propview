"""Tenant-scoped database connections for orchestrator persistence."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

_pool: asyncpg.Pool | None = None
_pool_database_url: str | None = None
_pool_lock = asyncio.Lock()


async def get_pool(database_url: str | None = None) -> asyncpg.Pool:
    global _pool, _pool_database_url
    resolved_url = database_url or os.environ.get("DATABASE_URL")
    if not resolved_url:
        raise RuntimeError("DATABASE_URL is required for orchestrator database access")

    async with _pool_lock:
        if _pool is not None:
            if _pool_database_url != resolved_url:
                raise RuntimeError("Orchestrator database pool is already bound to a different DATABASE_URL")
            return _pool

        _pool = await asyncpg.create_pool(resolved_url, min_size=1, max_size=10)
        _pool_database_url = resolved_url
        return _pool


async def close_pool() -> None:
    global _pool, _pool_database_url
    async with _pool_lock:
        if _pool is not None:
            await _pool.close()
            _pool = None
            _pool_database_url = None


def terminate_pool() -> None:
    """Synchronously release the worker pool at interpreter shutdown."""
    global _pool, _pool_database_url
    if _pool is not None:
        _pool.terminate()
        _pool = None
        _pool_database_url = None


@asynccontextmanager
async def tenant_connection(
    tenant_id: str, database_url: str | None = None
) -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool(database_url)
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            yield connection
