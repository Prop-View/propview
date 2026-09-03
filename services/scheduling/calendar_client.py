"""
PROP-403: Google Calendar integration -- availability lookup + booking.

Credentials come from tenant_settings.encrypted_calendar_credentials
(../admin-api/crypto.py, PROP-407) -- a JSON blob shaped
{"refresh_token": ..., "client_id": ..., "client_secret": ...} that
../admin-api/main.py's PUT /admin/tenants/{id}/calendar-credentials
already accepts and stores encrypted. This module is the consumer of
that credential, not a second place credentials get stored.

The Google API client (`googleapiclient`) is synchronous -- every call
here runs it in a thread via `asyncio.to_thread` so it never blocks the
orchestrator's event loop, matching the rest of this codebase's
async-first style.

**Not live-verified**: no real Google Cloud OAuth client/consent flow has
been run against this (same category of gap as PROP-101/102's Twilio/GCP
credentials -- needs a real account, not something obtainable in this
environment). Unit-tested against a mocked `googleapiclient` service
object instead (tests/test_calendar_client.py), which verifies the
request shapes and slot-computation logic are correct, but not that
Google's actual API accepts them as-is.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DEFAULT_BUSINESS_HOURS = (9, 17)  # 9am-5pm, tenant-local time (see book_appointment's tz note)
DEFAULT_SLOT_MINUTES = 30
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass
class TimeSlot:
    start: datetime
    end: datetime

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


class GoogleCalendarClient:
    def __init__(self, credentials_dict: dict, calendar_id: str = "primary"):
        """`credentials_dict` -- the decrypted JSON blob from
        tenant_settings (see module docstring). Missing required keys
        raises KeyError immediately rather than failing confusingly on
        the first real API call."""
        self._creds = Credentials(
            token=None,
            refresh_token=credentials_dict["refresh_token"],
            client_id=credentials_dict["client_id"],
            client_secret=credentials_dict["client_secret"],
            token_uri=GOOGLE_TOKEN_URI,
        )
        self._calendar_id = calendar_id
        self._service = build("calendar", "v3", credentials=self._creds, cache_discovery=False)

    def _list_busy_slots_sync(self, time_min: datetime, time_max: datetime) -> list[TimeSlot]:
        body = {"timeMin": time_min.isoformat(), "timeMax": time_max.isoformat(), "items": [{"id": self._calendar_id}]}
        result = self._service.freebusy().query(body=body).execute()
        busy = result["calendars"][self._calendar_id]["busy"]
        return [TimeSlot(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in busy]

    async def find_open_slots(
        self,
        time_min: datetime,
        time_max: datetime,
        duration_minutes: int = DEFAULT_SLOT_MINUTES,
        business_hours: tuple[int, int] = DEFAULT_BUSINESS_HOURS,
        max_results: int = 3,
    ) -> list[TimeSlot]:
        """Candidate slots at `duration_minutes` granularity within
        business hours, minus whatever Google's freebusy API reports as
        busy. Returns at most `max_results` -- the plan's demo scenario
        wants "the next 3 available slots," not an exhaustive list."""
        busy = await asyncio.to_thread(self._list_busy_slots_sync, time_min, time_max)

        open_slots: list[TimeSlot] = []
        cursor = time_min
        duration = timedelta(minutes=duration_minutes)
        start_hour, end_hour = business_hours
        while cursor < time_max and len(open_slots) < max_results:
            if not (start_hour <= cursor.hour < end_hour):
                # Jump to the next day's business-hours start rather than
                # stepping one slot at a time through the night.
                next_day = (cursor + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
                cursor = next_day
                continue

            candidate = TimeSlot(cursor, cursor + duration)
            if candidate.end.hour > end_hour or (candidate.end.hour == end_hour and candidate.end.minute > 0):
                cursor = (cursor + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
                continue

            overlaps = any(candidate.start < b.end and candidate.end > b.start for b in busy)
            if not overlaps:
                open_slots.append(candidate)
            cursor += duration

        return open_slots

    def _book_event_sync(self, slot: TimeSlot, summary: str, description: str) -> str:
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": slot.start.isoformat()},
            "end": {"dateTime": slot.end.isoformat()},
        }
        created = self._service.events().insert(calendarId=self._calendar_id, body=event).execute()
        return created["id"]

    async def book_event(self, slot: TimeSlot, summary: str, description: str = "") -> str:
        """Returns the Google Calendar event id. Callers should still
        treat this as best-effort under concurrent booking attempts for
        the *same* slot -- Google's own API doesn't prevent a double
        booking, so redis_lock.py's SlotLock must be held by the caller
        around this (see tools/book_site_visit.py) to avoid the race the
        plan's risk register flags."""
        return await asyncio.to_thread(self._book_event_sync, slot, summary, description)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
