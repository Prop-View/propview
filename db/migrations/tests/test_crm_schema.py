"""
PROP-401: Tests for the CRM schema against a real local Postgres.

Run: DATABASE_URL=postgresql://localhost/propview_dev python -m pytest tests/ -v
(assumes apply_migrations.py has already been run)
"""

import os

import asyncpg
import pytest
import pytest_asyncio

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/propview_dev")
TEST_PHONE = "+15125550999"


@pytest_asyncio.fixture
async def conn():
    connection = await asyncpg.connect(DATABASE_URL)
    await connection.execute("DELETE FROM contacts WHERE phone_number = $1", TEST_PHONE)
    yield connection
    await connection.execute("DELETE FROM contacts WHERE phone_number = $1", TEST_PHONE)
    await connection.close()


@pytest.mark.asyncio
async def test_full_crm_flow_insert(conn):
    contact_id = await conn.fetchval(
        "INSERT INTO contacts (phone_number, full_name) VALUES ($1, 'Jane Doe') RETURNING id", TEST_PHONE
    )
    lead_id = await conn.fetchval(
        "INSERT INTO leads (contact_id, intent, budget_min, budget_max, timeline, priority) "
        "VALUES ($1, 'buy', 500000, 550000, '1-3mo', 'high') RETURNING id",
        contact_id,
    )
    appt_id = await conn.fetchval(
        "INSERT INTO appointments (lead_id, scheduled_at, agent_name) VALUES ($1, now() + interval '1 day', 'Sarah') RETURNING id",
        lead_id,
    )
    await conn.execute(
        "INSERT INTO interactions (contact_id, lead_id, call_id, transcript, duration_seconds) "
        "VALUES ($1, $2, 'call-test-001', 'hello world', 120)",
        contact_id,
        lead_id,
    )

    assert contact_id and lead_id and appt_id


@pytest.mark.asyncio
async def test_invalid_intent_rejected_by_check_constraint(conn):
    contact_id = await conn.fetchval(
        "INSERT INTO contacts (phone_number) VALUES ($1) RETURNING id", TEST_PHONE
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute("INSERT INTO leads (contact_id, intent) VALUES ($1, 'not_a_real_intent')", contact_id)


@pytest.mark.asyncio
async def test_deleting_contact_cascades_to_leads_and_appointments(conn):
    contact_id = await conn.fetchval(
        "INSERT INTO contacts (phone_number) VALUES ($1) RETURNING id", TEST_PHONE
    )
    lead_id = await conn.fetchval(
        "INSERT INTO leads (contact_id, intent) VALUES ($1, 'buy') RETURNING id", contact_id
    )
    appt_id = await conn.fetchval(
        "INSERT INTO appointments (lead_id, scheduled_at) VALUES ($1, now()) RETURNING id", lead_id
    )

    await conn.execute("DELETE FROM contacts WHERE id = $1", contact_id)

    assert await conn.fetchval("SELECT count(*) FROM leads WHERE id = $1", lead_id) == 0
    assert await conn.fetchval("SELECT count(*) FROM appointments WHERE id = $1", appt_id) == 0


@pytest.mark.asyncio
async def test_duplicate_phone_number_per_tenant_rejected(conn):
    await conn.execute("INSERT INTO contacts (phone_number) VALUES ($1)", TEST_PHONE)
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute("INSERT INTO contacts (phone_number) VALUES ($1)", TEST_PHONE)
