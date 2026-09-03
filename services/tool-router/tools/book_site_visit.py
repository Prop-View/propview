"""
PROP-403/404: book_site_visit -- books a calendar slot and dispatches an
SMS confirmation, guarded by a Redis lock on the exact slot
(../../scheduling/redis_lock.py) so two concurrent calls can't both book
the same time (Sprint 4's risk register: "Property Double Booking...
Redis distributed locking on calendar slot keys during booking execution").
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import asyncpg
from pydantic import BaseModel

from redis_client import get_redis_client
from tools._calendar_context import get_calendar_client
from tools._lead_context import ensure_contact_and_lead

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "scheduling"))  # append, not insert(0) -- see _calendar_context.py
from calendar_client import TimeSlot  # noqa: E402
from redis_lock import SlotLock, slot_lock_key  # noqa: E402
from sms_dispatch import SmsDispatchError, build_appointment_confirmation, send_sms  # noqa: E402


class BookSiteVisitArgs(BaseModel):
    property_id: int | None = None
    slot_start: str  # ISO 8601 -- must match a start returned by check_calendar_slots
    slot_end: str
    agent_name: str | None = None


async def book_site_visit(
    connection: asyncpg.Connection,
    args: BookSiteVisitArgs,
    tenant_id: str = "default",
    caller_phone_number: str | None = None,
    lead_id: int | None = None,
) -> dict:
    """`caller_phone_number`/`lead_id` are call-scoped context, same
    treatment as update_lead_qualification.py -- if the caller books a
    visit without any prior BANT capture in this call, a bare contact+lead
    is created here rather than failing (see ensure_contact_and_lead)."""
    if not caller_phone_number:
        raise ValueError("caller_phone_number is required to book a site visit")

    _, lead_id = await ensure_contact_and_lead(connection, tenant_id, caller_phone_number, lead_id)

    client = await get_calendar_client(connection, tenant_id)
    slot = TimeSlot(datetime.fromisoformat(args.slot_start), datetime.fromisoformat(args.slot_end))
    duration_minutes = int((slot.end - slot.start).total_seconds() // 60)

    lock_key = slot_lock_key(tenant_id, "primary", slot.start.isoformat())
    async with SlotLock(get_redis_client(), lock_key):
        # Re-check the slot is still actually open now that we hold the
        # lock: a concurrent booking that started (and already released
        # its own lock) just before this one acquired it could have taken
        # it in between check_calendar_slots and this call.
        still_open = await client.find_open_slots(
            slot.start, slot.end + timedelta(seconds=1), duration_minutes=duration_minutes, max_results=50
        )
        if not any(s.start == slot.start for s in still_open):
            raise ValueError("That slot is no longer available -- please choose a different time")

        event_id = await client.book_event(
            slot, summary="Property site visit", description=f"property_id={args.property_id}"
        )

        appointment_id = await connection.fetchval(
            """
            INSERT INTO appointments (tenant_id, lead_id, property_id, scheduled_at, status, agent_name)
            VALUES ($1, $2, $3, $4, 'scheduled', $5)
            RETURNING id
            """,
            tenant_id,
            lead_id,
            args.property_id,
            slot.start,
            args.agent_name,
        )

    # SMS confirmation is best-effort and happens after the lock is
    # released -- a slow/failed SMS provider should never hold the slot
    # lock open and block other bookings.
    confirmation_sent = False
    try:
        address = f"property #{args.property_id}" if args.property_id else "the property"
        body = build_appointment_confirmation(address, slot.start.strftime("%A, %B %-d at %-I:%M %p"))
        await send_sms(caller_phone_number, body)
        confirmation_sent = True
        await connection.execute("UPDATE appointments SET confirmation_sms_sent_at = now() WHERE id = $1", appointment_id)
    except SmsDispatchError:
        pass

    return {
        "appointment_id": appointment_id,
        "calendar_event_id": event_id,
        "scheduled_at": slot.start.isoformat(),
        "confirmation_sms_sent": confirmation_sent,
    }
