"""
PROP-403/404: Tests for check_calendar_slots/book_site_visit against real
Postgres and real Redis (slot locking) -- but mocking Google Calendar and
Twilio, since no real credentials for either are available in this
environment (see calendar_client.py / sms_dispatch.py docstrings). Seeds
a tenant_settings row with real Fernet-encrypted (fake) credentials, the
same round trip ../admin-api/main.py's PUT endpoint produces.

Run: DATABASE_URL=postgresql://propview_app:devpassword@localhost/propview_dev \
     ENCRYPTION_KEY=<fernet key> REDIS_URL=redis://localhost:6379 \
     python -m pytest tests/test_booking.py -v
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# append, not insert(0, ...): admin-api has its own main.py/db.py, and
# inserting its directory ahead of tool-router's own would make `from
# main import app` below resolve to the WRONG service's main.py (this
# broke every test here the first time -- root-caused via `main.TOOLS`
# raising ImportError against admin-api's main.py instead of this one's).
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "admin-api"))
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "scheduling"))

os.environ.setdefault("DATABASE_URL", "postgresql://propview_app:devpassword@localhost/propview_dev")
os.environ.setdefault("ENCRYPTION_KEY", "FG6ZzLBZnosF1kPSMHKpkDwpdPrinkzVBQ5I9CdMHEE=")  # test-only key
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "AC_test")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "token_test")
os.environ.setdefault("TWILIO_SMS_FROM_NUMBER", "+15125550000")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-internal-token")

import asyncio

import asyncpg
import pytest
from crypto import encrypt
from fastapi.testclient import TestClient

from main import app

TEST_TENANT = "test-booking"
FAKE_CALENDAR_CREDS = {"refresh_token": "rt", "client_id": "cid", "client_secret": "secret"}


async def _seed() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
    await conn.execute("DELETE FROM appointments WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute("DELETE FROM leads WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute("DELETE FROM contacts WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute("DELETE FROM properties WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute("DELETE FROM tenant_settings WHERE tenant_id = $1", TEST_TENANT)
    property_id = await conn.fetchval(
        """
        INSERT INTO properties (tenant_id, address, city, state, property_type, beds, baths, sqft, price)
        VALUES ($1, '123 Oak St', 'Austin', 'TX', 'house', 3, 2.0, 1800, 520000)
        RETURNING id
        """,
        TEST_TENANT,
    )
    await conn.execute(
        """
        INSERT INTO tenant_settings (tenant_id, calendar_provider, encrypted_calendar_credentials)
        VALUES ($1, 'google', $2)
        """,
        TEST_TENANT,
        encrypt(json.dumps(FAKE_CALENDAR_CREDS)),
    )
    await conn.close()
    return property_id


async def _cleanup() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
    await conn.execute("DELETE FROM appointments WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute("DELETE FROM leads WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute("DELETE FROM contacts WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute("DELETE FROM properties WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute("DELETE FROM tenant_settings WHERE tenant_id = $1", TEST_TENANT)
    await conn.close()


@pytest.fixture(scope="module")
def client():
    # Seeding (incl. the tenant_settings row check_calendar_slots needs)
    # happens here, not in a separate property_id-only fixture -- a test
    # that only requests `client` still needs the tenant configured, and
    # fixtures that aren't in a test's own parameter list never run.
    seeded_property_id = asyncio.run(_seed())
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {os.environ['INTERNAL_SERVICE_TOKEN']}"
        c.seeded_property_id = seeded_property_id  # stash for the property_id fixture below
        yield c
    asyncio.run(_cleanup())


@pytest.fixture(scope="module")
def property_id(client):
    return client.seeded_property_id


def call_tool(client, name, args, caller_phone_number=None, lead_id=None):
    return client.post(
        "/tools/call",
        json={
            "name": name,
            "args": args,
            "tenant_id": TEST_TENANT,
            "caller_phone_number": caller_phone_number,
            "lead_id": lead_id,
        },
    )


def _mock_calendar_build(busy_ranges=()):
    """Patches calendar_client.build so check_calendar_slots/book_site_visit
    exercise real slot-computation/locking/DB logic without a real Google
    account. Returns the mock service so a test can assert on calls made
    to it (e.g. events().insert())."""
    mock_service = MagicMock()
    mock_service.freebusy().query().execute.return_value = {
        "calendars": {"primary": {"busy": [{"start": s, "end": e} for s, e in busy_ranges]}}
    }
    mock_service.events().insert().execute.return_value = {"id": "evt_test_1"}
    return mock_service


def test_check_calendar_slots_returns_open_slots(client):
    mock_service = _mock_calendar_build()
    with patch("calendar_client.build", return_value=mock_service):
        resp = call_tool(client, "check_calendar_slots", {"earliest": "2026-09-08T09:00:00", "search_days": 1})

    assert resp.status_code == 200
    slots = resp.json()["result"]["available_slots"]
    assert len(slots) == 3
    assert all("start" in s and "end" in s for s in slots)


def test_check_calendar_slots_requires_calendar_configured(client):
    # A tenant with no tenant_settings row at all.
    resp = client.post(
        "/tools/call",
        json={"name": "check_calendar_slots", "args": {}, "tenant_id": "tenant-with-no-calendar"},
    )
    assert resp.status_code == 422


def test_book_site_visit_creates_appointment_and_sends_sms(client, property_id):
    mock_service = _mock_calendar_build()
    slot_start = "2026-09-08T10:00:00"
    slot_end = "2026-09-08T10:30:00"

    with patch("calendar_client.build", return_value=mock_service), patch("sms_dispatch.Client") as mock_twilio_cls:
        mock_twilio_client = MagicMock()
        mock_twilio_client.messages.create.return_value = MagicMock(sid="SM_test")
        mock_twilio_cls.return_value = mock_twilio_client

        resp = call_tool(
            client,
            "book_site_visit",
            {"property_id": property_id, "slot_start": slot_start, "slot_end": slot_end},
            caller_phone_number="+15125550200",
        )

    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["calendar_event_id"] == "evt_test_1"
    assert result["confirmation_sms_sent"] is True
    mock_twilio_client.messages.create.assert_called_once()

    # events().insert() was actually called with our slot's times.
    _, kwargs = mock_service.events().insert.call_args
    assert kwargs["body"]["start"]["dateTime"] == slot_start


def test_book_site_visit_requires_caller_phone_number(client, property_id):
    mock_service = _mock_calendar_build()
    with patch("calendar_client.build", return_value=mock_service):
        resp = call_tool(
            client,
            "book_site_visit",
            {"property_id": property_id, "slot_start": "2026-09-09T10:00:00", "slot_end": "2026-09-09T10:30:00"},
        )
    assert resp.status_code == 422


def test_book_site_visit_rejects_already_booked_slot(client, property_id):
    """The slot is reported busy by the (mocked) freebusy check -- the
    re-check-under-lock must reject it rather than double-booking."""
    slot_start = "2026-09-10T10:00:00"
    slot_end = "2026-09-10T10:30:00"
    mock_service = _mock_calendar_build(busy_ranges=[(slot_start, slot_end)])

    with patch("calendar_client.build", return_value=mock_service):
        resp = call_tool(
            client,
            "book_site_visit",
            {"property_id": property_id, "slot_start": slot_start, "slot_end": slot_end},
            caller_phone_number="+15125550201",
        )

    assert resp.status_code == 422
    assert "no longer available" in resp.json()["detail"]
