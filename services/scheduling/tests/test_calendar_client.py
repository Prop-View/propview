"""
Tests for the slot-computation logic in calendar_client.py -- mocks
Google's API client (googleapiclient.discovery.build) since no real
Google Cloud OAuth credentials are available in this environment (see
calendar_client.py's module docstring). Verifies find_open_slots'
business-hours + overlap logic and book_event's request shape are
correct; does NOT verify Google's actual API accepts these requests.

Run: python -m pytest tests/test_calendar_client.py -v
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calendar_client import GoogleCalendarClient, TimeSlot

FAKE_CREDS = {"refresh_token": "rt", "client_id": "cid", "client_secret": "secret"}


def _make_client(busy_ranges: list[tuple[str, str]]) -> GoogleCalendarClient:
    with patch("calendar_client.build") as mock_build:
        mock_service = MagicMock()
        mock_service.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": [{"start": s, "end": e} for s, e in busy_ranges]}}
        }
        mock_build.return_value = mock_service
        client = GoogleCalendarClient(FAKE_CREDS)
    return client


@pytest.mark.asyncio
async def test_find_open_slots_skips_busy_ranges():
    # A Tuesday, 9am-5pm business hours, one meeting 10-11am.
    day = datetime(2026, 9, 8, 0, 0)  # a Tuesday
    client = _make_client([(f"{day.date()}T10:00:00", f"{day.date()}T11:00:00")])

    slots = await client.find_open_slots(
        time_min=day.replace(hour=9), time_max=day.replace(hour=17), duration_minutes=30, max_results=3
    )

    assert len(slots) == 3
    assert all(not (s.start.hour == 10) for s in slots)  # 10:00 slot excluded
    for s in slots:
        assert 9 <= s.start.hour < 17


@pytest.mark.asyncio
async def test_find_open_slots_respects_business_hours():
    day = datetime(2026, 9, 8, 0, 0)
    client = _make_client([])

    slots = await client.find_open_slots(
        time_min=day.replace(hour=16, minute=45),  # near end of business hours
        time_max=day.replace(hour=17) + timedelta(days=1),
        duration_minutes=30,
        business_hours=(9, 17),
        max_results=1,
    )

    assert len(slots) == 1
    # 16:45 + 30min would end at 17:15, past business hours -- must roll to next day 9am.
    assert slots[0].start.hour == 9
    assert slots[0].start.day == day.day + 1


@pytest.mark.asyncio
async def test_find_open_slots_returns_at_most_max_results():
    day = datetime(2026, 9, 8, 0, 0)
    client = _make_client([])

    slots = await client.find_open_slots(day.replace(hour=9), day.replace(hour=17), duration_minutes=30, max_results=3)

    assert len(slots) == 3


@pytest.mark.asyncio
async def test_book_event_sends_correct_request_shape():
    with patch("calendar_client.build") as mock_build:
        mock_service = MagicMock()
        mock_service.events().insert().execute.return_value = {"id": "evt_123"}
        mock_build.return_value = mock_service
        client = GoogleCalendarClient(FAKE_CREDS)

        slot = TimeSlot(datetime(2026, 9, 10, 14, 0), datetime(2026, 9, 10, 14, 30))
        event_id = await client.book_event(slot, summary="Site visit", description="property_id=42")

    assert event_id == "evt_123"
    _, kwargs = mock_service.events().insert.call_args
    assert kwargs["calendarId"] == "primary"
    assert kwargs["body"]["summary"] == "Site visit"
    assert kwargs["body"]["start"]["dateTime"] == "2026-09-10T14:00:00"
