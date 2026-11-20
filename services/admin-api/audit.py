"""Tenant-scoped audit-log writes."""

from __future__ import annotations

import json


async def write_audit(
    conn,
    tenant_id: str,
    action: str,
    actor_user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    metadata: dict | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO audit_log
            (tenant_id, actor_user_id, action, entity_type, entity_id, metadata)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        """,
        tenant_id,
        actor_user_id,
        action,
        entity_type,
        str(entity_id) if entity_id is not None else None,
        json.dumps(metadata or {}),
    )
