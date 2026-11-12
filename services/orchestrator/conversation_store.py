"""
Persists structured conversation data to Postgres at call end for ML
training and algorithm improvement.

Three tables (db/migrations/009_conversation_store.sql):
- conversation_turns: per-utterance structured records
- tool_invocations: every tool call the AI made
- call_analytics: aggregated per-call metrics

The write path runs once at call end, right after transcript_store's
save_interaction -- it flushes the Redis ConversationContextStore lines
(structured, with timestamps) into conversation_turns before they expire,
and persists tool invocations + analytics that were only in memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import asyncpg

from conversation_context import ConversationContextStore

logger = logging.getLogger("conversation_store")


@dataclass
class ToolInvocationRecord:
    tool_name: str
    input_params: dict
    output_result: dict | None
    error: str | None
    latency_ms: float
    success: bool


async def save_conversation_data(
    database_url: str,
    tenant_id: str,
    call_id: str,
    conversation_context: ConversationContextStore | None,
    tool_invocations: list[ToolInvocationRecord],
    duration_seconds: int,
    barge_in_count: int,
    outcome: str,
    lead_id: int | None = None,
) -> None:
    lines = []
    if conversation_context is not None:
        lines = await conversation_context.get_lines(call_id)

    if not lines and not tool_invocations:
        return

    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, true)", tenant_id
            )

            for idx, line in enumerate(lines):
                await conn.execute(
                    """
                    INSERT INTO conversation_turns
                        (tenant_id, call_id, turn_index, speaker, text,
                         interrupted, timestamp_ms)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    tenant_id,
                    call_id,
                    idx,
                    line.speaker,
                    line.text,
                    line.interrupted,
                    line.timestamp * 1000,
                )

            for inv in tool_invocations:
                await conn.execute(
                    """
                    INSERT INTO tool_invocations
                        (tenant_id, call_id, tool_name, input_params,
                         output_result, error, latency_ms, success)
                    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)
                    """,
                    tenant_id,
                    call_id,
                    inv.tool_name,
                    _to_json(inv.input_params),
                    _to_json(inv.output_result) if inv.output_result else None,
                    inv.error,
                    inv.latency_ms,
                    inv.success,
                )

            caller_turns = sum(1 for l in lines if l.speaker == "caller")
            agent_turns = sum(1 for l in lines if l.speaker == "agent")
            tools_used = list({inv.tool_name for inv in tool_invocations})

            await conn.execute(
                """
                INSERT INTO call_analytics
                    (tenant_id, call_id, total_turns, caller_turns,
                     agent_turns, duration_seconds, tools_used,
                     barge_in_count, outcome, lead_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
                ON CONFLICT (call_id) DO NOTHING
                """,
                tenant_id,
                call_id,
                len(lines),
                caller_turns,
                agent_turns,
                duration_seconds,
                _to_json(tools_used),
                barge_in_count,
                outcome,
                lead_id,
            )
    finally:
        await conn.close()


def _to_json(obj) -> str:
    import json

    return json.dumps(obj, default=str)
