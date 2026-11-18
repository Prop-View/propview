"""Restricted calls to platform registry SECURITY DEFINER functions."""

from __future__ import annotations

import asyncpg

from db import get_pool


async def resolve_tenant_by_phone(database_url: str, phone_number: str) -> str | None:
    """Resolve an active tenant through the platform-only database function."""
    pool = await get_pool(database_url)
    async with pool.acquire() as connection:
        return await connection.fetchval(
            "SELECT public.platform_resolve_tenant_by_phone($1)",
            phone_number,
        )


async def list_active_tenant_ids(database_url: str) -> list[str]:
    """Enumerate active tenants through the restricted platform function."""
    pool = await get_pool(database_url)
    async with pool.acquire() as connection:
        rows = await connection.fetch("SELECT public.platform_list_active_tenants() AS tenant_id")
    return [row["tenant_id"] for row in rows]


async def list_registry_tenants(database_url: str) -> list[asyncpg.Record]:
    pool = await get_pool(database_url)
    async with pool.acquire() as connection:
        return await connection.fetch(
            """
            SELECT slug, name, status, plan, created_at
            FROM public.platform_list_tenants()
            """
        )


async def list_registry_phone_numbers(database_url: str) -> list[asyncpg.Record]:
    pool = await get_pool(database_url)
    async with pool.acquire() as connection:
        return await connection.fetch(
            """
            SELECT phone_number, tenant_id, created_at
            FROM public.platform_list_tenant_phone_numbers()
            """
        )
