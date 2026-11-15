"""Tenant-scoped inserts into the usage_events ledger."""

from __future__ import annotations

import json
from typing import Literal

import asyncpg

UsageEventType = Literal["call", "sms", "whatsapp"]


async def record_usage_event(
    connection: asyncpg.Connection,
    tenant_id: str,
    event_type: UsageEventType,
    source_id: str,
    metadata: dict | None = None,
) -> None:
    if not source_id:
        raise ValueError("usage event source_id must not be empty")

    await connection.execute(
        """
        INSERT INTO usage_events (tenant_id, event_type, source_id, metadata)
        VALUES ($1, $2, $3, $4::jsonb)
        ON CONFLICT (tenant_id, event_type, source_id) DO NOTHING
        """,
        tenant_id,
        event_type,
        source_id,
        json.dumps(metadata or {}),
    )
