"""Tenant-scoped database connections for orchestrator persistence."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg


@asynccontextmanager
async def tenant_connection(tenant_id: str, database_url: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            yield conn
    finally:
        await conn.close()
