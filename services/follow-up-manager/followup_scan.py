"""
Follow-up Manager -- a post-plan addition (no Sprint Plan ticket, same
category as PROP-50/51/52 per CLAUDE.md) closing a real, previously
undocumented gap: nothing in this repo re-contacted a caller after the
call ended. Two independent passes, both deliberately asynchronous --
neither is a Gemini-facing tool, since there's no in-call moment where
either decision is made:

- **No-show pass**: `appointments` rows past their `scheduled_at` that
  are still `status = 'scheduled'` get flipped to `'no_show'` and trigger
  one re-contact SMS.
- **Nurture pass**: `leads` that had at least one completed call
  (`interactions`, written by ../orchestrator/transcript_store.py) but
  never got an appointment booked, where the most recent call is stale
  enough, get one nurture SMS.

This file is a **one-shot script**, meant to be invoked repeatedly on a
schedule -- it does not loop or sleep internally. Wiring a real cron job
/ Windows Task Scheduler entry is a separate, later infra decision (same
"code complete, infra pending" category as the rest of this repo's
cloud-account-gated pieces); for now, run it by hand or from any external
scheduler:

    python followup_scan.py

**Retry-safe by design**: `follow_ups` (db/migrations/008_follow_ups.sql)
is only written *after* an SMS send actually succeeds. A failed send
(certain right now -- the Twilio account in this environment is created
but not yet funded) leaves no ledger row, so the next run retries it
instead of silently losing it. The no-show status flip itself is
idempotent and intentionally decoupled from the ledger -- see
`_scan_no_shows`'s query comment.

Active tenants are enumerated through the restricted platform registry
function; tenant data is still accessed only through `tenant_connection()`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tool-router"))
sys.path.append(str(Path(__file__).resolve().parent.parent / "scheduling"))
sys.path.append(str(Path(__file__).resolve().parent.parent / "orchestrator"))

load_dotenv()

from db import close_pool, tenant_connection  # noqa: E402
from sms_dispatch import SmsDispatchError, build_no_show_followup, build_nurture_followup, send_sms  # noqa: E402
from tenant_registry import list_active_tenant_ids  # noqa: E402
from tenant_settings import get_tenant_call_settings  # noqa: E402
from usage_metering import record_usage_event  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("followup_scan")

NO_SHOW_DELAY_HOURS = float(os.environ.get("NO_SHOW_FOLLOWUP_DELAY_HOURS", "1"))
NURTURE_DELAY_DAYS = float(os.environ.get("NURTURE_FOLLOWUP_DELAY_DAYS", "2"))
DEFAULT_AGENCY_NAME = os.environ.get("AGENCY_NAME", "our brokerage")
DATABASE_URL = os.environ.get("DATABASE_URL")


async def _scan_no_shows(
    tenant_id: str, agency_name: str, sms_sender_number: str | None = None
) -> int:
    """Flips overdue `scheduled` appointments to `no_show` and sends one
    re-contact SMS per appointment.

    The WHERE clause matches `status IN ('scheduled', 'no_show')`
    deliberately, not just `'scheduled'` -- the status flip below always
    runs (idempotently), independent of whether the SMS send below it
    succeeds. If the flip and the dedup check both gated on
    `status = 'scheduled'`, a failed send on a previous run would have
    already flipped the row to `no_show`, permanently excluding it from
    ever being retried. The actual "already handled" signal is the
    `follow_ups` ledger (`NOT EXISTS` below), not `appointments.status`.
    """
    sent = 0
    async with tenant_connection(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT a.id AS appointment_id, a.lead_id, c.phone_number
            FROM appointments a
            JOIN leads l ON l.id = a.lead_id
            JOIN contacts c ON c.id = l.contact_id
            WHERE a.tenant_id = $1
              AND a.status IN ('scheduled', 'no_show')
              AND a.scheduled_at < now() - make_interval(hours => $2)
              AND NOT EXISTS (
                  SELECT 1 FROM follow_ups f
                  WHERE f.appointment_id = a.id AND f.kind = 'no_show'
              )
            """,
            tenant_id,
            NO_SHOW_DELAY_HOURS,
        )
        for row in rows:
            await conn.execute(
                "UPDATE appointments SET status = 'no_show' WHERE id = $1 AND status != 'no_show'",
                row["appointment_id"],
            )
            try:
                sms_kwargs = {"from_number": sms_sender_number} if sms_sender_number else {}
                await send_sms(row["phone_number"], build_no_show_followup(agency_name), **sms_kwargs)
            except SmsDispatchError as exc:
                logger.warning("No-show SMS failed for appointment %s: %s", row["appointment_id"], exc)
                continue
            await record_usage_event(
                conn,
                tenant_id,
                "sms",
                f"follow-up:no-show:{row['appointment_id']}",
            )
            await conn.execute(
                "INSERT INTO follow_ups (tenant_id, lead_id, appointment_id, kind) VALUES ($1, $2, $3, 'no_show')",
                tenant_id,
                row["lead_id"],
                row["appointment_id"],
            )
            sent += 1
    return sent


async def _scan_nurture(
    tenant_id: str, agency_name: str, sms_sender_number: str | None = None
) -> int:
    """Finds leads with at least one completed call, no appointment ever
    booked (any status -- a lead that booked and then no-showed belongs
    to the no-show pass instead, not nurture), and whose most recent
    `interactions` row is stale enough. `MAX(...) < threshold` on a lead
    with zero interactions is NULL (never true), so a lead with no
    recorded call is correctly excluded rather than nurtured on no
    evidence a call ever happened."""
    sent = 0
    async with tenant_connection(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT l.id AS lead_id, c.phone_number
            FROM leads l
            JOIN contacts c ON c.id = l.contact_id
            WHERE l.tenant_id = $1
              AND l.status NOT IN ('appointment_set', 'closed_won', 'closed_lost')
              AND NOT EXISTS (SELECT 1 FROM appointments ap WHERE ap.lead_id = l.id)
              AND (SELECT MAX(i.created_at) FROM interactions i WHERE i.lead_id = l.id)
                  < now() - make_interval(days => $2)
              AND NOT EXISTS (
                  SELECT 1 FROM follow_ups f WHERE f.lead_id = l.id AND f.kind = 'nurture'
              )
            """,
            tenant_id,
            NURTURE_DELAY_DAYS,
        )
        for row in rows:
            try:
                sms_kwargs = {"from_number": sms_sender_number} if sms_sender_number else {}
                await send_sms(row["phone_number"], build_nurture_followup(agency_name), **sms_kwargs)
            except SmsDispatchError as exc:
                logger.warning("Nurture SMS failed for lead %s: %s", row["lead_id"], exc)
                continue
            await record_usage_event(
                conn,
                tenant_id,
                "sms",
                f"follow-up:nurture:{row['lead_id']}",
            )
            await conn.execute(
                "INSERT INTO follow_ups (tenant_id, lead_id, kind) VALUES ($1, $2, 'nurture')",
                tenant_id,
                row["lead_id"],
            )
            sent += 1
    return sent


async def run_scan() -> dict[str, dict[str, int]]:
    if DATABASE_URL is None:
        raise RuntimeError("DATABASE_URL must be configured to enumerate active tenants")

    results: dict[str, dict[str, int]] = {}
    tenant_ids = await list_active_tenant_ids(DATABASE_URL)
    for tenant_id in tenant_ids:
        settings = await get_tenant_call_settings(tenant_id, DATABASE_URL, DEFAULT_AGENCY_NAME)
        no_show_count = await _scan_no_shows(
            tenant_id, settings.agency_name, settings.sms_sender_number
        )
        nurture_count = await _scan_nurture(
            tenant_id, settings.agency_name, settings.sms_sender_number
        )
        results[tenant_id] = {"no_show": no_show_count, "nurture": nurture_count}
        logger.info(
            "tenant=%r no_show_followups_sent=%d nurture_followups_sent=%d",
            tenant_id,
            no_show_count,
            nurture_count,
        )
    return results


async def main() -> None:
    try:
        await run_scan()
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
