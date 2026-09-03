"""
Persists a call's transcript into `interactions` (db/migrations/003) once
the call ends, PII-masked before storage (PROP-506). This is the write
path that PROP-506's own README flagged as missing -- nothing previously
wrote to `interactions.transcript` at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "compliance"))
from pii_masking import mask_pii  # noqa: E402


async def save_interaction(
    database_url: str,
    tenant_id: str,
    call_id: str,
    transcript: str,
    duration_seconds: int,
    contact_id: int | None = None,
    lead_id: int | None = None,
) -> None:
    if not transcript.strip():
        return

    masked_transcript = mask_pii(transcript)

    conn = await asyncpg.connect(database_url)
    try:
        # set_config(..., true) is transaction-LOCAL -- it must be set inside
        # the same transaction as the INSERT, or (as a bare conn.execute()
        # auto-commits its own implicit transaction) the setting is gone by
        # the time the next statement runs and RLS's WITH CHECK rejects the
        # insert as having no tenant context. Caught by running this for
        # real: first attempt failed with InsufficientPrivilegeError.
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            await conn.execute(
                """
                INSERT INTO interactions (tenant_id, contact_id, lead_id, call_id, channel, transcript, duration_seconds)
                VALUES ($1, $2, $3, $4, 'voice', $5, $6)
                """,
                tenant_id,
                contact_id,
                lead_id,
                call_id,
                masked_transcript,
                duration_seconds,
            )
    finally:
        await conn.close()
