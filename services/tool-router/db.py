"""Shared asyncpg connection pool for the Tool Router."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import asyncpg
from pgvector.asyncpg import register_vector

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL", "postgresql://localhost/propview_dev")
        # init=register_vector runs on every pooled connection so
        # search_knowledge_base.py can bind Python lists to `vector` columns
        # directly -- without it asyncpg has no idea how to encode them.
        _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10, init=register_vector)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def tenant_connection(tenant_id: str):
    """Acquires a connection with PROP-601's RLS tenant context set for the
    life of one transaction. Required since RLS here is fail-closed: a
    connection that never sets app.tenant_id sees zero rows, not all rows.

    NOTE: this only actually enforces isolation if DATABASE_URL connects as
    a non-superuser role -- Postgres always bypasses RLS for superusers,
    FORCE ROW LEVEL SECURITY notwithstanding. See db/migrations/README.md.
    """
    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            yield connection


def record_to_dict(row: asyncpg.Record) -> dict:
    """asyncpg returns NUMERIC as Decimal and JSONB as a raw JSON string --
    neither is directly JSON-serializable for a tool response sent back to
    Gemini, so normalize both here."""
    import json
    from decimal import Decimal

    out = dict(row)
    for key, value in out.items():
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif key == "amenities" and isinstance(value, str):
            out[key] = json.loads(value)
    return out
