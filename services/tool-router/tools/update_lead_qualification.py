"""
PROP-402: BANT qualification state extraction -- as a Gemini function-call
tool, not a separate NLP parser over the transcript.

Architecture note: the plan describes this as a "state extraction parser
in Core Brain." Since the orchestrator already routes every other piece
of structured information Gemini needs to act on (search_properties,
get_property_details) through function calling, having Gemini itself
call update_lead_qualification as it naturally learns BANT facts during
conversation (per ../../prompts/bant_conversation_design.md's per-field
triggers) is the same mechanism, not a second one -- a standalone
post-hoc transcript parser would duplicate the extraction Gemini is
already doing to decide what to say next, adding latency and a second
place BANT logic could drift from the actual conversation. `system_prompt.py`
instructs Gemini on when to call this.

Runs PROP-405's scoring (../../lead-engine/lead_scoring.py) every time,
so `leads.priority` always reflects the lead's current known state.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

import asyncpg
from pydantic import BaseModel, Field

from db import record_to_dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "lead-engine"))
from lead_scoring import score_lead  # noqa: E402

Intent = Literal["buy", "sell", "rent", "browsing"]
Timeline = Literal["immediate", "1-3mo", "3-6mo", "6mo+", "exploring"]
DecisionMaker = Literal["solo", "joint", "other"]


class UpdateLeadQualificationArgs(BaseModel):
    """All fields optional and independently settable -- BANT capture is
    incremental across a call (one or two fields per turn per the
    conversation design's "never ask more than one at a time" rule), not
    a single all-at-once submission. Only non-null fields overwrite the
    lead's existing state (see the COALESCE update below)."""

    caller_full_name: str | None = None
    intent: Intent | None = None
    budget_min: float | None = Field(None, ge=0)
    budget_max: float | None = Field(None, ge=0)
    timeline: Timeline | None = None
    decision_maker: DecisionMaker | None = None
    property_id: int | None = None


async def update_lead_qualification(
    connection: asyncpg.Connection,
    args: UpdateLeadQualificationArgs,
    tenant_id: str = "default",
    caller_phone_number: str | None = None,
    lead_id: int | None = None,
) -> dict:
    """`caller_phone_number` and `lead_id` are call-scoped context the
    orchestrator supplies directly (like `tenant_id`) -- never exposed to
    Gemini's function schema, since Gemini has no reliable way to know
    either (see ../../../services/orchestrator/orchestrator.py). A missing
    caller_phone_number is a caller-side bug (the orchestrator should
    always supply *something*, even a synthetic per-call fallback when
    real SIP caller ID isn't available yet -- see that module's docstring),
    not something this tool can recover from, since `contacts.phone_number`
    is the only way it has to identify who's calling.
    """
    if not caller_phone_number:
        raise ValueError("caller_phone_number is required to identify the contact")

    contact_row = await connection.fetchrow(
        """
        INSERT INTO contacts (tenant_id, full_name, phone_number)
        VALUES ($1, $2, $3)
        ON CONFLICT (tenant_id, phone_number)
        DO UPDATE SET full_name = COALESCE(EXCLUDED.full_name, contacts.full_name)
        RETURNING id
        """,
        tenant_id,
        args.caller_full_name,
        caller_phone_number,
    )
    contact_id = contact_row["id"]

    if lead_id is not None:
        lead_row = await connection.fetchrow(
            """
            UPDATE leads SET
                property_id    = COALESCE($1, property_id),
                intent         = COALESCE($2, intent),
                budget_min     = COALESCE($3, budget_min),
                budget_max     = COALESCE($4, budget_max),
                timeline       = COALESCE($5, timeline),
                decision_maker = COALESCE($6, decision_maker),
                updated_at     = now()
            WHERE id = $7 AND tenant_id = $8
            RETURNING *
            """,
            args.property_id,
            args.intent,
            args.budget_min,
            args.budget_max,
            args.timeline,
            args.decision_maker,
            lead_id,
            tenant_id,
        )
        # Defensive fallback: the lead_id the orchestrator remembered no
        # longer exists under this tenant (shouldn't happen in practice --
        # nothing deletes leads -- but don't silently drop the caller's
        # information if it somehow does).
        if lead_row is None:
            lead_id = None

    if lead_id is None:
        lead_row = await connection.fetchrow(
            """
            INSERT INTO leads (tenant_id, contact_id, property_id, intent, budget_min, budget_max, timeline, decision_maker)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
            """,
            tenant_id,
            contact_id,
            args.property_id,
            args.intent,
            args.budget_min,
            args.budget_max,
            args.timeline,
            args.decision_maker,
        )

    lead = record_to_dict(lead_row)
    priority = score_lead(lead)
    if priority != lead["priority"]:
        lead_row = await connection.fetchrow(
            "UPDATE leads SET priority = $1 WHERE id = $2 RETURNING *", priority, lead_row["id"]
        )
        lead = record_to_dict(lead_row)

    return {"lead_id": lead["id"], "contact_id": contact_id, "priority": lead["priority"], "captured": lead}
