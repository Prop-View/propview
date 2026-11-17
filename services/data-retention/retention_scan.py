"""One-shot per-tenant retention job for persisted call content."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool-router"))
sys.path.append(str(Path(__file__).resolve().parents[1] / "orchestrator"))

load_dotenv()

from db import close_pool, tenant_connection  # noqa: E402
from tenant_registry import list_active_tenant_ids  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_retention")

DATABASE_URL = os.environ.get("DATABASE_URL")


async def _purge_tenant(tenant_id: str, retention_days: int) -> dict[str, int]:
    async with tenant_connection(tenant_id) as connection:
        updated_transcripts = await connection.fetchval(
            """
            WITH changed AS (
                UPDATE interactions
                SET transcript = NULL
                WHERE tenant_id = $1
                  AND created_at < now() - make_interval(days => $2)
                  AND transcript IS NOT NULL
                RETURNING 1
            )
            SELECT count(*) FROM changed
            """,
            tenant_id,
            retention_days,
        )
        deleted_turns = await connection.fetchval(
            """
            WITH deleted AS (
                DELETE FROM conversation_turns
                WHERE tenant_id = $1
                  AND created_at < now() - make_interval(days => $2)
                RETURNING 1
            )
            SELECT count(*) FROM deleted
            """,
            tenant_id,
            retention_days,
        )
        deleted_tool_invocations = await connection.fetchval(
            """
            WITH deleted AS (
                DELETE FROM tool_invocations
                WHERE tenant_id = $1
                  AND created_at < now() - make_interval(days => $2)
                RETURNING 1
            )
            SELECT count(*) FROM deleted
            """,
            tenant_id,
            retention_days,
        )

    return {
        "transcripts_cleared": updated_transcripts,
        "turns_deleted": deleted_turns,
        "tool_invocations_deleted": deleted_tool_invocations,
    }


async def run_retention_scan() -> dict[str, dict[str, int]]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for data retention")

    tenant_ids = await list_active_tenant_ids(DATABASE_URL)
    if not tenant_ids:
        logger.info("No active tenants; no retention work was needed")
        return {}

    policies: dict[str, int] = {}
    tenants_without_policy: list[str] = []
    for tenant_id in tenant_ids:
        async with tenant_connection(tenant_id) as connection:
            retention_days = await connection.fetchval(
                "SELECT retention_days FROM tenant_data_retention WHERE tenant_id = $1",
                tenant_id,
            )
        if retention_days is None:
            tenants_without_policy.append(tenant_id)
        else:
            policies[tenant_id] = retention_days

    if tenants_without_policy:
        raise RuntimeError(
            "No retention policy configured for active tenant(s): "
            + ", ".join(tenants_without_policy)
            + "; no data was deleted"
        )

    results: dict[str, dict[str, int]] = {}
    for tenant_id in tenant_ids:
        results[tenant_id] = await _purge_tenant(tenant_id, policies[tenant_id])
        logger.info("Retention completed for tenant %s: %s", tenant_id, results[tenant_id])
    return results


async def _main() -> None:
    try:
        await run_retention_scan()
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
