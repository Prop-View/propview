"""
Shared helper for tools that need a contact/lead row to attach to (right
now: update_lead_qualification and book_site_visit), factored out so the
"find or create this caller's contact+lead" logic exists in exactly one
place rather than being copy-pasted between them.
"""

from __future__ import annotations

import asyncpg


async def ensure_contact_and_lead(
    connection: asyncpg.Connection,
    tenant_id: str,
    caller_phone_number: str,
    lead_id: int | None,
    caller_full_name: str | None = None,
) -> tuple[int, int]:
    """Returns (contact_id, lead_id). Upserts the contact by phone number
    (creating one if this is a new caller). If `lead_id` is given and
    still exists under this tenant, reuses it; otherwise creates a fresh
    lead row with everything else null -- callers apply their own field
    updates afterward."""
    contact_row = await connection.fetchrow(
        """
        INSERT INTO contacts (tenant_id, full_name, phone_number)
        VALUES ($1, $2, $3)
        ON CONFLICT (tenant_id, phone_number)
        DO UPDATE SET full_name = COALESCE(EXCLUDED.full_name, contacts.full_name)
        RETURNING id
        """,
        tenant_id,
        caller_full_name,
        caller_phone_number,
    )
    contact_id = contact_row["id"]

    if lead_id is not None:
        existing = await connection.fetchval(
            "SELECT id FROM leads WHERE id = $1 AND tenant_id = $2", lead_id, tenant_id
        )
        if existing is not None:
            return contact_id, existing
        # Falls through to create a new one -- the remembered lead_id no
        # longer exists under this tenant (shouldn't happen in practice).

    new_lead_id = await connection.fetchval(
        "INSERT INTO leads (tenant_id, contact_id) VALUES ($1, $2) RETURNING id",
        tenant_id,
        contact_id,
    )
    return contact_id, new_lead_id
