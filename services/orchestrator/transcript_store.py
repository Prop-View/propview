"""
Persists a call's transcript into `interactions` (db/migrations/003) once
the call ends, PII-masked before storage (PROP-506). This is the write
path that PROP-506's own README flagged as missing -- nothing previously
wrote to `interactions.transcript` at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "compliance"))
from pii_masking import mask_pii  # noqa: E402

from db import tenant_connection  # noqa: E402


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

    async with tenant_connection(tenant_id, database_url) as conn:
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
