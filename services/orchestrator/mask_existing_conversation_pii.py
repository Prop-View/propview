"""Backfill PII masking for one tenant's existing conversation records."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from db import tenant_connection
from conversation_store import _mask_json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "compliance"))
from pii_masking import mask_pii


async def mask_existing_conversation_data(
    database_url: str, tenant_id: str
) -> dict[str, int]:
    counts = {"turns": 0, "tool_invocations": 0}
    async with tenant_connection(tenant_id, database_url) as conn:
        last_id = 0
        while rows := await conn.fetch(
            """
            SELECT id, text FROM conversation_turns
            WHERE tenant_id = $1 AND id > $2
            ORDER BY id LIMIT 500
            """,
            tenant_id,
            last_id,
        ):
            for row in rows:
                masked = mask_pii(row["text"])
                if masked != row["text"]:
                    await conn.execute(
                        "UPDATE conversation_turns SET text = $1 WHERE tenant_id = $2 AND id = $3",
                        masked,
                        tenant_id,
                        row["id"],
                    )
                    counts["turns"] += 1
            last_id = rows[-1]["id"]

        last_id = 0
        while rows := await conn.fetch(
            """
            SELECT id, input_params, output_result, error FROM tool_invocations
            WHERE tenant_id = $1 AND id > $2
            ORDER BY id LIMIT 500
            """,
            tenant_id,
            last_id,
        ):
            for row in rows:
                raw_input = _decode_json(row["input_params"])
                raw_output = _decode_json(row["output_result"])
                input_params = _mask_json(raw_input)
                output_result = _mask_json(raw_output)
                error = mask_pii(row["error"]) if row["error"] is not None else None
                if (
                    input_params != raw_input
                    or output_result != raw_output
                    or error != row["error"]
                ):
                    await conn.execute(
                        """
                        UPDATE tool_invocations
                        SET input_params = $1::jsonb, output_result = $2::jsonb, error = $3
                        WHERE tenant_id = $4 AND id = $5
                        """,
                        json.dumps(input_params, default=str),
                        json.dumps(output_result, default=str)
                        if output_result is not None
                        else None,
                        error,
                        tenant_id,
                        row["id"],
                    )
                    counts["tool_invocations"] += 1
            last_id = rows[-1]["id"]

    return counts


def _decode_json(value: str | None):
    return json.loads(value) if isinstance(value, str) else value


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id", required=True, help="Tenant slug to process; run once per tenant"
    )
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL must be set to the propview_app database role")
    counts = await mask_existing_conversation_data(database_url, args.tenant_id)
    print(
        f"Masked {counts['turns']} conversation turns and "
        f"{counts['tool_invocations']} tool invocation rows for tenant {args.tenant_id!r}."
    )


if __name__ == "__main__":
    asyncio.run(_main())
