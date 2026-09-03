"""
PROP-403: check_calendar_slots -- reads agent calendar availability.

Returns at most 3 open slots (the plan's demo scenario: "checks calendar,
offers slot... presents top choice" / "identifies conflict, queries next
3 available slots"), not an exhaustive availability list -- a voice
conversation can't usefully enumerate more than that out loud anyway.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import asyncpg
from pydantic import BaseModel, Field

from tools._calendar_context import get_calendar_client


class CheckCalendarSlotsArgs(BaseModel):
    earliest: str | None = Field(
        None, description="ISO 8601 datetime to start searching from; defaults to now if omitted."
    )
    search_days: int = Field(7, ge=1, le=30, description="How many days ahead to search for an open slot.")
    duration_minutes: int = Field(30, ge=15, le=120)


async def check_calendar_slots(
    connection: asyncpg.Connection, args: CheckCalendarSlotsArgs, tenant_id: str = "default"
) -> dict:
    client = await get_calendar_client(connection, tenant_id)

    time_min = datetime.fromisoformat(args.earliest) if args.earliest else datetime.now().astimezone()
    time_max = time_min + timedelta(days=args.search_days)

    slots = await client.find_open_slots(time_min, time_max, duration_minutes=args.duration_minutes)
    return {"available_slots": [s.to_dict() for s in slots]}
