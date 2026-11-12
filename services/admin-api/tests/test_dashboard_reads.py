"""Dashboard read endpoint integration tests against real Postgres and Redis."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/propview_dev")
os.environ.setdefault("PLATFORM_OPERATOR_TOKEN", "test-platform-token")
os.environ.setdefault("RATE_LIMIT_ADMIN_REQUESTS_PER_WINDOW", "10000")
os.environ.setdefault("RATE_LIMIT_PROVISION_REQUESTS_PER_WINDOW", "10000")
os.environ.setdefault("RATE_LIMIT_DASHBOARD_REQUESTS_PER_WINDOW", "10000")

from db import tenant_connection
from main import app


def _tenant_id() -> str:
    return f"test-dashboard-{uuid.uuid4().hex}"


async def _seed_dashboard_data(tenant_id: str) -> dict[str, int | str]:
    call_id = f"dashboard-call-{uuid.uuid4().hex}"
    async with tenant_connection(tenant_id) as conn:
        property_id = await conn.fetchval(
            """
            INSERT INTO properties
                (tenant_id, address, city, state, property_type, price)
            VALUES ($1, '1 Test Avenue', 'Austin', 'TX', 'house', 450000)
            RETURNING id
            """,
            tenant_id,
        )
        contact_id = await conn.fetchval(
            """
            INSERT INTO contacts (tenant_id, full_name, phone_number, email)
            VALUES ($1, 'Test Caller', $2, 'caller@example.com')
            RETURNING id
            """,
            tenant_id,
            f"+1555{uuid.uuid4().int % 10**7:07d}",
        )
        lead_id = await conn.fetchval(
            """
            INSERT INTO leads
                (tenant_id, contact_id, property_id, intent, priority, status)
            VALUES ($1, $2, $3, 'buy', 'high', 'qualified')
            RETURNING id
            """,
            tenant_id,
            contact_id,
            property_id,
        )
        appointment_id = await conn.fetchval(
            """
            INSERT INTO appointments
                (tenant_id, lead_id, property_id, scheduled_at, agent_name)
            VALUES ($1, $2, $3, date_trunc('week', CURRENT_DATE) + interval '1 day', 'Test Agent')
            RETURNING id
            """,
            tenant_id,
            lead_id,
            property_id,
        )
        await conn.execute(
            """
            INSERT INTO interactions
                (tenant_id, contact_id, lead_id, call_id, transcript, duration_seconds, outcome)
            VALUES ($1, $2, $3, $4, 'Test call transcript', 90, 'booked')
            """,
            tenant_id,
            contact_id,
            lead_id,
            call_id,
        )
        await conn.execute(
            """
            INSERT INTO conversation_turns
                (tenant_id, call_id, turn_index, speaker, text, timestamp_ms)
            VALUES ($1, $2, 0, 'caller', 'I want to see the house', 1000)
            """,
            tenant_id,
            call_id,
        )
        await conn.execute(
            """
            INSERT INTO tool_invocations
                (tenant_id, call_id, tool_name, input_params, output_result)
            VALUES ($1, $2, 'book_site_visit', '{"property_id": 1}', '{"status": "booked"}')
            """,
            tenant_id,
            call_id,
        )
        await conn.execute(
            """
            INSERT INTO call_analytics
                (tenant_id, call_id, total_turns, caller_turns, duration_seconds, outcome, lead_id)
            VALUES ($1, $2, 1, 1, 90, 'booked', $3)
            """,
            tenant_id,
            call_id,
            lead_id,
        )
    return {
        "property_id": property_id,
        "lead_id": lead_id,
        "appointment_id": appointment_id,
        "call_id": call_id,
    }


async def _seed_foreign_call(tenant_id: str, call_id: str) -> None:
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            """
            INSERT INTO interactions (tenant_id, call_id, transcript)
            VALUES ($1, $2, 'foreign tenant call')
            """,
            tenant_id,
            call_id,
        )


async def _cleanup_tenant(tenant_id: str) -> None:
    async with tenant_connection(tenant_id) as conn:
        await conn.execute("DELETE FROM tenant_settings WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM call_analytics WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM tool_invocations WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM conversation_turns WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM interactions WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM appointments WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM leads WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM contacts WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM properties WHERE tenant_id = $1", tenant_id)


@pytest.fixture
def dashboard_client():
    tenant_id = _tenant_id()
    with TestClient(app) as client:
        provision = client.post(
            f"/admin/tenants/{tenant_id}/provision",
            headers={"Authorization": f"Bearer {os.environ['PLATFORM_OPERATOR_TOKEN']}"},
        )
        assert provision.status_code == 200, provision.text
        client.headers["Authorization"] = f"Bearer {provision.json()['admin_api_key']}"
        ids = client.portal.call(_seed_dashboard_data, tenant_id)
        try:
            yield client, tenant_id, ids
        finally:
            client.portal.call(_cleanup_tenant, tenant_id)


def test_list_properties_reads_tenant_listings(dashboard_client):
    client, tenant_id, _ = dashboard_client

    response = client.get(f"/admin/tenants/{tenant_id}/properties")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["address"] == "1 Test Avenue"


def test_list_leads_reads_tenant_leads(dashboard_client):
    client, tenant_id, _ = dashboard_client

    response = client.get(f"/admin/tenants/{tenant_id}/leads")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["full_name"] == "Test Caller"


def test_list_appointments_reads_tenant_appointments(dashboard_client):
    client, tenant_id, _ = dashboard_client

    response = client.get(f"/admin/tenants/{tenant_id}/appointments")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["lead_name"] == "Test Caller"
    assert response.json()["items"][0]["property_address"] == "1 Test Avenue"


def test_list_calls_reads_tenant_call_analytics(dashboard_client):
    client, tenant_id, ids = dashboard_client

    response = client.get(f"/admin/tenants/{tenant_id}/calls")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["call_id"] == ids["call_id"]
    assert response.json()["items"][0]["analytics_outcome"] == "booked"


def test_get_call_detail_reads_turns_tools_and_analytics(dashboard_client):
    client, tenant_id, ids = dashboard_client

    response = client.get(f"/admin/tenants/{tenant_id}/calls/{ids['call_id']}")

    assert response.status_code == 200
    assert response.json()["turns"][0]["text"] == "I want to see the house"
    assert response.json()["tool_invocations"][0]["tool_name"] == "book_site_visit"
    assert response.json()["analytics"]["outcome"] == "booked"


def test_dashboard_stats_returns_tenant_metrics(dashboard_client):
    client, tenant_id, _ = dashboard_client

    response = client.get(f"/admin/tenants/{tenant_id}/stats")

    assert response.status_code == 200
    assert response.json()["total_calls"] == 1
    assert response.json()["total_properties"] == 1
    assert response.json()["active_leads"] == 1
    assert response.json()["hot_leads"] == 1
    assert response.json()["conversion_rate"] == 100.0


def test_tenant_cannot_read_another_tenants_call(dashboard_client):
    client, tenant_id, _ = dashboard_client
    other_tenant_id = _tenant_id()
    foreign_call_id = f"foreign-call-{uuid.uuid4().hex}"

    client.portal.call(_seed_foreign_call, other_tenant_id, foreign_call_id)
    try:
        response = client.get(
            f"/admin/tenants/{tenant_id}/calls/{foreign_call_id}"
        )
    finally:
        client.portal.call(_cleanup_tenant, other_tenant_id)

    assert response.status_code == 404
