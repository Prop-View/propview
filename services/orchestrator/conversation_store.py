"""
Persists PII-masked structured conversation data to Postgres at call end.

Three tables (db/migrations/009_conversation_store.sql):
- conversation_turns: per-utterance structured records
- tool_invocations: every tool call the AI made
- call_analytics: aggregated per-call metrics

The orchestrator's in-process snapshot is the source of truth for the
complete turn history; the bounded Redis context window is a fallback for
callers that do not supply that snapshot.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from conversation_context import ContextLine, ConversationContextStore
from db import tenant_connection

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "compliance"))
from pii_masking import mask_pii


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
    conversation_lines: list[ContextLine] | None = None,
) -> None:
    if conversation_lines is not None:
        lines = conversation_lines
    elif conversation_context is not None:
        lines = await conversation_context.get_lines(call_id)
    else:
        lines = []

    if not lines and not tool_invocations:
        return

    async with tenant_connection(tenant_id, database_url) as conn:
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
                mask_pii(line.text),
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
                _to_json(inv.output_result) if inv.output_result is not None else None,
                mask_pii(inv.error) if inv.error is not None else None,
                inv.latency_ms,
                inv.success,
            )

        caller_turns = sum(1 for line in lines if line.speaker == "caller")
        agent_turns = sum(1 for line in lines if line.speaker == "agent")
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


def _mask_json(value: Any) -> Any:
    if isinstance(value, str):
        return mask_pii(value)
    if isinstance(value, list):
        return [_mask_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _mask_json(item) for key, item in value.items()}
    return value


def _to_json(obj: Any) -> str:
    return json.dumps(_mask_json(obj), default=str)
