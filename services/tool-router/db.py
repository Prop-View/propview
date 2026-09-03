"""Shared asyncpg connection pool for the Tool Router."""

from __future__ import annotations

import os

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
