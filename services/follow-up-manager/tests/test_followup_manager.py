"""
Tests for followup_scan.py against real Postgres (RLS-enforced, same
convention as ../../tool-router/tests/test_booking.py) with Twilio mocked
(no real Twilio credentials available in this environment -- the account
exists but isn't funded yet, see ../.env.example).

Run: DATABASE_URL=postgresql://propview_app:devpassword@localhost:5433/propview_dev \
     python -m pytest tests/ -v
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tool-router"))
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "scheduling"))

os.environ.setdefault("DATABASE_URL", "postgresql://propview_app:devpassword@localhost:5433/propview_dev")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "AC_test")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "token_test")
os.environ.setdefault("TWILIO_SMS_FROM_NUMBER", "+15125550000")

import asyncio

import asyncpg
import pytest
import pytest_asyncio

from followup_scan import _scan_no_shows, _scan_nurture, close_pool
from sms_dispatch import SmsDispatchError

TEST_TENANT = "test-followup-manager"
AGENCY = "Test Agency"


async def _cleanup() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
        await conn.execute("DELETE FROM follow_ups WHERE tenant_id = $1", TEST_TENANT)
        await conn.execute("DELETE FROM appointments WHERE tenant_id = $1", TEST_TENANT)
        await conn.execute("DELETE FROM interactions WHERE tenant_id = $1", TEST_TENANT)
        await conn.execute("DELETE FROM leads WHERE tenant_id = $1", TEST_TENANT)
        await conn.execute("DELETE FROM contacts WHERE tenant_id = $1", TEST_TENANT)
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def cleanup_around_each_test():
    """Blanket cleanup by tenant_id before and after every test -- each
    test seeds its own contact/lead directly (see `_seed` below) rather
    than sharing a fixture-provided connection, since an asyncpg
    connection created outside a test's own event loop (e.g. in a sync
    fixture via asyncio.run) can't safely be reused inside it. Same
    principle test_booking.py's module-scoped fixture already follows --
    seeding/cleanup go through their own asyncio.run calls, never a
    connection handed across loop boundaries."""
    asyncio.run(_cleanup())
    yield
    asyncio.run(_cleanup())


@pytest_asyncio.fixture(autouse=True)
async def reset_pool_between_tests():
    """`tool-router`'s db.py keeps a module-level connection pool, correct
    for a long-lived FastAPI process but not for pytest-asyncio's default
    of a fresh event loop per test: the second test to touch the pool
    would otherwise try to reuse one still bound to the first test's
    (already-closed) loop, crashing with "Event loop is closed". Closing
    it here, from the same loop the just-finished test ran on (not a
    separate asyncio.run), ensures the next test creates its own pool
    cleanly on its own loop."""
    yield
    await close_pool()


async def _seed(phone_suffix: str) -> dict:
    """Creates a fresh contact + lead under TEST_TENANT on the *caller's*
    event loop (called directly from inside an async test body, not from
    a fixture) and returns the open connection plus both ids so the test
    can add appointments/interactions and assert against the same
    connection."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
    contact_id = await conn.fetchval(
        "INSERT INTO contacts (tenant_id, phone_number) VALUES ($1, $2) RETURNING id",
        TEST_TENANT,
        f"+1512555{phone_suffix}",
    )
    lead_id = await conn.fetchval(
        "INSERT INTO leads (tenant_id, contact_id) VALUES ($1, $2) RETURNING id",
        TEST_TENANT,
        contact_id,
    )
    return {"conn": conn, "contact_id": contact_id, "lead_id": lead_id}


def _mock_send_sms(sid: str = "SM_test", raises: bool = False):
    mock = AsyncMock()
    if raises:
        mock.side_effect = SmsDispatchError("simulated unfunded Twilio account")
    else:
        mock.return_value = sid
    return mock


@pytest.mark.asyncio
async def test_no_show_scan_flips_status_and_sends_once():
    row = await _seed("0100")
    await row["conn"].execute(
        "INSERT INTO appointments (tenant_id, lead_id, scheduled_at, status) VALUES ($1, $2, $3, 'scheduled')",
        TEST_TENANT,
        row["lead_id"],
        datetime.now(timezone.utc) - timedelta(hours=2),
    )

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        sent = await _scan_no_shows(TEST_TENANT, AGENCY)

    assert sent == 1
    mock_send.assert_called_once()
    status = await row["conn"].fetchval("SELECT status FROM appointments WHERE lead_id = $1", row["lead_id"])
    assert status == "no_show"
    logged = await row["conn"].fetchval(
        "SELECT kind FROM follow_ups WHERE lead_id = $1 AND kind = 'no_show'", row["lead_id"]
    )
    assert logged == "no_show"
    await row["conn"].close()


@pytest.mark.asyncio
async def test_no_show_scan_skips_appointment_not_yet_overdue():
    row = await _seed("0101")
    await row["conn"].execute(
        "INSERT INTO appointments (tenant_id, lead_id, scheduled_at, status) VALUES ($1, $2, $3, 'scheduled')",
        TEST_TENANT,
        row["lead_id"],
        datetime.now(timezone.utc) - timedelta(minutes=10),  # under the 1-hour default delay
    )

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        sent = await _scan_no_shows(TEST_TENANT, AGENCY)

    assert sent == 0
    mock_send.assert_not_called()
    status = await row["conn"].fetchval("SELECT status FROM appointments WHERE lead_id = $1", row["lead_id"])
    assert status == "scheduled"
    await row["conn"].close()


@pytest.mark.asyncio
async def test_no_show_scan_retries_a_previously_failed_send():
    """A send failure (the real, current state of this environment --
    Twilio isn't funded yet) must not permanently block the follow-up:
    the appointment still flips to no_show, but the next scan should try
    the SMS again since no follow_ups row was logged."""
    row = await _seed("0102")
    await row["conn"].execute(
        "INSERT INTO appointments (tenant_id, lead_id, scheduled_at, status) VALUES ($1, $2, $3, 'scheduled')",
        TEST_TENANT,
        row["lead_id"],
        datetime.now(timezone.utc) - timedelta(hours=2),
    )

    with patch("followup_scan.send_sms", _mock_send_sms(raises=True)):
        first_sent = await _scan_no_shows(TEST_TENANT, AGENCY)
    assert first_sent == 0
    status = await row["conn"].fetchval("SELECT status FROM appointments WHERE lead_id = $1", row["lead_id"])
    assert status == "no_show"  # flipped even though the SMS failed
    logged = await row["conn"].fetchval(
        "SELECT count(*) FROM follow_ups WHERE lead_id = $1 AND kind = 'no_show'", row["lead_id"]
    )
    assert logged == 0

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        second_sent = await _scan_no_shows(TEST_TENANT, AGENCY)
    assert second_sent == 1  # retried successfully this time
    mock_send.assert_called_once()
    await row["conn"].close()


@pytest.mark.asyncio
async def test_no_show_scan_does_not_resend_once_logged():
    row = await _seed("0103")
    await row["conn"].execute(
        "INSERT INTO appointments (tenant_id, lead_id, scheduled_at, status) VALUES ($1, $2, $3, 'scheduled')",
        TEST_TENANT,
        row["lead_id"],
        datetime.now(timezone.utc) - timedelta(hours=2),
    )

    with patch("followup_scan.send_sms", _mock_send_sms()):
        await _scan_no_shows(TEST_TENANT, AGENCY)

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        second_sent = await _scan_no_shows(TEST_TENANT, AGENCY)

    assert second_sent == 0
    mock_send.assert_not_called()
    await row["conn"].close()


@pytest.mark.asyncio
async def test_nurture_scan_sends_for_stale_lead_without_appointment():
    row = await _seed("0200")
    await row["conn"].execute(
        "INSERT INTO interactions (tenant_id, contact_id, lead_id, call_id, created_at) VALUES ($1, $2, $3, $4, $5)",
        TEST_TENANT,
        row["contact_id"],
        row["lead_id"],
        "call-0200",
        datetime.now(timezone.utc) - timedelta(days=3),  # older than the 2-day default
    )

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        sent = await _scan_nurture(TEST_TENANT, AGENCY)

    assert sent == 1
    mock_send.assert_called_once()
    logged = await row["conn"].fetchval(
        "SELECT kind FROM follow_ups WHERE lead_id = $1 AND kind = 'nurture'", row["lead_id"]
    )
    assert logged == "nurture"
    await row["conn"].close()


@pytest.mark.asyncio
async def test_nurture_scan_skips_recent_interaction():
    row = await _seed("0201")
    await row["conn"].execute(
        "INSERT INTO interactions (tenant_id, contact_id, lead_id, call_id, created_at) VALUES ($1, $2, $3, $4, $5)",
        TEST_TENANT,
        row["contact_id"],
        row["lead_id"],
        "call-0201",
        datetime.now(timezone.utc) - timedelta(hours=1),  # well under the 2-day default
    )

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        sent = await _scan_nurture(TEST_TENANT, AGENCY)

    assert sent == 0
    mock_send.assert_not_called()
    await row["conn"].close()


@pytest.mark.asyncio
async def test_nurture_scan_skips_lead_with_an_appointment():
    row = await _seed("0202")
    await row["conn"].execute(
        "INSERT INTO interactions (tenant_id, contact_id, lead_id, call_id, created_at) VALUES ($1, $2, $3, $4, $5)",
        TEST_TENANT,
        row["contact_id"],
        row["lead_id"],
        "call-0202",
        datetime.now(timezone.utc) - timedelta(days=3),
    )
    await row["conn"].execute(
        "INSERT INTO appointments (tenant_id, lead_id, scheduled_at, status) VALUES ($1, $2, $3, 'completed')",
        TEST_TENANT,
        row["lead_id"],
        datetime.now(timezone.utc) - timedelta(days=1),
    )

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        sent = await _scan_nurture(TEST_TENANT, AGENCY)

    assert sent == 0
    mock_send.assert_not_called()
    await row["conn"].close()


@pytest.mark.asyncio
async def test_nurture_scan_skips_lead_with_no_interactions():
    row = await _seed("0203")  # lead exists, but no call was ever recorded for it

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        sent = await _scan_nurture(TEST_TENANT, AGENCY)

    assert sent == 0
    mock_send.assert_not_called()
    await row["conn"].close()


@pytest.mark.asyncio
async def test_nurture_scan_skips_already_qualified_lead_status():
    row = await _seed("0204")
    await row["conn"].execute("UPDATE leads SET status = 'appointment_set' WHERE id = $1", row["lead_id"])
    await row["conn"].execute(
        "INSERT INTO interactions (tenant_id, contact_id, lead_id, call_id, created_at) VALUES ($1, $2, $3, $4, $5)",
        TEST_TENANT,
        row["contact_id"],
        row["lead_id"],
        "call-0204",
        datetime.now(timezone.utc) - timedelta(days=3),
    )

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        sent = await _scan_nurture(TEST_TENANT, AGENCY)

    assert sent == 0
    mock_send.assert_not_called()
    await row["conn"].close()


@pytest.mark.asyncio
async def test_nurture_scan_does_not_resend_once_logged():
    row = await _seed("0205")
    await row["conn"].execute(
        "INSERT INTO interactions (tenant_id, contact_id, lead_id, call_id, created_at) VALUES ($1, $2, $3, $4, $5)",
        TEST_TENANT,
        row["contact_id"],
        row["lead_id"],
        "call-0205",
        datetime.now(timezone.utc) - timedelta(days=3),
    )

    with patch("followup_scan.send_sms", _mock_send_sms()):
        await _scan_nurture(TEST_TENANT, AGENCY)

    with patch("followup_scan.send_sms", _mock_send_sms()) as mock_send:
        second_sent = await _scan_nurture(TEST_TENANT, AGENCY)

    assert second_sent == 0
    mock_send.assert_not_called()
    await row["conn"].close()
