"""Shared asyncpg connection pool for the Tenant Admin API. Same
tenant_connection() pattern as services/tool-router/db.py -- RLS
(PROP-601) is fail-closed, so every query must set app.tenant_id first."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import asyncpg

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL", "postgresql://localhost/propview_dev")
        _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def tenant_connection(tenant_id: str):
    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            yield connection
